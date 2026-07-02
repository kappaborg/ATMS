"""
Failsafe controller state machine — gap #1 / Phase A1.

Three modes: AI_ADAPTIVE, FIXED_TIME, ALL_RED_FLASH.

See:
- docs/adr/0005-failsafe-controller-state-machine.md (design)
- docs/runbooks/failsafe.md (operations)

This module is pure synchronous Python. Asyncio / Kafka / FastAPI plumbing
lives in main.py and calls into this class. Tests inject FakeClock,
InMemoryMetrics, and a list-capturing logger.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from shared.atms_common.clock import Clock
from shared.atms_common.decision import (
    CommandedPhase,
    DecisionMessage,
    ValidationResult,
)
from shared.atms_common.metrics import MetricsRecorder
from shared.atms_common.preempt import (
    Approach,
    PedCallRequest,
    PreemptRequest,
    PreemptValidationResult,
    PreemptValidationStatus,
    preempt_priority_rank,
)
from shared.atms_common.safety import FixedTimePlan, SafetyConfig, is_conflicting

# ---------------------------------------------------------------------------
# Modes & transition reasons
# ---------------------------------------------------------------------------


class Mode(str, Enum):
    AI_ADAPTIVE = "ai_adaptive"
    FIXED_TIME = "fixed_time"
    ALL_RED_FLASH = "all_red_flash"


class TransitionReason(str, Enum):
    AI_DECISION_STALE = "ai_decision_stale"
    INVALID_DECISION_BURST = "invalid_decision_burst"
    RECOVERY_VALID_STREAM = "recovery_valid_stream"
    FLAP_THRESHOLD = "flap_threshold"
    OPERATOR_OVERRIDE = "operator_override"
    HARDWARE_FAULT = "hardware_fault"
    STARTUP = "startup"


# ---------------------------------------------------------------------------
# Transition log protocol
# ---------------------------------------------------------------------------


class TransitionLogger(Protocol):
    def log_transition(self, event: Mapping[str, Any]) -> None: ...


class _NullLogger:
    def log_transition(self, event: Mapping[str, Any]) -> None:
        return None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FailsafeConfig:
    intersection_id: int

    # Watchdog
    max_ai_staleness_ms: int = 2000
    invalid_decision_burst: int = 3

    # Recovery from FIXED_TIME -> AI_ADAPTIVE
    fixed_time_min_dwell_s: float = 30.0
    consecutive_valid_to_recover: int = 5

    # Flap detection -> ALL_RED_FLASH
    flap_window_s: float = 300.0
    flap_threshold: int = 3

    # Decision validation knobs
    signature_required: bool = False
    clock_skew_tolerance_ns: int = 500 * 1_000_000

    # Pedestrian clearance: minimum duration after PED_*_WALK before another
    # phase change is permitted. Per ADR-0004 / RiLSA §3.4 — operator-configurable.
    ped_clearance_min_s: float = 6.0

    # Phase A7 — pedestrian walk durations.
    ped_min_walk_s: float = 5.0
    # ADA-extended walk for accessibility ped-calls (per ADR-0007).
    ada_min_walk_s: float = 7.0

    # Phase A7 — emergency-vehicle preempt minimum dwell. Once a preempt is
    # armed, it stays armed for at least this long so the EV has time to
    # clear; very-short preempts are operationally meaningless and a likely
    # transponder glitch.
    preempt_min_dwell_s: float = 3.0


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubmitOutcome:
    accepted: bool
    validation: ValidationResult
    mode_after: Mode


@dataclass(frozen=True)
class PreemptOutcome:
    accepted: bool
    validation: PreemptValidationResult


@dataclass(frozen=True)
class PedCallOutcome:
    accepted: bool
    validation: PreemptValidationResult  # shares the schema/error shape


class _PedPhaseState(str, Enum):
    NONE = "none"
    WALK = "walk"
    CLEARANCE = "clearance"


# ---------------------------------------------------------------------------
# FailsafeController
# ---------------------------------------------------------------------------


class FailsafeController:
    """
    Stateful safety component sitting between Kafka and the NTCIP adapter.

    Lifecycle:
        ctl = FailsafeController(config, plan, safety, clock, metrics, logger)
        ctl.submit_decision(raw_dict)   # called by Kafka consumer
        commanded = ctl.tick(now_ns)    # called every WATCHDOG_TICK_MS
        # commanded is passed to the NTCIP layer.
    """

    WATCHDOG_TICK_MS = 200

    def __init__(
        self,
        config: FailsafeConfig,
        plan: FixedTimePlan,
        safety: SafetyConfig,
        clock: Clock,
        metrics: MetricsRecorder,
        logger: TransitionLogger | None = None,
    ) -> None:
        self._cfg = config
        self._plan = plan
        self._safety = safety
        self._clock = clock
        self._metrics = metrics
        self._logger = logger or _NullLogger()

        now = clock.now_ns()
        self._mode: Mode = Mode.FIXED_TIME
        self._mode_entered_at_ns: int = now

        # AI tracking
        self._last_accepted: DecisionMessage | None = None
        self._last_accepted_at_ns: int = 0
        self._last_accepted_id: int | None = None
        self._consecutive_invalid: int = 0
        self._consecutive_valid_since_fixed_time: int = 0

        # Commanded phase tracking (for safety filter)
        self._last_commanded_phase: CommandedPhase = self._plan.phase_at(0.0)
        self._phase_entered_at_ns: int = now
        self._ped_clearance_until_ns: int = 0

        # Flap detection: timestamps (ns) of AI_ADAPTIVE -> FIXED_TIME transitions.
        self._failsafe_transitions: deque[int] = deque()

        # Phase A7 — preempt + ped-call state.
        self._active_preempt: PreemptRequest | None = None
        self._preempt_armed_at_ns: int = 0
        self._ped_queue: dict[Approach, PedCallRequest] = {}
        self._ped_phase_state: _PedPhaseState = _PedPhaseState.NONE
        self._ped_phase_approach: Approach | None = None
        self._ped_phase_started_at_ns: int = 0
        self._ped_phase_accessibility: bool = False

        # Emit initial metric snapshot.
        self._emit_mode_gauge()
        self._logger.log_transition(
            {
                "event": "controller_mode_transition",
                "intersection_id": self._cfg.intersection_id,
                "from_mode": None,
                "to_mode": self._mode.value,
                "reason": TransitionReason.STARTUP.value,
            }
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def current_mode(self) -> Mode:
        return self._mode

    def submit_decision(self, raw: Mapping[str, Any]) -> SubmitOutcome:
        """Validate a decision message and update internal state."""
        now = self._clock.now_ns()
        parsed = DecisionMessage.from_dict(raw)
        if isinstance(parsed, ValidationResult):
            self._on_invalid(parsed, now)
            return SubmitOutcome(accepted=False, validation=parsed, mode_after=self._mode)

        result = parsed.validate_for_controller(
            controller_intersection_id=self._cfg.intersection_id,
            last_accepted_decision_id=self._last_accepted_id,
            now_ns=now,
            clock_skew_tolerance_ns=self._cfg.clock_skew_tolerance_ns,
            signature_required=self._cfg.signature_required,
        )
        if not result.ok:
            self._on_invalid(result, now)
            return SubmitOutcome(accepted=False, validation=result, mode_after=self._mode)

        # Accept
        self._last_accepted = parsed
        self._last_accepted_at_ns = now
        self._last_accepted_id = parsed.decision_id
        self._consecutive_invalid = 0

        if self._mode is Mode.FIXED_TIME:
            self._consecutive_valid_since_fixed_time += 1
            self._maybe_recover_to_ai(now)
        elif self._mode is Mode.AI_ADAPTIVE:
            self._consecutive_valid_since_fixed_time = 0  # not in FIXED_TIME
        # ALL_RED_FLASH: do not recover automatically (see ADR-0005).

        self._metrics.inc(
            "atms_controller_decisions_accepted_total",
            labels={"intersection_id": str(self._cfg.intersection_id)},
        )
        self._metrics.set_gauge(
            "atms_controller_ai_decision_age_ms",
            value=0.0,
            labels={"intersection_id": str(self._cfg.intersection_id)},
        )

        return SubmitOutcome(accepted=True, validation=result, mode_after=self._mode)

    def tick(self, now_ns: int | None = None) -> CommandedPhase:
        """Advance the watchdog and return the phase to command this tick."""
        now = now_ns if now_ns is not None else self._clock.now_ns()

        # 1. Watchdog: AI staleness -> FIXED_TIME
        self._check_staleness(now)

        # 2. Decide the desired phase per current mode
        desired = self._desired_phase(now)

        # 3. Apply hard safety invariants
        commanded = self._apply_safety_filter(desired, now)

        # 4. Track commanded phase
        if commanded is not self._last_commanded_phase:
            self._on_phase_change(commanded, now)

        # 5. Per-tick metrics
        if self._last_accepted_at_ns > 0:
            age_ms = (now - self._last_accepted_at_ns) / 1_000_000
            self._metrics.set_gauge(
                "atms_controller_ai_decision_age_ms",
                value=age_ms,
                labels={"intersection_id": str(self._cfg.intersection_id)},
            )
        self._metrics.inc(
            "atms_controller_commanded_phase_total",
            labels={
                "intersection_id": str(self._cfg.intersection_id),
                "phase": commanded.value,
            },
        )

        return commanded

    def submit_preempt(self, raw: Mapping[str, Any]) -> PreemptOutcome:
        """
        Arm an EV preempt (gap #3 / Phase A7).

        Priority rule: a higher-priority preempt replaces a lower-priority one
        in flight (FIRE_RESCUE > AMBULANCE > POLICE > TRANSIT, per ADR-0007).
        A preempt of equal-or-lower priority is rejected to avoid thrashing.
        """
        now = self._clock.now_ns()
        parsed = PreemptRequest.from_dict(raw)
        if isinstance(parsed, PreemptValidationResult):
            self._record_invalid_preempt(parsed, now)
            return PreemptOutcome(accepted=False, validation=parsed)

        result = parsed.validate_for_controller(
            controller_intersection_id=self._cfg.intersection_id, now_ns=now
        )
        if not result.ok:
            self._record_invalid_preempt(result, now)
            return PreemptOutcome(accepted=False, validation=result)

        # Existing active preempt: only replace if new is strictly higher priority.
        if self._active_preempt is not None:
            existing_rank = preempt_priority_rank(self._active_preempt.priority)
            new_rank = preempt_priority_rank(parsed.priority)
            if new_rank <= existing_rank:
                # Treat as rejected — operator must clear the existing first or
                # send a higher-priority preempt.
                self._metrics.inc(
                    "atms_controller_preempt_rejected_total",
                    labels={
                        "intersection_id": str(self._cfg.intersection_id),
                        "reason": "lower_or_equal_priority",
                    },
                )
                return PreemptOutcome(
                    accepted=False,
                    validation=PreemptValidationResult(
                        PreemptValidationStatus.OK,
                        detail="superseded by higher-priority active preempt",
                    ),
                )

        self._active_preempt = parsed
        self._preempt_armed_at_ns = now
        self._metrics.inc(
            "atms_controller_preempt_armed_total",
            labels={
                "intersection_id": str(self._cfg.intersection_id),
                "approach": parsed.approach.value,
                "priority": parsed.priority.value,
            },
        )
        self._logger.log_transition(
            {
                "event": "preempt_arm",
                "intersection_id": self._cfg.intersection_id,
                "approach": parsed.approach.value,
                "priority": parsed.priority.value,
                "transponder_id": parsed.transponder_id,
                "valid_until_ns": parsed.valid_until_ns,
            }
        )
        return PreemptOutcome(accepted=True, validation=result)

    def submit_preempt_clear(self, approach: Approach, reason: str = "operator") -> None:
        """Clear the active preempt for `approach`. No-op if none active for that approach."""
        if self._active_preempt is None or self._active_preempt.approach is not approach:
            return
        # Honour minimum dwell.
        now = self._clock.now_ns()
        dwell_s = (now - self._preempt_armed_at_ns) / 1_000_000_000
        if dwell_s < self._cfg.preempt_min_dwell_s:
            return
        self._active_preempt = None
        self._preempt_armed_at_ns = 0
        self._metrics.inc(
            "atms_controller_preempt_cleared_total",
            labels={
                "intersection_id": str(self._cfg.intersection_id),
                "approach": approach.value,
                "reason": reason,
            },
        )
        self._logger.log_transition(
            {
                "event": "preempt_clear",
                "intersection_id": self._cfg.intersection_id,
                "approach": approach.value,
                "reason": reason,
                "dwell_s": dwell_s,
            }
        )

    def submit_ped_call(self, raw: Mapping[str, Any]) -> PedCallOutcome:
        """Queue a pedestrian-call (gap #3 / Phase A7). Deduplicated by approach."""
        now = self._clock.now_ns()
        parsed = PedCallRequest.from_dict(raw)
        if isinstance(parsed, PreemptValidationResult):
            return PedCallOutcome(accepted=False, validation=parsed)

        result = parsed.validate_for_controller(
            controller_intersection_id=self._cfg.intersection_id, now_ns=now
        )
        if not result.ok:
            return PedCallOutcome(accepted=False, validation=result)

        existing = self._ped_queue.get(parsed.approach)
        # If an accessibility call arrives while a non-accessibility one is
        # queued for the same approach, upgrade.
        if existing is None or (parsed.accessibility and not existing.accessibility):
            self._ped_queue[parsed.approach] = parsed
            self._metrics.inc(
                "atms_controller_ped_call_queued_total",
                labels={
                    "intersection_id": str(self._cfg.intersection_id),
                    "approach": parsed.approach.value,
                    "accessibility": str(parsed.accessibility).lower(),
                },
            )
            self._logger.log_transition(
                {
                    "event": "ped_call_queued",
                    "intersection_id": self._cfg.intersection_id,
                    "approach": parsed.approach.value,
                    "accessibility": parsed.accessibility,
                }
            )
        return PedCallOutcome(accepted=True, validation=result)

    def has_active_preempt(self) -> bool:
        return self._active_preempt is not None

    def pending_ped_calls(self) -> tuple[Approach, ...]:
        return tuple(self._ped_queue.keys())

    def force_mode(self, mode: Mode, reason: str) -> None:
        """
        Operator-initiated mode change. Always succeeds. Audit-logged.

        The runbook (docs/runbooks/failsafe.md) requires operators to use this
        path to recover from ALL_RED_FLASH after a safety walk-through.
        """
        now = self._clock.now_ns()
        self._transition(mode, TransitionReason.OPERATOR_OVERRIDE, now, detail=reason)

    def report_hardware_fault(self, detail: str) -> None:
        """The NTCIP layer reports a controller/lamp fault. Drop to ALL_RED_FLASH."""
        now = self._clock.now_ns()
        self._transition(Mode.ALL_RED_FLASH, TransitionReason.HARDWARE_FAULT, now, detail=detail)

    def status(self) -> dict[str, Any]:
        now = self._clock.now_ns()
        age_ms = (
            (now - self._last_accepted_at_ns) / 1_000_000 if self._last_accepted_at_ns else None
        )
        return {
            "mode": self._mode.value,
            "mode_dwell_s": (now - self._mode_entered_at_ns) / 1_000_000_000,
            "last_decision_id": self._last_accepted_id,
            "last_decision_age_ms": age_ms,
            "commanded_phase": self._last_commanded_phase.value,
            "consecutive_invalid": self._consecutive_invalid,
            "consecutive_valid": self._consecutive_valid_since_fixed_time,
            "flap_count_in_window": self._count_recent_failsafe_transitions(now),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _on_invalid(self, result: ValidationResult, now: int) -> None:
        self._consecutive_invalid += 1
        self._consecutive_valid_since_fixed_time = 0
        self._metrics.inc(
            "atms_controller_invalid_decisions_total",
            labels={
                "intersection_id": str(self._cfg.intersection_id),
                "reason": result.status.value,
            },
        )
        if (
            self._mode is Mode.AI_ADAPTIVE
            and self._consecutive_invalid >= self._cfg.invalid_decision_burst
        ):
            self._transition(
                Mode.FIXED_TIME,
                TransitionReason.INVALID_DECISION_BURST,
                now,
                detail=result.status.value,
            )

    def _check_staleness(self, now: int) -> None:
        if self._mode is not Mode.AI_ADAPTIVE:
            return
        if self._last_accepted_at_ns == 0:
            # Never received a decision since becoming adaptive; stale by definition.
            self._transition(
                Mode.FIXED_TIME,
                TransitionReason.AI_DECISION_STALE,
                now,
                detail="no_decision_yet",
            )
            return
        age_ms = (now - self._last_accepted_at_ns) / 1_000_000
        if age_ms > self._cfg.max_ai_staleness_ms:
            self._transition(
                Mode.FIXED_TIME,
                TransitionReason.AI_DECISION_STALE,
                now,
                detail=f"age_ms={age_ms:.1f}",
            )

    def _maybe_recover_to_ai(self, now: int) -> None:
        dwell_s = (now - self._mode_entered_at_ns) / 1_000_000_000
        if dwell_s < self._cfg.fixed_time_min_dwell_s:
            return
        if self._consecutive_valid_since_fixed_time < self._cfg.consecutive_valid_to_recover:
            return
        self._transition(Mode.AI_ADAPTIVE, TransitionReason.RECOVERY_VALID_STREAM, now)

    def _desired_phase(self, now: int) -> CommandedPhase:
        # 1. Emergency stop always wins.
        if self._mode is Mode.ALL_RED_FLASH:
            return CommandedPhase.ALL_RED_FLASH

        # 2. Expire stale preempt before consulting it.
        if self._active_preempt is not None and now >= self._active_preempt.valid_until_ns:
            self._expire_preempt(now)

        # 3. Continue an in-flight pedestrian phase (walk + clearance).
        ped_phase = self._continue_ped_phase(now)
        if ped_phase is not None:
            return ped_phase

        # 4. Active preempt — but only after any in-flight ped clearance has run.
        if self._active_preempt is not None:
            return (
                CommandedPhase.EV_PREEMPT_NS
                if self._active_preempt.approach is Approach.NORTH_SOUTH
                else CommandedPhase.EV_PREEMPT_EW
            )

        # 5. Pending ped-call (and no preempt). Start a ped phase if we are not
        # mid-vehicular-green; otherwise wait for the next natural boundary.
        if self._ped_queue and self._is_safe_boundary_for_ped(now):
            self._start_ped_phase(now)
            ped_phase = self._continue_ped_phase(now)
            if ped_phase is not None:
                return ped_phase

        # 6. Normal mode-based scheduling.
        if self._mode is Mode.FIXED_TIME:
            elapsed = (now - self._mode_entered_at_ns) / 1_000_000_000
            return self._plan.phase_at(elapsed)

        if self._last_accepted is not None:
            return self._last_accepted.commanded_phase

        # Defensive: should not happen because staleness check fires first.
        return CommandedPhase.ALL_RED

    def _continue_ped_phase(self, now: int) -> CommandedPhase | None:
        """Advance the in-flight ped phase. Returns None if not in one."""
        if self._ped_phase_state is _PedPhaseState.NONE or self._ped_phase_approach is None:
            return None
        elapsed_s = (now - self._ped_phase_started_at_ns) / 1_000_000_000
        walk_min = (
            self._cfg.ada_min_walk_s if self._ped_phase_accessibility else self._cfg.ped_min_walk_s
        )
        if self._ped_phase_state is _PedPhaseState.WALK:
            if elapsed_s < walk_min:
                return self._walk_phase_for(self._ped_phase_approach)
            # Transition to clearance.
            self._ped_phase_state = _PedPhaseState.CLEARANCE
            self._ped_phase_started_at_ns = now
            return self._flashing_phase_for(self._ped_phase_approach)
        if self._ped_phase_state is _PedPhaseState.CLEARANCE:
            if elapsed_s < self._cfg.ped_clearance_min_s:
                return self._flashing_phase_for(self._ped_phase_approach)
            # Done. Emit completion event and unwind.
            self._logger.log_transition(
                {
                    "event": "ped_call_serviced",
                    "intersection_id": self._cfg.intersection_id,
                    "approach": self._ped_phase_approach.value,
                    "accessibility": self._ped_phase_accessibility,
                }
            )
            self._ped_phase_state = _PedPhaseState.NONE
            self._ped_phase_approach = None
            self._ped_phase_accessibility = False
            return None
        return None

    def _is_safe_boundary_for_ped(self, now: int) -> bool:
        """True when starting a ped phase right now would not violate min-green."""
        if self._last_commanded_phase in (
            CommandedPhase.NS_GREEN,
            CommandedPhase.EW_GREEN,
        ):
            elapsed_s = (now - self._phase_entered_at_ns) / 1_000_000_000
            return elapsed_s >= self._safety.min_green_s
        return True

    def _start_ped_phase(self, now: int) -> None:
        # Service highest-priority call (accessibility first, else first-come).
        ordered = sorted(
            self._ped_queue.items(),
            key=lambda kv: (not kv[1].accessibility, kv[1].producer_timestamp_ns),
        )
        approach, req = ordered[0]
        del self._ped_queue[approach]
        self._ped_phase_state = _PedPhaseState.WALK
        self._ped_phase_approach = approach
        self._ped_phase_started_at_ns = now
        self._ped_phase_accessibility = req.accessibility
        self._logger.log_transition(
            {
                "event": "accessible_signal_state",
                "intersection_id": self._cfg.intersection_id,
                "approach": approach.value,
                "state": "walk",
                "accessibility_active": req.accessibility,
            }
        )

    @staticmethod
    def _walk_phase_for(approach: Approach) -> CommandedPhase:
        return (
            CommandedPhase.PED_NS_WALK
            if approach is Approach.NORTH_SOUTH
            else CommandedPhase.PED_EW_WALK
        )

    @staticmethod
    def _flashing_phase_for(approach: Approach) -> CommandedPhase:
        return (
            CommandedPhase.PED_NS_FLASHING_GREEN
            if approach is Approach.NORTH_SOUTH
            else CommandedPhase.PED_EW_FLASHING_GREEN
        )

    def _expire_preempt(self, now: int) -> None:
        if self._active_preempt is None:
            return
        approach = self._active_preempt.approach
        self._active_preempt = None
        self._preempt_armed_at_ns = 0
        self._metrics.inc(
            "atms_controller_preempt_cleared_total",
            labels={
                "intersection_id": str(self._cfg.intersection_id),
                "approach": approach.value,
                "reason": "expired",
            },
        )
        self._logger.log_transition(
            {
                "event": "preempt_clear",
                "intersection_id": self._cfg.intersection_id,
                "approach": approach.value,
                "reason": "expired",
            }
        )

    def _record_invalid_preempt(self, result: PreemptValidationResult, _now: int) -> None:
        self._metrics.inc(
            "atms_controller_preempt_rejected_total",
            labels={
                "intersection_id": str(self._cfg.intersection_id),
                "reason": result.status.value,
            },
        )

    # Pairs of phases that are the SAME direction (e.g., NS_GREEN ↔ EV_PREEMPT_NS).
    # Transitioning between them does not require min-green to elapse — the
    # preempt is a continuation of the same approach's green, not a new phase.
    _SAME_DIRECTION_TRANSITIONS = frozenset(
        {
            frozenset({CommandedPhase.NS_GREEN, CommandedPhase.EV_PREEMPT_NS}),
            frozenset({CommandedPhase.EW_GREEN, CommandedPhase.EV_PREEMPT_EW}),
        }
    )

    def _apply_safety_filter(self, desired: CommandedPhase, now: int) -> CommandedPhase:
        # Emergency override: ALL_RED_FLASH is *safer* than any commanded green,
        # so a hardware fault / operator E-stop / flap-escalation may cut a green
        # short. Any vehicle in the intersection clears; any vehicle approaching
        # stops. This is consistent with how a real signal cabinet responds to a
        # conflict monitor trip.
        if self._mode is Mode.ALL_RED_FLASH or desired is CommandedPhase.ALL_RED_FLASH:
            return CommandedPhase.ALL_RED_FLASH

        current = self._last_commanded_phase

        # Legacy ped clearance guard. The Phase A7 state machine
        # (`_continue_ped_phase`) governs WALK → FLASHING → done explicitly,
        # so we only enforce this when no managed ped phase is in flight.
        if (
            self._ped_phase_state is _PedPhaseState.NONE
            and self._ped_clearance_until_ns
            and now < self._ped_clearance_until_ns
            and desired != current
        ):
            return current

        # Min-green: if currently in a vehicular green, hold it. A same-direction
        # EV preempt is a continuation of the same approach's green and is
        # exempt (ADR-0007 §priority order; see _SAME_DIRECTION_TRANSITIONS).
        if current in (CommandedPhase.NS_GREEN, CommandedPhase.EW_GREEN):
            elapsed_s = (now - self._phase_entered_at_ns) / 1_000_000_000
            if (
                elapsed_s < self._safety.min_green_s
                and desired != current
                and frozenset({current, desired}) not in self._SAME_DIRECTION_TRANSITIONS
            ):
                return current

        # No-conflict: never go directly from one vehicular GREEN to the conflicting GREEN
        # (must pass through YELLOW + ALL_RED). If asked to, insert the YELLOW.
        if (
            desired in (CommandedPhase.NS_GREEN, CommandedPhase.EW_GREEN)
            and current in (CommandedPhase.NS_GREEN, CommandedPhase.EW_GREEN)
            and is_conflicting(desired, current)
        ):
            return (
                CommandedPhase.NS_YELLOW
                if current is CommandedPhase.NS_GREEN
                else CommandedPhase.EW_YELLOW
            )

        return desired

    def _on_phase_change(self, new_phase: CommandedPhase, now: int) -> None:
        if new_phase in (CommandedPhase.PED_NS_WALK, CommandedPhase.PED_EW_WALK):
            self._ped_clearance_until_ns = now + int(self._cfg.ped_clearance_min_s * 1_000_000_000)
        # Phase A7 — emit ADA accessible-signal events whenever the ped phase
        # transitions, so downstream audio/tactile hardware can announce it.
        if new_phase in (CommandedPhase.PED_NS_WALK, CommandedPhase.PED_EW_WALK):
            self._logger.log_transition(
                {
                    "event": "accessible_signal_state",
                    "intersection_id": self._cfg.intersection_id,
                    "approach": (
                        "north_south" if new_phase is CommandedPhase.PED_NS_WALK else "east_west"
                    ),
                    "state": "walk",
                    "accessibility_active": self._ped_phase_accessibility,
                }
            )
        elif new_phase in (
            CommandedPhase.PED_NS_FLASHING_GREEN,
            CommandedPhase.PED_EW_FLASHING_GREEN,
        ):
            self._logger.log_transition(
                {
                    "event": "accessible_signal_state",
                    "intersection_id": self._cfg.intersection_id,
                    "approach": (
                        "north_south"
                        if new_phase is CommandedPhase.PED_NS_FLASHING_GREEN
                        else "east_west"
                    ),
                    "state": "clearance",
                    "accessibility_active": self._ped_phase_accessibility,
                }
            )
        self._last_commanded_phase = new_phase
        self._phase_entered_at_ns = now

    def _transition(
        self,
        new_mode: Mode,
        reason: TransitionReason,
        now: int,
        *,
        detail: str = "",
    ) -> None:
        if new_mode is self._mode:
            return

        # No automatic recovery from ALL_RED_FLASH (only operator override).
        if self._mode is Mode.ALL_RED_FLASH and reason is not TransitionReason.OPERATOR_OVERRIDE:
            return

        old = self._mode
        flap_count_in_window = self._count_recent_failsafe_transitions(now)

        # Record AI_ADAPTIVE -> FIXED_TIME for flap detection.
        if old is Mode.AI_ADAPTIVE and new_mode is Mode.FIXED_TIME:
            self._failsafe_transitions.append(now)
            self._evict_old_transitions(now)
            flap_count_in_window = len(self._failsafe_transitions)
            if flap_count_in_window >= self._cfg.flap_threshold:
                # Escalate to emergency. Do the FIXED_TIME bookkeeping first, then escalate.
                self._mode = Mode.FIXED_TIME
                self._mode_entered_at_ns = now
                self._consecutive_valid_since_fixed_time = 0
                self._emit_mode_gauge()
                self._emit_transition_log(
                    old, Mode.FIXED_TIME, reason, now, detail, flap_count_in_window
                )
                # Now escalate.
                old = Mode.FIXED_TIME
                new_mode = Mode.ALL_RED_FLASH
                reason = TransitionReason.FLAP_THRESHOLD

        self._mode = new_mode
        self._mode_entered_at_ns = now
        if new_mode is Mode.AI_ADAPTIVE:
            self._consecutive_valid_since_fixed_time = 0
            self._consecutive_invalid = 0
        self._emit_mode_gauge()
        self._emit_transition_log(old, new_mode, reason, now, detail, flap_count_in_window)

    def _emit_transition_log(
        self,
        from_mode: Mode,
        to_mode: Mode,
        reason: TransitionReason,
        now: int,
        detail: str,
        flap_count: int,
    ) -> None:
        self._metrics.inc(
            "atms_controller_mode_transitions_total",
            labels={
                "intersection_id": str(self._cfg.intersection_id),
                "from": from_mode.value,
                "to": to_mode.value,
                "reason": reason.value,
            },
        )
        age_ms = (
            (now - self._last_accepted_at_ns) / 1_000_000 if self._last_accepted_at_ns else None
        )
        self._logger.log_transition(
            {
                "event": "controller_mode_transition",
                "intersection_id": self._cfg.intersection_id,
                "from_mode": from_mode.value,
                "to_mode": to_mode.value,
                "reason": reason.value,
                "detail": detail,
                "last_decision_id": self._last_accepted_id,
                "last_decision_age_ms": age_ms,
                "flap_count_in_window": flap_count,
            }
        )

    def _emit_mode_gauge(self) -> None:
        for m in Mode:
            self._metrics.set_gauge(
                "atms_controller_mode",
                value=1.0 if m is self._mode else 0.0,
                labels={
                    "intersection_id": str(self._cfg.intersection_id),
                    "mode": m.value,
                },
            )

    def _count_recent_failsafe_transitions(self, now: int) -> int:
        self._evict_old_transitions(now)
        return len(self._failsafe_transitions)

    def _evict_old_transitions(self, now: int) -> None:
        threshold = now - int(self._cfg.flap_window_s * 1_000_000_000)
        while self._failsafe_transitions and self._failsafe_transitions[0] < threshold:
            self._failsafe_transitions.popleft()


# ---------------------------------------------------------------------------
# Convenience constructor for production wiring.
# ---------------------------------------------------------------------------


def build_default_controller(
    *,
    intersection_id: int,
    clock: Clock,
    metrics: MetricsRecorder,
    logger: TransitionLogger | None = None,
    plan: FixedTimePlan | None = None,
    safety: SafetyConfig | None = None,
    config: FailsafeConfig | None = None,
) -> FailsafeController:
    """Build a FailsafeController with EU/RiLSA defaults if not provided."""
    return FailsafeController(
        config=config or FailsafeConfig(intersection_id=intersection_id),
        plan=plan or FixedTimePlan.rilsa_default(),
        safety=safety or SafetyConfig(),
        clock=clock,
        metrics=metrics,
        logger=logger,
    )
