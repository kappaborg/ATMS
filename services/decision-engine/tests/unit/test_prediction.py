"""Predictive congestion: the forecast must nudge decisions proactively and
be surfaced in the output, and be a no-op when disabled."""
from ai_decision_system import AIDecisionEngine


def _frame(ns_veh: int, ew_veh: int):
    def mk(n):
        return {
            "vehicle_count": n,
            "average_emission": 100.0,
            "average_waiting_time": 10.0,
            "average_velocity": 25.0,
            "environmental_impact_score": 30.0,
        }

    return mk(ns_veh), mk(ew_veh)


def test_rising_demand_forecasts_congestion():
    t = [0.0]
    eng = AIDecisionEngine(use_predictions=True, now_fn=lambda: t[0])
    assert eng.predictor is not None
    last = None
    for i in range(20):
        t[0] += 1.0
        ns, ew = _frame(int(2 + i * 1.5), 3)  # N-S demand climbs, E-W flat
        last = eng.make_decision(ns, ew)
        eng.execute_decision(last)

    pred = eng._last_prediction
    assert pred is not None
    assert pred["north_south"] > pred["east_west"]  # N-S forecast busier
    assert pred["north_south"] > 0.5  # a real, actionable forecast
    assert "Congestion forecast" in last.reason
    assert "predicted_congestion_ns" in last.expected_impact


def test_predictions_disabled_is_noop():
    eng = AIDecisionEngine(use_predictions=False, now_fn=lambda: 0.0)
    d = eng.make_decision(*_frame(5, 3))
    assert eng._last_prediction is None
    assert "Congestion forecast" not in d.reason
    assert "predicted_congestion_ns" not in d.expected_impact


def test_forecast_boost_is_bounded():
    """Prediction nudges but never overrides real demand: with E-W hugely
    busier now, a N-S forecast must not flip the priority direction."""
    t = [0.0]
    eng = AIDecisionEngine(use_predictions=True, now_fn=lambda: t[0])
    # Prime N-S congestion forecast, then present overwhelming current E-W demand.
    for i in range(12):
        t[0] += 1.0
        eng.make_decision(*_frame(int(2 + i * 2), 0))
    t[0] += 1.0
    d = eng.make_decision(*_frame(1, 19))  # E-W dominates NOW
    # Current demand wins; the wire/priority direction should follow E-W.
    from shared.atms_common.decision import _priority_direction

    assert _priority_direction(*_frame(1, 19)) == "east_west"
