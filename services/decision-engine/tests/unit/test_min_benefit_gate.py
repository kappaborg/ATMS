"""Minimum-benefit switch gate: don't pay clearance to switch green for a
couple of cars while the current approach is still flowing — but do switch
when it has gapped out (empty) or when real demand is waiting."""
from ai_decision_system import AIDecisionEngine


def _eng():
    # active_direction starts north_south, current_phase GREEN.
    return AIDecisionEngine(min_switch_vehicles=3, switch_threshold=1.2)


def test_holds_green_for_trivial_waiting_demand():
    eng = _eng()  # N-S holds green
    # E-W wins on ratio (2 vs 1) but only 2 cars wait while N-S still flows.
    assert eng._rule_based_wants_switch(
        "east_west", priority_score=0.6, other_score=0.4,
        waiting_vehicles=2, current_vehicles=1,
    ) is False


def test_switches_when_current_approach_gapped_out():
    eng = _eng()  # N-S green but empty
    # Even 1 car waiting justifies a switch when the green approach is empty.
    assert eng._rule_based_wants_switch(
        "east_west", priority_score=0.6, other_score=0.0,
        waiting_vehicles=1, current_vehicles=0,
    ) is True


def test_switches_for_real_waiting_demand():
    eng = _eng()
    assert eng._rule_based_wants_switch(
        "east_west", priority_score=0.9, other_score=0.3,
        waiting_vehicles=8, current_vehicles=2,
    ) is True


def test_gate_does_not_override_hysteresis():
    eng = _eng()
    # Big waiting queue but ratio doesn't clear threshold -> still no switch.
    assert eng._rule_based_wants_switch(
        "east_west", priority_score=0.5, other_score=0.45,
        waiting_vehicles=20, current_vehicles=18,
    ) is False


def test_default_call_keeps_pure_ratio_behaviour():
    # Callers that don't pass counts (waiting defaults high) keep old behaviour.
    eng = _eng()
    assert eng._rule_based_wants_switch("east_west", 0.6, 0.4) is True
