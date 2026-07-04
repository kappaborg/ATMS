"""
License-plate capture for flagged violators.

Reuses the project's trained plate detector (models/license_plate_training/…/
best.pt) + easyocr. To stay real-time it reads a plate ONLY for a vehicle that
has been flagged for a violation (speeding / red-light / drift / wrong-way /
reckless), caps reads per frame, and caches the result per track — so OCR
(which is slow) runs a handful of times, not on every vehicle every frame.

Off by default (heavy models). Enable with PANEL_READ_PLATES=1.

PRIVACY: a real plate number is personal data. Capturing it for enforcement is
the opposite of the anonymise-by-default posture elsewhere in ATMS and needs a
lawful basis + retention policy + DPIA. This module returns the raw plate for
that purpose; storing it is a policy decision outside this module.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger("panel.plates")

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MODEL = _ROOT / "models/license_plate_training/outputs/license_plate_model/weights/best.pt"
_PLATE_RE = re.compile(r"[^A-Z0-9]")


def enabled() -> bool:
    return os.getenv("PANEL_READ_PLATES", "").lower() in ("1", "true", "yes")


class PlateReader:
    def __init__(self, model_path: str | None = None, max_per_frame: int = 1):
        self.model_path = model_path or os.getenv("PANEL_PLATE_MODEL", str(_DEFAULT_MODEL))
        self.max_per_frame = max_per_frame
        self._model = None
        self._ocr = None
        self._cache: dict[int, str] = {}   # track_id -> plate text
        self._tried: set[int] = set()      # tracks we've already attempted
        self._budget = 0

    def _lazy(self) -> bool:
        if self._model is None:
            try:
                from ultralytics import YOLO
                self._model = YOLO(self.model_path)
                log.info("plate detector loaded: %s", self.model_path)
            except Exception as e:  # noqa: BLE001
                log.warning("plate detector unavailable: %s", e)
                return False
        if self._ocr is None:
            try:
                import easyocr
                self._ocr = easyocr.Reader(["en"], gpu=False, verbose=False)
                log.info("OCR engine loaded (easyocr)")
            except Exception as e:  # noqa: BLE001
                log.warning("OCR engine unavailable: %s", e)
                return False
        return True

    def begin_frame(self) -> None:
        self._budget = self.max_per_frame

    def cached(self, track_id: int) -> str | None:
        return self._cache.get(track_id)

    def read(self, frame, bbox, track_id: int) -> str | None:
        """Read the plate of the vehicle at bbox in frame. Cached per track;
        respects the per-frame budget; returns the plate text or None."""
        tid = int(track_id)
        if tid in self._cache:
            return self._cache[tid]
        if tid in self._tried or self._budget <= 0:
            return None
        self._budget -= 1
        self._tried.add(tid)
        if not self._lazy():
            return None
        try:
            import numpy as np

            h, w = frame.shape[:2]
            x1, y1, x2, y2 = (int(max(0, bbox[0])), int(max(0, bbox[1])),
                              int(min(w, bbox[2])), int(min(h, bbox[3])))
            if x2 - x1 < 8 or y2 - y1 < 8:
                return None
            crop = frame[y1:y2, x1:x2]
            det = self._model(crop, verbose=False)[0]
            if det.boxes is None or len(det.boxes) == 0:
                return None
            # highest-confidence plate box within the vehicle crop
            best = max(det.boxes, key=lambda b: float(b.conf[0]))
            px1, py1, px2, py2 = (int(v) for v in best.xyxy[0].tolist())
            plate_img = crop[max(0, py1):py2, max(0, px1):px2]
            if plate_img.size == 0:
                return None
            texts = self._ocr.readtext(np.ascontiguousarray(plate_img), detail=0)
            plate = _PLATE_RE.sub("", "".join(texts).upper())
            if len(plate) >= 4:  # ignore junk reads
                self._cache[tid] = plate
                return plate
        except Exception as e:  # noqa: BLE001 — plate reading is best-effort
            log.debug("plate read failed: %s", e)
        return None

    def remove(self, track_id: int) -> None:
        self._cache.pop(track_id, None)
        self._tried.discard(track_id)
