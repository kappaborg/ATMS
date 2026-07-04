"""
Long-horizon metrics history for the panel — local, dependency-free SQLite.

The session report is in-memory (lost on restart). This store persists
per-interval DELTAS (vehicles, CO2, estimated savings, incidents accrued in
each interval) so the panel can answer "how much CO2 did we save this
month?" across restarts. Deltas (not cumulative snapshots) are stored so
range totals are a simple additive SUM and session resets can't corrupt them.

SQLite is the right fit for a self-contained desktop gateway (the full ATMS
stack uses TimescaleDB for the distributed services). Configure the file with
PANEL_HISTORY_DB; default sits next to PANEL_STATE_FILE.
"""
from __future__ import annotations

import os
import sqlite3
import threading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS intervals (
    camera_id  TEXT    NOT NULL,
    ts         INTEGER NOT NULL,   -- epoch seconds, interval end
    vehicles   INTEGER NOT NULL,
    co2_kg     REAL    NOT NULL,
    saved_kg   REAL    NOT NULL,
    incidents  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intervals_cam_ts ON intervals(camera_id, ts);
"""


def _default_db_path() -> str:
    env = os.getenv("PANEL_HISTORY_DB")
    if env:
        return env
    state = os.getenv("PANEL_STATE_FILE")
    if state:
        return os.path.join(os.path.dirname(os.path.abspath(state)) or ".", "panel_history.db")
    return "panel_history.db"


class HistoryStore:
    def __init__(self, path: str | None = None):
        self.path = path or _default_db_path()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def record_interval(
        self, camera_id: str, ts: int, vehicles: int, co2_kg: float,
        saved_kg: float, incidents: int,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO intervals VALUES (?,?,?,?,?,?)",
                (camera_id, int(ts), int(vehicles), float(co2_kg), float(saved_kg), int(incidents)),
            )
            self._conn.commit()

    def totals(self, since: int, until: int, camera_id: str | None = None) -> dict:
        q = ("SELECT COALESCE(SUM(vehicles),0), COALESCE(SUM(co2_kg),0), "
             "COALESCE(SUM(saved_kg),0), COALESCE(SUM(incidents),0) "
             "FROM intervals WHERE ts >= ? AND ts < ?")
        args: list = [since, until]
        if camera_id:
            q += " AND camera_id = ?"
            args.append(camera_id)
        with self._lock:
            v, c, s, i = self._conn.execute(q, args).fetchone()
        return {
            "vehicles": int(v), "co2_kg": round(c, 4),
            "saved_kg": round(s, 4), "incidents": int(i),
        }

    def series(self, since: int, until: int, bucket_s: int, camera_id: str | None = None) -> list[dict]:
        # Group interval rows into fixed-width time buckets.
        q = (f"SELECT (ts/{int(bucket_s)})*{int(bucket_s)} AS b, SUM(vehicles), "
             "SUM(co2_kg), SUM(saved_kg), SUM(incidents) "
             "FROM intervals WHERE ts >= ? AND ts < ?")
        args: list = [since, until]
        if camera_id:
            q += " AND camera_id = ?"
            args.append(camera_id)
        q += " GROUP BY b ORDER BY b"
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        return [
            {"bucket_epoch": int(b), "vehicles": int(v), "co2_kg": round(c, 4),
             "saved_kg": round(s, 4), "incidents": int(i)}
            for b, v, c, s, i in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_store: HistoryStore | None = None
_store_lock = threading.Lock()


def get_store() -> HistoryStore:
    """Process-wide singleton (opens the DB on first use)."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = HistoryStore()
    return _store


def reset_store_for_test(path: str) -> HistoryStore:
    global _store
    _store = HistoryStore(path)
    return _store
