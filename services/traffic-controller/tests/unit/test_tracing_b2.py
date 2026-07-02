"""
Tests for shared/atms_common/tracing.py (Phase B2).

Verifies:
- configure_tracing is idempotent
- start_span emits a span with the expected attributes
- trace_id / span_id propagate into JSON log lines while a span is active
- Kafka header inject/extract round-trips the trace context
"""

from __future__ import annotations

import json
import logging

import pytest
import structlog
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from shared.atms_common import logging as atms_logging
from shared.atms_common.tracing import (
    _reset_for_tests,
    configure_tracing,
    extract_kafka_headers,
    inject_kafka_headers,
    start_span,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def in_memory_exporter():
    """Install a fresh in-memory exporter for the duration of one test.

    OTel refuses to override an already-set global TracerProvider, so we
    sidestep the global and inject the tracer into the shared module directly.
    """
    _reset_for_tests()
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    import shared.atms_common.tracing as tr  # noqa: PLC0415

    tr._TRACER = provider.get_tracer("atms-test")  # noqa: SLF001
    tr._CONFIGURED = True  # noqa: SLF001
    yield exporter
    _reset_for_tests()


# ---------------------------------------------------------------------------
# configure_tracing
# ---------------------------------------------------------------------------


class TestConfigureTracing:
    def test_idempotent(self):
        _reset_for_tests()
        configure_tracing(service="svc", version="1.0.0", development=True)
        configure_tracing(service="svc", version="1.0.0", development=True)
        # No exception = pass

    def test_development_mode_uses_console_exporter(self):
        _reset_for_tests()
        # Just verify it doesn't fail — ConsoleSpanExporter prints to stdout.
        configure_tracing(service="svc", version="1.0.0", development=True)
        with start_span("test_span"):
            pass
        _reset_for_tests()


# ---------------------------------------------------------------------------
# start_span
# ---------------------------------------------------------------------------


class TestStartSpan:
    def test_emits_a_span(self, in_memory_exporter):
        with start_span("my_span", attributes={"k": "v"}):
            pass
        spans = in_memory_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "my_span"
        assert spans[0].attributes["k"] == "v"

    def test_nested_spans_share_trace_id(self, in_memory_exporter):
        with start_span("outer") as outer:
            outer_ctx = outer.get_span_context()
            with start_span("inner") as inner:
                inner_ctx = inner.get_span_context()
                assert inner_ctx.trace_id == outer_ctx.trace_id
                assert inner_ctx.span_id != outer_ctx.span_id

    def test_works_without_configuration(self):
        """start_span must not error when no tracer is configured."""
        _reset_for_tests()
        with start_span("orphan_span"):
            pass


# ---------------------------------------------------------------------------
# Logging bridge
# ---------------------------------------------------------------------------


class TestLoggingBridge:
    def test_trace_id_appears_in_log_record_while_span_active(self, in_memory_exporter, capsys):
        atms_logging.configure_logging(service="svc", version="1.0.0")
        log = structlog.get_logger()
        with start_span("traced") as span:
            ctx = span.get_span_context()
            expected_trace_id = format(ctx.trace_id, "032x")
            log.info("inside_span")

        captured = capsys.readouterr().out
        # Find the JSON line for our log entry.
        line = next(
            line for line in captured.splitlines() if '"event": "inside_span"' in line
        )
        record = json.loads(line)
        assert record["trace_id"] == expected_trace_id
        assert record["span_id"] != ""

    def test_no_span_yields_empty_trace_id(self, in_memory_exporter, capsys):
        atms_logging.configure_logging(service="svc", version="1.0.0")
        log = structlog.get_logger()
        log.info("outside_span")
        captured = capsys.readouterr().out
        line = next(
            line for line in captured.splitlines() if '"event": "outside_span"' in line
        )
        record = json.loads(line)
        assert record["trace_id"] == ""


# ---------------------------------------------------------------------------
# Kafka header propagation
# ---------------------------------------------------------------------------


class TestKafkaHeaders:
    def test_inject_adds_traceparent(self, in_memory_exporter):
        with start_span("send"):
            headers = inject_kafka_headers()
        keys = [k for k, _ in headers]
        assert "traceparent" in keys

    def test_inject_extract_round_trip(self, in_memory_exporter):
        with start_span("send") as send_span:
            send_ctx = send_span.get_span_context()
            headers = inject_kafka_headers()

        # Now on the consumer side: extract returns a context that, when
        # attached, makes the child span share the trace id.
        parent_ctx = extract_kafka_headers(headers)
        token = otel_context.attach(parent_ctx)
        try:
            with start_span("recv") as recv_span:
                recv_ctx = recv_span.get_span_context()
        finally:
            otel_context.detach(token)

        assert recv_ctx.trace_id == send_ctx.trace_id

    def test_extract_without_traceparent_returns_empty(self, in_memory_exporter):
        ctx = extract_kafka_headers([])
        # Empty context: attaching it doesn't cause a parent span on next call.
        token = otel_context.attach(ctx)
        try:
            with start_span("orphan") as span:
                # The parent_span_id will be 0 (no parent) when there's no
                # valid context to inherit from.
                assert span.parent is None or not span.parent.is_valid
        finally:
            otel_context.detach(token)

    def test_inject_with_existing_headers(self, in_memory_exporter):
        existing = [("user-header", b"value")]
        with start_span("send"):
            headers = inject_kafka_headers(existing)
        keys = [k for k, _ in headers]
        assert "user-header" in keys
        assert "traceparent" in keys


# ---------------------------------------------------------------------------
# Reset between tests so module state doesn't bleed
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_module_state():
    yield
    # Clear stdlib root handlers added by configure_logging.
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
