"""Emergency-vehicle preemption: forces an approach to green, respects
clearance, and releases back to demand."""
from ai_decision_system import AIDecisionEngine, DecisionPriority


def _f(n, v=25):
    return {"vehicle_count": n, "average_emission": 100.0, "average_waiting_time": 10.0,
            "average_velocity": v, "environmental_impact_score": 30.0}


def _run(eng, t, ns, ew, steps, step_s=6.0):
    d = None
    for _ in range(steps):
        t[0] += step_s
        d = eng.make_decision(_f(ns), _f(ew))
        eng.execute_decision(d)
    return d


def test_preemption_overrides_demand():
    t = [0.0]
    eng = AIDecisionEngine(now_fn=lambda: t[0], min_green_s=5, yellow_s=3, all_red_s=2)
    _run(eng, t, 1, 20, 6)  # E-W heavily loaded -> E-W green
    assert eng.active_direction == "east_west"
    eng.request_preemption("north_south")  # ambulance from the empty N-S approach
    d = _run(eng, t, 1, 20, 8)
    assert eng.active_direction == "north_south"  # forced green despite no demand
    assert d.priority == DecisionPriority.EMERGENCY
    assert "PREEMPTION" in d.reason


def test_preemption_releases_to_demand():
    t = [0.0]
    eng = AIDecisionEngine(now_fn=lambda: t[0], min_green_s=5, yellow_s=3, all_red_s=2)
    eng.request_preemption("north_south")
    _run(eng, t, 1, 20, 6)
    eng.clear_preemption()
    _run(eng, t, 1, 20, 10)
    assert eng.active_direction == "east_west"  # demand wins again


def test_preemption_auto_expires():
    t = [0.0]
    eng = AIDecisionEngine(now_fn=lambda: t[0])
    eng.request_preemption("east_west", hold_s=10)
    assert eng._preemption_active() == "east_west"
    t[0] += 11
    assert eng._preemption_active() is None  # auto-cleared


def test_invalid_direction_rejected():
    eng = AIDecisionEngine()
    import pytest

    with pytest.raises(ValueError):
        eng.request_preemption("diagonal")
