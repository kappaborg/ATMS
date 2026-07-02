"""TimescaleDB / Postgres audit archive forwarder.

Production storage problem: each edge node's SQLite audit DB rotates
when it hits `max_size_mb` (default 200 MB). The rotated `.YYYYMMDD.db`
files accumulate on local disk until they're forwarded to the city
archive. This module does the forwarding.

Why TimescaleDB:
- Postgres-compatible — every city already has Postgres ops expertise
- Hypertables auto-partition by time → fast time-range queries across
  multi-month archives
- Continuous aggregates make Grafana panels (rolling 24h emission, etc.)
  query-time-cheap

Schema (created at startup if missing):

    CREATE TABLE chamber_decisions (
        intersection_id  TEXT     NOT NULL,
        decision_id      TEXT     NOT NULL,
        tick_time        TIMESTAMPTZ NOT NULL,
        commanded_phase  TEXT     NOT NULL,
        mode             TEXT     NOT NULL,
        dominant         TEXT,
        emergency_count  INTEGER  NOT NULL,
        input_json       JSONB    NOT NULL,
        output_json      JSONB    NOT NULL,
        PRIMARY KEY (intersection_id, decision_id)
    );
    SELECT create_hypertable('chamber_decisions', 'tick_time');

    CREATE INDEX idx_chamber_decisions_mode  ON chamber_decisions(mode);
    CREATE INDEX idx_chamber_decisions_phase ON chamber_decisions(commanded_phase);

Operator workflow:
- Edge SQLite rotation produces `audit-20260614T120000.db`
- Forwarder picks it up, batches the rows into TimescaleDB, deletes the
  local file on success
- Failed forwards retry; persistent failures alert ops via Prometheus

The forwarder is a **separate process** from the chamber — chamber crash
shouldn't affect archive forwarding and vice versa. Run as a systemd
timer or kubernetes CronJob.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("audit_forwarder")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chamber_decisions (
    intersection_id  TEXT        NOT NULL,
    decision_id      TEXT        NOT NULL,
    tick_time        TIMESTAMPTZ NOT NULL,
    commanded_phase  TEXT        NOT NULL,
    mode             TEXT        NOT NULL,
    dominant         TEXT,
    emergency_count  INTEGER     NOT NULL,
    input_json       JSONB       NOT NULL,
    output_json      JSONB       NOT NULL,
    PRIMARY KEY (intersection_id, decision_id)
);

CREATE INDEX IF NOT EXISTS idx_chamber_decisions_mode
    ON chamber_decisions(mode);
CREATE INDEX IF NOT EXISTS idx_chamber_decisions_phase
    ON chamber_decisions(commanded_phase);
CREATE INDEX IF NOT EXISTS idx_chamber_decisions_intersection_time
    ON chamber_decisions(intersection_id, tick_time DESC);
"""

HYPERTABLE_SQL = """
SELECT create_hypertable('chamber_decisions', 'tick_time',
                         if_not_exists => TRUE,
                         chunk_time_interval => INTERVAL '7 days');
"""


class TimescaleAuditForwarder:
    """Forwards rotated SQLite audit DBs into a TimescaleDB hypertable.

    Production install pattern:
        - Edge node: chamber writes to /var/lib/atms/audit.db,
          rotation produces /var/lib/atms/audit.YYYYMMDDT*.db
        - Forwarder (systemd timer every 5 min): pulls each rotated
          file, batches rows into Timescale, deletes file on success
    """

    def __init__(
        self,
        intersection_id: str,
        timescale_dsn: str,
        batch_size: int = 1000,
        ensure_hypertable: bool = True,
    ):
        try:
            import psycopg2  # noqa: F401, PLC0415
        except ImportError as e:
            raise RuntimeError(
                "psycopg2-binary required. Install: pip install psycopg2-binary"
            ) from e

        self._intersection_id = intersection_id
        self._dsn = timescale_dsn
        self._batch_size = batch_size
        self._conn = None
        self._ensure_schema(ensure_hypertable)

    def _connect(self):
        if self._conn is None or self._conn.closed:
            import psycopg2  # noqa: PLC0415

            self._conn = psycopg2.connect(self._dsn)
        return self._conn

    def _ensure_schema(self, hypertable: bool) -> None:
        conn = self._connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
                if hypertable:
                    try:
                        cur.execute(HYPERTABLE_SQL)
                    except Exception as e:
                        log.warning(
                            "hypertable creation failed (vanilla Postgres "
                            "without TimescaleDB? continuing): %s", e,
                        )

    def forward(self, sqlite_path: Path) -> int:
        """Forward all rows from `sqlite_path` into Timescale. Returns
        count forwarded. The SQLite file is NOT deleted by this method;
        caller decides retention.
        """
        if not sqlite_path.exists():
            log.warning("source %s missing — skipping", sqlite_path)
            return 0
        src = sqlite3.connect(str(sqlite_path))
        try:
            src.row_factory = sqlite3.Row
            rows = src.execute(
                "SELECT decision_id, tick_time, commanded_phase, mode, dominant, "
                "emergency_count, input_json, output_json FROM decisions"
            )
            batch = []
            forwarded = 0
            for r in rows:
                batch.append(
                    (
                        self._intersection_id,
                        r["decision_id"],
                        r["tick_time"],
                        r["commanded_phase"],
                        r["mode"],
                        r["dominant"],
                        r["emergency_count"],
                        r["input_json"],
                        r["output_json"],
                    )
                )
                if len(batch) >= self._batch_size:
                    forwarded += self._insert_batch(batch)
                    batch.clear()
            if batch:
                forwarded += self._insert_batch(batch)
            log.info("forwarded %d rows from %s", forwarded, sqlite_path)
            return forwarded
        finally:
            src.close()

    def _insert_batch(self, batch: list) -> int:
        import psycopg2.extras  # noqa: PLC0415

        conn = self._connect()
        with conn:
            with conn.cursor() as cur:
                # ON CONFLICT lets us re-forward idempotently if the
                # forwarder retries after a partial failure.
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO chamber_decisions "
                    "(intersection_id, decision_id, tick_time, commanded_phase, "
                    " mode, dominant, emergency_count, input_json, output_json) "
                    "VALUES %s "
                    "ON CONFLICT (intersection_id, decision_id) DO NOTHING",
                    batch,
                )
                return cur.rowcount

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()


def main() -> int:
    """CLI for the forwarder. Run as a systemd timer / cron job.

    With back-pressure (Phase 9.1):
    - Forwards each rotated DB to TimescaleDB
    - On success: deletes local file (via BackpressureManager.mark_forwarded)
    - On failure: schedules exponential-backoff retry
    - Enforces local quota: oldest archives moved to S3 cold tier when
      `--cold-tier-bucket` is set
    """
    p = argparse.ArgumentParser(prog="audit_forwarder.py")
    p.add_argument("--intersection-id", required=True)
    p.add_argument(
        "--dsn",
        required=True,
        help='Postgres DSN, e.g. "postgresql://user:pass@db.atms.city:5432/audit"',
    )
    p.add_argument(
        "--rotated-dir",
        type=Path,
        required=True,
        help="directory containing rotated audit.*.db files",
    )
    p.add_argument(
        "--cold-tier-bucket",
        type=str,
        default="",
        help='S3 URL for cold-tier overflow, e.g. "s3://atms-archive-sarajevo/"',
    )
    p.add_argument(
        "--local-quota-bytes",
        type=int,
        default=10 * 1024 * 1024 * 1024,
        help="local archive disk quota (default 10 GB)",
    )
    args = p.parse_args()

    from simulation.decision_chamber.audit_backpressure import (  # noqa: PLC0415
        BackpressureConfig,
        BackpressureManager,
    )

    bp = BackpressureManager(
        archive_dir=args.rotated_dir,
        config=BackpressureConfig(
            local_archive_quota_bytes=args.local_quota_bytes,
            cold_tier_bucket=args.cold_tier_bucket,
        ),
        intersection_id=args.intersection_id,
    )

    fwd = TimescaleAuditForwarder(
        intersection_id=args.intersection_id,
        timescale_dsn=args.dsn,
    )
    total = 0
    forwarded = 0
    failed = 0
    for path in bp.list_local_archives():
        if not bp.should_retry(path):
            log.debug("skipping %s — backoff window not elapsed", path.name)
            continue
        try:
            n = fwd.forward(path)
            total += n
            bp.mark_forwarded(path)
            forwarded += 1
        except Exception as e:
            log.error("forward of %s failed: %s", path, e)
            bp.mark_failed(path)
            failed += 1

    quota_report = bp.enforce_quota()
    health = bp.health_snapshot()
    log.info(
        "forwarder run complete: %d rows forwarded, %d files succeeded, "
        "%d files retried later, %d local archives remain (%.1f MB)",
        total, forwarded, failed,
        health["local_archive_count"],
        health["local_archive_bytes"] / 1024 / 1024,
    )
    if quota_report["over_quota"]:
        log.warning(
            "QUOTA: uploaded %d to cold tier, deleted %d locally",
            quota_report["uploaded_to_cold"],
            quota_report["deleted_locally"],
        )
    fwd.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
