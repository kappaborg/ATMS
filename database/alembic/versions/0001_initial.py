"""initial schema baseline (mirrors legacy init.sql)

Revision ID: 0001
Revises:
Create Date: 2026-05-30 00:00:00

Faithful reimplementation of database/init.sql so a fresh Postgres
target ends up identical to the legacy state. Subsequent migrations
(0002+) layer the TimescaleDB extension and hypertable conversion
on top per ADR-0013.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")

    op.create_table(
        "intersections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("location_lat", sa.Numeric(10, 8)),
        sa.Column("location_lng", sa.Numeric(11, 8)),
        sa.Column("description", sa.Text),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.TIMESTAMP, server_default=sa.func.current_timestamp()),
    )

    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("intersection_id", sa.Integer, sa.ForeignKey("intersections.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("camera_url", sa.String(512)),
        sa.Column("camera_type", sa.String(50)),
        sa.Column("view_type", sa.String(50)),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.TIMESTAMP, server_default=sa.func.current_timestamp()),
    )

    op.create_table(
        "traffic_detections",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("intersection_id", sa.Integer, sa.ForeignKey("intersections.id"), nullable=False),
        sa.Column("camera_id", sa.Integer, sa.ForeignKey("cameras.id")),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("object_class", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("bbox_x", sa.Float),
        sa.Column("bbox_y", sa.Float),
        sa.Column("bbox_w", sa.Float),
        sa.Column("bbox_h", sa.Float),
        sa.Column("speed_kmh", sa.Float),
        sa.Column("direction", sa.String(20)),
    )
    op.create_index(
        "ix_traffic_detections_intersection_time",
        "traffic_detections",
        ["intersection_id", "detected_at"],
    )

    op.create_table(
        "decisions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("decision_id", sa.BigInteger, nullable=False),
        sa.Column("intersection_id", sa.Integer, sa.ForeignKey("intersections.id"), nullable=False),
        sa.Column("producer_timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("valid_until", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("commanded_phase", sa.String(40), nullable=False),
        sa.Column("priority", sa.String(20)),
        sa.Column("confidence", sa.Float),
        sa.Column("reason", sa.Text),
        sa.Column("audit_principal_sub", sa.String(255)),
        sa.Column("audit_principal_jti", sa.String(255)),
    )
    op.create_index(
        "ix_decisions_intersection_time",
        "decisions",
        ["intersection_id", "producer_timestamp"],
    )

    op.create_table(
        "mode_transitions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("intersection_id", sa.Integer, sa.ForeignKey("intersections.id"), nullable=False),
        sa.Column("transitioned_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("from_mode", sa.String(20)),
        sa.Column("to_mode", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(60)),
        sa.Column("detail", sa.Text),
        sa.Column("flap_count_in_window", sa.Integer),
    )
    op.create_index(
        "ix_mode_transitions_intersection_time",
        "mode_transitions",
        ["intersection_id", "transitioned_at"],
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("event_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("service", sa.String(60), nullable=False),
        sa.Column("event", sa.String(80), nullable=False),
        sa.Column("intersection_id", sa.Integer),
        sa.Column("principal_sub", sa.String(255)),
        sa.Column("principal_jti", sa.String(255)),
        sa.Column("outcome", sa.String(20)),
        sa.Column("detail_json", sa.JSON),
    )
    op.create_index(
        "ix_audit_log_event_time",
        "audit_log",
        ["event_at"],
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("mode_transitions")
    op.drop_table("decisions")
    op.drop_table("traffic_detections")
    op.drop_table("cameras")
    op.drop_table("intersections")
