"""SQLite-backed audit storage with rotation + retention.

Production-grade replacement for the Phase 1 JSONL writer:

- One row per chamber decision (input + output as JSON blobs, plus
  indexed columns for fast time-range queries)
- Automatic rotation: when DB size > max_size_mb, opens a new file and
  archives the old one
- Retention: prunes rows older than retention_days on startup + once
  per day
- Query helpers for the operator console + replay tool
- Same write interface (`write(decision_input, output)`) as JSONL so it
  drops in as a SQLAuditLogger swap

SQLite is appropriate for the edge (no separate DB server, ~10k
write/sec, durable). City-layer archival pulls the rotated files to
TimescaleDB or S3.

Schema:

    CREATE TABLE decisions (
        decision_id      TEXT    PRIMARY KEY,
        tick_time        TEXT    NOT NULL,  -- ISO-8601
        commanded_phase  TEXT    NOT NULL,
        mode             TEXT    NOT NULL,
        dominant         TEXT,
        emergency_count  INTEGER NOT NULL,
        input_json       TEXT    NOT NULL,
        output_json      TEXT    NOT NULL
    );
    CREATE INDEX idx_decisions_tick_time ON decisions(tick_time);
"""

from __future__ import annotations

import dataclasses
import enum
import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from simulation.decision_chamber.state import ChamberInput, ChamberOutput

log = logging.getLogger("atms.chamber.audit_db")


def _serialise(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"non-serialisable type: {type(obj)}")


SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    decision_id      TEXT    PRIMARY KEY,
    tick_time        TEXT    NOT NULL,
    commanded_phase  TEXT    NOT NULL,
    mode             TEXT    NOT NULL,
    dominant         TEXT,
    emergency_count  INTEGER NOT NULL,
    input_json       TEXT    NOT NULL,
    output_json      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_tick_time ON decisions(tick_time);
CREATE INDEX IF NOT EXISTS idx_decisions_mode ON decisions(mode);
"""


class SQLiteAuditLogger:
    """SQLite-backed audit writer. Thread-safe (single connection +
    lock). Rotation triggers when the active DB file exceeds
    `max_size_mb`. Retention runs once a day during write.
    """

    def __init__(
        self,
        db_path: Path | str,
        max_size_mb: float = 200.0,
        retention_days: int = 90,
    ):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_size_bytes = int(max_size_mb * 1024 * 1024)
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._last_retention_run: datetime | None = None
        self._open()

    def _open(self) -> None:
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit
        )
        self._conn.executescript(SCHEMA)
        # Write-ahead logging for better concurrent read perf + crash safety.
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        log.info("audit DB ready at %s", self._db_path)

    def write(self, decision_input: ChamberInput, output: ChamberOutput) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO decisions "
                    "(decision_id, tick_time, commanded_phase, mode, dominant, "
                    "emergency_count, input_json, output_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        output.decision_id,
                        decision_input.tick_time.isoformat(),
                        output.commanded_phase,
                        output.mode.value,
                        output.dominant_factor,
                        len(decision_input.emergency_signals),
                        json.dumps(dataclasses.asdict(decision_input), default=_serialise),
                        json.dumps(dataclasses.asdict(output), default=_serialise),
                    ),
                )
            except sqlite3.Error as e:
                log.warning("audit write failed: %s", e)
                return

        self._maybe_rotate()
        self._maybe_run_retention()

    # ------------- Rotation -----------------------------------------

    def _maybe_rotate(self) -> None:
        try:
            size = self._db_path.stat().st_size
        except OSError:
            return
        if size < self._max_size_bytes:
            return
        with self._lock:
            self._rotate_locked()

    def _rotate_locked(self) -> None:
        """Close current DB, rename with timestamp, open a fresh one."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        archived = self._db_path.with_suffix(f".{stamp}.db")
        try:
            self._db_path.rename(archived)
            log.info("rotated audit DB -> %s", archived)
        except OSError as e:
            log.warning("rotate rename failed: %s", e)
        self._open()

    # ------------- Retention ----------------------------------------

    def _maybe_run_retention(self) -> None:
        now = datetime.now(timezone.utc)
        if self._last_retention_run is not None:
            if now - self._last_retention_run < timedelta(hours=24):
                return
        self._last_retention_run = now
        cutoff = (now - timedelta(days=self._retention_days)).isoformat()
        with self._lock:
            try:
                cur = self._conn.execute(
                    "DELETE FROM decisions WHERE tick_time < ?", (cutoff,)
                )
                if cur.rowcount > 0:
                    log.info(
                        "retention: removed %d rows older than %d days",
                        cur.rowcount, self._retention_days,
                    )
                self._conn.execute("VACUUM")
            except sqlite3.Error as e:
                log.warning("retention failed: %s", e)

    # ------------- Query helpers ------------------------------------

    def recent_decisions(self, limit: int = 50) -> list[dict]:
        """Return the N most recent decision summaries (for operator UI)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT decision_id, tick_time, commanded_phase, mode, "
                "dominant, emergency_count FROM decisions "
                "ORDER BY tick_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "decision_id": r[0],
                "tick_time": r[1],
                "commanded_phase": r[2],
                "mode": r[3],
                "dominant": r[4],
                "emergency_count": r[5],
            }
            for r in rows
        ]

    def decisions_in_window(
        self, start: datetime, end: datetime
    ) -> list[dict]:
        """Full input + output for replay/audit investigation."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT input_json, output_json FROM decisions "
                "WHERE tick_time >= ? AND tick_time <= ? "
                "ORDER BY tick_time ASC",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [
            {
                "input": json.loads(r[0]),
                "output": json.loads(r[1]),
            }
            for r in rows
        ]

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
