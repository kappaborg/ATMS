"""Long-horizon SQLite history: per-interval deltas, range totals, buckets,
and cross-'restart' aggregation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from history import HistoryStore


def test_totals_sum_intervals(tmp_path):
    s = HistoryStore(str(tmp_path / "h.db"))
    s.record_interval("cam", 1000, vehicles=10, co2_kg=1.0, saved_kg=0.1, incidents=1)
    s.record_interval("cam", 1060, vehicles=5, co2_kg=0.5, saved_kg=0.05, incidents=0)
    t = s.totals(0, 2000)
    assert t["vehicles"] == 15
    assert abs(t["co2_kg"] - 1.5) < 1e-9
    assert abs(t["saved_kg"] - 0.15) < 1e-9
    assert t["incidents"] == 1


def test_range_filter_excludes_outside(tmp_path):
    s = HistoryStore(str(tmp_path / "h.db"))
    s.record_interval("cam", 100, 5, 0.5, 0.0, 0)
    s.record_interval("cam", 5000, 7, 0.7, 0.0, 0)
    assert s.totals(0, 1000)["vehicles"] == 5  # only the first
    assert s.totals(0, 6000)["vehicles"] == 12


def test_camera_scope(tmp_path):
    s = HistoryStore(str(tmp_path / "h.db"))
    s.record_interval("a", 100, 3, 0.3, 0.0, 0)
    s.record_interval("b", 100, 9, 0.9, 0.0, 0)
    assert s.totals(0, 1000, camera_id="a")["vehicles"] == 3
    assert s.totals(0, 1000)["vehicles"] == 12  # both


def test_series_buckets(tmp_path):
    s = HistoryStore(str(tmp_path / "h.db"))
    # two intervals in the same hour, one in the next
    s.record_interval("cam", 3600, 4, 0.4, 0.0, 0)
    s.record_interval("cam", 3660, 6, 0.6, 0.0, 0)
    s.record_interval("cam", 7300, 2, 0.2, 0.0, 0)
    series = s.series(0, 10000, bucket_s=3600)
    assert len(series) == 2
    assert series[0]["vehicles"] == 10  # 4+6 in the first hour bucket
    assert series[1]["vehicles"] == 2


def test_survives_reopen(tmp_path):
    p = str(tmp_path / "h.db")
    s1 = HistoryStore(p)
    s1.record_interval("cam", 100, 8, 0.8, 0.0, 1)
    s1.close()
    # a "restart" — new store on the same file sees the persisted data
    s2 = HistoryStore(p)
    assert s2.totals(0, 1000)["vehicles"] == 8
    assert s2.totals(0, 1000)["incidents"] == 1
