"""
Async Postgres adapter — Phase C4.

Thin wrapper around `asyncpg` for the runtime path. Migrations use Alembic +
psycopg2 (sync) — see `database/alembic/`. The runtime uses asyncpg here.

Failures surface as `DatabaseError` (subclass of `AtmsError`) so the B4
resilience primitives can wrap calls cleanly.

Lifecycle:
    db = AtmsDatabase(dsn=settings.postgres_dsn)
    await db.start()                 # opens the pool
    async with db.session() as conn: # checks out a connection
        rows = await conn.fetch("SELECT 1")
    await db.stop()
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from shared.atms_common.errors import AtmsError
from shared.atms_common.health import CheckResult

if TYPE_CHECKING:
    import asyncpg


log = logging.getLogger(__name__)


class DatabaseError(AtmsError):
    """Raised by AtmsDatabase on unrecoverable failure."""


def build_dsn(*, host: str, port: int, db: str, user: str, password: str) -> str:
    """Build the asyncpg DSN. Helper for use with `AtmsBaseSettings`."""
    auth = f"{user}:{password}" if password else user
    return f"postgresql://{auth}@{host}:{port}/{db}"


class AtmsDatabase:
    """
    Async Postgres pool with lifecycle + dependency-check integration.

    `session()` checks out a single connection for the lifetime of the with
    block. `transaction()` additionally wraps the work in a transaction.
    """

    def __init__(
        self,
        *,
        dsn: str,
        pool_min: int = 2,
        pool_max: int = 20,
        statement_timeout_ms: int = 10_000,
    ) -> None:
        self._dsn = dsn
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._statement_timeout_ms = statement_timeout_ms
        self._pool: asyncpg.pool.Pool | None = None

    async def start(self) -> None:
        try:
            import asyncpg
        except ImportError as e:
            raise DatabaseError("asyncpg is not installed") from e

        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._pool_min,
                max_size=self._pool_max,
                command_timeout=self._statement_timeout_ms / 1000.0,
            )
        except Exception as e:
            raise DatabaseError(f"failed to open Postgres pool: {e}") from e
        log.info("AtmsDatabase pool started")

    async def stop(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[asyncpg.Connection]:
        if self._pool is None:
            raise DatabaseError("database not started")
        async with self._pool.acquire() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        async with self.session() as conn, conn.transaction():
            yield conn

    @property
    def pool(self) -> asyncpg.pool.Pool | None:
        """Escape hatch for the health check or custom queries."""
        return self._pool


# ---------------------------------------------------------------------------
# HealthCheck integration — see shared/atms_common/health.py
# ---------------------------------------------------------------------------


def postgres_check(db: AtmsDatabase):
    """
    Return an async health-check callable suitable for HealthRouter.add_check.

    Verifies the pool is open AND a trivial query succeeds within the
    statement timeout.
    """

    async def _check() -> CheckResult:
        if db.pool is None:
            return CheckResult(ok=False, detail="pool not started")
        try:
            async with db.session() as conn:
                await conn.execute("SELECT 1")
        except Exception as e:
            return CheckResult(ok=False, detail=f"query failed: {e}")
        return CheckResult(ok=True, detail="connected")

    return _check
