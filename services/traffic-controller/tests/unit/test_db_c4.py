"""
Unit tests for shared/atms_common/db.py (Phase C4).

Real-Postgres integration lives in tests/integration/test_db_postgres.py
(Testcontainers-gated, skipped without Docker).
"""

from __future__ import annotations

import asyncio

import pytest

from shared.atms_common.db import (
    AtmsDatabase,
    DatabaseError,
    build_dsn,
    postgres_check,
)


class TestBuildDsn:
    def test_with_password(self):
        dsn = build_dsn(host="h", port=5432, db="d", user="u", password="p")
        assert dsn == "postgresql://u:p@h:5432/d"

    def test_without_password(self):
        dsn = build_dsn(host="h", port=5432, db="d", user="u", password="")
        assert dsn == "postgresql://u@h:5432/d"


class TestAtmsDatabaseLifecycle:
    def test_session_without_start_raises(self):
        db = AtmsDatabase(dsn="postgresql://u@h/d")

        async def _go():
            async with db.session():
                pass

        with pytest.raises(DatabaseError, match="not started"):
            asyncio.run(_go())

    def test_pool_property_none_before_start(self):
        db = AtmsDatabase(dsn="postgresql://u@h/d")
        assert db.pool is None


class TestPostgresCheck:
    async def test_check_returns_not_ok_when_pool_not_started(self):
        db = AtmsDatabase(dsn="postgresql://u@h/d")
        check = postgres_check(db)
        result = await check()
        assert not result.ok
        assert "not started" in result.detail
