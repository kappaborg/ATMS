# Legacy `database/migrations/*.sql`

Phase C4 (ADR-0013) replaces script-based migrations with Alembic. The raw
SQL files that previously lived here have moved to `archived/` for reference;
they are **not** applied to any running cluster.

The Alembic equivalent lives in `database/alembic/versions/`:

| Legacy file | Replaced by |
|-------------|-------------|
| `000_master_migration.sql` | `0001_initial.py` |
| `001_create_intersections.sql` | `0001_initial.py` |
| `002_create_users.sql` | (out of scope — kept until A6 user-store work) |
| `003_create_sensor_devices.sql` | (out of scope — Phase C device-onboarding work) |
| `004_create_traffic_detections.sql` | `0001_initial.py` + `0003_hypertables.py` (hypertable conversion) |
| `005_create_trajectories.sql` | (deferred until used) |
| `006_create_emissions.sql` | (deferred until used) |
| `007_create_traffic_lights.sql` | (deferred until used) |
| `008_create_system_monitoring.sql` | (deferred — Prometheus does this now) |
| `009_create_analytics_config.sql` | (deferred) |
| `999_rollback.sql` | Alembic `downgrade -1` step |

Run migrations:

```bash
cd database
alembic upgrade head
```

Roll back one step:

```bash
alembic downgrade -1
```

See [`docs/runbooks/database.md`](../../docs/runbooks/database.md) for the
full operational procedure.
