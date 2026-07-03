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
    assert d["source"] == "atms-controller"


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


# --- failsafe mode ---

def test_mode_surfaced():
    s = SystemState()
    s.set_mode("1", "all_red_flash", reachable=True)
    d = s.get("1")
    assert d["mode"] == "all_red_flash"
    assert d["mode_reachable"] is True
    # mode alone (no decision) still returns a record
    assert d["commanded_phase"] is None


def test_mode_unreachable():
    s = SystemState()
    s.set_mode("1", None, reachable=False)
    d = s.get("1")
    assert d["mode"] is None
    assert d["mode_reachable"] is False


def test_mode_goes_stale():
    s = SystemState(mode_staleness_s=0.05)
    s.set_mode("1", "ai_adaptive", reachable=True)
    time.sleep(0.1)
    d = s.get("1")
    assert d["mode"] is None  # stale poll -> mode unknown
    assert d["mode_reachable"] is False


def test_decision_and_mode_merge():
    s = SystemState()
    s.on_decision({"intersection_id": "1", "commanded_phase": "ew_green", "priority": "HIGH"})
    s.set_mode("1", "ai_adaptive", reachable=True)
    d = s.get("1")
    assert d["commanded_phase"] == "ew_green"
    assert d["priority"] == "HIGH"
    assert d["mode"] == "ai_adaptive"
