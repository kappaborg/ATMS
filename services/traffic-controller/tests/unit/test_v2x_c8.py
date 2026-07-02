"""Tests for shared/atms_common/v2x.py (Phase C8)."""

from __future__ import annotations

import pytest

from shared.atms_common.preempt import Approach, PreemptPriority, PreemptRequest
from shared.atms_common.v2x import (
    BSMMessage,
    BSMMessageType,
    V2XValidationResult,
    V2XValidationStatus,
    V2XVehicleClass,
    bsm_to_preempt_request,
)


def _wire(**overrides: object) -> dict:
    """Minimal valid wire dict."""
    base = {
        "temporary_id": "TMP-001",
        "intersection_id": 1,
        "message_type": "regular",
        "vehicle_class": "passenger",
        "latitude_deg": 52.5,
        "longitude_deg": 13.4,
        "elevation_m": 35.0,
        "speed_mps": 8.0,
        "heading_deg": 180.0,
        "acceleration_mps2": 0.5,
        "approach": "north_south",
        "distance_to_intersection_m": 50.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestBSMFromDict:
    def test_minimal_valid_parses(self):
        msg = BSMMessage.from_dict(_wire())
        assert isinstance(msg, BSMMessage)
        assert msg.temporary_id == "TMP-001"
        assert msg.vehicle_class is V2XVehicleClass.PASSENGER
        assert msg.approach is Approach.NORTH_SOUTH

    def test_missing_required_field(self):
        data = _wire()
        data.pop("intersection_id")
        result = BSMMessage.from_dict(data)
        assert isinstance(result, V2XValidationResult)
        assert result.status is V2XValidationStatus.SCHEMA_MISSING_FIELD
        assert "intersection_id" in result.detail

    def test_unknown_vehicle_class(self):
        result = BSMMessage.from_dict(_wire(vehicle_class="hovercraft"))
        assert isinstance(result, V2XValidationResult)
        assert result.status is V2XValidationStatus.SCHEMA_UNKNOWN_VALUE

    def test_bad_type(self):
        result = BSMMessage.from_dict(_wire(speed_mps="fast"))
        assert isinstance(result, V2XValidationResult)
        assert result.status is V2XValidationStatus.SCHEMA_BAD_TYPE

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("latitude_deg", 91.0),       # > 90
            ("latitude_deg", -91.0),      # < -90
            ("longitude_deg", 200.0),     # > 180
            ("heading_deg", 360.0),       # not < 360
            ("heading_deg", -10.0),       # not >= 0
            ("speed_mps", -1.0),          # negative
            ("speed_mps", 200.0),         # > 100
        ],
    )
    def test_out_of_range(self, field, value):
        result = BSMMessage.from_dict(_wire(**{field: value}))
        assert isinstance(result, V2XValidationResult)
        assert result.status is V2XValidationStatus.OUT_OF_RANGE

    def test_intersection_mismatch_in_validate(self):
        msg = BSMMessage.from_dict(_wire(intersection_id=1))
        assert isinstance(msg, BSMMessage)
        result = msg.validate_for_intersection(controller_intersection_id=2)
        assert result.status is V2XValidationStatus.INTERSECTION_MISMATCH

    def test_intersection_match_in_validate(self):
        msg = BSMMessage.from_dict(_wire(intersection_id=7))
        assert isinstance(msg, BSMMessage)
        result = msg.validate_for_intersection(controller_intersection_id=7)
        assert result.ok


# ---------------------------------------------------------------------------
# Predicates for preempt eligibility
# ---------------------------------------------------------------------------


class TestPreemptEligibility:
    def test_regular_passenger_not_emergency(self):
        msg = BSMMessage.from_dict(_wire())
        assert isinstance(msg, BSMMessage)
        assert not msg.is_emergency_active
        assert not msg.is_transit_priority

    def test_emergency_without_siren_not_eligible(self):
        msg = BSMMessage.from_dict(_wire(vehicle_class="emergency"))
        assert isinstance(msg, BSMMessage)
        assert not msg.is_emergency_active

    def test_emergency_with_siren_is_eligible(self):
        msg = BSMMessage.from_dict(
            _wire(vehicle_class="emergency", siren_active=True, transponder_id="EV-7")
        )
        assert isinstance(msg, BSMMessage)
        assert msg.is_emergency_active

    def test_emergency_with_lightbar_only_is_eligible(self):
        msg = BSMMessage.from_dict(
            _wire(vehicle_class="emergency", light_bar_active=True)
        )
        assert isinstance(msg, BSMMessage)
        assert msg.is_emergency_active

    def test_transit_with_route_eligible(self):
        msg = BSMMessage.from_dict(
            _wire(vehicle_class="transit", transit_route_id="42N")
        )
        assert isinstance(msg, BSMMessage)
        assert msg.is_transit_priority

    def test_transit_without_route_not_eligible(self):
        msg = BSMMessage.from_dict(_wire(vehicle_class="transit"))
        assert isinstance(msg, BSMMessage)
        assert not msg.is_transit_priority


# ---------------------------------------------------------------------------
# BSM → PreemptRequest bridge
# ---------------------------------------------------------------------------


class TestBsmToPreempt:
    def test_returns_none_for_regular_vehicle(self):
        msg = BSMMessage.from_dict(_wire())
        assert isinstance(msg, BSMMessage)
        assert bsm_to_preempt_request(msg) is None

    def test_emergency_yields_fire_rescue_preempt(self):
        msg = BSMMessage.from_dict(
            _wire(
                vehicle_class="emergency",
                siren_active=True,
                transponder_id="EV-7",
                approach="east_west",
            )
        )
        assert isinstance(msg, BSMMessage)
        req = bsm_to_preempt_request(msg)
        assert isinstance(req, PreemptRequest)
        assert req.priority is PreemptPriority.FIRE_RESCUE
        assert req.approach is Approach.EAST_WEST
        assert req.transponder_id == "EV-7"
        # Default 30s TTL.
        assert req.valid_until_ns - req.producer_timestamp_ns == 30 * 1_000_000_000

    def test_transit_yields_transit_priority(self):
        msg = BSMMessage.from_dict(
            _wire(vehicle_class="transit", transit_route_id="42N")
        )
        assert isinstance(msg, BSMMessage)
        req = bsm_to_preempt_request(msg)
        assert isinstance(req, PreemptRequest)
        assert req.priority is PreemptPriority.TRANSIT

    def test_transponder_id_falls_back_to_temporary_id(self):
        msg = BSMMessage.from_dict(
            _wire(
                vehicle_class="emergency",
                siren_active=True,
                temporary_id="TMP-99",
                # no transponder_id
            )
        )
        assert isinstance(msg, BSMMessage)
        req = bsm_to_preempt_request(msg)
        assert isinstance(req, PreemptRequest)
        assert req.transponder_id == "TMP-99"

    def test_custom_ttl(self):
        msg = BSMMessage.from_dict(
            _wire(vehicle_class="emergency", siren_active=True)
        )
        assert isinstance(msg, BSMMessage)
        req = bsm_to_preempt_request(msg, ttl_ns=60 * 1_000_000_000)
        assert isinstance(req, PreemptRequest)
        assert req.valid_until_ns - req.producer_timestamp_ns == 60 * 1_000_000_000
