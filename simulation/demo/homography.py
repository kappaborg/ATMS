"""Per-camera homography — pixel coords → real-world metres.

Production speed estimation problem: a single `pixels_per_meter` ratio
is OK at the camera centre but wrong by 30-50% at the frame edges
where perspective distortion is highest. A vehicle 60 pixels closer
to the camera might actually be 1.5 m away; the same 60 pixels far
from the camera might be 4 m. Single-ratio math overstates the close
speeds and understates the far ones.

The proper fix is a 3×3 homography matrix mapping pixel (u, v) →
real-world (X, Y) in metres. `scripts/calibrate_camera_homography.py`
produces these per-camera JSON files via a 4-point site survey.

This module loads + applies the homography in the chamber's speed
calculation path. When no homography file is configured the pipeline
falls back to the single-ratio approximation transparently.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("atms.video.homography")


class Homography:
    """Wraps a 3×3 homography matrix + the metadata needed to validate
    that the loaded calibration matches the current camera.

    Production guard: if the loaded calibration's `frame_shape` doesn't
    match the live camera's resolution, the homography is INVALID
    (camera was reconfigured or the wrong cal was loaded). We refuse
    to use it rather than silently producing wrong speeds.
    """

    def __init__(
        self,
        H: np.ndarray,
        frame_shape: tuple[int, int],
        intersection_id: str = "",
        max_residual_m: float = 0.0,
    ):
        if H.shape != (3, 3):
            raise ValueError(f"homography must be 3×3, got {H.shape}")
        self._H = H.astype(np.float64)
        self._frame_shape = tuple(frame_shape)
        self._intersection_id = intersection_id
        self._max_residual_m = max_residual_m

    @classmethod
    def load(cls, path: Path | str) -> "Homography":
        """Load a homography from the JSON produced by
        `scripts/calibrate_camera_homography.py`.
        """
        data = json.loads(Path(path).read_text())
        if data.get("schema_version") != 1:
            raise ValueError(
                f"homography {path} has unknown schema_version "
                f"{data.get('schema_version')!r}"
            )
        H = np.array(data["homography"], dtype=np.float64)
        frame_shape = tuple(data["frame_shape"])
        validation = data.get("validation", {})
        log.info(
            "loaded homography for %s — frame=%s residual_rmse=%.2fm",
            data.get("intersection_id", "?"),
            frame_shape,
            validation.get("rmse_m", 0.0),
        )
        return cls(
            H=H,
            frame_shape=frame_shape,
            intersection_id=data.get("intersection_id", ""),
            max_residual_m=validation.get("max_error_m", 0.0),
        )

    def matches_camera(self, frame_width: int, frame_height: int) -> bool:
        """Guard: calibration must match the current camera resolution."""
        return self._frame_shape == (frame_height, frame_width)

    def pixel_to_meters(
        self, u: float, v: float
    ) -> tuple[float, float]:
        """Transform a single pixel point to the real-world plane (X, Y)
        in metres. Uses the standard perspective division.
        """
        vec = self._H @ np.array([u, v, 1.0])
        w = vec[2]
        if abs(w) < 1e-9:
            return 0.0, 0.0
        return float(vec[0] / w), float(vec[1] / w)

    def pixel_distance_meters(
        self,
        u1: float, v1: float,
        u2: float, v2: float,
    ) -> float:
        """Distance in metres between two pixel points. This is the
        primitive the speed calculation needs.
        """
        x1, y1 = self.pixel_to_meters(u1, v1)
        x2, y2 = self.pixel_to_meters(u2, v2)
        dx = x2 - x1
        dy = y2 - y1
        return float(np.sqrt(dx * dx + dy * dy))

    @property
    def intersection_id(self) -> str:
        return self._intersection_id

    @property
    def max_residual_m(self) -> float:
        return self._max_residual_m
