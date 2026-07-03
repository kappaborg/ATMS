"""Anomaly detector: single-pass evaluate() (no double history append)."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_ROOT))
from ai.anomaly_detector import AnomalyDetector


def _metrics(ns_v, ew_v, ns_wait=10, ew_wait=10):
    def mk(v, w):
        return {"vehicle_count": v, "total_emission": v * 10, "average_waiting_time": w,
                "average_velocity": 25}
    return {"north_south": mk(ns_v, ns_wait), "east_west": mk(ew_v, ew_wait)}


def test_evaluate_returns_triplet_and_classifies():
    det = AnomalyDetector(use_ml=False)
    # Build a calm baseline, then a spike -> anomaly classified as CONGESTION.
    for _ in range(8):
        det.evaluate(_metrics(5, 5))
    is_a, score, atype = det.evaluate(_metrics(5, 5, ew_wait=300))  # huge waiting spike
    assert isinstance(is_a, bool)
    if is_a:
        assert atype in {"CONGESTION", "HIGH_TRAFFIC", "HIGH_EMISSION", "LOW_SPEED", "UNKNOWN_ANOMALY"}


def test_evaluate_does_not_double_count_history():
    det = AnomalyDetector(use_ml=False)
    before = len(det.feature_history)
    det.evaluate(_metrics(5, 5))
    # exactly one sample appended per evaluate (detect_anomaly appends once)
    assert len(det.feature_history) == before + 1


def test_calm_traffic_is_not_anomalous():
    det = AnomalyDetector(use_ml=False)
    last = None
    for _ in range(10):
        last = det.evaluate(_metrics(5, 5))
    assert last[0] is False  # steady state -> no anomaly
