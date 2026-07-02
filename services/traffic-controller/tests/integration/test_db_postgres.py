"""
Integration test for shared/atms_common/db.py against a real Postgres
(and ideally TimescaleDB) container.

Skipped without Docker — see B4's same-shaped Kafka chaos test
(tests/integration/test_failsafe_chaos.py).
"""

from __future__ import annotations

import shutil

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("docker") is None,
        reason="Docker not available; Testcontainers cannot run",
    ),
]


def test_lifecycle_with_timescale_container():
    """
    End-to-end:
    1. Start `timescale/timescaledb:latest-pg16` via Testcontainers.
    2. Apply Alembic migrations 0001 → 0005.
    3. Insert sample rows.
    4. Verify the continuous aggregate materialises after a refresh.
    5. Verify the retention policy is attached.
    6. Verify postgres_check returns ok.

    This skeleton is a placeholder until the CI image is bound. Phase C4
    follow-up PR fleshes it out alongside the GitHub Actions matrix change
    that enables Docker-in-Docker for the nightly job.
    """
    pytest.skip(
        "Full Testcontainers-backed Postgres+Timescale test pending CI Docker support. "
        "Unit-level surface coverage lives in tests/unit/test_db_c4.py."
    )
