"""
Tests for shared/atms_common/resilience.py (Phase B4).

Covers Retry, CircuitBreaker, Bulkhead, with_timeout, hardened_call.
"""

from __future__ import annotations

import asyncio

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from shared.atms_common.errors import AtmsError, KafkaError, SafetyViolation
from shared.atms_common.metrics import InMemoryMetrics
from shared.atms_common.resilience import (
    Bulkhead,
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    OperationTimeout,
    Retry,
    hardened_call,
    with_timeout,
)


# ---------------------------------------------------------------------------
# with_timeout
# ---------------------------------------------------------------------------


class TestWithTimeout:
    async def test_success_path(self):
        async def quick() -> int:
            return 42

        result = await with_timeout(quick(), timeout_s=1.0, name="t")
        assert result == 42

    async def test_timeout_raises_operation_timeout(self):
        async def slow() -> None:
            await asyncio.sleep(0.5)

        with pytest.raises(OperationTimeout) as exc:
            await with_timeout(slow(), timeout_s=0.05, name="slow")
        assert exc.value.name == "slow"

    async def test_timeout_increments_metric(self):
        m = InMemoryMetrics()

        async def slow() -> None:
            await asyncio.sleep(0.5)

        with pytest.raises(OperationTimeout):
            await with_timeout(slow(), timeout_s=0.05, name="slow", metrics=m)
        assert m.counter("atms_operation_timeouts_total", {"name": "slow"}) == 1


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


class TestRetry:
    async def test_success_first_attempt(self):
        m = InMemoryMetrics()
        retry = Retry(name="r", attempts=3, base_delay_s=0.01, max_delay_s=0.05)

        async def ok() -> str:
            return "yes"

        result = await retry.call(ok, _metrics=m)
        assert result == "yes"
        assert m.counter("atms_retry_attempts_total", {"name": "r", "outcome": "success"}) == 1

    async def test_succeeds_after_two_failures(self):
        attempts = {"n": 0}
        retry = Retry(name="r", attempts=3, base_delay_s=0.001, max_delay_s=0.01)

        async def flaky() -> str:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise KafkaError("flaky")
            return "ok"

        result = await retry.call(flaky)
        assert result == "ok"
        assert attempts["n"] == 3

    async def test_exhausted_after_attempts(self):
        m = InMemoryMetrics()
        retry = Retry(name="r", attempts=2, base_delay_s=0.001, max_delay_s=0.01)

        async def always_fails() -> None:
            raise KafkaError("nope")

        with pytest.raises(KafkaError):
            await retry.call(always_fails, _metrics=m)
        assert m.counter("atms_retry_attempts_total", {"name": "r", "outcome": "exhausted"}) == 1

    async def test_never_retry_safety_violation(self):
        attempts = {"n": 0}
        retry = Retry(name="r", attempts=5, base_delay_s=0.001, max_delay_s=0.01)

        async def boom() -> None:
            attempts["n"] += 1
            raise SafetyViolation("conflict")

        with pytest.raises(SafetyViolation):
            await retry.call(boom)
        # SafetyViolation must propagate immediately, not be retried.
        assert attempts["n"] == 1

    async def test_never_retry_value_error(self):
        attempts = {"n": 0}
        retry = Retry(
            name="r",
            attempts=5,
            base_delay_s=0.001,
            max_delay_s=0.01,
            retry_on=(Exception,),
        )

        async def boom() -> None:
            attempts["n"] += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError):
            await retry.call(boom)
        assert attempts["n"] == 1

    async def test_does_not_retry_non_matching_exception(self):
        attempts = {"n": 0}
        retry = Retry(name="r", attempts=5, base_delay_s=0.001, retry_on=(KafkaError,))

        async def boom() -> None:
            attempts["n"] += 1
            raise RuntimeError("not in retry_on")

        with pytest.raises(RuntimeError):
            await retry.call(boom)
        assert attempts["n"] == 1


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    async def test_starts_closed(self):
        cb = CircuitBreaker(name="t")
        assert cb.state is CircuitState.CLOSED

    async def test_failure_threshold_opens(self):
        cb = CircuitBreaker(name="t", failure_threshold=3, reset_timeout_s=10)

        async def fail() -> None:
            raise KafkaError("x")

        for _ in range(3):
            with pytest.raises(KafkaError):
                await cb.call(fail)
        assert cb.state is CircuitState.OPEN

    async def test_open_short_circuits_subsequent_calls(self):
        m = InMemoryMetrics()
        cb = CircuitBreaker(
            name="t", failure_threshold=1, reset_timeout_s=10, metrics=m
        )

        async def fail() -> None:
            raise KafkaError("x")

        with pytest.raises(KafkaError):
            await cb.call(fail)
        # Next call short-circuits.
        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(fail)
        assert m.counter("atms_circuit_breaker_short_circuited_total", {"name": "t"}) == 1

    async def test_open_to_half_open_after_reset_timeout(self, monkeypatch):
        cb = CircuitBreaker(name="t", failure_threshold=1, reset_timeout_s=0.05)

        async def fail() -> None:
            raise KafkaError("x")

        async def ok() -> str:
            return "ok"

        with pytest.raises(KafkaError):
            await cb.call(fail)
        assert cb.state is CircuitState.OPEN

        await asyncio.sleep(0.06)  # past reset_timeout
        # Next call should go through (probe) and succeed → HALF_OPEN.
        result = await cb.call(ok)
        assert result == "ok"
        assert cb.state is CircuitState.HALF_OPEN

    async def test_half_open_closes_after_required_successes(self):
        cb = CircuitBreaker(
            name="t",
            failure_threshold=1,
            reset_timeout_s=0.05,
            half_open_successes_required=2,
        )

        async def fail() -> None:
            raise KafkaError("x")

        async def ok() -> str:
            return "ok"

        with pytest.raises(KafkaError):
            await cb.call(fail)
        await asyncio.sleep(0.06)
        await cb.call(ok)  # → HALF_OPEN, 1 success
        await cb.call(ok)  # → CLOSED after 2 successes
        assert cb.state is CircuitState.CLOSED

    async def test_half_open_reopens_on_failure(self):
        cb = CircuitBreaker(
            name="t", failure_threshold=1, reset_timeout_s=0.05
        )

        async def fail() -> None:
            raise KafkaError("x")

        with pytest.raises(KafkaError):
            await cb.call(fail)
        await asyncio.sleep(0.06)
        with pytest.raises(KafkaError):
            await cb.call(fail)  # → HALF_OPEN → re-OPEN
        assert cb.state is CircuitState.OPEN

    async def test_force_open_and_close(self):
        cb = CircuitBreaker(name="t")
        cb.force_open("test")
        assert cb.state is CircuitState.OPEN
        cb.force_close()
        assert cb.state is CircuitState.CLOSED

    async def test_safety_violation_does_not_count(self):
        cb = CircuitBreaker(name="t", failure_threshold=3)

        async def boom() -> None:
            raise SafetyViolation("conflict")

        for _ in range(5):
            with pytest.raises(SafetyViolation):
                await cb.call(boom)
        assert cb.state is CircuitState.CLOSED  # never opened


# ---------------------------------------------------------------------------
# Bulkhead
# ---------------------------------------------------------------------------


class TestBulkhead:
    async def test_under_limit_no_saturation(self):
        m = InMemoryMetrics()
        b = Bulkhead(name="x", max_concurrent=3, metrics=m)
        async with b:
            pass
        assert m.counter("atms_bulkhead_saturated_total", {"name": "x"}) == 0

    async def test_saturation_increments_metric(self):
        m = InMemoryMetrics()
        b = Bulkhead(name="x", max_concurrent=1, metrics=m)

        async def hold() -> None:
            async with b:
                await asyncio.sleep(0.05)

        # Two coroutines, second must wait → saturation.
        await asyncio.gather(hold(), hold())
        assert m.counter("atms_bulkhead_saturated_total", {"name": "x"}) >= 1

    async def test_max_concurrent_enforced(self):
        peak = {"n": 0, "max": 0}
        b = Bulkhead(name="x", max_concurrent=2)

        async def work() -> None:
            async with b:
                peak["n"] += 1
                peak["max"] = max(peak["max"], peak["n"])
                await asyncio.sleep(0.02)
                peak["n"] -= 1

        await asyncio.gather(*(work() for _ in range(6)))
        assert peak["max"] <= 2

    def test_zero_max_concurrent_rejected(self):
        with pytest.raises(ValueError):
            Bulkhead(name="x", max_concurrent=0)


# ---------------------------------------------------------------------------
# hardened_call composition
# ---------------------------------------------------------------------------


class TestHardenedCall:
    async def test_passes_through_with_no_primitives(self):
        async def ok() -> int:
            return 7

        assert await hardened_call(ok) == 7

    async def test_all_primitives_compose(self):
        attempts = {"n": 0}

        async def flaky() -> str:
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise KafkaError("x")
            return "good"

        bulkhead = Bulkhead(name="x", max_concurrent=1)
        breaker = CircuitBreaker(name="x", failure_threshold=10)
        retry = Retry(name="x", attempts=3, base_delay_s=0.001, max_delay_s=0.01)

        result = await hardened_call(
            flaky,
            bulkhead=bulkhead,
            breaker=breaker,
            retry=retry,
            timeout_s=1.0,
        )
        assert result == "good"


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    max_examples=15,
)
@given(
    failure_threshold=st.integers(min_value=1, max_value=10),
    n_calls=st.integers(min_value=1, max_value=20),
)
async def test_property_breaker_opens_at_or_before_threshold(failure_threshold, n_calls):
    """Breaker MUST open by the time failure_threshold consecutive failures arrive."""
    cb = CircuitBreaker(
        name="prop",
        failure_threshold=failure_threshold,
        reset_timeout_s=100,
    )

    async def fail() -> None:
        raise KafkaError("x")

    short_circuited = False
    for _ in range(n_calls):
        try:
            await cb.call(fail)
        except CircuitBreakerOpenError:
            short_circuited = True
        except KafkaError:
            pass

    # If we made more calls than the threshold, we must have seen at least one
    # short-circuit (post-threshold calls are short-circuited).
    if n_calls > failure_threshold:
        assert short_circuited
        assert cb.state is CircuitState.OPEN
