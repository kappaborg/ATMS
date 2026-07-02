"""Shared fixtures for traffic-controller tests."""
from __future__ import annotations

from typing import Any, List, Mapping

import pytest

from shared.atms_common.clock import FakeClock
from shared.atms_common.metrics import InMemoryMetrics
from shared.atms_common.safety import FixedTimePlan, SafetyConfig

from failsafe import (
    FailsafeConfig,
    FailsafeController,
    TransitionLogger,
)


class ListLogger(TransitionLogger):
    """TransitionLogger that captures events into a list for assertions."""

    def __init__(self) -> None:
        self.events: List[Mapping[str, Any]] = []

    def log_transition(self, event: Mapping[str, Any]) -> None:
        self.events.append(dict(event))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(start_ns=1_000_000_000_000)


@pytest.fixture
def metrics() -> InMemoryMetrics:
    return InMemoryMetrics()


@pytest.fixture
def transition_log() -> ListLogger:
    return ListLogger()


@pytest.fixture
def plan() -> FixedTimePlan:
    return FixedTimePlan.rilsa_default()


@pytest.fixture
def safety() -> SafetyConfig:
    return SafetyConfig()


@pytest.fixture
def make_controller(clock, metrics, transition_log, plan, safety):
    def _factory(**cfg_overrides) -> FailsafeController:
        cfg = FailsafeConfig(intersection_id=cfg_overrides.pop("intersection_id", 1), **cfg_overrides)
        return FailsafeController(
            config=cfg,
            plan=plan,
            safety=safety,
            clock=clock,
            metrics=metrics,
            logger=transition_log,
        )
    return _factory


def make_decision(
    *,
    decision_id: int,
    now_ns: int,
    commanded_phase: str = "ns_green",
    intersection_id: int = 1,
    ttl_ms: int = 2500,
) -> dict:
    """Helper to construct a wire-format decision dict."""
    return {
        "decision_id": decision_id,
        "intersection_id": intersection_id,
        "producer_timestamp_ns": now_ns,
        "valid_until_ns": now_ns + ttl_ms * 1_000_000,
        "commanded_phase": commanded_phase,
        "priority": "normal",
        "confidence": 0.9,
        "reason": "test",
    }
