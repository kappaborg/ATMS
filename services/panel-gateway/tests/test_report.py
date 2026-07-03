"""Session report accumulation + CSV export."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from report import SessionReport


def test_summary_accumulates_kpis():
    r = SessionReport("cam1", snapshot_interval_s=1.0)
    for i in range(5):
        r.record(vehicles_in_frame=i + 1, pedestrians_in_frame=0, incident_ids=[], emissions=None, t=float(i))
    r.record(3, 0, [7], None, 5.0)  # one incident (track 7)
    r.record(3, 0, [7], None, 6.0)  # same incident id -> still 1 unique
    em = {"vehicles": 12, "total_co2_kg": 1.5, "idle_co2_kg": 0.4, "est_saved_kg": 0.06,
          "avg_g_per_km": 150.0, "savings_ratio": 0.15}
    s = r.summary(em, now=6.0)
    assert s["camera_id"] == "cam1"
    assert s["peak_vehicles_in_frame"] == 5
    assert s["incidents_total"] == 1
    assert s["unique_vehicles"] == 12
    assert s["measured_co2_kg"] == 1.5
    assert s["estimated_saved_kg"] == 0.06
    assert s["duration_s"] == 6


def test_csv_has_summary_and_timeseries():
    r = SessionReport("cam1", snapshot_interval_s=1.0)
    for i in range(4):
        r.record(2, 0, [], {"total_co2_kg": 0.1 * i, "rate_kg_h": 1.0}, float(i))
    csv_text = r.to_csv({"vehicles": 4, "total_co2_kg": 0.3, "idle_co2_kg": 0.0,
                         "est_saved_kg": 0.0, "avg_g_per_km": 120.0, "savings_ratio": 0.15}, now=4.0)
    assert "metric,value" in csv_text
    assert "measured_co2_kg" in csv_text
    assert "timestamp_epoch,vehicles" in csv_text  # time-series header
    # estimate is labelled, not presented as raw measurement
    assert "estimated_saved_kg is a model" in csv_text


def test_empty_report_is_safe():
    r = SessionReport("cam1")
    s = r.summary(None, now=10.0)
    assert s["duration_s"] == 0
    assert s["unique_vehicles"] == 0
    assert "metric,value" in r.to_csv(None, now=10.0)
