"""
Resilience primitives — Phase B4.

Four async-native primitives:
- `Retry` — tenacity-backed, exponential backoff + jitter
- `CircuitBreaker` — async state machine (CLOSED / OPEN / HALF_OPEN)
- `Bulkhead` — named asyncio.Semaphore with saturation metric
- `with_timeout` — bounded asyncio.wait_for raising OperationTimeout

Composition (outer → inner) for a hardened call:

    Bulkhead → CircuitBreaker → Retry → with_timeout → upstream

See docs/adr/0009-resilience-patterns.md.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

import tenacity

from shared.atms_common.errors import AtmsError, SafetyViolation
from shared.atms_common.metrics import InMemoryMetrics, MetricsRecorder

T = TypeVar("T")


# Default in-memory metrics so callers that don't inject one still emit.
# Production code injects a real Prometheus-backed recorder.
_DEFAULT_METRICS: MetricsRecorder = InMemoryMetrics()


def _now_s() -> float:
    return time.monotonic()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CircuitBreakerOpenError(AtmsError):
    """Raised when a CircuitBreaker is OPEN and a call is short-circuited."""


class OperationTimeout(AtmsError):
    """Raised when `with_timeout` exceeds its deadline."""

    def __init__(self, name: str, timeout_s: float) -> None:
        super().__init__(f"operation {name!r} timed out after {timeout_s}s")
        self.name = name
        self.timeout_s = timeout_s


# ---------------------------------------------------------------------------
# with_timeout
# ---------------------------------------------------------------------------


async def with_timeout(
    awaitable: Awaitable[T],
    *,
    timeout_s: float,
    name: str,
    metrics: MetricsRecorder | None = None,
) -> T:
    """Bound an `await` with a named timeout. Raises OperationTimeout on expiry."""
    m = metrics or _DEFAULT_METRICS
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_s)
    except TimeoutError as e:
        m.inc("atms_operation_timeouts_total", labels={"name": name})
        raise OperationTimeout(name=name, timeout_s=timeout_s) from e


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


# Exceptions that are NEVER retried — these are programmer errors or hard
# safety violations and should propagate immediately.
_NEVER_RETRY: tuple[type[BaseException], ...] = (
    SafetyViolation,
    ValueError,
    TypeError,
    KeyboardInterrupt,
    SystemExit,
    asyncio.CancelledError,
)


@dataclass(frozen=True)
class Retry:
    """
    Async retry policy. Exponential backoff with full jitter.

    Defaults are conservative; tighten per call-site as needed.
    """

    name: str
    attempts: int = 3
    base_delay_s: float = 0.2
    max_delay_s: float = 5.0
    # Tuple of additional exception classes that trigger a retry. By default
    # AtmsError (and its non-_NEVER_RETRY subclasses) trigger a retry.
    retry_on: tuple[type[BaseException], ...] = (AtmsError,)

    async def call(self, fn: Callable[..., Awaitable[T]], /, *args: Any, **kwargs: Any) -> T:
        metrics = kwargs.pop("_metrics", None) or _DEFAULT_METRICS

        def _should_retry(exc: BaseException) -> bool:
            if isinstance(exc, _NEVER_RETRY):
                return False
            return isinstance(exc, self.retry_on)

        retryer = tenacity.AsyncRetrying(
            stop=tenacity.stop_after_attempt(self.attempts),
            wait=tenacity.wait_random_exponential(
                multiplier=self.base_delay_s, max=self.max_delay_s
            ),
            retry=tenacity.retry_if_exception(_should_retry),
            reraise=True,
        )
        try:
            async for attempt in retryer:
                with attempt:
                    result = await fn(*args, **kwargs)
            metrics.inc(
                "atms_retry_attempts_total",
                labels={"name": self.name, "outcome": "success"},
            )
            return result
        except BaseException:
            metrics.inc(
                "atms_retry_attempts_total",
                labels={"name": self.name, "outcome": "exhausted"},
            )
            raise


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _BreakerState:
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    consecutive_half_open_successes: int = 0
    opened_at_s: float = 0.0


class CircuitBreaker:
    """
    Async circuit breaker. Thread-unsafe; use one per-resource per-process.
    """

    def __init__(
        self,
        *,
        name: str,
        failure_threshold: int = 5,
        reset_timeout_s: float = 30.0,
        half_open_successes_required: int = 2,
        metrics: MetricsRecorder | None = None,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout_s = reset_timeout_s
        self.half_open_successes_required = half_open_successes_required
        self._state = _BreakerState()
        self._metrics = metrics or _DEFAULT_METRICS
        self._emit_state_gauges()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        return self._state.state

    async def call(self, fn: Callable[..., Awaitable[T]], /, *args: Any, **kwargs: Any) -> T:
        self._maybe_half_open()
        if self._state.state is CircuitState.OPEN:
            self._metrics.inc(
                "atms_circuit_breaker_short_circuited_total",
                labels={"name": self.name},
            )
            raise CircuitBreakerOpenError(
                f"circuit breaker {self.name!r} is OPEN; not attempting upstream call"
            )
        try:
            result = await fn(*args, **kwargs)
        except _NEVER_RETRY:
            # Programmer errors don't count against the breaker.
            raise
        except BaseException:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result

    def force_open(self, reason: str = "manual") -> None:
        """Operator-initiated open. Audit-logged via metrics + transition counter."""
        self._transition_to(CircuitState.OPEN, reason=reason)
        self._state.opened_at_s = _now_s()

    def force_close(self) -> None:
        self._state.consecutive_failures = 0
        self._state.consecutive_half_open_successes = 0
        self._transition_to(CircuitState.CLOSED, reason="manual_reset")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _maybe_half_open(self) -> None:
        if self._state.state is not CircuitState.OPEN:
            return
        if _now_s() - self._state.opened_at_s < self.reset_timeout_s:
            return
        self._state.consecutive_half_open_successes = 0
        self._transition_to(CircuitState.HALF_OPEN, reason="reset_timeout_elapsed")

    def _on_success(self) -> None:
        if self._state.state is CircuitState.HALF_OPEN:
            self._state.consecutive_half_open_successes += 1
            if self._state.consecutive_half_open_successes >= self.half_open_successes_required:
                self._state.consecutive_failures = 0
                self._transition_to(CircuitState.CLOSED, reason="half_open_probe_succeeded")
        else:
            self._state.consecutive_failures = 0

    def _on_failure(self) -> None:
        if self._state.state is CircuitState.HALF_OPEN:
            # Any failure during probing → re-open.
            self._state.opened_at_s = _now_s()
            self._transition_to(CircuitState.OPEN, reason="half_open_probe_failed")
            return
        self._state.consecutive_failures += 1
        if self._state.consecutive_failures >= self.failure_threshold:
            self._state.opened_at_s = _now_s()
            self._transition_to(CircuitState.OPEN, reason="failure_threshold_reached")

    def _transition_to(self, new_state: CircuitState, *, reason: str) -> None:
        old = self._state.state
        if new_state is old:
            return
        self._state.state = new_state
        self._metrics.inc(
            "atms_circuit_breaker_transitions_total",
            labels={"name": self.name, "from": old.value, "to": new_state.value, "reason": reason},
        )
        self._emit_state_gauges()

    def _emit_state_gauges(self) -> None:
        for s in CircuitState:
            self._metrics.set_gauge(
                "atms_circuit_breaker_state",
                value=1.0 if s is self._state.state else 0.0,
                labels={"name": self.name, "state": s.value},
            )


# ---------------------------------------------------------------------------
# Bulkhead
# ---------------------------------------------------------------------------


class Bulkhead:
    """Bounded-concurrency `asyncio.Semaphore` with saturation metric."""

    def __init__(
        self,
        *,
        name: str,
        max_concurrent: int,
        metrics: MetricsRecorder | None = None,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self.name = name
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._in_flight = 0
        self._metrics = metrics or _DEFAULT_METRICS
        self._emit_in_flight()

    async def __aenter__(self) -> Bulkhead:
        # If we can't acquire immediately, record saturation.
        if self._semaphore.locked() or self._in_flight >= self.max_concurrent:
            self._metrics.inc("atms_bulkhead_saturated_total", labels={"name": self.name})
        await self._semaphore.acquire()
        self._in_flight += 1
        self._emit_in_flight()
        return self

    async def __aexit__(self, _et: Any, _ev: Any, _tb: Any) -> None:
        self._in_flight -= 1
        self._semaphore.release()
        self._emit_in_flight()

    async def call(self, fn: Callable[..., Awaitable[T]], /, *args: Any, **kwargs: Any) -> T:
        async with self:
            return await fn(*args, **kwargs)

    def _emit_in_flight(self) -> None:
        self._metrics.set_gauge(
            "atms_bulkhead_in_flight",
            value=float(self._in_flight),
            labels={"name": self.name},
        )


# ---------------------------------------------------------------------------
# Convenience: compose Bulkhead + Breaker + Retry + with_timeout
# ---------------------------------------------------------------------------


async def hardened_call(
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    bulkhead: Bulkhead | None = None,
    breaker: CircuitBreaker | None = None,
    retry: Retry | None = None,
    timeout_s: float | None = None,
    timeout_name: str | None = None,
    metrics: MetricsRecorder | None = None,
    **kwargs: Any,
) -> T:
    """One-call composition of every B4 primitive (see ADR-0009)."""

    async def _inner() -> T:
        if timeout_s is not None:
            name = timeout_name or (breaker.name if breaker else "hardened_call")
            return await with_timeout(
                fn(*args, **kwargs), timeout_s=timeout_s, name=name, metrics=metrics
            )
        return await fn(*args, **kwargs)

    async def _with_retry() -> T:
        if retry is not None:
            return await retry.call(_inner, _metrics=metrics)
        return await _inner()

    async def _with_breaker() -> T:
        if breaker is not None:
            return await breaker.call(_with_retry)
        return await _with_retry()

    if bulkhead is not None:
        async with bulkhead:
            return await _with_breaker()
    return await _with_breaker()
