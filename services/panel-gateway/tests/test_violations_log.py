"""Violation evidence log: record, query, filter, retention prune, persistence."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from violations_log import ViolationsLog


def _seed(log):
    log.record(1000, "cam1", "1", 42, "speeding", "ABC123", {"speed_kmh": 75, "limit_kmh": 50}, "/tmp/x.jpg")
    log.record(1100, "cam1", "1", 7, "red_light", "XYZ999", {"approach": "ns"}, None)
    log.record(2000, "cam2", "2", 9, "drift", None, {"lateral_g": 1.2}, None)


def test_records_newest_first(tmp_path):
    log = ViolationsLog(str(tmp_path / "v.db"))
    _seed(log)
    rows = log.query(0, 3000)
    assert [r["type"] for r in rows] == ["drift", "red_light", "speeding"]  # ts DESC
    assert rows[2]["detail"]["speed_kmh"] == 75  # detail JSON round-trips
    assert rows[2]["has_snapshot"] is True and rows[0]["has_snapshot"] is False


def test_filters(tmp_path):
    log = ViolationsLog(str(tmp_path / "v.db"))
    _seed(log)
    assert log.query(0, 3000, vtype="speeding")[0]["plate"] == "ABC123"
    assert [r["type"] for r in log.query(0, 3000, camera_id="cam2")] == ["drift"]
    assert log.query(0, 1500) and len(log.query(0, 1050)) == 1  # time window


def test_snapshot_path(tmp_path):
    log = ViolationsLog(str(tmp_path / "v.db"))
    vid = log.record(1000, "c", "1", 1, "speeding", None, {}, "/snaps/1.jpg")
    assert log.snapshot_path(vid) == "/snaps/1.jpg"
    assert log.snapshot_path(9999) is None


def test_retention_prune_returns_snapshot_paths(tmp_path):
    log = ViolationsLog(str(tmp_path / "v.db"))
    _seed(log)
    paths = log.prune(1500)  # removes ts<1500 (both cam1 rows)
    assert paths == ["/tmp/x.jpg"]  # only the one that had a snapshot
    assert len(log.query(0, 3000)) == 1  # only the drift (ts 2000) remains


def test_sweep_enforces_retention_and_unlinks_snapshots(tmp_path):
    snap = tmp_path / "old.jpg"
    snap.write_bytes(b"jpeg")
    log = ViolationsLog(str(tmp_path / "v.db"))
    log.record(1000, "c", "1", 1, "speeding", "P1", {}, str(snap))       # old
    log.record(9_000_000, "c", "1", 2, "speeding", "P2", {}, None)      # recent
    # retention 30 days, "now" far past the first record
    n = log.sweep(retention_days=30, now=9_000_000 + 10)
    assert n == 1
    assert not snap.exists()  # snapshot file deleted with the row
    assert [r["track_id"] for r in log.query(0, 10_000_000)] == [2]


def test_sweep_noop_when_retention_off(tmp_path):
    log = ViolationsLog(str(tmp_path / "v.db"))
    log.record(1000, "c", "1", 1, "speeding", None, {}, None)
    assert log.sweep(retention_days=0, now=10_000_000) == 0
    assert len(log.query(0, 10_000_000)) == 1


def test_survives_reopen(tmp_path):
    p = str(tmp_path / "v.db")
    log = ViolationsLog(p)
    log.record(1000, "c", "1", 1, "speeding", "P1", {}, None)
    log.close()
    assert len(ViolationsLog(p).query(0, 2000)) == 1
