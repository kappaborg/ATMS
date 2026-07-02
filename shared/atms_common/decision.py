"""
DecisionMessage schema.

The wire contract between `services/decision-engine` and
`services/traffic-controller`. Required by ADR-0005 (failsafe controller).

A decision is *validated* by `DecisionMessage.validate_for_controller(...)`,
which returns a `ValidationResult` enumerating the failure reason if any.
The failsafe state machine uses this result to decide whether to accept the
decision and reset its watchdog.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Default skew tolerance: producer clock may be up to 500 ms ahead of consumer.
DEFAULT_CLOCK_SKEW_TOLERANCE_NS = 500 * 1_000_000


class CommandedPhase(str, Enum):
    """Phases the failsafe may command to the NTCIP layer.

    Names are jurisdiction-neutral. The mapping to RiLSA / MUTCD state codes
    happens in the NTCIP adapter layer.
    """

    NS_GREEN = "ns_green"
    NS_YELLOW = "ns_yellow"
    EW_GREEN = "ew_green"
    EW_YELLOW = "ew_yellow"
    ALL_RED = "all_red"
    ALL_RED_FLASH = "all_red_flash"
    PED_NS_WALK = "ped_ns_walk"
    PED_EW_WALK = "ped_ew_walk"
    # Phase A7 — pedestrian clearance (flashing green-man / countdown).
    PED_NS_FLASHING_GREEN = "ped_ns_flashing_green"
    PED_EW_FLASHING_GREEN = "ped_ew_flashing_green"
    # Phase A7 — EV preempt: priority approach gets green, conflicts go red.
    EV_PREEMPT_NS = "ev_preempt_ns"
    EV_PREEMPT_EW = "ev_preempt_ew"


class DecisionPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    PREEMPT = "preempt"  # emergency vehicle preemption


class ValidationStatus(str, Enum):
    OK = "ok"
    SCHEMA_MISSING_FIELD = "schema_missing_field"
    SCHEMA_BAD_TYPE = "schema_bad_type"
    SCHEMA_UNKNOWN_PHASE = "schema_unknown_phase"
    INTERSECTION_MISMATCH = "intersection_mismatch"
    NON_MONOTONIC_ID = "non_monotonic_id"
    FUTURE_TIMESTAMP = "future_timestamp"
    EXPIRED = "expired"
    SIGNATURE_INVALID = "signature_invalid"


@dataclass(frozen=True)
class ValidationResult:
    status: ValidationStatus
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status is ValidationStatus.OK


# Required fields for a decision message coming off Kafka.
_REQUIRED_FIELDS = (
    "decision_id",
    "intersection_id",
    "producer_timestamp_ns",
    "valid_until_ns",
    "commanded_phase",
)


@dataclass(frozen=True)
class DecisionMessage:
    decision_id: int
    intersection_id: int
    producer_timestamp_ns: int
    valid_until_ns: int
    commanded_phase: CommandedPhase
    priority: DecisionPriority = DecisionPriority.NORMAL
    confidence: float = 1.0
    reason: str = ""
    signature: str | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)

    # ----- (de)serialization -----

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> DecisionMessage | ValidationResult:
        """Parse a wire-format dict. Returns a ValidationResult on schema failure."""
        for f in _REQUIRED_FIELDS:
            if f not in data:
                return ValidationResult(ValidationStatus.SCHEMA_MISSING_FIELD, detail=f)

        try:
            decision_id = int(data["decision_id"])
            intersection_id = int(data["intersection_id"])
            producer_ts = int(data["producer_timestamp_ns"])
            valid_until = int(data["valid_until_ns"])
        except (TypeError, ValueError) as e:
            return ValidationResult(ValidationStatus.SCHEMA_BAD_TYPE, detail=str(e))

        try:
            phase = CommandedPhase(data["commanded_phase"])
        except ValueError:
            return ValidationResult(
                ValidationStatus.SCHEMA_UNKNOWN_PHASE,
                detail=str(data.get("commanded_phase")),
            )

        try:
            priority = DecisionPriority(data.get("priority", "normal"))
        except ValueError:
            priority = DecisionPriority.NORMAL

        confidence = float(data.get("confidence", 1.0))
        reason = str(data.get("reason", ""))
        signature = data.get("signature")
        signature = str(signature) if signature is not None else None
        known = set(_REQUIRED_FIELDS) | {"priority", "confidence", "reason", "signature"}
        extras = {k: v for k, v in data.items() if k not in known}

        return DecisionMessage(
            decision_id=decision_id,
            intersection_id=intersection_id,
            producer_timestamp_ns=producer_ts,
            valid_until_ns=valid_until,
            commanded_phase=phase,
            priority=priority,
            confidence=confidence,
            reason=reason,
            signature=signature,
            extras=extras,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "decision_id": self.decision_id,
            "intersection_id": self.intersection_id,
            "producer_timestamp_ns": self.producer_timestamp_ns,
            "valid_until_ns": self.valid_until_ns,
            "commanded_phase": self.commanded_phase.value,
            "priority": self.priority.value,
            "confidence": self.confidence,
            "reason": self.reason,
        }
        if self.signature is not None:
            out["signature"] = self.signature
        if self.extras:
            out.update(self.extras)
        return out

    # ----- validation gate -----

    def validate_for_controller(
        self,
        *,
        controller_intersection_id: int,
        last_accepted_decision_id: int | None,
        now_ns: int,
        clock_skew_tolerance_ns: int = DEFAULT_CLOCK_SKEW_TOLERANCE_NS,
        signature_required: bool = False,
        signature_verifier=None,
    ) -> ValidationResult:
        if self.intersection_id != controller_intersection_id:
            return ValidationResult(
                ValidationStatus.INTERSECTION_MISMATCH,
                detail=f"got={self.intersection_id} expected={controller_intersection_id}",
            )
        if last_accepted_decision_id is not None and self.decision_id <= last_accepted_decision_id:
            return ValidationResult(
                ValidationStatus.NON_MONOTONIC_ID,
                detail=f"got={self.decision_id} last={last_accepted_decision_id}",
            )
        if self.producer_timestamp_ns > now_ns + clock_skew_tolerance_ns:
            return ValidationResult(
                ValidationStatus.FUTURE_TIMESTAMP,
                detail=f"producer_ts={self.producer_timestamp_ns} now={now_ns}",
            )
        if self.valid_until_ns <= now_ns:
            return ValidationResult(
                ValidationStatus.EXPIRED,
                detail=f"valid_until={self.valid_until_ns} now={now_ns}",
            )
        if signature_required and (signature_verifier is None or not signature_verifier(self)):
            return ValidationResult(
                ValidationStatus.SIGNATURE_INVALID,
                detail="signature missing or did not verify",
            )
        return ValidationResult(ValidationStatus.OK)


# ---------------------------------------------------------------------------
# Wire-mapping helpers — pure data manipulation, no FastAPI / OTel / JWT deps.
#
# Moved here (from services/decision-engine/src/main.py) so the simulation
# harness and any non-service caller can do the AI-phase → directional-wire
# mapping without pulling in the service's full HTTP stack. The decision-
# engine service re-exports these via `from shared.atms_common.decision import
# _priority_direction, _wire_commanded_phase`.
# ---------------------------------------------------------------------------

# Must mirror AIDecisionEngine.weights. Duplicated rather than imported so the
# wire-mapping has its own testable surface and is not coupled to the legacy
# ai_decision_system internals. Drift between the two is caught by
# `services/decision-engine/tests/unit/test_priority_direction.py`.
_SCORE_WEIGHTS = {
    "vehicle_count": 0.30,
    "emissions": 0.30,
    "waiting_time": 0.20,
    "traffic_flow": 0.20,
}


def _score_direction(data: Mapping[str, Any]) -> float:
    """Priority score for a single direction. Mirrors
    `AIDecisionEngine._calculate_direction_score`."""
    vehicle_count = float(data.get("vehicle_count", 0))
    avg_emission = float(data.get("average_emission", 0.0))
    waiting_time = float(data.get("average_waiting_time", 0.0))
    velocity = float(data.get("average_velocity", 0.0))
    env_score = float(data.get("environmental_impact_score", 0.0))

    vehicle = min(1.0, vehicle_count / 20.0)
    emission = min(1.0, avg_emission / 200.0)
    waiting = min(1.0, waiting_time / 60.0)
    flow = min(1.0, max(0.0, (velocity - 5.0) / 50.0))

    score = (
        vehicle * _SCORE_WEIGHTS["vehicle_count"]
        + emission * _SCORE_WEIGHTS["emissions"]
        + waiting * _SCORE_WEIGHTS["waiting_time"]
        + flow * _SCORE_WEIGHTS["traffic_flow"]
    )
    if env_score > 70:
        score *= 1.2
    return score


def _priority_direction(north_south: Mapping[str, Any], east_west: Mapping[str, Any]) -> str:
    """Return 'north_south' or 'east_west' — the side that should get green."""
    ns = _score_direction(north_south)
    ew = _score_direction(east_west)
    return "north_south" if ns > ew else "east_west"


def _wire_commanded_phase(phase_value: str, priority_direction: str) -> str:
    """Combine the AI's TrafficPhase value with priority direction → wire enum.

    `phase_value` is the string value of an `ai_decision_system.TrafficPhase`
    member: "GREEN", "RED", "YELLOW", or "ALL_RED".
    """
    if phase_value == "GREEN":
        return "ns_green" if priority_direction == "north_south" else "ew_green"
    if phase_value == "YELLOW":
        # YELLOW from the AI means "the priority direction is about to lose green".
        # The failsafe will insert the actual YELLOW/ALL_RED transition itself;
        # we still report the directional YELLOW so observers see the intent.
        return "ns_yellow" if priority_direction == "north_south" else "ew_yellow"
    if phase_value in ("RED", "ALL_RED"):
        return "all_red"
    # Defensive default: unknown AI output → all_red. The failsafe's hard
    # invariants (ADR-0005) ensure the intersection stays safe regardless.
    return "all_red"
