# ADR-0010: OpenTelemetry tracing end-to-end

**Status:** Accepted
**Date:** 2026-05-30
**Closes:** PRODUCTION_GAPS.md gap #7 (Phase B2)

## Context

The Phase A1 audit (gap #7) called out the impossibility of debugging multi-service failures: when a wrong signal is commanded at 2am, the on-call engineer cannot follow a single frame from camera → perception → decision → controller → NTCIP without manually correlating logs by timestamp across half a dozen services. B1's logging already has `trace_id` / `span_id` placeholder fields; B2 lights them up by adopting OpenTelemetry.

The B4 resilience primitives (Retry, CircuitBreaker, Bulkhead) and B1 Kafka wrappers are natural span-instrumentation points — each adds observability without changing call-site code.

## Decision

### Standards
- **W3C Trace Context** for HTTP propagation (default in OTel).
- **W3C Trace Context** via Kafka message headers for async propagation (`traceparent`, `tracestate`).
- **OTLP gRPC** as the exporter protocol. Endpoint configured via `OTEL_EXPORTER_OTLP_ENDPOINT` (default `http://otel-collector:4317`).
- Sampling: parent-based with a `ParentBased(TraceIdRatioBased(sample_ratio))` root. Default 100% in dev, 10% in staging, 1% in prod (env-tunable via `OTEL_TRACES_SAMPLER_ARG`).

### `shared/atms_common/tracing.py` — module shape

```python
def configure_tracing(
    *,
    service: str,
    version: str,
    endpoint: str | None = None,
    sample_ratio: float = 1.0,
    insecure: bool = True,
    development: bool = False,  # use ConsoleSpanExporter instead of OTLP
) -> None: ...

def start_span(name: str, *, attributes: dict | None = None) -> Span: ...

def inject_kafka_headers(headers: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]: ...
def extract_kafka_headers(headers: list[tuple[str, bytes]]) -> Context: ...

def instrument_fastapi(app: FastAPI) -> None: ...
```

Idempotent (multiple calls are no-ops after first). Tests use the in-memory exporter via a `configure_tracing(development=True)` + `set_test_exporter()` pattern.

### Span naming convention

| Span name | Producer | Attributes |
|-----------|----------|------------|
| `kafka.send.<topic>` | `AtmsKafkaProducer.send` | `messaging.system=kafka`, `messaging.destination=<topic>`, `messaging.kafka.message_id=<key>` |
| `kafka.consume.<topic>` | `AtmsKafkaConsumer.run_forever` (per-message) | same shape, parent extracted from incoming `traceparent` header |
| `failsafe.tick` | wrapped in `FailsafeController.tick` (via main.py) | `atms.intersection_id`, `atms.mode`, `atms.commanded_phase` |
| `failsafe.submit_decision` | wrapped at `submit_decision` callsite | `atms.decision_id`, `atms.commanded_phase`, `atms.validation_status` |
| `decision_engine.make_decision` | `DecisionEngineService.make_decision` | `atms.intersection_id`, `atms.priority_direction`, `atms.commanded_phase` |
| `ntcip.write` (placeholder, C1) | NTCIP adapter | `atms.intersection_id`, `atms.phase` |
| `http.server` (auto) | FastAPI auto-instrumentation | route, status, latency |

### Bridge to logging

`shared/atms_common/logging.py` adds a structlog processor that reads the current span's `trace_id` and `span_id` from `opentelemetry.trace.get_current_span()` on every log emit. Empty when no span is active (or OTel SDK not initialised). The B1 placeholders are replaced — no other change to the log line shape.

### Kafka header propagation

Producer side: `AtmsKafkaProducer.send` calls `inject_kafka_headers()` to add the current span context as `traceparent` (and `tracestate`) header bytes. aiokafka's `send_and_wait` accepts a `headers` kwarg of `list[tuple[str, bytes]]`.

Consumer side: `AtmsKafkaConsumer.run_forever` calls `extract_kafka_headers()` on each incoming message's headers and uses the extracted context as the parent of the per-message span. The handler runs inside that span so every downstream operation is correlated to the originating camera frame.

### Sampling and overhead

- Default 100% sampling in dev is fine — single-intersection, low msg rate.
- Production tuned via env. The whole adaptive path runs at ~30 Hz per intersection × N intersections; at 1% sampling the OTel overhead is negligible.
- `failsafe.tick` runs at 5 Hz; sampled aggressively, but every state transition is *also* recorded as a span attribute event so context isn't lost on un-sampled ticks.

### Out of scope for B2

- **Metrics via OTel**: keep Prometheus (B1's MetricsRecorder) for now. OTel metrics path stays open; future ADR if we want to consolidate.
- **Logs via OTel**: keep structlog → stdout → Loki (B3). OTel logs are nominally Beta and migration is not urgent.
- **NTCIP span**: Phase C1 wires it.
- **Auto-instrumentation of httpx**: lands with the first httpx caller.

## Consequences

- A new runtime dep: `opentelemetry-{api,sdk,exporter-otlp-proto-grpc,instrumentation-fastapi}`.
- Every service calls `configure_tracing(...)` right after `configure_logging(...)`. Documented in CONTRIBUTING.
- Operators get a single Tempo/Jaeger trace per camera frame end-to-end. The audit's claim "you can't follow a request" is closed.
- A2 (probes across remaining services) becomes "add configure_logging + configure_tracing + HealthRouter" — three lines per service.
- B3 (Loki sink) gains free correlation: log lines already carry `trace_id`, so Loki → click → Tempo round-trip works out of the box.
- A future ADR documents log-and-trace sampling tuning per environment.
