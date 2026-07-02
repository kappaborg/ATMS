# ADR-0009: Resilience patterns — retry, circuit breaker, bulkhead, timeout

**Status:** Accepted
**Date:** 2026-05-30
**Closes:** PRODUCTION_GAPS.md gap #14 (Phase B4)

## Context

The Phase A1 chaos integration test proved the system's first failure mode: when Kafka goes silent, the failsafe correctly falls back to fixed-time, **but** the path that should retry / reconnect / time out cleanly was the bare aiokafka client with no policy. In a real outage we'd see:

- `await kafka_producer.send_and_wait(...)` blocking forever
- Threads piling up on stuck calls
- No backoff between reconnect attempts (thundering herd)
- No way to express "this dependency is sick, stop trying for a bit"
- No bulkhead between the AI inference path and the control path

The audit (gap #14) called out the absence of every classical resilience pattern. B1 already surfaced the failure types (`KafkaError`) and added retry hooks; B4 fills them in for real.

## Decision

Four primitives, all in `shared/atms_common/resilience.py`. Each is async-native, emits metrics, and has a name (used in the metric label so dashboards can attribute saturation/breaks).

### 1. `Retry` — `tenacity`-backed retry policy

Wraps `tenacity` with sensible defaults for the project:
- 3 attempts (configurable per-callsite)
- Exponential backoff: `base_delay_s * 2^(attempt-1)`, capped at `max_delay_s`
- Full jitter (random uniform [0, computed_delay])
- Retries on `AtmsError` and its configured subtypes; **never** retries on `SafetyViolation` or `ValueError` (programmer errors)
- Emits `atms_retry_attempts_total{name,outcome="success|exhausted"}`

### 2. `CircuitBreaker` — async state machine

Three states: `CLOSED` (normal), `OPEN` (failing fast), `HALF_OPEN` (probing).

Transitions:
- `CLOSED → OPEN`: `failure_threshold` consecutive failures
- `OPEN → HALF_OPEN`: `reset_timeout_s` elapsed since opening
- `HALF_OPEN → CLOSED`: `half_open_successes_required` consecutive successes
- `HALF_OPEN → OPEN`: any failure during probing

While `OPEN`, calls fail immediately with `CircuitBreakerOpenError` — no upstream call is attempted. A sick dependency cannot starve the calling service.

Emits:
- `atms_circuit_breaker_state{name,state}` (gauge, 1 for current state)
- `atms_circuit_breaker_transitions_total{name,from,to}` (counter)
- `atms_circuit_breaker_short_circuited_total{name}` (counter for fast-fail)

### 3. `Bulkhead` — named `asyncio.Semaphore`

Bounded concurrency for a logical resource. Ensures slow upstreams don't starve fast ones:
- AI inference (potentially slow under load) gets its own bulkhead
- Control-loop ticks (fast, deadline-bounded) get their own bulkhead
- A noisy ML batch job can't exhaust the controller's tick capacity

Emits:
- `atms_bulkhead_in_flight{name}` (gauge)
- `atms_bulkhead_saturated_total{name}` (counter — incremented when a call had to wait)

### 4. `with_timeout` — bounded `asyncio.wait_for`

Cross-cutting rule: **no unbounded `await` in the codebase**. Every external call gets a named timeout. On expiry, raises `OperationTimeout` (subclass of `AtmsError`) with the name and elapsed time.

Emits `atms_operation_timeouts_total{name}` (counter).

## Combining the primitives — call-site pattern

A "hardened call" wraps the primitives in this order (outer to inner):

```
Bulkhead → CircuitBreaker → Retry → with_timeout → upstream call
```

Reasoning:
- **Bulkhead outermost** — wait for capacity before deciding to call at all
- **Breaker next** — fail fast if the dependency is known-sick
- **Retry inside breaker** — retries count against the breaker's failure tally
- **Timeout innermost** — each underlying attempt is bounded

`shared/atms_common/kafka.py` (B1) is updated to use this composition for `send_and_wait`.

## Configuration defaults

| Pattern | Parameter | Default | Source |
|---------|-----------|---------|--------|
| Retry | attempts | 3 | Operator policy |
| Retry | base_delay_s | 0.2 | Avoids thundering herd, fast enough for the control loop |
| Retry | max_delay_s | 5 | Bounded so failsafe staleness window (2s) trips before retry timeout |
| Breaker | failure_threshold | 5 | Tolerates a transient run; fast enough to react |
| Breaker | reset_timeout_s | 30 | Half a minute is typical for a broker leader election |
| Breaker | half_open_successes_required | 2 | Two consecutive successes to declare healthy |
| Bulkhead | ai_inference | 4 | One per GPU on a single Jetson; adjust per hardware |
| Bulkhead | control_loop | 1 | Single-writer guarantee |
| Timeout | kafka_send | 2s | Within decision validity window |
| Timeout | ntcip_write | 1s | NTCIP latency over LAN is sub-100ms typical |
| Timeout | http_default | 5s | Operator-facing endpoints |

## Out of scope for B4

- **HTTP client wrapper** (`shared/atms_common/http.py`) — neither service currently makes outbound HTTP calls. The pattern composes cleanly with `with_timeout` + `Retry`; lands in the PR that introduces the first HTTP caller (likely B2 OTel exporter).
- **NTCIP SNMP integration** — that's Phase C1. The breaker config above is the contract C1 should honour.
- **Distributed-trace propagation through breakers** — B2 work.

## Consequences

- A single line — `from shared.atms_common.resilience import Retry, CircuitBreaker, Bulkhead, with_timeout` — replaces ~50 lines of hand-rolled try/except + sleep loops per service.
- Every `await` that crosses a process boundary should be wrapped. B4 enforces this for Kafka; subsequent PRs apply it as new boundaries appear.
- Tenacity is added to the runtime dependency set (already in test deps).
- Operators get a uniform observability surface across resilience events; one Grafana dashboard works for every service.
