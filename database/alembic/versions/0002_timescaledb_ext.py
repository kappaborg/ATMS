"""enable TimescaleDB extension

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-30 00:00:01
"""

from __future__ import annotations

from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Requires the Postgres image to have the timescaledb shared library
    # preloaded — we use timescale/timescaledb:latest-pg16 in CI.
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")


def downgrade() -> None:
    # Dropping the extension forces all hypertables to lose their chunking,
    # so the safe path is to undo subsequent revisions first.
    op.execute("DROP EXTENSION IF EXISTS timescaledb CASCADE")
