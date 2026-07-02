"""DecisionMessage schema tests."""
from __future__ import annotations

from shared.atms_common.decision import (
    CommandedPhase,
    DecisionMessage,
    DecisionPriority,
    ValidationResult,
    ValidationStatus,
)


def _base(now_ns: int = 1_000_000) -> dict:
    return {
        "decision_id": 1,
        "intersection_id": 7,
        "producer_timestamp_ns": now_ns,
        "valid_until_ns": now_ns + 1_000_000_000,
        "commanded_phase": "ns_green",
        "priority": "normal",
        "confidence": 0.9,
        "reason": "ok",
    }


class TestFromDict:
    def test_roundtrip(self) -> None:
        msg = DecisionMessage.from_dict(_base())
        assert isinstance(msg, DecisionMessage)
        assert msg.commanded_phase is CommandedPhase.NS_GREEN
        assert msg.priority is DecisionPriority.NORMAL

        as_dict = msg.to_dict()
        again = DecisionMessage.from_dict(as_dict)
        assert isinstance(again, DecisionMessage)
        assert again == msg

    def test_missing_required_field(self) -> None:
        data = _base()
        data.pop("intersection_id")
        result = DecisionMessage.from_dict(data)
        assert isinstance(result, ValidationResult)
        assert result.status is ValidationStatus.SCHEMA_MISSING_FIELD
        assert "intersection_id" in result.detail

    def test_bad_type(self) -> None:
        data = _base()
        data["decision_id"] = "not-a-number"
        result = DecisionMessage.from_dict(data)
        assert isinstance(result, ValidationResult)
        assert result.status is ValidationStatus.SCHEMA_BAD_TYPE

    def test_unknown_phase(self) -> None:
        data = _base()
        data["commanded_phase"] = "fly_to_the_moon"
        result = DecisionMessage.from_dict(data)
        assert isinstance(result, ValidationResult)
        assert result.status is ValidationStatus.SCHEMA_UNKNOWN_PHASE

    def test_unknown_priority_defaults_to_normal(self) -> None:
        data = _base()
        data["priority"] = "absurdly_high"
        msg = DecisionMessage.from_dict(data)
        assert isinstance(msg, DecisionMessage)
        assert msg.priority is DecisionPriority.NORMAL

    def test_extras_preserved(self) -> None:
        data = _base()
        data["legacy_decision_id"] = 42
        data["expected_impact"] = {"queue_reduction": 0.3}
        msg = DecisionMessage.from_dict(data)
        assert isinstance(msg, DecisionMessage)
        assert msg.extras["legacy_decision_id"] == 42
        assert "expected_impact" in msg.extras


class TestValidateForController:
    def test_ok(self) -> None:
        msg = DecisionMessage.from_dict(_base())
        assert isinstance(msg, DecisionMessage)
        now = 1_000_000
        res = msg.validate_for_controller(
            controller_intersection_id=7,
            last_accepted_decision_id=None,
            now_ns=now,
        )
        assert res.ok

    def test_intersection_mismatch(self) -> None:
        msg = DecisionMessage.from_dict(_base())
        assert isinstance(msg, DecisionMessage)
        res = msg.validate_for_controller(
            controller_intersection_id=99,
            last_accepted_decision_id=None,
            now_ns=1_000_000,
        )
        assert res.status is ValidationStatus.INTERSECTION_MISMATCH

    def test_non_monotonic_id(self) -> None:
        msg = DecisionMessage.from_dict(_base())
        assert isinstance(msg, DecisionMessage)
        res = msg.validate_for_controller(
            controller_intersection_id=7,
            last_accepted_decision_id=5,  # > our id (1)
            now_ns=1_000_000,
        )
        assert res.status is ValidationStatus.NON_MONOTONIC_ID

    def test_future_timestamp_beyond_skew(self) -> None:
        data = _base(now_ns=10_000_000_000)  # 10s producer ts
        msg = DecisionMessage.from_dict(data)
        assert isinstance(msg, DecisionMessage)
        res = msg.validate_for_controller(
            controller_intersection_id=7,
            last_accepted_decision_id=None,
            now_ns=1_000_000,  # consumer "now" much earlier
            clock_skew_tolerance_ns=500 * 1_000_000,
        )
        assert res.status is ValidationStatus.FUTURE_TIMESTAMP

    def test_expired(self) -> None:
        data = _base(now_ns=1_000_000)
        data["valid_until_ns"] = 2_000_000  # 1ms after producer
        msg = DecisionMessage.from_dict(data)
        assert isinstance(msg, DecisionMessage)
        res = msg.validate_for_controller(
            controller_intersection_id=7,
            last_accepted_decision_id=None,
            now_ns=3_000_000,  # past valid_until
        )
        assert res.status is ValidationStatus.EXPIRED

    def test_signature_required_but_missing(self) -> None:
        msg = DecisionMessage.from_dict(_base())
        assert isinstance(msg, DecisionMessage)
        res = msg.validate_for_controller(
            controller_intersection_id=7,
            last_accepted_decision_id=None,
            now_ns=1_000_000,
            signature_required=True,
            signature_verifier=None,
        )
        assert res.status is ValidationStatus.SIGNATURE_INVALID

    def test_signature_verifier_called(self) -> None:
        data = _base()
        data["signature"] = "abc"
        msg = DecisionMessage.from_dict(data)
        assert isinstance(msg, DecisionMessage)
        seen = {}

        def verify(m: DecisionMessage) -> bool:
            seen["called_with"] = m
            return True

        res = msg.validate_for_controller(
            controller_intersection_id=7,
            last_accepted_decision_id=None,
            now_ns=1_000_000,
            signature_required=True,
            signature_verifier=verify,
        )
        assert res.ok
        assert seen["called_with"] is msg
