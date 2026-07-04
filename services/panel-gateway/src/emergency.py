"""
Emergency-vehicle detection via a FLASHING blue/red light bar.

The detector (YOLO/COCO) can't tell a police car from a car — there's no
emergency class. But an emergency vehicle *running its lights* has a
distinctive, detectable signature: a patch of saturated blue and/or red that
FLASHES (turns on and off ~1-4 Hz). A steady brake light (constant red) or an
amber turn signal does NOT match, so those don't false-trigger.

Per tracked vehicle we measure the fraction of "emergency-coloured" pixels in
its box each frame; if that fraction both reaches a presence threshold AND
swings on/off across a short window, the vehicle is flagged. Works when the
lights are on and visible (which is exactly when preemption matters). Small/
distant vehicles (aerial) won't have a readable light bar — an honest limit.
"""
from __future__ import annotations

import os
from collections import deque

import cv2
import numpy as np


class EmergencyVehicleDetector:
    def __init__(self, window: int = 12, cooldown_s: float = 3.0):
        self.window = window
        self.on_thresh = float(os.getenv("PANEL_EMERGENCY_ON", "0.010"))   # light "on" pixel frac
        self.cooldown_s = cooldown_s
        self._hist: dict[int, deque] = {}
        self._flagged_until: dict[int, float] = {}

    @staticmethod
    def _emergency_fraction(crop: np.ndarray) -> float:
        """Fraction of saturated blue-or-red pixels in the crop (light-bar cue)."""
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        # saturated, bright blue (H~100-130) or red (H<8 or >172)
        blue = cv2.inRange(hsv, (100, 90, 110), (135, 255, 255))
        red1 = cv2.inRange(hsv, (0, 100, 130), (8, 255, 255))
        red2 = cv2.inRange(hsv, (172, 100, 130), (180, 255, 255))
        mask = cv2.bitwise_or(cv2.bitwise_or(blue, red1), red2)
        return float(np.count_nonzero(mask)) / float(mask.size or 1)

    def update(self, frame: np.ndarray, vehicles: list, t: float) -> set[int]:
        ids: set[int] = set()
        live: set[int] = set()
        h, w = frame.shape[:2]
        for v in vehicles:
            tid = int(v.track_id)
            live.add(tid)
            if self._flagged_until.get(tid, 0.0) > t:
                ids.add(tid)
            x1, y1, x2, y2 = (int(max(0, v.bbox[0])), int(max(0, v.bbox[1])),
                              int(min(w, v.bbox[2])), int(min(h, v.bbox[3])))
            if x2 - x1 < 12 or y2 - y1 < 12:
                continue
            frac = self._emergency_fraction(frame[y1:y2, x1:x2])
            dq = self._hist.setdefault(tid, deque(maxlen=self.window))
            dq.append(frac)
            if len(dq) >= self.window:
                bright = sum(1 for f in dq if f >= self.on_thresh)
                dim = sum(1 for f in dq if f < self.on_thresh * 0.35)
                # FLASHING = the light-bar patch turns on (bright frames) AND off
                # (dim frames) within the window — not steady, not absent.
                if bright >= 2 and dim >= 2:
                    ids.add(tid)
                    self._flagged_until[tid] = t + self.cooldown_s
        for tid in list(self._hist):
            if tid not in live:
                self._hist.pop(tid, None)
                self._flagged_until.pop(tid, None)
        return ids

    def remove(self, track_id: int) -> None:
        self._hist.pop(track_id, None)
        self._flagged_until.pop(track_id, None)
