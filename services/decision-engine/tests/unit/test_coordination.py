"""Green-wave coordination: a bounded bias toward the corridor direction while
the corridor clock is in this intersection's green band; heavy demand overrides."""
from ai_decision_system import AIDecisionEngine


def _f(n):
    return {"vehicle_count": n, "average_emission": 100.0, "average_waiting_time": 10.0,
            "average_velocity": 25.0, "environmental_impact_score": 30.0}


def test_bias_only_inside_green_band():
    t = [0.0]
    eng = AIDecisionEngine(now_fn=lambda: t[0])
    eng.set_coordination(offset_s=0.0, cycle_s=60.0, green_s=27.0, direction="north_south")
    t[0] = 10.0
    assert eng._coordination_direction() == "north_south"  # phase 10 < 27
    t[0] = 40.0
    assert eng._coordination_direction() is None  # phase 40 >= 27
    t[0] = 70.0
    assert eng._coordination_direction() == "north_south"  # wraps: phase 10


def test_offset_shifts_the_band():
    t = [0.0]
    eng = AIDecisionEngine(now_fn=lambda: t[0])
    eng.set_coordination(offset_s=30.0, cycle_s=60.0, green_s=27.0, direction="east_west")
    t[0] = 10.0
    assert eng._coordination_direction() is None  # before the band (offset 30)
    t[0] = 35.0
    assert eng._coordination_direction() == "east_west"  # phase 5 within band


def test_coordination_surfaces_and_is_bounded():
    t = [10.0]
    eng = AIDecisionEngine(now_fn=lambda: t[0])
    eng.set_coordination(0.0, 60.0, 27.0, "north_south")
    d = eng.make_decision(_f(4), _f(4))
    assert "Green-wave" in d.reason and d.expected_impact.get("coordination") == "north_south"
    # bounded: heavy cross demand overrides the coordination bias
    ns = eng._calculate_direction_score(_f(3)) + eng.coordination_weight
    ew = eng._calculate_direction_score(_f(18))
    assert ew > ns


def test_clear_coordination():
    t = [10.0]
    eng = AIDecisionEngine(now_fn=lambda: t[0])
    eng.set_coordination(0.0, 60.0, 27.0, "north_south")
    eng.clear_coordination()
    assert eng._coordination_direction() is None
