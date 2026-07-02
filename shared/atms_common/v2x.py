"""
V2X (J2735 BSM) message schema — Phase C8 (ADR-0019).

The wire contract between the v2x-interface service and downstream consumers.
Real V2X uses ASN.1 BER/DER encoding; the stub uses JSON-over-MQTT. The
schema below is the SAE J2735 subset relevant to signal control + preempt.

When a real V2X provider is selected, the ASN.1 ↔ JSON adapter lives in
`services/v2x-interface/src/` — the rest of the stack continues to consume
this schema.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from shared.atms_common.errors import AtmsError
from shared.atms_common.preempt import Approach, PreemptPriority, PreemptRequest
from shared.atms_common.timekeeping import SyncedTimestamp


class V2XError(AtmsError):
    """Raised on BSM validation failure."""


class BSMMessageType(str, Enum):
    REGULAR = "regular"
    EVENT = "event"


class V2XVehicleClass(str, Enum):
    PASSENGER = "passenger"
    TRUCK = "truck"
    BUS = "bus"
    MOTORCYCLE = "motorcycle"
    EMERGENCY = "emergency"
    TRANSIT = "transit"


# ---------------------------------------------------------------------------
# Validation result (shape consistent with shared.atms_common.preempt)
# ---------------------------------------------------------------------------


class V2XValidationStatus(str, Enum):
    OK = "ok"
    SCHEMA_MISSING_FIELD = "schema_missing_field"
    SCHEMA_BAD_TYPE = "schema_bad_type"
    SCHEMA_UNKNOWN_VALUE = "schema_unknown_value"
    INTERSECTION_MISMATCH = "intersection_mismatch"
    OUT_OF_RANGE = "out_of_range"


@dataclass(frozen=True)
class V2XValidationResult:
    status: V2XValidationStatus
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status is V2XValidationStatus.OK


# Required fields on the wire.
_BSM_REQUIRED_FIELDS = (
    "temporary_id",
    "intersection_id",
    "message_type",
    "vehicle_class",
    "latitude_deg",
    "longitude_deg",
    "speed_mps",
    "heading_deg",
    "approach",
    "distance_to_intersection_m",
)


@dataclass(frozen=True)
class BSMMessage:
    """SAE J2735 BSM subset relevant to signal control + EV preempt."""

    temporary_id: str
    intersection_id: int
    received_at: SyncedTimestamp
    message_type: BSMMessageType
    vehicle_class: V2XVehicleClass
    latitude_deg: float
    longitude_deg: float
    elevation_m: float
    speed_mps: float
    heading_deg: float
    acceleration_mps2: float
    approach: Approach
    distance_to_intersection_m: float
    siren_active: bool = False
    light_bar_active: bool = False
    transit_route_id: str = ""
    signature_valid: bool = False
    transponder_id: str = ""

    @staticmethod
    def from_dict(
        data: Mapping[str, Any],
    ) -> BSMMessage | V2XValidationResult:
        for f in _BSM_REQUIRED_FIELDS:
            if f not in data:
                return V2XValidationResult(V2XValidationStatus.SCHEMA_MISSING_FIELD, detail=f)
        try:
            intersection_id = int(data["intersection_id"])
            latitude_deg = float(data["latitude_deg"])
            longitude_deg = float(data["longitude_deg"])
            elevation_m = float(data.get("elevation_m", 0.0))
            speed_mps = float(data["speed_mps"])
            heading_deg = float(data["heading_deg"])
            acceleration_mps2 = float(data.get("acceleration_mps2", 0.0))
            distance = float(data["distance_to_intersection_m"])
        except (TypeError, ValueError) as e:
            return V2XValidationResult(V2XValidationStatus.SCHEMA_BAD_TYPE, detail=str(e))

        try:
            message_type = BSMMessageType(data["message_type"])
        except ValueError:
            return V2XValidationResult(
                V2XValidationStatus.SCHEMA_UNKNOWN_VALUE,
                detail=f"message_type={data.get('message_type')}",
            )
        try:
            vehicle_class = V2XVehicleClass(data["vehicle_class"])
        except ValueError:
            return V2XValidationResult(
                V2XValidationStatus.SCHEMA_UNKNOWN_VALUE,
                detail=f"vehicle_class={data.get('vehicle_class')}",
            )
        try:
            approach = Approach(data["approach"])
        except ValueError:
            return V2XValidationResult(
                V2XValidationStatus.SCHEMA_UNKNOWN_VALUE,
                detail=f"approach={data.get('approach')}",
            )

        # Range checks for navigation fields.
        if not (-90 <= latitude_deg <= 90):
            return V2XValidationResult(
                V2XValidationStatus.OUT_OF_RANGE,
                detail=f"latitude_deg={latitude_deg}",
            )
        if not (-180 <= longitude_deg <= 180):
            return V2XValidationResult(
                V2XValidationStatus.OUT_OF_RANGE,
                detail=f"longitude_deg={longitude_deg}",
            )
        if not (0 <= heading_deg < 360):
            return V2XValidationResult(
                V2XValidationStatus.OUT_OF_RANGE,
                detail=f"heading_deg={heading_deg}",
            )
        if speed_mps < 0 or speed_mps > 100:
            return V2XValidationResult(
                V2XValidationStatus.OUT_OF_RANGE,
                detail=f"speed_mps={speed_mps}",
            )

        received_at = SyncedTimestamp.now()  # the receipt-time boundary
        return BSMMessage(
            temporary_id=str(data["temporary_id"]),
            intersection_id=intersection_id,
            received_at=received_at,
            message_type=message_type,
            vehicle_class=vehicle_class,
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            elevation_m=elevation_m,
            speed_mps=speed_mps,
            heading_deg=heading_deg,
            acceleration_mps2=acceleration_mps2,
            approach=approach,
            distance_to_intersection_m=distance,
            siren_active=bool(data.get("siren_active", False)),
            light_bar_active=bool(data.get("light_bar_active", False)),
            transit_route_id=str(data.get("transit_route_id", "")),
            signature_valid=bool(data.get("signature_valid", False)),
            transponder_id=str(data.get("transponder_id", "")),
        )

    def validate_for_intersection(self, *, controller_intersection_id: int) -> V2XValidationResult:
        if self.intersection_id != controller_intersection_id:
            return V2XValidationResult(
                V2XValidationStatus.INTERSECTION_MISMATCH,
                detail=(f"got={self.intersection_id} expected={controller_intersection_id}"),
            )
        return V2XValidationResult(V2XValidationStatus.OK)

    @property
    def is_emergency_active(self) -> bool:
        """True if this BSM should drive a PreemptRequest."""
        return self.vehicle_class is V2XVehicleClass.EMERGENCY and (
            self.siren_active or self.light_bar_active
        )

    @property
    def is_transit_priority(self) -> bool:
        """True if this BSM should drive a TRANSIT-priority preempt."""
        return self.vehicle_class is V2XVehicleClass.TRANSIT and bool(self.transit_route_id)


# ---------------------------------------------------------------------------
# BSM → PreemptRequest bridge (ADR-0019 §Emergency-vehicle path)
# ---------------------------------------------------------------------------


def bsm_to_preempt_request(
    bsm: BSMMessage,
    *,
    ttl_ns: int = 30 * 1_000_000_000,
) -> PreemptRequest | None:
    """
    Translate an EV / transit BSM into an A7 PreemptRequest.

    Returns None when the BSM is not preempt-eligible (regular vehicle, or EV
    without active siren). The caller passes the resulting request to the
    failsafe controller via `submit_preempt`.

    `ttl_ns` is the preempt validity window — defaults to 30 s, which covers
    a typical EV approach + dwell at an intersection.
    """
    if not (bsm.is_emergency_active or bsm.is_transit_priority):
        return None
    # Default emergency to FIRE_RESCUE rank when the BSM doesn't distinguish.
    # Operators can refine via a deployment-specific BSM-to-priority map.
    priority = PreemptPriority.FIRE_RESCUE if bsm.is_emergency_active else PreemptPriority.TRANSIT

    now_ns = bsm.received_at.monotonic_ns
    return PreemptRequest(
        intersection_id=bsm.intersection_id,
        approach=bsm.approach,
        priority=priority,
        valid_until_ns=now_ns + ttl_ns,
        transponder_id=bsm.transponder_id or bsm.temporary_id,
        producer_timestamp_ns=now_ns,
    )
