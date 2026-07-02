"""Unit tests for shared/atms_common/model_registry.py (Phase D1)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from shared.atms_common.model_registry import (
    AtmsModelRegistry,
    ModelRegistryError,
    ModelStage,
    ModelVersion,
    _is_allowed,
)


@dataclass
class _FakeMlflowVersion:
    """Stand-in for mlflow.entities.model_registry.ModelVersion."""

    name: str
    version: str
    current_stage: str
    source: str = "s3://atms-models/foo/1"
    run_id: str = "run-1"
    description: str = ""


# ---------------------------------------------------------------------------
# Stage transitions
# ---------------------------------------------------------------------------


class TestStageTransitions:
    @pytest.mark.parametrize(
        ("from_s", "to_s", "ok"),
        [
            (ModelStage.NONE, ModelStage.STAGING, True),
            (ModelStage.STAGING, ModelStage.CANARY, True),
            (ModelStage.CANARY, ModelStage.PRODUCTION, True),
            (ModelStage.CANARY, ModelStage.STAGING, True),
            (ModelStage.PRODUCTION, ModelStage.ARCHIVED, True),
            (ModelStage.ARCHIVED, ModelStage.STAGING, True),
            # Disallowed
            (ModelStage.STAGING, ModelStage.PRODUCTION, False),  # skip Canary
            (ModelStage.NONE, ModelStage.PRODUCTION, False),
            (ModelStage.PRODUCTION, ModelStage.CANARY, False),    # no backwards
            (ModelStage.STAGING, ModelStage.STAGING, False),      # no self
        ],
    )
    def test_transition_matrix(self, from_s, to_s, ok):
        assert _is_allowed(from_s, to_s) is ok


# ---------------------------------------------------------------------------
# ModelVersion.from_mlflow
# ---------------------------------------------------------------------------


class TestModelVersionFromMlflow:
    def test_normal(self):
        mv = _FakeMlflowVersion(name="yolov8", version="3", current_stage="Production")
        out = ModelVersion.from_mlflow(mv)
        assert out.model_name == "yolov8"
        assert out.version == "3"
        assert out.stage is ModelStage.PRODUCTION
        assert out.source == "s3://atms-models/foo/1"

    def test_unknown_stage_defaults_to_none(self):
        mv = _FakeMlflowVersion(name="x", version="1", current_stage="Quarantine")
        out = ModelVersion.from_mlflow(mv)
        assert out.stage is ModelStage.NONE


# ---------------------------------------------------------------------------
# AtmsModelRegistry — mocked MLflow client
# ---------------------------------------------------------------------------


def _registry_with_mock_client():
    """Build a registry whose client is a MagicMock — no real MLflow needed."""
    reg = AtmsModelRegistry(tracking_uri="http://mlflow:5000")
    mock_client = MagicMock()
    reg._client = mock_client  # noqa: SLF001  — test-only injection
    return reg, mock_client


class TestRegistry:
    def test_get_uri(self):
        reg, _ = _registry_with_mock_client()
        assert reg.get_uri("yolov8") == "models:/yolov8/Production"
        assert reg.get_uri("yolov8", ModelStage.STAGING) == "models:/yolov8/Staging"

    def test_register_returns_version(self):
        reg, client = _registry_with_mock_client()
        client.create_model_version.return_value = _FakeMlflowVersion(
            name="yolov8", version="4", current_stage="None"
        )
        out = reg.register(
            model_name="yolov8",
            source_path="s3://atms-models/yolov8/4",
            run_id="run-42",
            description="nightly retrain",
        )
        assert out.version == "4"
        client.create_model_version.assert_called_once()

    def test_register_wraps_upstream_error(self):
        reg, client = _registry_with_mock_client()
        client.create_model_version.side_effect = RuntimeError("upstream down")
        with pytest.raises(ModelRegistryError, match="register failed"):
            reg.register(
                model_name="x", source_path="s", run_id="r", description=""
            )

    def test_list_versions(self):
        reg, client = _registry_with_mock_client()
        client.search_model_versions.return_value = [
            _FakeMlflowVersion(name="yolov8", version="1", current_stage="Archived"),
            _FakeMlflowVersion(name="yolov8", version="2", current_stage="Production"),
        ]
        out = reg.list_versions("yolov8")
        assert len(out) == 2
        assert {mv.stage for mv in out} == {ModelStage.ARCHIVED, ModelStage.PRODUCTION}

    def test_promote_happy_path(self):
        reg, client = _registry_with_mock_client()
        client.get_model_version.return_value = _FakeMlflowVersion(
            name="yolov8", version="3", current_stage="Staging"
        )
        audit = reg.promote(
            model_name="yolov8",
            version="3",
            to_stage=ModelStage.CANARY,
            operator_sub="alice",
            operator_jti="jti-1",
        )
        client.transition_model_version_stage.assert_called_once()
        assert audit.from_stage == "Staging"
        assert audit.to_stage == "Canary"
        assert audit.operator_sub == "alice"
        assert audit.event == "model_promotion"

    def test_promote_invalid_transition_refused(self):
        reg, client = _registry_with_mock_client()
        client.get_model_version.return_value = _FakeMlflowVersion(
            name="yolov8", version="3", current_stage="Staging"
        )
        # Skip Canary — should fail.
        with pytest.raises(ModelRegistryError, match="transition refused"):
            reg.promote(
                model_name="yolov8",
                version="3",
                to_stage=ModelStage.PRODUCTION,
                operator_sub="alice",
            )
        # Stage transition was NOT called on MLflow.
        client.transition_model_version_stage.assert_not_called()

    def test_promote_requires_operator_sub(self):
        reg, client = _registry_with_mock_client()
        client.get_model_version.return_value = _FakeMlflowVersion(
            name="yolov8", version="3", current_stage="Staging"
        )
        with pytest.raises(ModelRegistryError, match="operator_sub"):
            reg.promote(
                model_name="yolov8",
                version="3",
                to_stage=ModelStage.CANARY,
                operator_sub="",
            )

    def test_promote_wraps_upstream_failure(self):
        reg, client = _registry_with_mock_client()
        client.get_model_version.return_value = _FakeMlflowVersion(
            name="yolov8", version="3", current_stage="Staging"
        )
        client.transition_model_version_stage.side_effect = RuntimeError("timeout")
        with pytest.raises(ModelRegistryError, match="transition failed"):
            reg.promote(
                model_name="yolov8",
                version="3",
                to_stage=ModelStage.CANARY,
                operator_sub="alice",
            )

    def test_audit_serialises(self):
        reg, client = _registry_with_mock_client()
        client.get_model_version.return_value = _FakeMlflowVersion(
            name="yolov8", version="3", current_stage="Canary"
        )
        audit = reg.promote(
            model_name="yolov8",
            version="3",
            to_stage=ModelStage.PRODUCTION,
            operator_sub="alice",
            operator_jti="jti-1",
        )
        d = audit.to_dict()
        assert d["event"] == "model_promotion"
        assert d["from_stage"] == "Canary"
        assert d["to_stage"] == "Production"
        assert "at" in d
