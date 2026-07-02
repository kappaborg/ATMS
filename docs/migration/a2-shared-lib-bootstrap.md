# A2 — Migrating services onto `shared/atms_common/`

The senior-engineer prompt's A2 task: every service should use the shared library's logging + tracing + health-probe bootstrap so a single Grafana dashboard works across the fleet. This doc shows the migration pattern and tracks per-service status.

## The bootstrap pattern (~15 lines)

Drop this into the top of every service's `main.py`, right after the existing imports and before the FastAPI app is created. Adjust `service=` to the service's name.

```python
import os
import sys
from pathlib import Path

# Make `shared.*` importable.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Phase B1/B2/B3 — shared observability bootstrap.
from shared.atms_common.logging import configure_logging
from shared.atms_common.tracing import configure_tracing, instrument_fastapi

configure_logging(
    service="<service-name>",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    intersection_id=int(os.getenv("ATMS_INTERSECTION_ID", "1")),
    level=os.getenv("LOG_LEVEL", "INFO"),
    development=os.getenv("ATMS_LOG_DEV", "").lower() in ("1", "true", "yes"),
)
configure_tracing(
    service="<service-name>",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    sample_ratio=float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")),
    development=os.getenv("ATMS_OTEL_DEV", "1").lower() in ("1", "true", "yes"),
)
```

Then, right after `app = FastAPI(...)`:

```python
instrument_fastapi(app)
```

Replace any `logging.basicConfig(...)` block with `configure_logging` — keep stdlib `logger = logging.getLogger(__name__)` (it now writes through structlog).

### Optional: `HealthRouter`

If the service does not already have `/live`, `/ready`, `/startup` endpoints (or you want to standardise them):

```python
from shared.atms_common.health import HealthRouter, CheckResult

_health = HealthRouter(service_name="<service-name>")

async def _kafka_dep_check() -> CheckResult:
    return CheckResult(ok=True, detail="ok")

_health.add_check("kafka", _kafka_dep_check)
_health.attach(app)
_health.mark_started()  # call after async init is done
```

## What each service inherits, automatically

- **JSON logs** with `service`, `version`, `intersection_id`, `trace_id`, `span_id`, `decision_id` (when bound).
- **OTLP spans** for every HTTP request (FastAPI auto-instrumentation), every Kafka produce/consume (via `shared.atms_common.kafka`), and any explicit `start_span(...)` blocks.
- **Trace context propagation** across Kafka boundaries (W3C `traceparent` header).
- **Trace-ID click-through** in Grafana from any log line to Tempo.

## Per-service status

| Service | LoC | Status | Notes |
|---------|----:|--------|-------|
| traffic-controller | ~700 | ✅ done (B1+B2) | Reference implementation; HealthRouter wired. |
| decision-engine | ~430 | ✅ done (B1+B2) | HealthRouter follow-up tracked. |
| api-gateway | 380 | ✅ done (A2) | Bootstrap + instrument_fastapi. No HealthRouter yet. |
| data-aggregator | 276 | ✅ done (A2) | Bootstrap + instrument_fastapi. |
| intersection-coordinator | 668 | ✅ done (A2) | Bootstrap + instrument_fastapi. |
| ntcip-interface | 410 | ✅ done (A2) | Bootstrap + instrument_fastapi. Key for C1 trace continuity. |
| analytics | 407 | ✅ done (A2) | Bootstrap + instrument_fastapi. |
| dashboard | 432 | ✅ done (A2) | Bootstrap + instrument_fastapi. UI-side trace passthrough is a follow-up. |
| video-processor | 1981 | ⏳ deferred | Monolith — refactor into smaller modules first (see B1/A2 follow-up issue). |
| ai-perception | 1999 | ⏳ deferred | Monolith — refactor first. Highest LoC, sophisticated patterns already; needs careful migration. |
| sensor-fusion | (multi-file) | ⏳ deferred | Has its own subdir structure; migrate after its internal refactor. |

`✅ done`: bootstrap in place, service emits JSON logs and OTel spans through the shared collector.

`⏳ pending`: straightforward to apply, just hasn't shipped yet — small follow-up PR.

`⏳ deferred`: large or complex service that benefits from a refactor first; track separately.

## Verification

After applying the bootstrap to a service:

1. **Compile:** `python -m py_compile services/<service>/src/main.py`
2. **Start it locally:** `uvicorn services.<service>.src.main:app` (or the service's existing run command). Logs should be JSON.
3. **Trace in dev:** with `ATMS_OTEL_DEV=1` (default), spans print to stdout. Look for `kind: SpanKind.SERVER` entries.
4. **Cluster verify (after Loki/Tempo deploy):** Grafana → Explore → Loki → `{service="<service>"} | json` should show the service's lines with `trace_id` populated.

## Rollback

The bootstrap is purely additive. If a service misbehaves after the change, revert the import + `configure_*` calls + `instrument_fastapi`. No state migration needed.
