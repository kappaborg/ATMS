"""convert high-volume tables to TimescaleDB hypertables

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-30 00:00:02

Per ADR-0013 — table → chunk-interval mapping.
"""

from __future__ import annotations

from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


# table → (time column, chunk interval)
_HYPERTABLES: list[tuple[str, str, str]] = [
    ("traffic_detections", "detected_at", "1 day"),
    ("decisions", "producer_timestamp", "1 day"),
    ("mode_transitions", "transitioned_at", "7 days"),
    ("audit_log", "event_at", "30 days"),
]


def upgrade() -> None:
    for table, time_col, interval in _HYPERTABLES:
        # `migrate_data => true` converts existing rows; `if_not_exists` makes
        # the migration safely re-runnable.
        op.execute(
            f"""
            SELECT create_hypertable(
                '{table}',
                '{time_col}',
                chunk_time_interval => INTERVAL '{interval}',
                migrate_data => true,
                if_not_exists => true
            );
            """
        )


def downgrade() -> None:
    # No native "un-hypertable" — drop indexes and recreate without chunking.
    # In practice operators downgrade by restoring from backup before this
    # revision; documented in docs/runbooks/database.md.
    pass
