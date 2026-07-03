"""SystemState: latest-decision tracking + staleness."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from system_state import SystemState


def test_no_decision_returns_none():
    s = SystemState()
    assert s.get("1") is None


def test_latest_decision_surfaced():
    s = SystemState(staleness_s=5.0)
    s.on_decision({"intersection_id": "1", "commanded_phase": "ns_green", "priority": "HIGH"})
    d = s.get("1")
    assert d["commanded_phase"] == "ns_green"
    assert d["priority"] == "HIGH"
    assert d["stale"] is False
    assert d["source"] == "decision-engine"


def test_newer_decision_replaces_older():
    s = SystemState()
    s.on_decision({"intersection_id": "1", "commanded_phase": "ns_green"})
    s.on_decision({"intersection_id": "1", "commanded_phase": "ew_green"})
    assert s.get("1")["commanded_phase"] == "ew_green"


def test_goes_stale_after_window():
    s = SystemState(staleness_s=0.05)
    s.on_decision({"intersection_id": "1", "commanded_phase": "ns_green"})
    time.sleep(0.1)
    assert s.get("1")["stale"] is True  # controller stream silent -> flagged stale


def test_per_intersection_isolation():
    s = SystemState()
    s.on_decision({"intersection_id": "1", "commanded_phase": "ns_green"})
    s.on_decision({"intersection_id": "2", "commanded_phase": "all_red"})
    assert s.get("1")["commanded_phase"] == "ns_green"
    assert s.get("2")["commanded_phase"] == "all_red"
    assert s.get("3") is None
