"""
Violation evidence log — persisted record of each distinct violation.

One row per (vehicle, violation) occurrence: timestamp, camera, intersection,
track, type, plate, the type-specific detail, and a path to a snapshot image
(saved by the worker). Backed by the same dependency-free SQLite approach as
the history store; survives restarts.

This is an evidence trail — for enforcement it must be paired with a lawful
basis, retention policy and DPIA (plates are personal data). Retention is
policy: PANEL_VIOLATION_RETENTION_DAYS prunes rows (and their snapshots)
older than N days (0 = keep).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS violations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              INTEGER NOT NULL,
    camera_id       TEXT    NOT NULL,
    intersection_id TEXT,
    track_id        INTEGER,
    type            TEXT    NOT NULL,
    plate           TEXT,
    detail          TEXT,
    snapshot        TEXT
);
CREATE INDEX IF NOT EXISTS idx_viol_ts ON violations(ts);
CREATE INDEX IF NOT EXISTS idx_viol_type ON violations(type);
"""


def _default_db_path() -> str:
    env = os.getenv("PANEL_VIOLATIONS_DB")
    if env:
        return env
    state = os.getenv("PANEL_STATE_FILE")
    base = os.path.dirname(os.path.abspath(state)) if state else "."
    return os.path.join(base or ".", "panel_violations.db")


class ViolationsLog:
    def __init__(self, path: str | None = None):
        self.path = path or _default_db_path()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def record(
        self, ts: int, camera_id: str, intersection_id: str | None, track_id: int | None,
        vtype: str, plate: str | None, detail: dict | None, snapshot: str | None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO violations (ts,camera_id,intersection_id,track_id,type,plate,detail,snapshot)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (int(ts), camera_id, intersection_id, track_id, vtype, plate,
                 json.dumps(detail or {}), snapshot),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def query(
        self, since: int, until: int, camera_id: str | None = None,
        vtype: str | None = None, limit: int = 500, plate: str | None = None,
    ) -> list[dict]:
        q = "SELECT id,ts,camera_id,intersection_id,track_id,type,plate,detail,snapshot FROM violations WHERE ts>=? AND ts<?"
        args: list = [since, until]
        if camera_id:
            q += " AND camera_id=?"
            args.append(camera_id)
        if vtype:
            q += " AND type=?"
            args.append(vtype)
        if plate:
            # DSAR support: find all records for a specific plate.
            q += " AND plate=?"
            args.append(plate.upper())
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r[0], "ts": r[1], "camera_id": r[2], "intersection_id": r[3],
                "track_id": r[4], "type": r[5], "plate": r[6],
                "detail": json.loads(r[7]) if r[7] else {}, "has_snapshot": bool(r[8]),
            })
        return out

    def set_plate(self, vid: int, plate: str) -> int:
        """Back-fill a plate onto an already-logged violation. Returns rows
        updated.

        Needed because a violation is logged the moment it is seen, while a
        plate needs several agreeing reads across frames — so the row is very
        often written before the plate exists.

        Only fills a NULL: a plate already on the record is evidence, and a
        later read disagreeing with it must not silently rewrite it.
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE violations SET plate=? WHERE id=? AND plate IS NULL", (plate, vid)
            )
            self._conn.commit()
            return int(cur.rowcount)

    def delete(self, vid: int) -> int:
        """Erase a single record (DSAR erasure). Returns rows deleted."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM violations WHERE id=?", (vid,))
            self._conn.commit()
            return int(cur.rowcount)

    def snapshot_path(self, vid: int) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT snapshot FROM violations WHERE id=?", (vid,)).fetchone()
        return row[0] if row and row[0] else None

    def prune(self, older_than_ts: int) -> list[str]:
        """Delete rows older than a cutoff; return their snapshot paths so the
        caller can unlink the files."""
        with self._lock:
            paths = [r[0] for r in self._conn.execute(
                "SELECT snapshot FROM violations WHERE ts<? AND snapshot IS NOT NULL", (older_than_ts,)
            ).fetchall()]
            self._conn.execute("DELETE FROM violations WHERE ts<?", (older_than_ts,))
            self._conn.commit()
        return paths

    def sweep(self, retention_days: float, now: float) -> int:
        """Enforce retention: delete rows older than `retention_days` AND their
        snapshot files. Returns rows deleted. No-op when retention is 0/off."""
        if retention_days <= 0:
            return 0
        cutoff = int(now - retention_days * 86400)
        with self._lock:
            n = self._conn.execute(
                "SELECT COUNT(*) FROM violations WHERE ts<?", (cutoff,)
            ).fetchone()[0]
        if n == 0:
            return 0
        paths = self.prune(cutoff)
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass
        return int(n)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_log: ViolationsLog | None = None
_lock = threading.Lock()


def get_log() -> ViolationsLog:
    global _log
    if _log is None:
        with _lock:
            if _log is None:
                _log = ViolationsLog()
    return _log


def reset_for_test(path: str) -> ViolationsLog:
    global _log
    _log = ViolationsLog(path)
    return _log
