"""Transit signal priority: a detected bus gets SOFT priority — enough to
help it through, but heavy cross-demand still overrides it (unlike the hard
emergency preemption)."""
from ai_decision_system import AIDecisionEngine


def _f(n, bus=False):
    return {"vehicle_count": n, "average_emission": 100.0, "average_waiting_time": 10.0,
            "average_velocity": 25.0, "environmental_impact_score": 30.0, "transit_present": bus}


def test_bus_wins_equal_demand():
    eng = AIDecisionEngine()
    assert eng._calculate_direction_score(_f(3, bus=True)) > eng._calculate_direction_score(_f(3))


def test_bus_priority_is_soft_not_override():
    eng = AIDecisionEngine()
    # Heavy demand (18) beats a bus on a near-empty approach (2) — soft, not hard.
    assert eng._calculate_direction_score(_f(18)) > eng._calculate_direction_score(_f(2, bus=True))


def test_transit_surfaced_in_decision():
    eng = AIDecisionEngine()
    d = eng.make_decision(_f(3), _f(3, bus=True))
    assert "Transit priority" in d.reason
    assert d.expected_impact.get("transit_priority") == "E-W"
    assert eng._last_transit == {"north_south": False, "east_west": True}


def test_no_bus_no_priority():
    eng = AIDecisionEngine()
    d = eng.make_decision(_f(4), _f(4))
    assert "Transit priority" not in d.reason
    assert eng._last_transit == {"north_south": False, "east_west": False}


def test_bus_bonus_equals_transit_weight():
    # The bonus is exactly transit_weight (a bus ~= this much score; at 0.2 it's
    # worth ~13 cars of demand — defensible by person-throughput: 1 bus ≈ 40
    # people ≈ 25+ cars). Heavy congestion still overrides it (test above).
    eng = AIDecisionEngine(transit_weight=0.2)
    base = eng._calculate_direction_score(_f(5))
    with_bus = eng._calculate_direction_score(_f(5, bus=True))
    assert abs((with_bus - base) - 0.2) < 1e-6


def test_transit_weight_is_configurable():
    # A smaller weight yields weaker priority (a bus no longer beats 10 cars).
    low = AIDecisionEngine(transit_weight=0.05)
    assert low._calculate_direction_score(_f(10)) > low._calculate_direction_score(_f(1, bus=True))
