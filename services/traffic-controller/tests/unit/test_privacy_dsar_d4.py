"""
Tests for shared/atms_common/{privacy,dsar}.py (Phase D4).
"""

from __future__ import annotations

import os

import pytest

from shared.atms_common.dsar import (
    DSARAction,
    DSAR_LINKED_TABLES,
    DSARError,
    DSARProcessor,
    DSARRequest,
    DSARStatus,
    InMemoryDSARStorage,
)
from shared.atms_common.privacy import (
    AnonymizationEvent,
    PlateAnonymizer,
    PrivacyError,
    RetentionProfile,
    all_data_types,
    retention_horizon_for,
)


# ---------------------------------------------------------------------------
# PlateAnonymizer
# ---------------------------------------------------------------------------


class TestPlateAnonymizer:
    def test_deterministic(self):
        a = PlateAnonymizer(salt=os.urandom(32))
        assert a.subject_id_for("AB-12-CD") == a.subject_id_for("AB-12-CD")

    def test_normalisation_collapses_format(self):
        a = PlateAnonymizer(salt=os.urandom(32))
        assert a.subject_id_for("AB12CD") == a.subject_id_for("AB-12-CD")
        assert a.subject_id_for("ab12cd") == a.subject_id_for("AB12CD")
        assert a.subject_id_for(" AB 12 CD ") == a.subject_id_for("AB12CD")

    def test_different_salt_different_id(self):
        a = PlateAnonymizer(salt=b"x" * 32)
        b = PlateAnonymizer(salt=b"y" * 32)
        assert a.subject_id_for("AB12CD") != b.subject_id_for("AB12CD")

    def test_short_salt_rejected(self):
        with pytest.raises(PrivacyError, match=">=.*16"):
            PlateAnonymizer(salt=b"short")

    def test_empty_salt_rejected(self):
        with pytest.raises(PrivacyError, match="non-empty"):
            PlateAnonymizer(salt=b"")

    def test_empty_plate_rejected(self):
        a = PlateAnonymizer(salt=os.urandom(32))
        with pytest.raises(PrivacyError, match="empty"):
            a.subject_id_for("")

    def test_batch(self):
        a = PlateAnonymizer(salt=os.urandom(32))
        ids = a.subject_ids_for(["AB12CD", "EF34GH"])
        assert len(ids) == 2
        assert ids[0] != ids[1]


# ---------------------------------------------------------------------------
# Retention table
# ---------------------------------------------------------------------------


class TestRetention:
    def test_every_type_has_every_profile(self):
        for t in all_data_types():
            for p in RetentionProfile:
                assert retention_horizon_for(t, p) > 0, (
                    f"missing retention for {t}/{p}"
                )

    def test_unknown_type_raises(self):
        with pytest.raises(PrivacyError, match="unknown data_type"):
            retention_horizon_for("nonsense")

    def test_unknown_profile_raises(self):
        with pytest.raises(PrivacyError, match="unknown retention profile"):
            retention_horizon_for("traffic_detections", "production")

    def test_prod_raw_video_capped(self):
        """ADR-0014 §3: raw frames retention capped at 7 days in prod."""
        assert retention_horizon_for("raw_video_frames", RetentionProfile.PROD) == 168

    def test_audit_log_has_legal_floor(self):
        """ADR-0014 §3 / GDPR audit retention >= 365 days."""
        for p in RetentionProfile:
            assert retention_horizon_for("audit_log", p) >= 8760


# ---------------------------------------------------------------------------
# AnonymizationEvent
# ---------------------------------------------------------------------------


class TestAnonymizationEvent:
    def test_default_mode(self):
        e = AnonymizationEvent(subject_id_hash="abc", source_service="ai-perception")
        d = e.to_dict()
        assert d["mode"] == "anonymized"
        assert d["operator_sub"] == ""

    def test_warranted_mode_serialises(self):
        e = AnonymizationEvent(
            subject_id_hash="abc",
            source_service="api-gateway",
            mode="warranted",
            operator_sub="alice",
            operator_jti="jti-1",
            justification="warrant #INC-1234",
        )
        d = e.to_dict()
        assert d["mode"] == "warranted"
        assert d["operator_sub"] == "alice"


# ---------------------------------------------------------------------------
# DSARRequest factory
# ---------------------------------------------------------------------------


class TestDSARRequest:
    def test_new_assigns_uuid(self):
        r = DSARRequest.new(
            subject_id_hash="abc",
            action=DSARAction.ACCESS,
            operator_sub="alice",
            operator_jti="jti-1",
        )
        assert r.request_id  # non-empty
        assert len(r.request_id) == 36  # uuid4

    def test_accepts_str_action(self):
        r = DSARRequest.new(
            subject_id_hash="abc",
            action="erase",
            operator_sub="alice",
            operator_jti="jti-1",
        )
        assert r.action is DSARAction.ERASE

    def test_unknown_action_rejected(self):
        with pytest.raises(DSARError, match="unknown DSAR action"):
            DSARRequest.new(
                subject_id_hash="abc",
                action="oblivion",
                operator_sub="alice",
                operator_jti="jti-1",
            )

    def test_missing_subject_rejected(self):
        with pytest.raises(DSARError, match="subject_id_hash"):
            DSARRequest.new(
                subject_id_hash="",
                action=DSARAction.ACCESS,
                operator_sub="alice",
                operator_jti="jti-1",
            )

    def test_missing_operator_rejected(self):
        """ADR-0014 §2 — every DSAR audit row needs the operator's principal."""
        with pytest.raises(DSARError, match="operator_sub"):
            DSARRequest.new(
                subject_id_hash="abc",
                action=DSARAction.ACCESS,
                operator_sub="",
                operator_jti="jti-1",
            )

    def test_default_tables_match_constant(self):
        r = DSARRequest.new(
            subject_id_hash="abc",
            action=DSARAction.ACCESS,
            operator_sub="alice",
            operator_jti="jti-1",
        )
        assert r.tables == DSAR_LINKED_TABLES


# ---------------------------------------------------------------------------
# DSARProcessor with in-memory storage
# ---------------------------------------------------------------------------


class TestDSARProcessor:
    async def test_access_returns_matching_rows(self):
        storage = InMemoryDSARStorage()
        storage.seed(
            "traffic_detections",
            [
                {"subject_id": "sub-1", "intersection_id": 1, "ts": 100},
                {"subject_id": "sub-1", "intersection_id": 2, "ts": 200},
                {"subject_id": "sub-2", "intersection_id": 1, "ts": 150},
            ],
        )
        processor = DSARProcessor(storage)
        req = DSARRequest.new(
            subject_id_hash="sub-1",
            action=DSARAction.ACCESS,
            operator_sub="alice",
            operator_jti="jti",
        )
        result = await processor.handle(req)
        assert result.status is DSARStatus.COMPLETED
        assert result.rows_affected["traffic_detections"] == 2
        assert len(result.payload) == 2
        # Storage recorded the request + completion.
        assert storage.requests[0].request_id == req.request_id
        assert storage.completions[0].request_id == req.request_id

    async def test_erase_removes_only_matching_subject(self):
        storage = InMemoryDSARStorage()
        storage.seed(
            "traffic_detections",
            [
                {"subject_id": "sub-1", "intersection_id": 1},
                {"subject_id": "sub-2", "intersection_id": 1},
            ],
        )
        processor = DSARProcessor(storage)
        req = DSARRequest.new(
            subject_id_hash="sub-1",
            action=DSARAction.ERASE,
            operator_sub="alice",
            operator_jti="jti",
        )
        result = await processor.handle(req)
        assert result.rows_affected["traffic_detections"] == 1
        remaining = storage.rows["traffic_detections"]
        assert len(remaining) == 1
        assert remaining[0]["subject_id"] == "sub-2"

    async def test_export_same_data_as_access(self):
        storage = InMemoryDSARStorage()
        storage.seed("traffic_detections", [{"subject_id": "sub-1"}])
        processor = DSARProcessor(storage)
        access = await processor.handle(
            DSARRequest.new(
                subject_id_hash="sub-1",
                action=DSARAction.ACCESS,
                operator_sub="x",
                operator_jti="y",
            )
        )
        export = await processor.handle(
            DSARRequest.new(
                subject_id_hash="sub-1",
                action=DSARAction.EXPORT,
                operator_sub="x",
                operator_jti="y",
            )
        )
        assert access.payload == export.payload

    async def test_result_serialises(self):
        storage = InMemoryDSARStorage()
        processor = DSARProcessor(storage)
        req = DSARRequest.new(
            subject_id_hash="sub-1",
            action=DSARAction.ACCESS,
            operator_sub="x",
            operator_jti="y",
        )
        result = await processor.handle(req)
        d = result.to_dict()
        assert d["request_id"] == result.request_id
        assert d["status"] == "completed"
