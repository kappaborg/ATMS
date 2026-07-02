"""
Phase A7 — failsafe controller tests for EV preempt, ped-call, and ADA events.

Covers the ADR-0007 acceptance criteria:
- Preempt arrives → controller commands EV_PREEMPT_* within the next tick.
- Preempt clears → controller resumes normal cycle.
- Pedestrian call queues → next safe boundary serves WALK → FLASHING_GREEN.
- Walk + clearance durations honoured (ADA-extended for accessibility=True).
- ADA event emitted on every ped phase entry.
- Priority: ALL_RED_FLASH > preempt > ped clearance > AI/fixed-time.
"""

from __future__ import annotations

import pytest

from shared.atms_common.decision import CommandedPhase
from shared.atms_common.preempt import Approach

from failsafe import Mode


def _make_decision(
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


def _make_preempt(
    *,
    now_ns: int,
    approach: str = "north_south",
    priority: str = "fire_rescue",
    ttl_ms: int = 30_000,
    transponder_id: str = "TX-001",
    intersection_id: int = 1,
) -> dict:
    return {
        "intersection_id": intersection_id,
        "approach": approach,
        "priority": priority,
        "valid_until_ns": now_ns + ttl_ms * 1_000_000,
        "transponder_id": transponder_id,
        "producer_timestamp_ns": now_ns,
    }


def _make_ped_call(
    *,
    now_ns: int,
    approach: str = "north_south",
    accessibility: bool = False,
    ttl_ms: int = 60_000,
    intersection_id: int = 1,
) -> dict:
    return {
        "intersection_id": intersection_id,
        "approach": approach,
        "valid_until_ns": now_ns + ttl_ms * 1_000_000,
        "accessibility": accessibility,
        "producer_timestamp_ns": now_ns,
    }


# ---------------------------------------------------------------------------
# Preempt behaviour
# ---------------------------------------------------------------------------


class TestPreemptArm:
    def test_arm_commands_preempt_phase_next_tick(self, make_controller, clock):
        c = make_controller()
        outcome = c.submit_preempt(_make_preempt(now_ns=clock.now_ns()))
        assert outcome.accepted, outcome.validation
        phase = c.tick(clock.now_ns())
        assert phase is CommandedPhase.EV_PREEMPT_NS

    def test_preempt_overrides_ai_decision(self, make_controller, clock):
        """ADR-0007 acceptance: preempt > AI decision, after min-green elapses.

        Min-green is honoured (ADR-0007 §priority order: 'preempt cannot cut a
        vehicular green shorter than min_green_s'), so cross-direction preempt
        becomes effective on the next safe boundary.
        """
        c = make_controller(fixed_time_min_dwell_s=1.0, consecutive_valid_to_recover=2)
        # Drive into AI mode.
        clock.advance_ms(1100)
        for i in range(2):
            c.submit_decision(_make_decision(decision_id=i + 1, now_ns=clock.now_ns()))
            clock.advance_ms(50)
        assert c.current_mode() is Mode.AI_ADAPTIVE

        # AI commands NS_GREEN; tick to lock it in.
        c.submit_decision(
            _make_decision(decision_id=99, now_ns=clock.now_ns(), commanded_phase="ns_green")
        )
        c.tick(clock.now_ns())

        # Cross-direction preempt arrives; min-green has not elapsed yet.
        c.submit_preempt(_make_preempt(now_ns=clock.now_ns(), approach="east_west"))

        # Advance past min-green and run a few ticks for the intergreen sequence.
        clock.advance_ms(int(c._safety.min_green_s * 1000) + 100)
        last_phase = None
        for _ in range(5):
            last_phase = c.tick(clock.now_ns())
            clock.advance_ms(500)
        assert last_phase is CommandedPhase.EV_PREEMPT_EW

    def test_preempt_invalid_intersection_rejected(self, make_controller, clock):
        c = make_controller()
        outcome = c.submit_preempt(
            _make_preempt(now_ns=clock.now_ns(), intersection_id=42)
        )
        assert not outcome.accepted
        assert outcome.validation.status.value == "intersection_mismatch"

    def test_preempt_expired_rejected(self, make_controller, clock):
        c = make_controller()
        raw = _make_preempt(now_ns=clock.now_ns())
        raw["valid_until_ns"] = clock.now_ns() - 1  # already expired
        outcome = c.submit_preempt(raw)
        assert not outcome.accepted
        assert outcome.validation.status.value == "expired"

    def test_preempt_empty_transponder_rejected(self, make_controller, clock):
        c = make_controller()
        raw = _make_preempt(now_ns=clock.now_ns(), transponder_id="")
        outcome = c.submit_preempt(raw)
        assert not outcome.accepted
        assert outcome.validation.status.value == "empty_transponder"


class TestPreemptPriority:
    def test_higher_priority_replaces_lower(self, make_controller, clock):
        c = make_controller()
        # Transit preempt first.
        c.submit_preempt(
            _make_preempt(
                now_ns=clock.now_ns(),
                priority="transit",
                transponder_id="T1",
                approach="north_south",
            )
        )
        assert c.tick(clock.now_ns()) is CommandedPhase.EV_PREEMPT_NS

        # Fire-rescue preempt for EW: higher priority, should replace.
        outcome = c.submit_preempt(
            _make_preempt(
                now_ns=clock.now_ns(),
                priority="fire_rescue",
                transponder_id="T2",
                approach="east_west",
            )
        )
        assert outcome.accepted
        assert c.tick(clock.now_ns()) is CommandedPhase.EV_PREEMPT_EW

    def test_equal_or_lower_priority_rejected(self, make_controller, clock):
        c = make_controller()
        c.submit_preempt(
            _make_preempt(
                now_ns=clock.now_ns(),
                priority="ambulance",
                transponder_id="A1",
                approach="north_south",
            )
        )
        # Police (lower than ambulance) should be rejected.
        out = c.submit_preempt(
            _make_preempt(
                now_ns=clock.now_ns(),
                priority="police",
                transponder_id="P1",
                approach="east_west",
            )
        )
        assert not out.accepted

        # Equal-priority second ambulance also rejected.
        out2 = c.submit_preempt(
            _make_preempt(
                now_ns=clock.now_ns(),
                priority="ambulance",
                transponder_id="A2",
                approach="east_west",
            )
        )
        assert not out2.accepted


class TestPreemptClear:
    def test_clear_after_min_dwell(self, make_controller, clock):
        c = make_controller()
        c.submit_preempt(_make_preempt(now_ns=clock.now_ns()))
        clock.advance_ms(int(c._cfg.preempt_min_dwell_s * 1000) + 100)
        c.submit_preempt_clear(Approach.NORTH_SOUTH)
        assert not c.has_active_preempt()

    def test_clear_before_min_dwell_ignored(self, make_controller, clock):
        c = make_controller()
        c.submit_preempt(_make_preempt(now_ns=clock.now_ns()))
        # Try to clear immediately.
        c.submit_preempt_clear(Approach.NORTH_SOUTH)
        assert c.has_active_preempt(), (
            "preempt cleared before min_dwell — operationally wrong"
        )

    def test_clear_wrong_approach_no_op(self, make_controller, clock):
        c = make_controller()
        c.submit_preempt(_make_preempt(now_ns=clock.now_ns(), approach="north_south"))
        clock.advance_ms(int(c._cfg.preempt_min_dwell_s * 1000) + 100)
        c.submit_preempt_clear(Approach.EAST_WEST)
        assert c.has_active_preempt()

    def test_expired_preempt_auto_cleared_on_tick(self, make_controller, clock):
        c = make_controller()
        c.submit_preempt(_make_preempt(now_ns=clock.now_ns(), ttl_ms=500))
        assert c.has_active_preempt()
        clock.advance_ms(600)
        c.tick(clock.now_ns())
        assert not c.has_active_preempt()


# ---------------------------------------------------------------------------
# Pedestrian call behaviour
# ---------------------------------------------------------------------------


class TestPedCallQueue:
    def test_call_queues_and_serves_at_safe_boundary(self, make_controller, clock):
        c = make_controller()
        # Drop into ALL_RED via a non-vehicular-green start: tick once to reach
        # NS_GREEN, but we just queue and let safe-boundary check decide.
        outcome = c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns()))
        assert outcome.accepted

        # Force the controller out of the initial NS_GREEN by advancing past min-green.
        clock.advance_ms(int(c._safety.min_green_s * 1000) + 100)
        phase = c.tick(clock.now_ns())
        assert phase is CommandedPhase.PED_NS_WALK

    def test_dedup_same_approach(self, make_controller, clock):
        c = make_controller()
        c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns()))
        c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns()))
        assert len(c.pending_ped_calls()) == 1

    def test_accessibility_upgrade(self, make_controller, clock):
        c = make_controller()
        c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns(), accessibility=False))
        c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns(), accessibility=True))
        # Internal: queue entry now has accessibility=True.
        queue = c._ped_queue
        assert queue[Approach.NORTH_SOUTH].accessibility is True

    def test_invalid_intersection_rejected(self, make_controller, clock):
        c = make_controller()
        out = c.submit_ped_call(
            _make_ped_call(now_ns=clock.now_ns(), intersection_id=42)
        )
        assert not out.accepted


class TestPedPhaseDurations:
    def test_walk_held_for_ped_min_walk_s(self, make_controller, clock):
        c = make_controller()
        clock.advance_ms(int(c._safety.min_green_s * 1000) + 100)
        c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns()))
        assert c.tick(clock.now_ns()) is CommandedPhase.PED_NS_WALK

        # Half-way through min walk → still walk.
        clock.advance_ms(int(c._cfg.ped_min_walk_s * 1000) // 2)
        assert c.tick(clock.now_ns()) is CommandedPhase.PED_NS_WALK

    def test_walk_transitions_to_flashing_at_min_walk(self, make_controller, clock):
        c = make_controller()
        clock.advance_ms(int(c._safety.min_green_s * 1000) + 100)
        c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns()))
        c.tick(clock.now_ns())  # enter walk
        clock.advance_ms(int(c._cfg.ped_min_walk_s * 1000) + 100)
        phase = c.tick(clock.now_ns())
        assert phase is CommandedPhase.PED_NS_FLASHING_GREEN

    def test_ada_extends_walk(self, make_controller, clock):
        c = make_controller()
        clock.advance_ms(int(c._safety.min_green_s * 1000) + 100)
        c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns(), accessibility=True))
        c.tick(clock.now_ns())
        # Just past ped_min_walk but before ada_min_walk → still WALK.
        clock.advance_ms(int(c._cfg.ped_min_walk_s * 1000) + 100)
        assert c.tick(clock.now_ns()) is CommandedPhase.PED_NS_WALK
        # Past ada_min_walk → flashing.
        clock.advance_ms(
            int((c._cfg.ada_min_walk_s - c._cfg.ped_min_walk_s) * 1000) + 100
        )
        assert c.tick(clock.now_ns()) is CommandedPhase.PED_NS_FLASHING_GREEN

    def test_clearance_completes_then_ped_phase_ends(self, make_controller, clock):
        c = make_controller()
        clock.advance_ms(int(c._safety.min_green_s * 1000) + 100)
        c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns()))
        c.tick(clock.now_ns())
        # Run walk + clearance.
        clock.advance_ms(int(c._cfg.ped_min_walk_s * 1000) + 100)
        c.tick(clock.now_ns())  # → FLASHING
        clock.advance_ms(int(c._cfg.ped_clearance_min_s * 1000) + 100)
        # After clearance completes, we fall back to normal scheduling.
        phase = c.tick(clock.now_ns())
        assert phase not in (
            CommandedPhase.PED_NS_WALK,
            CommandedPhase.PED_NS_FLASHING_GREEN,
        )


# ---------------------------------------------------------------------------
# Hard safety invariant: ALL_RED_FLASH overrides everything (including ped)
# ---------------------------------------------------------------------------


class TestPriorityOrder:
    def test_all_red_flash_overrides_preempt(self, make_controller, clock):
        c = make_controller()
        c.submit_preempt(_make_preempt(now_ns=clock.now_ns()))
        c.report_hardware_fault("conflict_monitor_trip")
        assert c.tick(clock.now_ns()) is CommandedPhase.ALL_RED_FLASH

    def test_all_red_flash_overrides_ped(self, make_controller, clock):
        c = make_controller()
        clock.advance_ms(int(c._safety.min_green_s * 1000) + 100)
        c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns()))
        c.tick(clock.now_ns())  # enter walk
        c.report_hardware_fault("trip")
        assert c.tick(clock.now_ns()) is CommandedPhase.ALL_RED_FLASH

    def test_preempt_does_not_cut_ped_clearance(self, make_controller, clock):
        """Pedestrian clearance must run to completion before preempt takes over."""
        c = make_controller()
        clock.advance_ms(int(c._safety.min_green_s * 1000) + 100)
        c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns()))
        c.tick(clock.now_ns())  # WALK
        clock.advance_ms(int(c._cfg.ped_min_walk_s * 1000) + 100)
        c.tick(clock.now_ns())  # FLASHING
        # Preempt arrives mid-clearance.
        c.submit_preempt(_make_preempt(now_ns=clock.now_ns()))
        # Tick before clearance done — must still be clearance.
        phase = c.tick(clock.now_ns())
        assert phase is CommandedPhase.PED_NS_FLASHING_GREEN


# ---------------------------------------------------------------------------
# ADA event emission
# ---------------------------------------------------------------------------


class TestAdaEvents:
    def test_walk_emits_accessible_signal_event(
        self, make_controller, clock, transition_log
    ):
        c = make_controller()
        clock.advance_ms(int(c._safety.min_green_s * 1000) + 100)
        c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns()))
        c.tick(clock.now_ns())
        ada_events = [
            e
            for e in transition_log.events
            if e.get("event") == "accessible_signal_state"
        ]
        assert any(e["state"] == "walk" for e in ada_events)

    def test_clearance_emits_event(self, make_controller, clock, transition_log):
        c = make_controller()
        clock.advance_ms(int(c._safety.min_green_s * 1000) + 100)
        c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns()))
        c.tick(clock.now_ns())
        clock.advance_ms(int(c._cfg.ped_min_walk_s * 1000) + 100)
        c.tick(clock.now_ns())  # WALK → FLASHING
        clearance_events = [
            e
            for e in transition_log.events
            if e.get("event") == "accessible_signal_state"
            and e.get("state") == "clearance"
        ]
        assert clearance_events, "no clearance ADA event emitted"

    def test_accessibility_flag_propagates(
        self, make_controller, clock, transition_log
    ):
        c = make_controller()
        clock.advance_ms(int(c._safety.min_green_s * 1000) + 100)
        c.submit_ped_call(_make_ped_call(now_ns=clock.now_ns(), accessibility=True))
        c.tick(clock.now_ns())
        ada_events = [
            e
            for e in transition_log.events
            if e.get("event") == "accessible_signal_state"
        ]
        assert any(e.get("accessibility_active") is True for e in ada_events)


# ---------------------------------------------------------------------------
# Acceptance: simulated EV scenario triggers preempt within one tick + restores
# ---------------------------------------------------------------------------


def test_acceptance_simulated_ev_scenario(make_controller, clock):
    """Mirrors the PROMPT acceptance: 'simulated EV scenario in test harness
    triggers preempt within one decision cycle and restores cleanly.'

    'Within one decision cycle' = within one cycle of the fixed-time plan
    (~80 s default). Cross-direction preempt waits for min-green to elapse
    (ADR-0007) then transitions through the intergreen sequence.
    """
    c = make_controller()
    cycle_s = c._plan.cycle_s

    # Pre-state: NS_GREEN.
    assert c.tick(clock.now_ns()) is CommandedPhase.NS_GREEN

    # EV arrives on EW approach.
    c.submit_preempt(_make_preempt(now_ns=clock.now_ns(), approach="east_west"))

    # Iterate ticks for up to one cycle, asserting preempt is reached.
    saw_preempt = False
    elapsed_ms = 0
    while elapsed_ms < cycle_s * 1000:
        clock.advance_ms(500)
        elapsed_ms += 500
        if c.tick(clock.now_ns()) is CommandedPhase.EV_PREEMPT_EW:
            saw_preempt = True
            break
    assert saw_preempt, f"preempt not reached within {cycle_s}s"

    # EV passes; operator clears after honouring min dwell.
    clock.advance_ms(int(c._cfg.preempt_min_dwell_s * 1000) + 100)
    c.submit_preempt_clear(Approach.EAST_WEST, reason="ev_cleared")
    assert not c.has_active_preempt()

    # Normal scheduling resumes (fixed-time on this offset).
    after = c.tick(clock.now_ns())
    assert after in (
        CommandedPhase.NS_GREEN,
        CommandedPhase.NS_YELLOW,
        CommandedPhase.EW_GREEN,
        CommandedPhase.EW_YELLOW,
        CommandedPhase.ALL_RED,
    )
