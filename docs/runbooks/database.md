# Runbook: Postgres + TimescaleDB + Alembic (Phase C4)

**Audience:** SRE + on-call.
**Design:** [ADR-0013](../adr/0013-timescaledb-alembic.md).
**Manifests:** [`database/alembic/`](../../database/alembic/), [`database/alembic.ini`](../../database/alembic.ini).

---

## 1. Day-to-day workflow

### Apply pending migrations

```bash
cd database
alembic upgrade head
```

Production deploys run this via Flux post-sync hook (or a Job manifest gated by the deploy pipeline). Operators don't run `alembic upgrade head` interactively in prod.

### Roll back one revision

```bash
alembic downgrade -1
```

> **Caution:** `0003_hypertables.py` cannot be downgraded — TimescaleDB has no native "un-hypertable" operation. If you reach that point, restore from backup. Documented in the revision itself.

### Inspect history

```bash
alembic history --verbose
alembic current
```

### Generate a new revision

```bash
alembic revision -m "add foo column"
# Edit the new file in alembic/versions/. Manually write upgrade/downgrade.
```

We do **not** use `--autogenerate` because there is no SQLAlchemy `MetaData` source of truth for the schema (yet). Once the runtime adopts SQLAlchemy or SQLModel, autogenerate becomes available.

## 2. Bootstrap a fresh cluster

```bash
# 1. Create the database role and DB (out-of-band, one-time).
psql -h <host> -U postgres <<SQL
CREATE ROLE atms WITH LOGIN PASSWORD :'pwd';
CREATE DATABASE atms OWNER atms;
SQL

# 2. Ensure the Postgres image has the timescaledb shared library preloaded.
#    In CI / cluster: use timescale/timescaledb:latest-pg16.

# 3. Apply migrations.
cd database
ATMS_DB_URL=postgresql://atms:pwd@<host>:5432/atms \
ATMS_RETENTION_PROFILE=staging \
alembic upgrade head
```

The `ATMS_RETENTION_PROFILE` env var selects the retention values (per ADR-0013):
- `dev` — 7 day raw / 30 day 1-min / 90 day 1-h
- `staging` — 30 / 90 / 365
- `prod` — 90 / 180 / 2 years

## 3. Inspecting hypertables

```bash
psql -d atms -c "SELECT hypertable_name, num_chunks, total_chunks
                 FROM timescaledb_information.hypertables;"
```

Inspect a continuous aggregate's most recent refresh:

```bash
psql -d atms -c "SELECT view_name, refresh_lag, materialized_only
                 FROM timescaledb_information.continuous_aggregates;"
```

Force a manual refresh (incident debugging):

```bash
psql -d atms -c "CALL refresh_continuous_aggregate(
    'traffic_detections_1min', NOW() - INTERVAL '2 hours', NULL);"
```

## 4. Common queries

```sql
-- Decisions affecting intersection 1 in the last 10 minutes
SELECT producer_timestamp, commanded_phase, priority, audit_principal_sub
FROM decisions
WHERE intersection_id = 1
  AND producer_timestamp > NOW() - INTERVAL '10 minutes'
ORDER BY producer_timestamp DESC;

-- Mode-transition timeline for the last hour
SELECT transitioned_at, from_mode, to_mode, reason
FROM mode_transitions
WHERE intersection_id = 1
  AND transitioned_at > NOW() - INTERVAL '1 hour'
ORDER BY transitioned_at DESC;

-- Per-intersection vehicle counts per minute (last hour, from continuous aggregate)
SELECT bucket, intersection_id, sum(detection_count) AS total
FROM traffic_detections_1min
WHERE bucket > NOW() - INTERVAL '1 hour'
  AND object_class IN ('car', 'truck', 'bus')
GROUP BY bucket, intersection_id
ORDER BY bucket DESC;
```

## 5. Retention tuning

Per-env retention is set during migration `0005_retention.py` and is **not** auto-applied — operators run it with the appropriate `ATMS_RETENTION_PROFILE` set.

Update retention on an already-deployed cluster:

```sql
SELECT remove_retention_policy('traffic_detections', if_exists => true);
SELECT add_retention_policy('traffic_detections', INTERVAL '90 days');
```

Verify:

```sql
SELECT * FROM timescaledb_information.jobs WHERE proc_name = 'policy_retention';
```

## 6. Disaster recovery

### Restore from backup
1. Stop applications writing to Postgres (scale Deployments to 0 in `atms` namespace).
2. Drop and recreate the database.
3. `psql atms < backup.sql`.
4. Re-apply Alembic to head: `alembic upgrade head` (should be a no-op if backup is current).
5. Restart applications.

### Lost a hypertable's chunking
- `0003_hypertables.py`'s downgrade is intentionally a no-op (see ADR-0013). Restore from backup before this revision and re-apply.

### Continuous aggregate stuck not refreshing
- Check the job: `SELECT * FROM timescaledb_information.jobs;`.
- If `next_start` is in the past and `last_run_status` is `Failed`, inspect logs and consider `CALL refresh_continuous_aggregate(...)` to force-refresh, then `SELECT alter_job(<job_id>, scheduled => true)`.

## 7. Out of scope

- **Cross-region replication** — single-region for the pilot.
- **Multi-tenant isolation** — single tenant per cluster.
- **Postgres major-version upgrade** — separate planning doc; involves a TimescaleDB extension upgrade in lockstep.

## 8. What this runbook supersedes

- `database/run_migrations.sh` / `database/run_migrations_docker.sh` — superseded by `alembic upgrade head`. The shell scripts remain in the repo for one release while the migration completes, then are deleted.
- `database/migrations/*.sql` — superseded by Alembic. Archived under `database/migrations/archived/`; see `database/migrations/README.md`.
