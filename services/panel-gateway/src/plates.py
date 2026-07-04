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
from collections import Counter
from pathlib import Path

import plate_validation

log = logging.getLogger("panel.plates")

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MODEL = _ROOT / "models/license_plate_training/outputs/license_plate_model/weights/best.pt"


def enabled() -> bool:
    return os.getenv("PANEL_READ_PLATES", "").lower() in ("1", "true", "yes")


class PlateReader:
    def __init__(self, model_path: str | None = None, max_per_frame: int = 2, max_tries: int = 12):
        self.model_path = model_path or os.getenv("PANEL_PLATE_MODEL", str(_DEFAULT_MODEL))
        self.max_per_frame = max_per_frame
        self.max_tries = int(os.getenv("PANEL_PLATE_MAX_TRIES", str(max_tries)))
        # Accept a plate only after it's been read (validated) this many times —
        # multi-frame consensus so a one-off OCR error is never reported.
        self.min_agreement = int(os.getenv("PANEL_PLATE_MIN_AGREEMENT", "2"))
        # Low per-read gate on purpose: consensus + format validation do the
        # real filtering, so we let borderline reads vote rather than drop them.
        self.ocr_conf = float(os.getenv("PANEL_PLATE_OCR_CONF", "0.2"))
        self._model = None
        self._ocr = None
        self._cache: dict[int, str] = {}      # track_id -> accepted plate
        self._attempts: dict[int, int] = {}   # track_id -> read attempts so far
        self._candidates: dict[int, Counter] = {}  # track_id -> validated read votes
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
        # Retry across frames (a plate may only be readable as the vehicle
        # nears/clears), but bounded so OCR can't run unbounded per track.
        if self._attempts.get(tid, 0) >= self.max_tries or self._budget <= 0:
            return None
        self._budget -= 1
        self._attempts[tid] = self._attempts.get(tid, 0) + 1
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
            plate_img = self._preprocess(plate_img)
            # detail=1 -> (bbox, text, confidence); keep only confident text
            results = self._ocr.readtext(plate_img, detail=1)
            parts = [txt for (_b, txt, conf) in results if conf >= self.ocr_conf]
            raw = plate_validation.clean("".join(parts))
            if not raw:
                return None
            cand = plate_validation.disambiguate(raw)
            # Reject anything that doesn't match a valid plate format — better
            # NO plate than a WRONG plate.
            if not plate_validation.is_valid(cand):
                return None
            # Multi-frame consensus: only accept once the same validated read
            # has been seen min_agreement times for this vehicle.
            votes = self._candidates.setdefault(tid, Counter())
            votes[cand] += 1
            top, n = votes.most_common(1)[0]
            if n >= self.min_agreement:
                self._cache[tid] = top
                return top
        except Exception as e:  # noqa: BLE001 — plate reading is best-effort
            log.debug("plate read failed: %s", e)
        return None

    def _preprocess(self, img):
        """Upscale small plates to a workable height and grayscale — small,
        distant plates OCR far better after this (verified: the correct plate
        goes from unreadable to a strong consensus winner)."""
        import cv2
        import numpy as np

        h = img.shape[0]
        if 0 < h < 90:
            s = 90.0 / h
            img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return np.ascontiguousarray(gray)

    def remove(self, track_id: int) -> None:
        self._cache.pop(track_id, None)
        self._attempts.pop(track_id, None)
        self._candidates.pop(track_id, None)
