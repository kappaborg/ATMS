"""
Alembic environment for ATMS — Phase C4.

Reads DB connection from `AtmsBaseSettings` (shared/atms_common/config.py) so
local dev, CI Testcontainers, and prod Flux-managed deployments all use the
same source of truth.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make shared.atms_common importable from this script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.atms_common.config import AtmsBaseSettings  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _build_url() -> str:
    """Build the SQLAlchemy URL.

    Priority:
      1. `ATMS_DB_URL` env override (used by CI / Testcontainers tests).
      2. `AtmsBaseSettings`-composed URL from `POSTGRES_*` env vars.
    """
    override = os.getenv("ATMS_DB_URL")
    if override:
        return override

    settings = AtmsBaseSettings()
    # asyncpg-aware: we still use sync psycopg for migrations because Alembic's
    # migration ops are synchronous. Runtime app uses asyncpg via AtmsDatabase.
    return (
        f"postgresql+psycopg2://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def run_migrations_offline() -> None:
    """Emit SQL only — used for code review and CI dry runs."""
    url = _build_url()
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against the live DB."""
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _build_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
