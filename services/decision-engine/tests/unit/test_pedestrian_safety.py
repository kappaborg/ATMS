"""Pedestrian safety: hold the all-red clearance while a pedestrian is in the
roadway (bounded), so cross-traffic is never released into someone crossing."""
from ai_decision_system import AIDecisionEngine, TrafficPhase


def _f(n):
    return {"vehicle_count": n, "average_emission": 100.0, "average_waiting_time": 10.0,
            "average_velocity": 25.0, "environmental_impact_score": 30.0}


def _eng():
    t = [0.0]
    return AIDecisionEngine(now_fn=lambda: t[0], min_green_s=5, yellow_s=3,
                            all_red_s=2, max_ped_extend_s=6), t


def _tick(eng, t, ped):
    """Always demand the approach OPPOSITE the current green, so the engine
    keeps cycling green -> yellow -> all-red -> green (and re-enters ALL_RED)."""
    t[0] += 1
    ns, ew = (_f(1), _f(15)) if eng.active_direction == "north_south" else (_f(15), _f(1))
    eng.execute_decision(eng.make_decision(ns, ew, pedestrian_present=ped))
    return eng.current_phase


def _all_red_ticks(eng, t, ped, n=40):
    return sum(1 for _ in range(n) if _tick(eng, t, ped) == TrafficPhase.ALL_RED)


def test_clearance_extends_while_pedestrian_present():
    e1, t1 = _eng()
    e2, t2 = _eng()
    with_ped = _all_red_ticks(e1, t1, ped=True)
    without = _all_red_ticks(e2, t2, ped=False)
    assert with_ped > without  # pedestrian holds all-red longer


def test_extension_is_bounded():
    # Even with a pedestrian present forever, a single all-red phase can't
    # exceed base (2) + cap (6) = 8s — the intersection is never stalled.
    eng, t = _eng()
    run = longest = 0
    for _ in range(80):
        if _tick(eng, t, ped=True) == TrafficPhase.ALL_RED:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    assert 0 < longest <= 9  # <= base+cap (+1 tick tolerance)


def test_pedestrian_hold_surfaced_in_reason():
    eng, t = _eng()
    saw = False
    for _ in range(40):
        t[0] += 1
        ns, ew = (_f(1), _f(15)) if eng.active_direction == "north_south" else (_f(15), _f(1))
        d = eng.make_decision(ns, ew, pedestrian_present=True)
        eng.execute_decision(d)
        if eng._ped_hold_active:
            assert "pedestrian clearance" in d.reason.lower()
            assert d.expected_impact.get("pedestrian_clearance") is True
            saw = True
    assert saw


def test_no_hold_without_pedestrian():
    eng, t = _eng()
    for _ in range(40):
        t[0] += 1
        ns, ew = (_f(1), _f(15)) if eng.active_direction == "north_south" else (_f(15), _f(1))
        d = eng.make_decision(ns, ew, pedestrian_present=False)
        eng.execute_decision(d)
        assert eng._ped_hold_active is False
        assert "pedestrian clearance" not in d.reason.lower()
