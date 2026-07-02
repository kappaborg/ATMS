# ADR-0013: TimescaleDB hypertables + Alembic migrations

**Status:** Accepted
**Date:** 2026-05-30
**Closes:** PRODUCTION_GAPS.md gap #18 (Phase C4)

## Context

Audit gap #18: the project uses plain PostgreSQL with raw `.sql` migration files (`database/migrations/000_master_migration.sql` … `009_create_analytics_config.sql`) applied via `database/run_migrations.sh`. Two problems:

1. **Write volume.** Real-time detections from a 30 FPS camera at 30+ detections per frame produce ~900 rows/sec per intersection. At 50 pilot intersections that's 45 k rows/sec sustained. Plain Postgres can do it, but query patterns over weeks of data become painful and storage explodes without partitioning.

2. **Migration tooling.** Raw SQL files have no schema versioning, no rollback story, no auto-detect of model drift, no transactional safety guarantee for the migration step itself. Any schema change today is a manual ops task.

C4 fixes both.

## Decision

### TimescaleDB extension

Install [TimescaleDB](https://www.timescale.com/) on top of the existing Postgres (it's a Postgres extension — no second database to operate). Convert the high-volume tables to **hypertables**:

| Table | Hypertable? | `time` column | Chunk interval |
|-------|-------------|---------------|----------------|
| `intersections` | No (low-cardinality metadata) | — | — |
| `cameras` | No | — | — |
| `traffic_detections` | **Yes** | `detected_at` | 1 day |
| `decisions` (new) | **Yes** | `producer_timestamp` | 1 day |
| `mode_transitions` (new) | **Yes** | `transitioned_at` | 7 days |
| `audit_log` (new) | **Yes** | `event_at` | 30 days |
| `emissions` | **Yes** | `measured_at` | 1 day |
| `trajectories` | **Yes** | `started_at` | 1 day |

### Continuous aggregates

TimescaleDB's continuous-aggregate feature pre-computes rollups that auto-refresh as new data arrives. Add:

- `traffic_detections_1min` — per-intersection per-direction count, average confidence (refreshed every 30s, materialized every 1m)
- `traffic_detections_1h` — same fields at hourly grain (refreshed every 5m)
- `decisions_per_minute` — per-intersection commanded-phase distribution
- `mode_dwell_1h` — time-in-each-mode per intersection

The dashboards in `infrastructure/observability/grafana/dashboards/` query the continuous aggregates by default, falling back to the raw hypertables only when finer granularity is asked for.

### Retention policy

Per ADR-0011 timing budgets:

| Table | Retention | Why |
|-------|-----------|-----|
| `traffic_detections` (raw) | 7 days dev / 30 days staging / 90 days prod | Detection data is voluminous; anonymisation applied at ingestion (D4) so PII retention is bounded |
| `traffic_detections_1min` | 30 / 90 / 180 days | One-minute granularity is the operational replay window |
| `traffic_detections_1h` | 90 / 365 / **2 years** | Long-term analytics + DOT compliance |
| `decisions` | 90 days | Failsafe audit trail; longer windows in cold storage |
| `mode_transitions` | 90 / 180 / 365 days | Incident review |
| `audit_log` | 365 days minimum (legal requirement) | Operator action accountability |

Retention is implemented via TimescaleDB's `add_retention_policy` per table; tunable per env via Alembic data migration.

### Alembic for schema migrations

Replace `database/run_migrations.sh` with Alembic. Layout:

```
database/
├── alembic/
│   ├── env.py                       # Reads from AtmsBaseSettings (B1)
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_initial.py          # Mirrors existing init.sql baseline
│       ├── 0002_timescaledb_ext.py  # CREATE EXTENSION timescaledb
│       ├── 0003_hypertables.py      # convert detections+decisions+...
│       ├── 0004_continuous_aggs.py
│       └── 0005_retention.py
├── alembic.ini
├── database.py                       # legacy — kept until B-phase fully ports
└── migrations/                       # legacy raw .sql — archived
```

Existing `database/migrations/*.sql` are moved to `database/migrations/archived/` with a README pointing forward; Alembic's `0001_initial` is a faithful reimplementation of the same schema so a fresh cluster ends up in the same state.

Migration policy:
- All schema changes go through Alembic. `alembic revision --autogenerate` to draft; manual review before commit.
- Every revision is tested **upgrade and downgrade** in CI against a Testcontainers Postgres + TimescaleDB image.
- No data migrations in the same revision as a schema migration. Two separate revisions if both are needed.

### Async Postgres adapter — `shared/atms_common/db.py`

A new shared module:

```python
class AtmsDatabase:
    def __init__(self, dsn: str, *, pool_min: int = 2, pool_max: int = 20): ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    @asynccontextmanager
    async def session(self) -> AsyncIterator[asyncpg.Connection]: ...
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]: ...
```

asyncpg-based pool. Surfaces failures as `KafkaError`-shaped `DatabaseError(AtmsError)`. Plugs into the `HealthRouter` via `postgres_check`. The B4 resilience primitives wrap external calls.

### Test strategy

Tests live under `services/<svc>/tests/integration/test_db_*.py` (per-service) and `shared/tests/test_db.py` (shared lib level). They use Testcontainers' `PostgresContainer` plus a custom image with TimescaleDB:

```python
TIMESCALE_IMAGE = "timescale/timescaledb:latest-pg16"
```

The B4 chaos-test pattern applies: kill the DB mid-write, verify the failsafe path (decision-engine can buffer or drop; controller is unaffected because it doesn't write to DB).

## Out of scope for C4

- **Live data migration from the existing raw-SQL schema.** Operators run Alembic against fresh Postgres in dev/staging; prod migration is a separate, gated rollout per the runbook.
- **Reading from continuous aggregates in the controller hot path.** Controller is Kafka-driven (A1) and the DB is for analytics + audit. No change to the safety path.
- **Sharding across nodes.** TimescaleDB single-node handles our pilot scale; distributed mode is a Phase D-or-beyond decision.

## Consequences

- New runtime deps: `alembic`, `asyncpg`, `psycopg2-binary` (for Alembic itself).
- TimescaleDB extension required on the Postgres instance — documented in cluster bootstrap.
- Operators learn the Alembic workflow (`alembic upgrade head`, `alembic downgrade -1`, `alembic history`). Documented in `docs/runbooks/database.md`.
- Existing raw `.sql` files become reference material in `database/migrations/archived/`.
- Future schema changes ship as Alembic revisions in the same PR as the model code that needs them.
