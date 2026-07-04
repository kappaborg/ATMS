"""Driver-behaviour detection (speeding, wrong-way) and cross-detection
consistency: flags, the violations list, and the frame annotation all agree."""
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import math

from behavior import DriverBehavior, ErraticDriving, RedLightDetector
from detection import Detection, FrameResult, annotate
from incidents import IncidentDetector
from scene import SceneConfig
import numpy as np


_SL = [{"approach": "ns", "points": [[0, 100], [200, 100]]}]  # horizontal line at y=100


def test_red_light_flagged_on_red_crossing():
    det = RedLightDetector()
    det.update([V(1, (50, 80))], 0.0, _SL, lambda a: True)
    viol, ids = det.update([V(1, (50, 120))], 1.0, _SL, lambda a: True)  # cross while RED
    assert 1 in ids and viol and viol[0]["type"] == "red_light"


def test_red_light_not_flagged_on_green():
    det = RedLightDetector()
    det.update([V(2, (50, 80))], 0.0, _SL, lambda a: False)
    _, ids = det.update([V(2, (50, 120))], 1.0, _SL, lambda a: False)  # cross while GREEN
    assert 2 not in ids


def test_red_light_needs_a_crossing():
    det = RedLightDetector()
    det.update([V(3, (10, 80))], 0.0, _SL, lambda a: True)
    _, ids = det.update([V(3, (190, 80))], 1.0, _SL, lambda a: True)  # never crosses the line
    assert 3 not in ids


def test_scene_parses_and_serialises_stop_lines():
    sc = SceneConfig.from_payload({"stop_lines": [{"approach": "ns", "points": [[10, 20], [30, 40]]}]})
    assert len(sc.stop_lines) == 1 and sc.stop_lines[0]["approach"] == "ns"
    assert sc.to_payload()["stop_lines"][0]["points"] == [[10.0, 20.0], [30.0, 40.0]]


def test_scene_rejects_bad_stop_line():
    import pytest
    with pytest.raises(ValueError):
        SceneConfig.from_payload({"stop_lines": [{"approach": "ns", "points": [[1, 2]]}]})  # 1 point


@dataclass
class V:
    track_id: int
    center: tuple
    speed_kmh: float | None = None
    approach: str = "ns"


def _establish_flow(det, direction=(5, 0), n=10):
    # Pass ALL vehicles each frame (as the worker does) — passing one at a time
    # would prune the others' motion state.
    for f in range(n):
        vs = [V(tid, (20 + f * direction[0] + tid * 40, 100 + f * direction[1])) for tid in range(4)]
        det.update(vs, float(f))


def test_speeding_over_limit_only():
    det = DriverBehavior(speed_limit_kmh=50)
    _, sp, _ = det.update([V(1, (0, 0), speed_kmh=70), V(2, (0, 0), speed_kmh=40)], 0.0)
    assert 1 in sp and 2 not in sp


def test_speeding_needs_speed():
    det = DriverBehavior(speed_limit_kmh=50)
    _, sp, _ = det.update([V(1, (0, 0), speed_kmh=None)], 0.0)  # uncalibrated
    assert not sp


def test_wrong_way_against_learned_flow():
    det = DriverBehavior()
    _establish_flow(det, (5, 0))  # flow is +x
    wr = set()
    for f in range(8):
        _, _, wr = det.update([V(9, (300 - f * 6, 120))], 100.0 + f)  # moving -x
    assert 9 in wr


def test_wrong_way_disabled_when_uncalibrated():
    # With wrong_way=False (no real approach zones) it must never fire, even
    # for a vehicle moving against the (would-be) flow.
    det = DriverBehavior()
    for f in range(10):
        vs = [V(tid, (20 + f * 5 + tid * 40, 100)) for tid in range(4)]
        det.update(vs, float(f), wrong_way=False)
    wr = set()
    for f in range(8):
        _, _, wr = det.update([V(9, (300 - f * 6, 120))], 100.0 + f, wrong_way=False)
    assert not wr


def test_forward_vehicle_not_wrong_way():
    det = DriverBehavior()
    _establish_flow(det, (5, 0))
    wr = set()
    for f in range(8):
        _, _, wr = det.update([V(9, (50 + f * 5, 120))], 100.0 + f)  # moving +x
    assert 9 not in wr


def test_detections_flags_match_violation_list():
    """The worker sets d.stopped/speeding/wrong_way from the same ids used to
    build the violations list — verify they can't disagree."""
    inc = IncidentDetector(stop_seconds=2.0)
    beh = DriverBehavior(speed_limit_kmh=50)
    # one speeder (id 1), one forward (id 2)
    vehicles = [V(1, (0, 0), speed_kmh=80), V(2, (10, 0), speed_kmh=30)]
    incidents, stopped = inc.update(vehicles, 0.0)
    bviol, speeding, wrong = beh.update(vehicles, 0.0)
    violations = [{"type": "stopped_vehicle", "track_id": i["track_id"]} for i in incidents] + bviol
    flagged_ids = stopped | speeding | wrong
    listed_ids = {v["track_id"] for v in violations}
    assert flagged_ids == listed_ids  # perfect agreement


def _run_erratic(path):
    det = ErraticDriving()
    ids = set()
    for i, (x, y) in enumerate(path):
        _, ids = det.update([V(1, (x, y))], float(i))
    return 1 in ids


def test_weaving_is_reckless():
    weave = [(i * 10, 100 + (20 if i % 2 == 0 else -20)) for i in range(20)]
    assert _run_erratic(weave)


def test_straight_line_not_reckless():
    assert not _run_erratic([(i * 10, 100) for i in range(20)])


def test_smooth_turn_not_reckless():
    # A legitimate turn is a monotonic heading change — must NOT be flagged.
    turn = [(math.cos(t) * 100 + 100, math.sin(t) * 100 + 100) for t in [i * 0.15 for i in range(20)]]
    assert not _run_erratic(turn)


def test_annotation_uses_most_severe_flag():
    d = Detection(1, 2, "car", 0.9, (10, 10, 40, 40), speed_kmh=80,
                  stopped=True, speeding=True, wrong_way=True)
    frame = np.zeros((80, 80, 3), dtype=np.uint8)
    annotate(frame, FrameResult([d], 1, 0), "GREEN", 30.0)  # must not raise; wrong-way wins
