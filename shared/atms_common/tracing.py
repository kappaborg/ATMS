"""
OpenTelemetry tracing bootstrap and helpers — Phase B2.

`configure_tracing()` is called by every service right after `configure_logging`.
After it runs:
- `start_span(name)` opens a span that participates in the trace.
- `inject_kafka_headers` / `extract_kafka_headers` propagate the trace context
  across async Kafka boundaries.
- `instrument_fastapi(app)` adds the FastAPI auto-instrumentation so every
  HTTP request is a span automatically.
- Structured logging (`shared.atms_common.logging`) picks up the active
  `trace_id` / `span_id` from the OpenTelemetry context.

Idempotent — calling configure_tracing twice is a no-op.

See ADR-0010.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.propagators.textmap import Getter, Setter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    ParentBased,
    TraceIdRatioBased,
)
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

_CONFIGURED = False
_TRACER: trace.Tracer | None = None


def configure_tracing(
    *,
    service: str,
    version: str,
    endpoint: str | None = None,
    sample_ratio: float = 1.0,
    insecure: bool = True,
    development: bool = False,
) -> None:
    """Bootstrap OTel. Idempotent.

    Args:
        service: short name (e.g., "traffic-controller").
        version: semver.
        endpoint: OTLP gRPC URL. Defaults to env `OTEL_EXPORTER_OTLP_ENDPOINT`
            or `http://otel-collector:4317`.
        sample_ratio: parent-based ratio sampler root probability.
            1.0 = sample everything (dev). 0.01 = 1% (prod).
        insecure: pass-through to the OTLP gRPC exporter (TLS off for in-cluster).
        development: if True, use the ConsoleSpanExporter (prints to stdout)
            instead of OTLP. Useful for local dev when no collector is running.
    """
    global _CONFIGURED, _TRACER  # noqa: PLW0603 — singleton pattern
    if _CONFIGURED:
        return

    resource = Resource.create(
        {
            "service.name": service,
            "service.version": version,
        }
    )

    if sample_ratio >= 1.0:
        sampler = ParentBased(root=ALWAYS_ON)
    elif sample_ratio <= 0.0:
        sampler = ParentBased(root=ALWAYS_OFF)
    else:
        sampler = ParentBased(root=TraceIdRatioBased(sample_ratio))

    provider = TracerProvider(resource=resource, sampler=sampler)

    if development:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        # Lazy import — only in non-dev path, so unit tests don't need grpc.
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=insecure))
        )

    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer(service, version)
    _CONFIGURED = True


def get_tracer() -> trace.Tracer:
    """Return the project tracer. Falls back to a no-op tracer if not configured."""
    if _TRACER is not None:
        return _TRACER
    return trace.get_tracer("atms")


def start_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> AbstractContextManager[Span]:
    """Open a span. Use as a context manager."""
    return get_tracer().start_as_current_span(name, attributes=attributes or {}, kind=kind)


def record_exception(span: Span, exc: BaseException, *, escaped: bool = True) -> None:
    """Convenience: record an exception on a span and set status to ERROR."""
    span.record_exception(exc, escaped=escaped)
    span.set_status(Status(StatusCode.ERROR, str(exc)))


# ---------------------------------------------------------------------------
# Kafka header propagation
# ---------------------------------------------------------------------------


class _KafkaHeadersSetter(Setter[list[tuple[str, bytes]]]):
    def set(self, carrier: list[tuple[str, bytes]], key: str, value: str) -> None:
        # Replace any existing entry with the same key, then append.
        for i, (k, _) in enumerate(carrier):
            if k == key:
                carrier[i] = (key, value.encode("utf-8"))
                return
        carrier.append((key, value.encode("utf-8")))


class _KafkaHeadersGetter(Getter[Iterable[tuple[str, bytes | None]]]):
    def get(self, carrier: Iterable[tuple[str, bytes | None]], key: str) -> list[str] | None:
        values = [v.decode("utf-8") for k, v in carrier if k == key and v is not None]
        return values or None

    def keys(self, carrier: Iterable[tuple[str, bytes | None]]) -> list[str]:
        return [k for k, _ in carrier]


_KAFKA_SETTER = _KafkaHeadersSetter()
_KAFKA_GETTER = _KafkaHeadersGetter()


def inject_kafka_headers(
    headers: list[tuple[str, bytes]] | None = None,
) -> list[tuple[str, bytes]]:
    """
    Add the current trace context (`traceparent`, `tracestate`) to a Kafka
    message header list. Returns the (possibly newly-allocated) list.
    """
    out = list(headers) if headers else []
    propagate.inject(out, setter=_KAFKA_SETTER)
    return out


def extract_kafka_headers(
    headers: Iterable[tuple[str, bytes | None]] | None,
) -> otel_context.Context:
    """
    Extract a parent context from incoming Kafka message headers. Returns an
    empty context if no traceparent is present.
    """
    if headers is None:
        return otel_context.Context()
    return propagate.extract(headers, getter=_KAFKA_GETTER)


# ---------------------------------------------------------------------------
# FastAPI auto-instrumentation
# ---------------------------------------------------------------------------


def instrument_fastapi(app: Any) -> None:
    """
    Add FastAPI auto-instrumentation. Every HTTP request becomes a span with
    route, status_code, latency. Idempotent on the same app.
    """
    from opentelemetry.instrumentation.fastapi import (
        FastAPIInstrumentor,
    )

    FastAPIInstrumentor.instrument_app(app)


# ---------------------------------------------------------------------------
# Test helper: reset module-level config so tests can re-init with a different
# exporter. NOT for production use.
# ---------------------------------------------------------------------------


def _reset_for_tests() -> None:
    global _CONFIGURED, _TRACER  # noqa: PLW0603 — test-only helper
    _CONFIGURED = False
    _TRACER = None
