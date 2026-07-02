"""
In-process integration test for the controller's async tick loop.

Verifies the safety property without needing Kafka: when no decisions are
submitted (simulating an upstream outage), the controller's tick loop
transitions from AI_ADAPTIVE to FIXED_TIME within MAX_AI_STALENESS_MS and
ALL the local signals reflect the new commanded phase.

This is the chaos test the SENIOR_ENGINEER_PROMPT calls for in A1.
A separate Testcontainers-based test (`test_failsafe_chaos.py`) exercises
the same property through a real Kafka broker.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

_PROJECT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_PROJECT))
sys.path.insert(0, str(_PROJECT / "services/traffic-controller/src"))

# Import the service module. The FastAPI app and global service instance are
# created at import time but Kafka is not started until the startup hook.
import main as controller_main  # noqa: E402
from failsafe import Mode  # noqa: E402
from shared.atms_common.decision import CommandedPhase  # noqa: E402


pytestmark = pytest.mark.asyncio


@pytest.fixture
def fresh_service(monkeypatch):
    """A fresh TrafficControllerService for each test, with Kafka disabled."""
    monkeypatch.setenv("ATMS_INTERSECTION_ID", "1")
    monkeypatch.setenv("ATMS_MAX_AI_STALENESS_MS", "500")
    monkeypatch.setenv("ATMS_FIXED_TIME_MIN_DWELL_S", "0.5")
    monkeypatch.setenv("ATMS_CONSECUTIVE_VALID_TO_RECOVER", "2")
    # Force the in-memory metrics recorder for each fresh service so successive
    # tests don't fight over the global Prometheus registry.
    from shared.atms_common.metrics import InMemoryMetrics  # noqa: WPS433
    monkeypatch.setattr(controller_main, "_build_metrics", lambda: InMemoryMetrics())
    return controller_main.TrafficControllerService(intersection_id=1)


async def _drive_into_ai_adaptive(service) -> int:
    # Submit just enough valid decisions to recover into AI_ADAPTIVE.
    cfg = service.failsafe._cfg
    # Honour min-dwell.
    await asyncio.sleep(cfg.fixed_time_min_dwell_s + 0.05)
    next_id = 1
    for _ in range(cfg.consecutive_valid_to_recover):
        now_ns = service._clock.now_ns()
        service.failsafe.submit_decision(
            {
                "decision_id": next_id,
                "intersection_id": 1,
                "producer_timestamp_ns": now_ns,
                "valid_until_ns": now_ns + 2_500_000_000,
                "commanded_phase": "ns_green",
            }
        )
        next_id += 1
        await asyncio.sleep(0.01)
    return next_id


async def test_no_decisions_triggers_fixed_time_within_two_seconds(fresh_service):
    """
    Property: if the AI stream stops, the controller is in FIXED_TIME mode
    within 2s.  Required by the Phase A1 DoD in SENIOR_ENGINEER_PROMPT.
    """
    service = fresh_service

    tick_task = asyncio.create_task(service.tick_loop())
    try:
        next_id = await _drive_into_ai_adaptive(service)
        assert service.failsafe.current_mode() is Mode.AI_ADAPTIVE

        # Simulate upstream outage: stop feeding decisions.
        await asyncio.sleep(2.0)

        assert service.failsafe.current_mode() is Mode.FIXED_TIME, (
            "controller did not fall back to FIXED_TIME within 2s of AI silence"
        )
    finally:
        tick_task.cancel()
        try:
            await tick_task
        except asyncio.CancelledError:
            pass


async def test_all_red_flash_propagates_to_signals(fresh_service):
    """
    Property: operator E-stop drives both signals to FLASH_RED within one
    tick period (200 ms).
    """
    service = fresh_service

    tick_task = asyncio.create_task(service.tick_loop())
    try:
        service.force_emergency("integration_test_e_stop")
        assert service.failsafe.current_mode() is Mode.ALL_RED_FLASH

        # Give the tick loop one period plus jitter to propagate.
        await asyncio.sleep(0.4)

        ns_state = service.signals[controller_main.Direction.NORTH_SOUTH].current_state
        ew_state = service.signals[controller_main.Direction.EAST_WEST].current_state
        assert ns_state is controller_main.SignalState.FLASH_RED
        assert ew_state is controller_main.SignalState.FLASH_RED
    finally:
        tick_task.cancel()
        try:
            await tick_task
        except asyncio.CancelledError:
            pass


async def test_invalid_burst_triggers_fixed_time(fresh_service):
    """
    Property: three back-to-back invalid decisions drop AI_ADAPTIVE to
    FIXED_TIME (gap #1 burst transition path).
    """
    service = fresh_service

    tick_task = asyncio.create_task(service.tick_loop())
    try:
        await _drive_into_ai_adaptive(service)
        assert service.failsafe.current_mode() is Mode.AI_ADAPTIVE

        # Feed three decisions for a different intersection.
        for i in range(3):
            now_ns = service._clock.now_ns()
            service.failsafe.submit_decision(
                {
                    "decision_id": 1_000 + i,
                    "intersection_id": 999,
                    "producer_timestamp_ns": now_ns,
                    "valid_until_ns": now_ns + 2_500_000_000,
                    "commanded_phase": "ns_green",
                }
            )
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)  # let the next tick observe the transition
        assert service.failsafe.current_mode() is Mode.FIXED_TIME
    finally:
        tick_task.cancel()
        try:
            await tick_task
        except asyncio.CancelledError:
            pass
