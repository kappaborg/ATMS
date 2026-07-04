"""Stopped-vehicle incident detection."""
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


def test_stationary_vehicle_flagged():
    det = IncidentDetector(stop_seconds=5.0, move_threshold_px=18.0)
    inc = []
    for i in range(10):
        t = i * 1.0
        inc, stopped = det.update([V(1, (100.0, 100.0))], t)  # never moves
    assert any(x["type"] == "stopped_vehicle" and x["track_id"] == 1 for x in inc)
    assert inc[0]["seconds"] >= 5.0
    assert 1 in stopped


def test_moving_vehicle_not_flagged():
    det = IncidentDetector(stop_seconds=5.0, move_threshold_px=18.0)
    stopped = set()
    for i in range(10):
        t = i * 1.0
        _, stopped = det.update([V(1, (100.0 + i * 40, 100.0))], t)  # moves each frame
    assert 1 not in stopped


def test_congestion_suppresses_stops():
    # A queue of stopped cars (red light / jam) must NOT flag as incidents.
    det = IncidentDetector(stop_seconds=5.0, move_threshold_px=18.0)
    fleet = [V(i, (100.0, 100.0 + i * 30)) for i in range(6)]  # 6 stationary cars
    inc, stopped = [], set()
    for k in range(10):
        inc, stopped = det.update(fleet, k * 1.0)
    assert inc == [] and not stopped  # congestion -> suppressed


def test_lone_stall_amid_moving_traffic_still_flags():
    # One stopped car while others drive past IS an incident.
    det = IncidentDetector(stop_seconds=5.0, move_threshold_px=18.0)
    stopped = set()
    for k in range(10):
        moving = [V(10 + j, (200.0 + j * 40 + k * 60, 100.0)) for j in range(4)]  # 4 moving
        _, stopped = det.update([V(1, (100.0, 100.0))] + moving, k * 1.0)  # car 1 stuck
    assert 1 in stopped


def test_lone_stall_on_empty_road_flags():
    # A single stalled car (no queue) still flags — congestion gate needs >=3.
    det = IncidentDetector(stop_seconds=5.0, move_threshold_px=18.0)
    inc = []
    for k in range(10):
        inc, _ = det.update([V(1, (100.0, 100.0))], k * 1.0)
    assert any(x["track_id"] == 1 for x in inc)


def test_resets_when_it_moves_again():
    det = IncidentDetector(stop_seconds=3.0, move_threshold_px=18.0)
    # sit still long enough to flag
    for i in range(5):
        inc, stopped = det.update([V(1, (100.0, 100.0))], i * 1.0)
    assert 1 in stopped
    # then move far -> clock resets, not flagged next frame
    _, stopped = det.update([V(1, (400.0, 100.0))], 5.0)
    assert 1 not in stopped


def test_track_end_is_pruned():
    det = IncidentDetector(stop_seconds=2.0)
    det.update([V(1, (100.0, 100.0))], 0.0)
    det.update([], 5.0)  # track gone
    assert 1 not in det._tracks
