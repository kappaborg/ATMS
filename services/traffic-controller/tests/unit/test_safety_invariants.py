"""
Property-based safety invariants.

These tests prove that no matter what stream of decisions the AI emits, the
failsafe controller's `tick()` output never violates the hard safety rules
required for a signalized intersection.
"""
from __future__ import annotations

from hypothesis import HealthCheck, given, settings, strategies as st

from shared.atms_common.decision import CommandedPhase

from failsafe import (
    FailsafeConfig,
    FailsafeController,
    Mode,
)

# These imports are resolved via conftest path setup.
from shared.atms_common.clock import FakeClock
from shared.atms_common.metrics import InMemoryMetrics
from shared.atms_common.safety import FixedTimePlan, SafetyConfig

PHASE_STRINGS = [p.value for p in CommandedPhase]
# Phases the AI never produces directly. These are internal-only:
# - ALL_RED_FLASH: emergency signal (overrides min-green by design)
# - EV_PREEMPT_*: commanded only by the failsafe when an EV preempt is armed
# - PED_*_FLASHING_GREEN: ped-clearance state managed by the failsafe
# Test the min-green property over normal AI-producible phases only.
_INTERNAL_ONLY = {
    CommandedPhase.ALL_RED_FLASH,
    CommandedPhase.EV_PREEMPT_NS,
    CommandedPhase.EV_PREEMPT_EW,
    CommandedPhase.PED_NS_FLASHING_GREEN,
    CommandedPhase.PED_EW_FLASHING_GREEN,
}
NORMAL_PHASE_STRINGS = [p.value for p in CommandedPhase if p not in _INTERNAL_ONLY]
_VEHICULAR_GREENS = {CommandedPhase.NS_GREEN, CommandedPhase.EW_GREEN}


def _build_controller() -> FailsafeController:
    return FailsafeController(
        config=FailsafeConfig(
            intersection_id=1,
            max_ai_staleness_ms=10_000,  # large so stochastic gaps don't trip it
            invalid_decision_burst=10_000,  # we don't want stochastic invalids to flip mode
            fixed_time_min_dwell_s=0.0,
            consecutive_valid_to_recover=1,
        ),
        plan=FixedTimePlan.rilsa_default(),
        safety=SafetyConfig(),
        clock=FakeClock(start_ns=1_000_000_000),
        metrics=InMemoryMetrics(),
        logger=None,
    )


@st.composite
def decision_sequence(draw, phases_pool=None):
    pool = phases_pool if phases_pool is not None else PHASE_STRINGS
    n = draw(st.integers(min_value=1, max_value=40))
    phases = draw(st.lists(st.sampled_from(pool), min_size=n, max_size=n))
    intervals_ms = draw(
        st.lists(st.integers(min_value=10, max_value=2000), min_size=n, max_size=n)
    )
    return list(zip(phases, intervals_ms))


@settings(deadline=None, suppress_health_check=[HealthCheck.too_slow], max_examples=80)
@given(decision_sequence())
def test_never_conflicting_greens(seq):
    """Two conflicting GREENs must never appear in successive tick outputs."""
    c = _build_controller()
    clock: FakeClock = c._clock  # type: ignore[assignment]
    next_id = 1
    last_green = None
    for phase, dt_ms in seq:
        clock.advance_ms(dt_ms)
        c.submit_decision(
            {
                "decision_id": next_id,
                "intersection_id": 1,
                "producer_timestamp_ns": clock.now_ns(),
                "valid_until_ns": clock.now_ns() + 5_000_000_000,
                "commanded_phase": phase,
            }
        )
        next_id += 1
        out = c.tick(clock.now_ns())
        if out in _VEHICULAR_GREENS:
            if last_green is not None and last_green != out:
                # A direct vehicular-green-to-conflicting-vehicular-green flip would
                # be a safety violation. The failsafe must insert a YELLOW first.
                # I.e., the previous tick output cannot be the *other* green.
                assert False, (
                    f"conflicting greens back-to-back: {last_green} -> {out}"
                )
            last_green = out
        else:
            last_green = None


@settings(deadline=None, suppress_health_check=[HealthCheck.too_slow], max_examples=40)
@given(decision_sequence(phases_pool=NORMAL_PHASE_STRINGS))
def test_min_green_honored(seq):
    """A vehicular GREEN, once commanded, runs for at least min_green_s."""
    c = _build_controller()
    clock: FakeClock = c._clock  # type: ignore[assignment]
    next_id = 1
    in_green_phase = None
    green_started_ns = 0
    for phase, dt_ms in seq:
        clock.advance_ms(dt_ms)
        c.submit_decision(
            {
                "decision_id": next_id,
                "intersection_id": 1,
                "producer_timestamp_ns": clock.now_ns(),
                "valid_until_ns": clock.now_ns() + 5_000_000_000,
                "commanded_phase": phase,
            }
        )
        next_id += 1
        out = c.tick(clock.now_ns())
        if out in _VEHICULAR_GREENS:
            if out != in_green_phase:
                in_green_phase = out
                # Use the controller's truth — the test's observation time can
                # lag the actual phase-entry by up to one tick gap.
                green_started_ns = c._phase_entered_at_ns
        else:
            if in_green_phase is not None:
                elapsed_s = (clock.now_ns() - green_started_ns) / 1_000_000_000
                assert elapsed_s + 1e-6 >= c._safety.min_green_s, (
                    f"green {in_green_phase} cut short after {elapsed_s:.3f}s "
                    f"(min {c._safety.min_green_s}s)"
                )
                in_green_phase = None
