"""continuous aggregates for analytics rollups

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-30 00:00:03

Per ADR-0013 — auto-refreshing materialised views over hypertables.
"""

from __future__ import annotations

from alembic import op


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1-minute detection rollup.
    op.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS traffic_detections_1min
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 minute', detected_at) AS bucket,
            intersection_id,
            direction,
            object_class,
            count(*)            AS detection_count,
            avg(confidence)     AS avg_confidence,
            avg(speed_kmh)      AS avg_speed_kmh
        FROM traffic_detections
        GROUP BY bucket, intersection_id, direction, object_class
        WITH NO DATA;
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'traffic_detections_1min',
            start_offset => INTERVAL '2 hours',
            end_offset   => INTERVAL '1 minute',
            schedule_interval => INTERVAL '30 seconds',
            if_not_exists => true
        );
        """
    )

    # 1-hour detection rollup (derived from 1min for cost).
    op.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS traffic_detections_1h
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 hour', detected_at) AS bucket,
            intersection_id,
            direction,
            object_class,
            count(*)            AS detection_count,
            avg(confidence)     AS avg_confidence,
            avg(speed_kmh)      AS avg_speed_kmh
        FROM traffic_detections
        GROUP BY bucket, intersection_id, direction, object_class
        WITH NO DATA;
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'traffic_detections_1h',
            start_offset => INTERVAL '2 days',
            end_offset   => INTERVAL '1 hour',
            schedule_interval => INTERVAL '5 minutes',
            if_not_exists => true
        );
        """
    )

    # Decisions per minute, by commanded phase.
    op.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS decisions_per_minute
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 minute', producer_timestamp) AS bucket,
            intersection_id,
            commanded_phase,
            count(*) AS n
        FROM decisions
        GROUP BY bucket, intersection_id, commanded_phase
        WITH NO DATA;
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'decisions_per_minute',
            start_offset => INTERVAL '2 hours',
            end_offset   => INTERVAL '1 minute',
            schedule_interval => INTERVAL '1 minute',
            if_not_exists => true
        );
        """
    )

    # Mode dwell, hourly.
    op.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS mode_dwell_1h
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 hour', transitioned_at) AS bucket,
            intersection_id,
            to_mode,
            count(*) AS transitions
        FROM mode_transitions
        GROUP BY bucket, intersection_id, to_mode
        WITH NO DATA;
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'mode_dwell_1h',
            start_offset => INTERVAL '7 days',
            end_offset   => INTERVAL '1 hour',
            schedule_interval => INTERVAL '15 minutes',
            if_not_exists => true
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mode_dwell_1h CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS decisions_per_minute CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS traffic_detections_1h CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS traffic_detections_1min CASCADE")
