"""
Scene calibration for the panel gateway.

Turns pixel measurements into real-world ones so the panel reports defensible
numbers instead of frame-relative stand-ins:

  * GroundPlaneCalibration — a homography mapping image pixels to a flat
    ground plane in metres (bird's-eye). Built from >=4 point correspondences
    the operator marks on the scene (e.g. lane-marking corners with known
    spacing). This is the standard planar-homography approach; it is accurate
    for vehicles on the road surface and is the honest way to measure speed
    from a single fixed camera.

  * SpeedEstimator — per-track speed from ground-plane displacement over a
    short time window (robust to per-frame jitter), pruned when a track ends.

  * ApproachZones — named polygons classifying a point into an approach
    (e.g. "north", "east"), so per-approach counts are real rather than a
    left/right-of-centre split.

Calibration quality is only as good as the reference points; the API records
a reprojection-error estimate so operators can see how trustworthy it is.
"""
from __future__ import annotations

from collections import deque

import cv2
import numpy as np


class GroundPlaneCalibration:
    def __init__(
        self,
        image_points: list[tuple[float, float]],
        world_points_m: list[tuple[float, float]],
    ) -> None:
        if len(image_points) < 4 or len(world_points_m) != len(image_points):
            raise ValueError("need >=4 matching image/world point pairs")
        self.image_points = image_points
        self.world_points_m = world_points_m
        img = np.array(image_points, dtype=np.float64)
        wrl = np.array(world_points_m, dtype=np.float64)
        H, _ = cv2.findHomography(img, wrl, method=0)
        if H is None:
            raise ValueError("homography could not be computed (degenerate points?)")
        self.H = H
        self.reprojection_error_m = self._reprojection_error(img, wrl)

    def _reprojection_error(self, img: np.ndarray, wrl: np.ndarray) -> float:
        proj = self.to_ground_many(img)
        return float(np.sqrt(((proj - wrl) ** 2).sum(axis=1)).mean())

    def to_ground(self, x: float, y: float) -> tuple[float, float]:
        p = self.H @ np.array([x, y, 1.0])
        return float(p[0] / p[2]), float(p[1] / p[2])

    def to_ground_many(self, pts: np.ndarray) -> np.ndarray:
        n = pts.shape[0]
        homog = np.hstack([pts, np.ones((n, 1))])
        proj = (self.H @ homog.T).T
        return proj[:, :2] / proj[:, 2:3]


class SpeedEstimator:
    """Per-track ground-plane speed, averaged over a time window for stability.

    Uses timestamps (not frame counts) so it is correct under variable FPS.
    """

    def __init__(self, calib: GroundPlaneCalibration, window_s: float = 0.6, max_kmh: float = 250.0):
        self.calib = calib
        self.window_s = window_s
        self.max_kmh = max_kmh
        # track_id -> deque[(t, x_m, y_m)]
        self._hist: dict[int, deque] = {}

    def update(self, track_id: int, cx: float, cy: float, t: float) -> float | None:
        xm, ym = self.calib.to_ground(cx, cy)
        hist = self._hist.setdefault(track_id, deque(maxlen=32))
        hist.append((t, xm, ym))
        # drop samples older than the window
        while len(hist) > 2 and t - hist[0][0] > self.window_s:
            hist.popleft()
        if len(hist) < 2:
            return None
        t0, x0, y0 = hist[0]
        dt = t - t0
        if dt <= 1e-3:
            return None
        dist_m = float(np.hypot(xm - x0, ym - y0))
        kmh = (dist_m / dt) * 3.6
        if kmh > self.max_kmh:  # reject impossible jumps (bad track association)
            return None
        return round(kmh, 1)

    def remove(self, track_id: int) -> None:
        self._hist.pop(track_id, None)

    def prune(self, live_ids: set[int]) -> None:
        for tid in list(self._hist):
            if tid not in live_ids:
                del self._hist[tid]


class ApproachZones:
    """Named polygons over the image; classify a point into an approach."""

    def __init__(self, zones: dict[str, list[tuple[float, float]]]):
        self.zones = {
            name: np.array(poly, dtype=np.int32)
            for name, poly in zones.items()
            if len(poly) >= 3
        }

    def classify(self, x: float, y: float) -> str | None:
        pt = (float(x), float(y))
        for name, poly in self.zones.items():
            if cv2.pointPolygonTest(poly, pt, False) >= 0:
                return name
        return None

    @property
    def names(self) -> list[str]:
        return list(self.zones)
