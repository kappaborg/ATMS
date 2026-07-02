"""Unit tests for the FailsafeController state machine."""
from __future__ import annotations

import pytest

from shared.atms_common.decision import CommandedPhase

from failsafe import Mode, TransitionReason


def make_decision(
    *,
    decision_id: int,
    now_ns: int,
    commanded_phase: str = "ns_green",
    intersection_id: int = 1,
    ttl_ms: int = 2500,
) -> dict:
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


# `make_controller`, `clock`, `metrics`, `transition_log` come from tests/conftest.py.


def _enter_ai_adaptive(controller, clock, *, intersection_id: int = 1) -> int:
    """
    Drive the controller from FIXED_TIME -> AI_ADAPTIVE.

    Returns the next decision_id to use after recovery.
    """
    # Dwell past minimum dwell.
    clock.advance_ms(controller._cfg.fixed_time_min_dwell_s * 1000 + 100)
    next_id = 1
    for _ in range(controller._cfg.consecutive_valid_to_recover):
        out = controller.submit_decision(
            make_decision(
                decision_id=next_id, now_ns=clock.now_ns(), intersection_id=intersection_id
            )
        )
        assert out.accepted, f"setup decision rejected: {out.validation.status}"
        next_id += 1
        clock.advance_ms(50)
    assert controller.current_mode() is Mode.AI_ADAPTIVE
    return next_id


class TestStartup:
    def test_starts_in_fixed_time_mode(self, make_controller):
        c = make_controller()
        assert c.current_mode() is Mode.FIXED_TIME

    def test_startup_transition_logged(self, make_controller, transition_log):
        make_controller()
        assert any(
            e["reason"] == TransitionReason.STARTUP.value
            for e in transition_log.events
        )


class TestRecoveryToAIAdaptive:
    def test_requires_min_dwell(self, make_controller, clock):
        c = make_controller(fixed_time_min_dwell_s=10.0, consecutive_valid_to_recover=3)
        # Even with valid decisions, dwell not met -> no recovery.
        for i in range(3):
            c.submit_decision(make_decision(decision_id=i + 1, now_ns=clock.now_ns()))
            clock.advance_ms(100)
        assert c.current_mode() is Mode.FIXED_TIME

    def test_requires_consecutive_valid_count(self, make_controller, clock):
        c = make_controller(fixed_time_min_dwell_s=1.0, consecutive_valid_to_recover=5)
        clock.advance_ms(2_000)
        # Only 4 valid decisions.
        for i in range(4):
            c.submit_decision(make_decision(decision_id=i + 1, now_ns=clock.now_ns()))
            clock.advance_ms(50)
        assert c.current_mode() is Mode.FIXED_TIME

    def test_recovers_when_both_satisfied(self, make_controller, clock):
        c = make_controller(fixed_time_min_dwell_s=1.0, consecutive_valid_to_recover=3)
        clock.advance_ms(2_000)
        for i in range(3):
            c.submit_decision(make_decision(decision_id=i + 1, now_ns=clock.now_ns()))
            clock.advance_ms(50)
        assert c.current_mode() is Mode.AI_ADAPTIVE


class TestStaleness:
    def test_ai_adaptive_falls_back_after_staleness(self, make_controller, clock):
        c = make_controller(
            fixed_time_min_dwell_s=1.0,
            consecutive_valid_to_recover=3,
            max_ai_staleness_ms=500,
        )
        _enter_ai_adaptive(c, clock)
        clock.advance_ms(600)  # past staleness
        c.tick()
        assert c.current_mode() is Mode.FIXED_TIME

    def test_fresh_decisions_keep_ai_adaptive(self, make_controller, clock):
        c = make_controller(
            fixed_time_min_dwell_s=1.0,
            consecutive_valid_to_recover=3,
            max_ai_staleness_ms=500,
        )
        next_id = _enter_ai_adaptive(c, clock)
        for _ in range(10):
            clock.advance_ms(200)  # within staleness window
            c.submit_decision(
                make_decision(decision_id=next_id, now_ns=clock.now_ns())
            )
            next_id += 1
            c.tick()
        assert c.current_mode() is Mode.AI_ADAPTIVE


class TestInvalidDecisionBurst:
    def test_burst_triggers_fixed_time(self, make_controller, clock):
        c = make_controller(
            fixed_time_min_dwell_s=1.0,
            consecutive_valid_to_recover=3,
            invalid_decision_burst=3,
        )
        next_id = _enter_ai_adaptive(c, clock)
        # Submit 3 invalid decisions (intersection mismatch).
        for _ in range(3):
            c.submit_decision(
                make_decision(
                    decision_id=next_id, now_ns=clock.now_ns(), intersection_id=999
                )
            )
            next_id += 1
        assert c.current_mode() is Mode.FIXED_TIME

    def test_one_valid_resets_invalid_counter(self, make_controller, clock):
        c = make_controller(
            fixed_time_min_dwell_s=1.0,
            consecutive_valid_to_recover=3,
            invalid_decision_burst=3,
        )
        next_id = _enter_ai_adaptive(c, clock)
        c.submit_decision(
            make_decision(decision_id=next_id, now_ns=clock.now_ns(), intersection_id=999)
        )
        next_id += 1
        c.submit_decision(
            make_decision(decision_id=next_id, now_ns=clock.now_ns(), intersection_id=999)
        )
        next_id += 1
        # One valid in between
        c.submit_decision(make_decision(decision_id=next_id, now_ns=clock.now_ns()))
        next_id += 1
        # Two more invalid — should NOT cumulate to 3 because counter reset.
        c.submit_decision(
            make_decision(decision_id=next_id, now_ns=clock.now_ns(), intersection_id=999)
        )
        next_id += 1
        c.submit_decision(
            make_decision(decision_id=next_id, now_ns=clock.now_ns(), intersection_id=999)
        )
        assert c.current_mode() is Mode.AI_ADAPTIVE


class TestFlapEscalation:
    def test_three_flaps_escalate_to_all_red_flash(self, make_controller, clock):
        c = make_controller(
            fixed_time_min_dwell_s=1.0,
            consecutive_valid_to_recover=2,
            max_ai_staleness_ms=200,
            flap_window_s=300.0,
            flap_threshold=3,
        )
        next_id = 1
        # Three rounds of: recover -> stale -> fallback
        for _ in range(3):
            # Recover
            clock.advance_ms(1100)
            for _ in range(2):
                c.submit_decision(
                    make_decision(decision_id=next_id, now_ns=clock.now_ns())
                )
                next_id += 1
                clock.advance_ms(50)
            assert c.current_mode() in (Mode.AI_ADAPTIVE, Mode.ALL_RED_FLASH)
            if c.current_mode() is Mode.ALL_RED_FLASH:
                break
            # Go stale
            clock.advance_ms(300)
            c.tick()
        assert c.current_mode() is Mode.ALL_RED_FLASH

    def test_old_flaps_are_evicted(self, make_controller, clock):
        c = make_controller(
            fixed_time_min_dwell_s=1.0,
            consecutive_valid_to_recover=2,
            max_ai_staleness_ms=200,
            flap_window_s=10.0,  # tiny window
            flap_threshold=3,
        )
        next_id = 1
        # Two flap transitions
        for _ in range(2):
            clock.advance_ms(1100)
            for _ in range(2):
                c.submit_decision(
                    make_decision(decision_id=next_id, now_ns=clock.now_ns())
                )
                next_id += 1
                clock.advance_ms(50)
            clock.advance_ms(300)
            c.tick()
        # Wait past flap window so old flaps evict.
        clock.advance_ms(15_000)
        # One more flap — should NOT escalate to ALL_RED_FLASH because the
        # earlier two have aged out.
        clock.advance_ms(1100)
        for _ in range(2):
            c.submit_decision(
                make_decision(decision_id=next_id, now_ns=clock.now_ns())
            )
            next_id += 1
            clock.advance_ms(50)
        clock.advance_ms(300)
        c.tick()
        assert c.current_mode() is Mode.FIXED_TIME


class TestAllRedFlash:
    def test_no_auto_recovery(self, make_controller, clock):
        c = make_controller()
        c.report_hardware_fault("lamp_burnt_NSG")
        assert c.current_mode() is Mode.ALL_RED_FLASH

        # Submit a stream of valid decisions; mode must stay ALL_RED_FLASH.
        for i in range(20):
            clock.advance_ms(100)
            c.submit_decision(make_decision(decision_id=i + 1, now_ns=clock.now_ns()))
            c.tick()
        assert c.current_mode() is Mode.ALL_RED_FLASH

    def test_operator_recovers(self, make_controller, clock):
        c = make_controller()
        c.force_mode(Mode.ALL_RED_FLASH, reason="safety_walk")
        assert c.current_mode() is Mode.ALL_RED_FLASH
        c.force_mode(Mode.FIXED_TIME, reason="all_clear")
        assert c.current_mode() is Mode.FIXED_TIME

    def test_hardware_fault_overrides_any_mode(self, make_controller, clock):
        c = make_controller(fixed_time_min_dwell_s=1.0, consecutive_valid_to_recover=2)
        _enter_ai_adaptive(c, clock)
        c.report_hardware_fault("detector_short")
        assert c.current_mode() is Mode.ALL_RED_FLASH


class TestCommandedPhase:
    def test_fixed_time_follows_plan(self, make_controller, clock, plan):
        c = make_controller()
        # At cycle offset 0 plan starts on NS_GREEN.
        assert c.tick(clock.now_ns()) is CommandedPhase.NS_GREEN

    def test_ai_adaptive_follows_decision(self, make_controller, clock):
        c = make_controller(fixed_time_min_dwell_s=1.0, consecutive_valid_to_recover=2)
        _enter_ai_adaptive(c, clock)
        next_id = c._last_accepted_id + 1
        # Honour min-green hold first: drive into AI mode, then wait min-green.
        clock.advance_ms(int(c._safety.min_green_s * 1000) + 100)
        c.submit_decision(
            make_decision(
                decision_id=next_id,
                now_ns=clock.now_ns(),
                commanded_phase="ew_green",
            )
        )
        # The controller will insert a YELLOW first (no-conflict rule).
        phase = c.tick(clock.now_ns())
        assert phase in (
            CommandedPhase.NS_YELLOW,
            CommandedPhase.EW_GREEN,
        )

    def test_all_red_flash_phase(self, make_controller, clock):
        c = make_controller()
        c.report_hardware_fault("x")
        assert c.tick(clock.now_ns()) is CommandedPhase.ALL_RED_FLASH


class TestMinGreenInvariant:
    def test_min_green_held_under_conflicting_decision(self, make_controller, clock):
        c = make_controller(fixed_time_min_dwell_s=1.0, consecutive_valid_to_recover=2)
        _enter_ai_adaptive(c, clock)
        # Force commanded phase to NS_GREEN at known time.
        c.submit_decision(
            make_decision(
                decision_id=c._last_accepted_id + 1,
                now_ns=clock.now_ns(),
                commanded_phase="ns_green",
            )
        )
        c.tick(clock.now_ns())
        assert c._last_commanded_phase is CommandedPhase.NS_GREEN
        phase_start = clock.now_ns()

        # Immediately try to flip to EW_GREEN — should be held.
        c.submit_decision(
            make_decision(
                decision_id=c._last_accepted_id + 1,
                now_ns=clock.now_ns(),
                commanded_phase="ew_green",
            )
        )
        held = c.tick(clock.now_ns())
        assert held is CommandedPhase.NS_GREEN

        # Advance past min_green and request again — yellow inserted.
        clock.advance_ms(int(c._safety.min_green_s * 1000) + 100)
        c.submit_decision(
            make_decision(
                decision_id=c._last_accepted_id + 1,
                now_ns=clock.now_ns(),
                commanded_phase="ew_green",
            )
        )
        next_phase = c.tick(clock.now_ns())
        assert next_phase is CommandedPhase.NS_YELLOW
        # Sanity: at least min_green elapsed since NS_GREEN started.
        assert (clock.now_ns() - phase_start) >= c._safety.min_green_s * 1_000_000_000


class TestMetrics:
    def test_mode_transition_increments_counter(
        self, make_controller, clock, metrics
    ):
        c = make_controller(fixed_time_min_dwell_s=1.0, consecutive_valid_to_recover=2)
        _enter_ai_adaptive(c, clock)
        labels = {
            "intersection_id": "1",
            "from": "fixed_time",
            "to": "ai_adaptive",
            "reason": TransitionReason.RECOVERY_VALID_STREAM.value,
        }
        assert metrics.counter("atms_controller_mode_transitions_total", labels) >= 1

    def test_invalid_decision_counter(self, make_controller, clock, metrics):
        c = make_controller(fixed_time_min_dwell_s=1.0, consecutive_valid_to_recover=2)
        _enter_ai_adaptive(c, clock)
        c.submit_decision(
            make_decision(
                decision_id=c._last_accepted_id + 1,
                now_ns=clock.now_ns(),
                intersection_id=999,
            )
        )
        labels = {"intersection_id": "1", "reason": "intersection_mismatch"}
        assert metrics.counter("atms_controller_invalid_decisions_total", labels) == 1


class TestStatus:
    def test_status_shape(self, make_controller, clock):
        c = make_controller()
        s = c.status()
        for key in (
            "mode",
            "mode_dwell_s",
            "last_decision_id",
            "last_decision_age_ms",
            "commanded_phase",
            "consecutive_invalid",
            "consecutive_valid",
            "flap_count_in_window",
        ):
            assert key in s
