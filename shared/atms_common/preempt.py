"""
Emergency-vehicle preempt and pedestrian-call schemas — Phase A7.

The wire contracts for `POST /control/preempt`, `POST /control/preempt/clear`,
and `POST /control/ped-call` on traffic-controller. See:

- docs/adr/0007-preempt-pedestrian-ada.md (design)
- docs/runbooks/failsafe.md §preempt + §ped-call (operations)

Per ADR-0004, EU/RiLSA dedicated-channel semantics: preempt arrives via a
trusted input (NTCIP MIB, transponder receiver, edge GPIO) and is signed by
the producing component. Vision-based siren/strobe heuristics are *not*
preempt sources.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class Approach(str, Enum):
    """Which approach is requesting (or being served by) the controller."""

    NORTH_SOUTH = "north_south"
    EAST_WEST = "east_west"


class PreemptPriority(str, Enum):
    """
    Preempt source priority. Higher priority overrides lower priority preempts
    in flight, per common-jurisdiction conventions:

        FIRE_RESCUE > AMBULANCE > POLICE > TRANSIT
    """

    FIRE_RESCUE = "fire_rescue"
    AMBULANCE = "ambulance"
    POLICE = "police"
    TRANSIT = "transit"


_PREEMPT_RANK = {
    PreemptPriority.FIRE_RESCUE: 3,
    PreemptPriority.AMBULANCE: 2,
    PreemptPriority.POLICE: 1,
    PreemptPriority.TRANSIT: 0,
}


def preempt_priority_rank(p: PreemptPriority) -> int:
    """Higher rank wins when two preempts overlap."""
    return _PREEMPT_RANK[p]


# ---------------------------------------------------------------------------
# Validation result (shared shape with shared/atms_common/decision.py)
# ---------------------------------------------------------------------------


class PreemptValidationStatus(str, Enum):
    OK = "ok"
    SCHEMA_MISSING_FIELD = "schema_missing_field"
    SCHEMA_BAD_TYPE = "schema_bad_type"
    SCHEMA_UNKNOWN_VALUE = "schema_unknown_value"
    INTERSECTION_MISMATCH = "intersection_mismatch"
    EXPIRED = "expired"
    EMPTY_TRANSPONDER = "empty_transponder"


@dataclass(frozen=True)
class PreemptValidationResult:
    status: PreemptValidationStatus
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status is PreemptValidationStatus.OK


_PREEMPT_REQUIRED_FIELDS = (
    "intersection_id",
    "approach",
    "priority",
    "valid_until_ns",
    "transponder_id",
    "producer_timestamp_ns",
)


@dataclass(frozen=True)
class PreemptRequest:
    intersection_id: int
    approach: Approach
    priority: PreemptPriority
    valid_until_ns: int
    transponder_id: str
    producer_timestamp_ns: int

    @staticmethod
    def from_dict(
        data: Mapping[str, Any],
    ) -> PreemptRequest | PreemptValidationResult:
        for f in _PREEMPT_REQUIRED_FIELDS:
            if f not in data:
                return PreemptValidationResult(
                    PreemptValidationStatus.SCHEMA_MISSING_FIELD, detail=f
                )
        try:
            intersection_id = int(data["intersection_id"])
            valid_until_ns = int(data["valid_until_ns"])
            producer_ts = int(data["producer_timestamp_ns"])
        except (TypeError, ValueError) as e:
            return PreemptValidationResult(PreemptValidationStatus.SCHEMA_BAD_TYPE, detail=str(e))

        try:
            approach = Approach(data["approach"])
        except ValueError:
            return PreemptValidationResult(
                PreemptValidationStatus.SCHEMA_UNKNOWN_VALUE,
                detail=f"approach={data.get('approach')}",
            )
        try:
            priority = PreemptPriority(data["priority"])
        except ValueError:
            return PreemptValidationResult(
                PreemptValidationStatus.SCHEMA_UNKNOWN_VALUE,
                detail=f"priority={data.get('priority')}",
            )

        transponder_id = str(data.get("transponder_id", ""))
        if not transponder_id:
            return PreemptValidationResult(PreemptValidationStatus.EMPTY_TRANSPONDER)

        return PreemptRequest(
            intersection_id=intersection_id,
            approach=approach,
            priority=priority,
            valid_until_ns=valid_until_ns,
            transponder_id=transponder_id,
            producer_timestamp_ns=producer_ts,
        )

    def validate_for_controller(
        self,
        *,
        controller_intersection_id: int,
        now_ns: int,
    ) -> PreemptValidationResult:
        if self.intersection_id != controller_intersection_id:
            return PreemptValidationResult(
                PreemptValidationStatus.INTERSECTION_MISMATCH,
                detail=(f"got={self.intersection_id} expected={controller_intersection_id}"),
            )
        if self.valid_until_ns <= now_ns:
            return PreemptValidationResult(
                PreemptValidationStatus.EXPIRED,
                detail=f"valid_until={self.valid_until_ns} now={now_ns}",
            )
        return PreemptValidationResult(PreemptValidationStatus.OK)


# ---------------------------------------------------------------------------
# PedCallRequest
# ---------------------------------------------------------------------------


_PED_REQUIRED_FIELDS = (
    "intersection_id",
    "approach",
    "valid_until_ns",
    "producer_timestamp_ns",
)


@dataclass(frozen=True)
class PedCallRequest:
    intersection_id: int
    approach: Approach
    accessibility: bool
    producer_timestamp_ns: int
    valid_until_ns: int

    @staticmethod
    def from_dict(
        data: Mapping[str, Any],
    ) -> PedCallRequest | PreemptValidationResult:
        for f in _PED_REQUIRED_FIELDS:
            if f not in data:
                return PreemptValidationResult(
                    PreemptValidationStatus.SCHEMA_MISSING_FIELD, detail=f
                )
        try:
            intersection_id = int(data["intersection_id"])
            valid_until_ns = int(data["valid_until_ns"])
            producer_ts = int(data["producer_timestamp_ns"])
        except (TypeError, ValueError) as e:
            return PreemptValidationResult(PreemptValidationStatus.SCHEMA_BAD_TYPE, detail=str(e))
        try:
            approach = Approach(data["approach"])
        except ValueError:
            return PreemptValidationResult(
                PreemptValidationStatus.SCHEMA_UNKNOWN_VALUE,
                detail=f"approach={data.get('approach')}",
            )
        accessibility = bool(data.get("accessibility", False))
        return PedCallRequest(
            intersection_id=intersection_id,
            approach=approach,
            accessibility=accessibility,
            producer_timestamp_ns=producer_ts,
            valid_until_ns=valid_until_ns,
        )

    def validate_for_controller(
        self,
        *,
        controller_intersection_id: int,
        now_ns: int,
    ) -> PreemptValidationResult:
        if self.intersection_id != controller_intersection_id:
            return PreemptValidationResult(
                PreemptValidationStatus.INTERSECTION_MISMATCH,
                detail=(f"got={self.intersection_id} expected={controller_intersection_id}"),
            )
        if self.valid_until_ns <= now_ns:
            return PreemptValidationResult(
                PreemptValidationStatus.EXPIRED,
                detail=f"valid_until={self.valid_until_ns} now={now_ns}",
            )
        return PreemptValidationResult(PreemptValidationStatus.OK)
