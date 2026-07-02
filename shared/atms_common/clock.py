"""
Clock abstraction.

The failsafe controller's correctness depends on `now`. We pass it in
explicitly so unit tests can advance time deterministically.
"""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    """Source of monotonic time in nanoseconds."""

    def now_ns(self) -> int: ...


class MonotonicClock:
    """Production clock backed by time.monotonic_ns()."""

    def now_ns(self) -> int:
        return time.monotonic_ns()


class FakeClock:
    """Test clock. Advance with `advance_ms` or `advance_ns`."""

    def __init__(self, start_ns: int = 0) -> None:
        self._now_ns = start_ns

    def now_ns(self) -> int:
        return self._now_ns

    def advance_ms(self, ms: float) -> None:
        self._now_ns += int(ms * 1_000_000)

    def advance_ns(self, ns: int) -> None:
        self._now_ns += ns
