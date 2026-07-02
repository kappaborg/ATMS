"""data retention policies per ADR-0013

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-30 00:00:04

Default to staging-tier retention. Per-env Alembic data migrations override
via the ATMS_RETENTION_PROFILE env var consumed by an op.execute block in a
later revision.
"""

from __future__ import annotations

import os

from alembic import op


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


# Retention by env profile, hours. Override at migration time via
# `ATMS_RETENTION_PROFILE=prod alembic upgrade head`.
_RETENTION_PROFILES = {
    "dev": {
        "traffic_detections": "168 hours",       # 7 d
        "traffic_detections_1min": "720 hours",  # 30 d
        "traffic_detections_1h": "2160 hours",   # 90 d
        "decisions": "2160 hours",
        "mode_transitions": "2160 hours",
        "audit_log": "8760 hours",               # 365 d (legal floor)
    },
    "staging": {
        "traffic_detections": "720 hours",
        "traffic_detections_1min": "2160 hours",
        "traffic_detections_1h": "8760 hours",
        "decisions": "4320 hours",
        "mode_transitions": "4320 hours",
        "audit_log": "8760 hours",
    },
    "prod": {
        "traffic_detections": "2160 hours",      # 90 d
        "traffic_detections_1min": "4320 hours", # 180 d
        "traffic_detections_1h": "17520 hours",  # 2 y
        "decisions": "2160 hours",
        "mode_transitions": "8760 hours",
        "audit_log": "8760 hours",
    },
}


def upgrade() -> None:
    profile = os.getenv("ATMS_RETENTION_PROFILE", "staging")
    retentions = _RETENTION_PROFILES.get(profile, _RETENTION_PROFILES["staging"])

    for table, interval in retentions.items():
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
    for table in _RETENTION_PROFILES["staging"]:
        op.execute(f"SELECT remove_retention_policy('{table}', if_exists => true)")
