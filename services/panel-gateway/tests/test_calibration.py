"""
Calibration + speed math verification against a known synthetic scene.

Since we can't validate against a physical camera here, these tests prove the
math recovers ground truth exactly: a homography built from 4 correspondences
reprojects with ~0 error, round-trips points, and the speed estimator recovers
known constant speeds. On a real camera, accuracy then depends only on the
operator's reference-point quality (surfaced as reprojection_error_m).

Run:  python -m pytest services/panel-gateway/tests -q
      (needs numpy + opencv-python + the gateway src on sys.path)
"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from calibration import ApproachZones, GroundPlaneCalibration, SpeedEstimator

# A perspective view of a 12m-wide x 40m-long road segment.
IMG = [(100, 600), (1180, 600), (400, 250), (880, 250)]
WORLD = [(0, 0), (12, 0), (0, 40), (12, 40)]


def _world_to_img():
    H = cv2.findHomography(np.array(WORLD, float), np.array(IMG, float))[0]

    def f(xw, yw):
        p = H @ np.array([xw, yw, 1.0])
        return p[0] / p[2], p[1] / p[2]

    return f


def test_reprojection_is_near_zero():
    calib = GroundPlaneCalibration(IMG, WORLD)
    assert calib.reprojection_error_m < 0.01


def test_point_round_trips():
    calib = GroundPlaneCalibration(IMG, WORLD)
    w2i = _world_to_img()
    ix, iy = w2i(6, 20)
    gx, gy = calib.to_ground(ix, iy)
    assert abs(gx - 6) < 0.05 and abs(gy - 20) < 0.05


def test_speed_recovers_ground_truth():
    calib = GroundPlaneCalibration(IMG, WORLD)
    w2i = _world_to_img()
    for truth_mps, tid in ((10.0, 1), (20.0, 2)):
        est = SpeedEstimator(calib, window_s=0.6)
        samples = []
        for i in range(40):
            t = i / 30.0
            ix, iy = w2i(6.0, truth_mps * t)  # centreline, constant speed
            s = est.update(tid, ix, iy, t)
            if s is not None:
                samples.append(s)
        mean = sum(samples) / len(samples)
        assert abs(mean - truth_mps * 3.6) < 2.0  # within 2 km/h of truth


def test_impossible_jump_rejected():
    calib = GroundPlaneCalibration(IMG, WORLD)
    est = SpeedEstimator(calib, window_s=0.6, max_kmh=200)
    w2i = _world_to_img()
    est.update(1, *w2i(0, 0), 0.0)
    # teleport 40 m in 20 ms -> 7200 km/h -> must be rejected
    assert est.update(1, *w2i(0, 40), 0.02) is None


def test_zone_classification():
    zones = ApproachZones(
        {
            "north": [(0, 0), (640, 0), (640, 360), (0, 360)],
            "south": [(0, 360), (640, 360), (640, 720), (0, 720)],
        }
    )
    assert zones.classify(100, 100) == "north"
    assert zones.classify(100, 500) == "south"
    assert zones.classify(700, 100) is None


def test_scene_payload_roundtrips():
    """A scene serialised for persistence must rebuild identically (so an
    operator's calibration survives a gateway restart)."""
    from scene import SceneConfig

    payload = {
        "calibration": {"image_points": IMG, "world_points_m": WORLD},
        "zones": {"north": [[0, 0], [640, 0], [640, 720], [0, 720]]},
        "zone_directions": {"north": "ns"},
    }
    scene = SceneConfig.from_payload(payload)
    out = scene.to_payload()
    # calibration points preserved
    assert out["calibration"]["image_points"] == [list(p) for p in IMG]
    assert out["calibration"]["world_points_m"] == [list(p) for p in WORLD]
    # zones + directions preserved; rebuilding again is stable
    assert out["zones"]["north"] == [[0, 0], [640, 0], [640, 720], [0, 720]]
    assert out["zone_directions"] == {"north": "ns"}
    assert SceneConfig.from_payload(out).info()["calibrated"] is True
