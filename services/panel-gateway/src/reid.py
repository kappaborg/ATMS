"""
Deep appearance re-identification (ReID) for track continuity.

The IoU tracker loses a vehicle when it's occluded (a truck passes in front,
detection flickers) and re-births it under a NEW id — which breaks plate
caching, violation dedup, unique-vehicle counts, and the parked/stall gates.

This module gives every tracked vehicle an appearance fingerprint — a deep
embedding from a MobileNetV3-Small backbone (ImageNet features, cosine
similarity) — and keeps a short-lived gallery of recently-LOST tracks. When a
new track is born, it is matched against the gallery (appearance + spatial
sanity); a hit means "same physical vehicle" and the OLD identity is restored.

CPU cost is kept small: a track is embedded at birth and refreshed every
`update_every` frames (EMA), not every frame. Set PANEL_REID=0 to disable,
PANEL_REID_SIM to tune the match threshold.
"""
from __future__ import annotations

import logging
import math
import os

import numpy as np

log = logging.getLogger("panel.reid")


def enabled() -> bool:
    return os.getenv("PANEL_REID", "1").lower() in ("1", "true", "yes")


class DeepReID:
    def __init__(
        self,
        ttl_s: float = 10.0,
        sim_thresh: float | None = None,
        margin: float = 0.05,
        update_every: int = 30,
        max_gallery: int = 64,
    ):
        self.ttl_s = ttl_s
        # CONSERVATIVE by design (measured on real footage: same-vehicle mean
        # ~0.90, different-vehicle max ~0.89 — the distributions overlap!).
        # A missed recovery = status quo (new id); a WRONG merge corrupts
        # evidence. So: high threshold + a clear margin over the runner-up.
        self.sim_thresh = (
            sim_thresh if sim_thresh is not None
            else float(os.getenv("PANEL_REID_SIM", "0.90"))
        )
        self.margin = margin
        self.update_every = update_every
        self.max_gallery = max_gallery
        self._model = None
        self._failed = False
        # live tracks: id -> {"emb": vec|None, "center": (x,y), "frames": n}
        self._live: dict[int, dict] = {}
        # lost gallery: id -> {"emb": vec, "center": (x,y), "t": t_lost}
        self._gallery: dict[int, dict] = {}

    # --- embedding backbone ---

    def _lazy(self) -> bool:
        if self._failed:
            return False
        if self._model is None:
            try:
                import torch
                from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

                m = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.DEFAULT)
                m.eval()
                self._model = m
                self._torch = torch
                log.info("ReID backbone loaded (MobileNetV3-Small)")
            except Exception as e:  # noqa: BLE001 — ReID is an enhancement, never fatal
                log.warning("ReID unavailable: %s", e)
                self._failed = True
                return False
        return True

    def embed(self, frame: np.ndarray, bbox) -> np.ndarray | None:
        """L2-normalised appearance embedding of the vehicle crop, or None."""
        if not self._lazy():
            return None
        try:
            import cv2

            h, w = frame.shape[:2]
            x1, y1 = max(0, int(bbox[0])), max(0, int(bbox[1]))
            x2, y2 = min(w, int(bbox[2])), min(h, int(bbox[3]))
            # tiny/distant crops embed poorly AND dominate CPU on busy scenes —
            # identity recovery only makes sense for decently-sized vehicles.
            if x2 - x1 < 48 or y2 - y1 < 36:
                return None
            crop = cv2.resize(frame[y1:y2, x1:x2], (96, 96))
            rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            rgb = (rgb - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)
            t = self._torch.from_numpy(rgb.transpose(2, 0, 1)[None]).float()
            with self._torch.no_grad():
                f = self._model.features(t)
                f = self._torch.nn.functional.adaptive_avg_pool2d(f, 1).flatten(1)
            v = f[0].numpy()
            n = np.linalg.norm(v)
            return v / n if n > 0 else None
        except Exception as e:  # noqa: BLE001
            log.debug("embed failed: %s", e)
            return None

    # --- track lifecycle ---

    def note_seen(self, tid: int, frame: np.ndarray, bbox, center) -> None:
        """Refresh a live track's fingerprint (EMA) every `update_every` frames.

        Embedding is DEFERRED until a track has survived 3 frames — detection
        flicker creates hordes of 1-2 frame tracks, and embedding them would
        dominate CPU for identities that never matter."""
        st = self._live.setdefault(tid, {"emb": None, "center": center, "frames": 0})
        st["center"] = center
        st["frames"] += 1
        if st["frames"] < 3:
            return
        if st["emb"] is not None and st["frames"] % self.update_every != 0:
            return
        emb = self.embed(frame, bbox)
        if emb is None:
            return
        if st["emb"] is None:
            st["emb"] = emb
        else:
            mixed = 0.7 * st["emb"] + 0.3 * emb
            n = np.linalg.norm(mixed)
            st["emb"] = mixed / n if n > 0 else emb

    def note_lost(self, tid: int, t: float) -> None:
        """Move a lost track's fingerprint into the recovery gallery."""
        st = self._live.pop(tid, None)
        if st is None or st["emb"] is None:
            return
        self._gallery[tid] = {"emb": st["emb"], "center": st["center"], "t": t}
        while len(self._gallery) > self.max_gallery:
            oldest = min(self._gallery, key=lambda k: self._gallery[k]["t"])
            self._gallery.pop(oldest)

    def recover(self, frame: np.ndarray, bbox, center, t: float, frame_diag: float) -> int | None:
        """Match a NEW track against recently-lost fingerprints. On a hit,
        return the old id (and consume it from the gallery)."""
        # prune expired
        for k in [k for k, g in self._gallery.items() if t - g["t"] > self.ttl_s]:
            self._gallery.pop(k)
        if not self._gallery:
            return None
        emb = self.embed(frame, bbox)
        if emb is None:
            return None
        # score every spatially-plausible candidate; accept only a CLEAR winner
        scored: list[tuple[float, int]] = []
        for k, g in self._gallery.items():
            # spatial sanity: a re-appearing vehicle is near where it vanished
            if math.hypot(center[0] - g["center"][0], center[1] - g["center"][1]) > 0.25 * frame_diag:
                continue
            scored.append((float(np.dot(emb, g["emb"])), k))
        if not scored:
            return None
        scored.sort(reverse=True)
        best_sim, best_id = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        # threshold AND margin: two similar cars must not be confused — if the
        # runner-up is close, we can't be sure, so we don't merge.
        if best_sim < self.sim_thresh or best_sim - second < self.margin:
            return None
        self._gallery.pop(best_id)
        self._live[best_id] = {"emb": emb, "center": center, "frames": 1}
        log.debug("ReID recovered track %s (sim %.2f, margin %.2f)", best_id, best_sim, best_sim - second)
        return best_id

    def remove(self, tid: int) -> None:
        self._live.pop(tid, None)
        self._gallery.pop(tid, None)
