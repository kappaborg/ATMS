# ADR-0008: `shared/atms_common/` library — scope and migration strategy

**Status:** Accepted
**Date:** 2026-05-30
**Closes (partial):** PRODUCTION_GAPS.md gap #9 (B1)

## Context

The Phase A audit (gap #9) flagged service inconsistency as a major risk:
- `services/ai-perception/src/main.py` is **1,999 lines** with sophisticated patterns.
- `services/decision-engine/src/main.py` is **329 lines** of bare async loops.
- `services/traffic-controller/src/main.py` was **409 lines** before Phase A; now Phase-A-extended.

Every service reinvents its own logging setup, env-var parsing, Kafka client wiring, and health-endpoint structure. The result is that a code-review of one service teaches you nothing about another, and a fix in one place doesn't propagate.

Phase A already started extracting shared modules:
- `shared/atms_common/clock.py` — A1
- `shared/atms_common/decision.py` — A1
- `shared/atms_common/metrics.py` — A1
- `shared/atms_common/safety.py` — A1
- `shared/atms_common/auth.py` — A6
- `shared/atms_common/preempt.py` — A7

B1 completes the foundational layer so every service can share one idiom.

## Decision

### Modules added in B1 (this ADR)

| Module | Purpose | Replaces in current code |
|--------|---------|--------------------------|
| `errors.py` | Domain exception hierarchy: `AtmsError`, `ConfigError`, `SchemaError`, `KafkaError`, `ControllerError`, `SafetyViolation`. `auth.AuthError` re-exported here. | Scattered `raise Exception("...")` and bare `except Exception` blocks. |
| `config.py` | `AtmsBaseSettings(BaseSettings)` — common fields (kafka, postgres, redis, auth, log_level, intersection_id). Each service subclasses with its specifics. Validation at startup. | ~20 `os.getenv(...)` calls per service. |
| `logging.py` | `configure_logging()` bootstrap. structlog with JSON renderer, fields: `service`, `version`, `trace_id`, `span_id`, `intersection_id`. Redirects stdlib `logging.getLogger` to the same output. | `logging.basicConfig(...)` in every service. |
| `health.py` | `HealthRouter` factory exposing `/live`, `/ready`, `/startup`. Pluggable `HealthCheck` protocol; bundled checks for kafka, postgres, redis, model-loaded. Probe semantics that match K8s expectations. | Hand-rolled `/live` etc. in each service. |
| `kafka.py` | `AtmsKafkaProducer` (idempotent), `AtmsKafkaConsumer` (manual commit, optional DLQ). Schema-validation hook. Pre-Phase-B4: surfaces failures via `KafkaError` — real circuit-breaker and retries land in B4. | Bespoke `start_kafka`/`stop_kafka` in each service. |

### Modules deferred to a later phase

| Module | Phase | Why deferred |
|--------|-------|--------------|
| `tracing.py` | B2 | OTel SDK + OTLP exporter; depends on the collector being deployed. |
| `http.py` (httpx client) | B4 | Adds tenacity-based retries + circuit breaker which are themselves B4 work. |
| `events.py` (structured event emitter) | B3 | Hooks into structlog + tracing; arrives with B3. |

The B1 modules above define **stubs / placeholders** where B2/B3/B4 features plug in — e.g., `configure_logging()` already accepts a `trace_id` field and emits it (empty string until B2 wires OTel).

### Migration strategy (existing services)

1. **Additive**: new modules ship alongside existing code. Services migrate when they touch the relevant area; no big-bang rewrites.
2. **Tests stay green during migration**: the traffic-controller's 110 tests and decision-engine's 43 tests must not regress.
3. **Old patterns are deprecated, not deleted**: the `os.getenv` calls in `main.py` keep working until each service migrates to its `Settings` class. Same for `logging.basicConfig`. Only the auth wiring (already on shared lib) and the failsafe-only types stay obligatory.
4. **B1 PR proves it**: traffic-controller is refactored onto the new shared lib in the same PR that adds the modules. The refactor demonstrates the migration and forces the API to be ergonomic.
5. **Decision-engine and others follow in subsequent PRs** — each one independently small.

### Public API surface (snapshot)

```python
from shared.atms_common import (
    AtmsError, ConfigError, SchemaError, KafkaError, ControllerError, SafetyViolation,
    AtmsBaseSettings, configure_logging,
    HealthRouter, HealthCheck, CheckResult,
    AtmsKafkaProducer, AtmsKafkaConsumer,
)
```

(Backwards-compatible: the existing imports — `Clock`, `DecisionMessage`, `MetricsRecorder`, `Principal`, etc. — keep working.)

## Consequences

- The `shared/` directory becomes the canonical home for cross-service logic. Anything that lives in two services and serves the same purpose belongs here.
- Every new service starts from a `Settings(AtmsBaseSettings)` + `configure_logging()` + `HealthRouter.attach(app)` skeleton — three lines instead of fifty.
- A2 (probes for the remaining 9 services) becomes mechanical and ~1 line per service after B1 ships.
- The shared library imports FastAPI + aiokafka + Pydantic + structlog at module level (already true for `auth.py` since A6). Tests for these modules pull in those deps; that's already the case in our test environment.
- A future ADR documents the API contract once B2/B3/B4 land and the library stabilises.
