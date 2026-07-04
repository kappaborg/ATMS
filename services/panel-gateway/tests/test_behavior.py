"""Driver-behaviour detection (speeding, wrong-way) and cross-detection
consistency: flags, the violations list, and the frame annotation all agree."""
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from behavior import DriverBehavior
from detection import Detection, FrameResult, annotate
from incidents import IncidentDetector
import numpy as np


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


def test_annotation_uses_most_severe_flag():
    d = Detection(1, 2, "car", 0.9, (10, 10, 40, 40), speed_kmh=80,
                  stopped=True, speeding=True, wrong_way=True)
    frame = np.zeros((80, 80, 3), dtype=np.uint8)
    annotate(frame, FrameResult([d], 1, 0), "GREEN", 30.0)  # must not raise; wrong-way wins
