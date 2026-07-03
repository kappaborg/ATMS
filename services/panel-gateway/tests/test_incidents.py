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
