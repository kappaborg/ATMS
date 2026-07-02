"""DSAR + anonymisation audit tables (D4 / ADR-0014)

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-30 00:00:05

Creates:
- `dsar_requests` — every DSAR ever processed; legal-floor retention.
- `anonymization_audit` — proves the LPR pipeline ran anonymisation.

Both are hypertables so retention policies match the existing C4 pattern.
Also adds a `subject_id` column on `traffic_detections` (HMAC hash from
PlateAnonymizer). Plaintext plate columns are NOT introduced — per
ADR-0014 §1, plate text never reaches storage.
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----- DSAR requests -----
    op.create_table(
        "dsar_requests",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(40), nullable=False, unique=True),
        sa.Column("subject_id_hash", sa.String(64), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("requested_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="received"),
        sa.Column("operator_sub", sa.String(255), nullable=False),
        sa.Column("operator_jti", sa.String(255)),
        sa.Column("justification", sa.Text),
        sa.Column("rows_affected", sa.JSON),
    )
    op.create_index(
        "ix_dsar_requests_subject_time",
        "dsar_requests",
        ["subject_id_hash", "requested_at"],
    )
    op.execute(
        """
        SELECT create_hypertable(
            'dsar_requests',
            'requested_at',
            chunk_time_interval => INTERVAL '90 days',
            migrate_data => true,
            if_not_exists => true
        );
        """
    )

    # ----- Anonymisation audit -----
    op.create_table(
        "anonymization_audit",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("subject_id_hash", sa.String(64), nullable=False),
        sa.Column("source_service", sa.String(60), nullable=False),
        sa.Column("anonymized_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("mode", sa.String(20), nullable=False, server_default="anonymized"),
        sa.Column("operator_sub", sa.String(255)),
        sa.Column("operator_jti", sa.String(255)),
        sa.Column("justification", sa.Text),
    )
    op.create_index(
        "ix_anonymization_audit_subject_time",
        "anonymization_audit",
        ["subject_id_hash", "anonymized_at"],
    )
    op.execute(
        """
        SELECT create_hypertable(
            'anonymization_audit',
            'anonymized_at',
            chunk_time_interval => INTERVAL '30 days',
            migrate_data => true,
            if_not_exists => true
        );
        """
    )

    # ----- Add subject_id to traffic_detections -----
    op.add_column(
        "traffic_detections",
        sa.Column("subject_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_traffic_detections_subject",
        "traffic_detections",
        ["subject_id"],
    )

    # ----- Retention policies (per ADR-0014 / profile env var) -----
    # Default to the operator-set ATMS_RETENTION_PROFILE; staging tier as fallback.
    profile = os.getenv("ATMS_RETENTION_PROFILE", "staging")
    horizons = {
        "dsar_requests": "8760 hours",           # 1 year (legal floor)
        "anonymization_audit": "8760 hours",
    }
    # Note: dev/staging/prod all use the same 8760h here per ADR-0014 §3.
    del profile  # not used at this granularity
    for table, interval in horizons.items():
        op.execute(
            f"""
            SELECT add_retention_policy(
                '{table}',
                INTERVAL '{interval}',
                if_not_exists => true
            );
            """
        )


def downgrade() -> None:
    op.execute("SELECT remove_retention_policy('anonymization_audit', if_exists => true)")
    op.execute("SELECT remove_retention_policy('dsar_requests', if_exists => true)")
    op.drop_index("ix_traffic_detections_subject", table_name="traffic_detections")
    op.drop_column("traffic_detections", "subject_id")
    op.drop_table("anonymization_audit")
    op.drop_table("dsar_requests")
