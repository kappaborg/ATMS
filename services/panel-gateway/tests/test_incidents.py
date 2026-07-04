"""Stopped-vehicle incident detection: parked / roadway / congestion gates."""
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from incidents import IncidentDetector


@dataclass
class V:
    track_id: int
    center: tuple
    label: str = "car"


def _drive_then_stall(det, tid=1, stop_at=(300.0, 100.0), extra=None, roadway=None):
    """Vehicle drives for 4 ticks, then stands still; returns last result."""
    inc, stopped = [], set()
    for k in range(14):
        pos = (100.0 + min(k, 4) * 50.0, 100.0) if k < 4 else stop_at
        fleet = [V(tid, pos)] + (extra(k) if extra else [])
        inc, stopped = det.update(fleet, k * 1.0, roadway_ids=roadway(fleet) if roadway else None)
    return inc, stopped


def test_stall_after_driving_flagged():
    det = IncidentDetector(stop_seconds=5.0, move_threshold_px=18.0)
    inc, stopped = _drive_then_stall(det)
    assert 1 in stopped
    assert any(x["type"] == "stopped_vehicle" and x["track_id"] == 1 for x in inc)


def test_parked_from_birth_never_flagged():
    # A car already stationary when first seen = PARKED, not an incident.
    det = IncidentDetector(stop_seconds=5.0, move_threshold_px=18.0)
    inc, stopped = [], set()
    for k in range(15):
        inc, stopped = det.update([V(1, (100.0, 100.0))], k * 1.0)
    assert not stopped and inc == []


def test_stop_outside_roadway_is_parking():
    # Drives then stops, but OUTSIDE the roadway zones -> parking, no flag.
    det = IncidentDetector(stop_seconds=5.0, move_threshold_px=18.0)
    inc, stopped = _drive_then_stall(det, roadway=lambda fleet: set())  # nobody in roadway
    assert not stopped and inc == []


def test_stop_inside_roadway_flags():
    det = IncidentDetector(stop_seconds=5.0, move_threshold_px=18.0)
    inc, stopped = _drive_then_stall(det, roadway=lambda fleet: {1})
    assert 1 in stopped


def test_moving_vehicle_not_flagged():
    det = IncidentDetector(stop_seconds=5.0, move_threshold_px=18.0)
    stopped = set()
    for i in range(10):
        _, stopped = det.update([V(1, (100.0 + i * 40, 100.0))], i * 1.0)
    assert 1 not in stopped


def test_congestion_suppresses_stops():
    # A queue: they all drive in, then ALL stand (red light) -> suppressed.
    det = IncidentDetector(stop_seconds=5.0, move_threshold_px=18.0)
    inc, stopped = [], set()
    for k in range(14):
        x = 100.0 + min(k, 4) * 50.0
        fleet = [V(i, (x, 100.0 + i * 30)) for i in range(6)]
        inc, stopped = det.update(fleet, k * 1.0)
    assert inc == [] and not stopped


def test_lone_stall_amid_moving_traffic_still_flags():
    det = IncidentDetector(stop_seconds=5.0, move_threshold_px=18.0)
    moving = lambda k: [V(10 + j, (200.0 + j * 40 + k * 60, 300.0)) for j in range(4)]  # noqa: E731
    inc, stopped = _drive_then_stall(det, extra=moving)
    assert 1 in stopped


def test_resets_when_it_moves_again():
    det = IncidentDetector(stop_seconds=3.0, move_threshold_px=18.0)
    # drive, stall long enough to flag...
    for k in range(4):
        det.update([V(1, (100.0 + k * 50, 100.0))], k * 1.0)
    stopped = set()
    for k in range(4, 9):
        _, stopped = det.update([V(1, (250.0, 100.0))], k * 1.0)
    assert 1 in stopped
    # ...then it moves off -> clock resets, not flagged next frame
    _, stopped = det.update([V(1, (500.0, 100.0))], 9.0)
    assert 1 not in stopped


def test_track_end_is_pruned():
    det = IncidentDetector(stop_seconds=2.0)
    det.update([V(1, (100.0, 100.0))], 0.0)
    det.update([], 5.0)  # track gone
    assert 1 not in det._tracks
