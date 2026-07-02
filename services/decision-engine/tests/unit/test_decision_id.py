"""
Tests for the monotonic decision_id generator.

Property the failsafe controller relies on (ADR-0005 validation gate):
every decision_id must be strictly greater than the previous one emitted by
the same producer instance.
"""

from __future__ import annotations

import re

from main import _next_decision_id


class TestNextDecisionId:
    def test_monotonic_within_process(self):
        previous = _next_decision_id()
        for _ in range(100):
            current = _next_decision_id()
            assert current > previous
            previous = current

    def test_seed_is_wall_clock_derived(self):
        """The counter starts from `int(time.time() * 1000)`, so its order of
        magnitude reflects current epoch milliseconds. This guarantees the
        controller does not reject ids from a freshly-restarted producer for
        being below the last-seen id."""
        # 2024-01-01 in ms is ~1.7e12. After 2030 still <2e12 for many years.
        v = _next_decision_id()
        digits = len(re.sub(r"\D", "", str(v)))
        # Restart-resilience requires the seed have epoch-ms scale.
        assert digits >= 12, f"decision_id {v} doesn't look epoch-ms-seeded"
