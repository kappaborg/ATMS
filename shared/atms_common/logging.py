"""
Structured JSON logging — Phase B1.

`configure_logging()` is the single bootstrap helper every service calls at
startup. After it runs:

- `structlog.get_logger()` and `logging.getLogger()` both emit JSON.
- Each log line carries `service`, `version`, `intersection_id`, `trace_id`,
  `span_id` (the last two are empty strings until Phase B2 wires OpenTelemetry).
- The root stdlib logger is redirected through structlog so legacy
  `logging.getLogger("uvicorn")` etc. also produce JSON.

See ADR-0008.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

# Module-level context that every log line includes. Mutated by
# configure_logging(); reads must NOT mutate.
_CONTEXT: dict[str, Any] = {
    "service": "",
    "version": "",
    "intersection_id": "",
    "trace_id": "",
    "span_id": "",
}


def _inject_static_context(_logger: Any, _name: str, event_dict: EventDict) -> EventDict:
    for k, v in _CONTEXT.items():
        event_dict.setdefault(k, v)
    return event_dict


def _inject_otel_context(_logger: Any, _name: str, event_dict: EventDict) -> EventDict:
    """
    Phase B2 — pull `trace_id` / `span_id` from the OpenTelemetry active span
    context. Empty strings when no span is active or the SDK isn't initialised.
    Idempotent on top of the B1 placeholder fields.
    """
    try:
        from opentelemetry import trace  # noqa: PLC0415

        span = trace.get_current_span()
        ctx = span.get_span_context() if span is not None else None
        if ctx is not None and ctx.is_valid:
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
    except ImportError:
        # OTel not installed in this environment — keep B1 placeholders.
        pass
    return event_dict


def _drop_color_message_key(_logger: Any, _name: str, event_dict: EventDict) -> EventDict:
    # uvicorn's access logger adds a noisy `color_message`; we don't want it.
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging(
    *,
    service: str,
    version: str,
    intersection_id: int | None = None,
    level: str = "INFO",
    development: bool = False,
) -> None:
    """
    Bootstrap structured logging. Idempotent — safe to call multiple times.

    Args:
        service: short service name (e.g., "traffic-controller").
        version: semver of the running service.
        intersection_id: per-intersection identity; included in every line.
        level: stdlib log level name.
        development: if True, use a colorised console renderer instead of JSON.
    """
    _CONTEXT["service"] = service
    _CONTEXT["version"] = version
    _CONTEXT["intersection_id"] = "" if intersection_id is None else str(intersection_id)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        _inject_static_context,
        _inject_otel_context,
        _drop_color_message_key,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        timestamper,
    ]

    if development:
        renderer: Processor = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Redirect stdlib logging into structlog so libraries (FastAPI, uvicorn,
    # aiokafka) emit JSON too.
    stdlib_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(stdlib_formatter)

    root = logging.getLogger()
    # Idempotency: replace handlers we own; leave others alone.
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler):
            root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level.upper())


def bind_intersection(intersection_id: int) -> None:
    """Update the static intersection_id on subsequent log lines."""
    _CONTEXT["intersection_id"] = str(intersection_id)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Convenience wrapper around `structlog.get_logger`."""
    return structlog.get_logger(name)


# ---------------------------------------------------------------------------
# Phase B3 — per-request / per-decision context binding via structlog contextvars.
# Safe across async tasks (structlog.contextvars uses contextvars.ContextVar).
# ---------------------------------------------------------------------------

from contextlib import contextmanager  # noqa: E402
from typing import Iterator  # noqa: E402, UP035


@contextmanager
def bind_decision_id(decision_id: int) -> Iterator[None]:
    """
    Bind `decision_id` to every log line emitted within the scope.

    Pattern at use site:

        with bind_decision_id(msg["decision_id"]):
            failsafe.submit_decision(msg)
            ...

    Every log call inside the with-block carries `decision_id` as a JSON field.
    """
    structlog.contextvars.bind_contextvars(decision_id=str(decision_id))
    try:
        yield
    finally:
        structlog.contextvars.unbind_contextvars("decision_id")


@contextmanager
def bind_log_context(**fields: object) -> Iterator[None]:
    """
    General-purpose contextvars binder. Use for per-request principal id,
    per-frame frame id, per-intersection id (when one process serves many), etc.

    Example:
        with bind_log_context(principal_sub=p.sub, request_id=req_id):
            ...
    """
    str_fields = {k: str(v) for k, v in fields.items()}
    structlog.contextvars.bind_contextvars(**str_fields)
    try:
        yield
    finally:
        structlog.contextvars.unbind_contextvars(*str_fields.keys())
