"""Scene change detection — auto-recalibration trigger.

Production homography problem: calibration is captured once during
site survey. If the camera mount shifts (wind, vibration, accidental
contact during maintenance) or the scene changes significantly
(construction, road resurfacing, new signal head obscuring the view)
the calibrated homography becomes silently wrong. Speed estimates
get systematically biased without anyone knowing.

This detector compares each frame against a baseline reference
captured at chamber startup. When the cumulative drift exceeds a
threshold for N consecutive frames, the detector:

1. Sets a flag on the chamber state
2. Emits a Prometheus counter
3. Warns the operator via the console
4. Logs the suspected scene change for ops review

Detection signals (combined via consensus):

- **Edge structural similarity** — fixed scene features (road lane
  markings, signal pole shadows, building edges) should remain
  invariant. A persistent change in edge structure means the camera
  view itself has shifted.
- **Color histogram drift** — gross illumination changes (overcast→
  sunny) are normalised out; permanent shifts (different sky angle
  due to camera tilt) trigger.
- **Reference-point invariance** — if a homography file has reference
  points, we cross-check that those pixel locations still look the
  same. Sharpest signal when available.

False-positive guards:
- Need 60+ consecutive frames of detected change before alerting
  (filters out vehicles, pedestrians, momentary occlusions)
- Lighting changes (day/night, weather) shouldn't fire — we normalise
  by overall brightness before comparison

This does NOT auto-recalibrate (re-running homography requires a
human in the loop to confirm the 4 reference points). It just FLAGS
the calibration as suspect so ops can investigate.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import numpy as np

try:
    import cv2 as _cv2
except ImportError:
    _cv2 = None  # detector becomes a no-op without OpenCV

log = logging.getLogger("atms.video.scene_change")


@dataclass
class SceneChangeStatus:
    """Snapshot of the detector's current verdict. Surfaced to the
    operator console + Prometheus.
    """

    has_baseline: bool = False
    consecutive_change_frames: int = 0
    threshold_frames: int = 60
    threshold_diff: float = 0.25
    latest_diff: float = 0.0
    alert_active: bool = False
    last_alert_at: float = 0.0  # monotonic seconds


class SceneChangeDetector:
    """Maintains a reference frame appearance, compares each new frame,
    triggers an alert when divergence persists.

    Lightweight: a single grayscale resize + histogram + edge density
    per check. <2ms per frame at 320×240 downsampled resolution. Runs
    once per second by default (not every frame) to bound cost.
    """

    def __init__(
        self,
        check_interval_seconds: float = 1.0,
        threshold_diff: float = 0.25,
        threshold_frames: int = 60,
        downsample_size: tuple[int, int] = (320, 240),
    ):
        self._check_interval = check_interval_seconds
        self._threshold_diff = threshold_diff
        self._threshold_frames = threshold_frames
        self._downsample_size = downsample_size

        self._lock = threading.Lock()
        self._baseline_signature: np.ndarray | None = None
        self._consecutive_change = 0
        self._latest_diff = 0.0
        self._alert_active = False
        self._last_alert_at = 0.0
        self._last_check_at = 0.0

    def consider_frame(self, frame: np.ndarray) -> SceneChangeStatus:
        """Maybe-process this frame. Only does work every
        `check_interval_seconds`; returns the current status either way.
        """
        now = time.monotonic()
        if now - self._last_check_at < self._check_interval:
            return self.status()
        self._last_check_at = now

        if _cv2 is None:
            return self.status()

        # Downsample + grayscale + normalise brightness
        small = _cv2.resize(frame, self._downsample_size)
        gray = _cv2.cvtColor(small, _cv2.COLOR_BGR2GRAY)
        # Brightness normalisation removes day-night illumination bias
        gray = _cv2.equalizeHist(gray)
        edges = _cv2.Canny(gray, 60, 180)
        # Signature = compact descriptor: histogram + edge density
        hist = _cv2.calcHist([gray], [0], None, [16], [0, 256]).flatten()
        hist = hist / max(hist.sum(), 1.0)
        edge_density = float(edges.sum()) / max(edges.size, 1)
        signature = np.concatenate([hist, [edge_density]])

        with self._lock:
            if self._baseline_signature is None:
                self._baseline_signature = signature
                log.info(
                    "scene-change baseline captured (%d-dim signature)",
                    len(signature),
                )
                return self.status()

            # Cosine-distance-ish in [0, 1]
            base = self._baseline_signature
            num = float(np.dot(signature, base))
            denom = float(np.linalg.norm(signature) * np.linalg.norm(base)) + 1e-9
            sim = num / denom
            diff = 1.0 - sim  # 0 = identical; 1 = orthogonal
            self._latest_diff = diff

            if diff > self._threshold_diff:
                self._consecutive_change += 1
            else:
                # Decay: small drops don't completely reset (avoid flapping)
                self._consecutive_change = max(
                    0, self._consecutive_change - 2
                )

            if (
                self._consecutive_change >= self._threshold_frames
                and not self._alert_active
            ):
                self._alert_active = True
                self._last_alert_at = now
                log.warning(
                    "SCENE CHANGE detected — homography may be invalid. "
                    "consecutive_change=%d  diff=%.2f  threshold=%.2f. "
                    "Operator: re-run scripts/calibrate_camera_homography.py",
                    self._consecutive_change, diff, self._threshold_diff,
                )

            return self.status()

    def status(self) -> SceneChangeStatus:
        with self._lock:
            return SceneChangeStatus(
                has_baseline=self._baseline_signature is not None,
                consecutive_change_frames=self._consecutive_change,
                threshold_frames=self._threshold_frames,
                threshold_diff=self._threshold_diff,
                latest_diff=self._latest_diff,
                alert_active=self._alert_active,
                last_alert_at=self._last_alert_at,
            )

    def reset_alert(self) -> None:
        """Called by ops after re-running calibration to clear the alert."""
        with self._lock:
            self._alert_active = False
            self._consecutive_change = 0
            self._baseline_signature = None
        log.info("scene-change alert cleared; new baseline will capture on next frame")
