"""
Model registry client — Phase D1 (ADR-0015).

Thin wrapper around the MLflow REST API for registration, promotion, and
lookup. Designed to be importable without MLflow installed — the actual
`mlflow.client.MlflowClient` is imported lazily inside the methods so unit
tests can mock the layer cleanly.

Promotion stage transitions are validated locally to provide useful errors
without a round-trip. Audit-log payloads are generated and surfaced to the
caller (the caller writes them through the service's audit logger).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from shared.atms_common.errors import AtmsError


class ModelRegistryError(AtmsError):
    """Raised by AtmsModelRegistry on misuse or upstream failure."""


class ModelStage(str, Enum):
    NONE = "None"
    STAGING = "Staging"
    CANARY = "Canary"
    PRODUCTION = "Production"
    ARCHIVED = "Archived"


# Allowed forward transitions per ADR-0015.
_ALLOWED_TRANSITIONS: dict[ModelStage, frozenset[ModelStage]] = {
    ModelStage.NONE: frozenset({ModelStage.STAGING}),
    ModelStage.STAGING: frozenset({ModelStage.CANARY, ModelStage.ARCHIVED}),
    ModelStage.CANARY: frozenset({ModelStage.PRODUCTION, ModelStage.STAGING, ModelStage.ARCHIVED}),
    ModelStage.PRODUCTION: frozenset({ModelStage.ARCHIVED}),
    ModelStage.ARCHIVED: frozenset({ModelStage.STAGING}),  # for re-evaluation
}


def _is_allowed(from_stage: ModelStage, to_stage: ModelStage) -> bool:
    if from_stage is to_stage:
        return False
    return to_stage in _ALLOWED_TRANSITIONS.get(from_stage, frozenset())


@dataclass(frozen=True)
class ModelVersion:
    model_name: str
    version: str
    stage: ModelStage
    source: str
    run_id: str | None
    description: str = ""

    @staticmethod
    def from_mlflow(mv: Any) -> ModelVersion:
        """Map an `mlflow.entities.model_registry.ModelVersion` to ours.

        Accepts `Any` because we import MLflow lazily; the field shapes are
        stable across versions.
        """
        try:
            stage = ModelStage(mv.current_stage)
        except (ValueError, AttributeError):
            stage = ModelStage.NONE
        return ModelVersion(
            model_name=getattr(mv, "name", ""),
            version=str(getattr(mv, "version", "")),
            stage=stage,
            source=getattr(mv, "source", ""),
            run_id=getattr(mv, "run_id", None),
            description=getattr(mv, "description", "") or "",
        )


@dataclass(frozen=True)
class PromotionAudit:
    """Audit payload for a promotion. Caller passes to its audit logger."""

    event: str
    model_name: str
    version: str
    from_stage: str
    to_stage: str
    operator_sub: str
    operator_jti: str
    at_iso: str

    def to_dict(self) -> dict[str, str]:
        return {
            "event": self.event,
            "model_name": self.model_name,
            "version": self.version,
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "operator_sub": self.operator_sub,
            "operator_jti": self.operator_jti,
            "at": self.at_iso,
        }


class AtmsModelRegistry:
    """MLflow Model Registry client wrapper."""

    def __init__(
        self,
        *,
        tracking_uri: str,
        auth_token_provider: Callable[[], str] | None = None,
    ) -> None:
        self._tracking_uri = tracking_uri
        self._auth_token_provider = auth_token_provider
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from mlflow.tracking import MlflowClient  # noqa: PLC0415
        except ImportError as e:
            raise ModelRegistryError(
                "mlflow-skinny is not installed; add `mlflow-skinny>=2.10` to requirements."
            ) from e
        self._client = MlflowClient(tracking_uri=self._tracking_uri)
        return self._client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(
        self,
        *,
        model_name: str,
        source_path: str,
        run_id: str,
        description: str = "",
    ) -> ModelVersion:
        """Register a new model version. New versions land in `Staging` next."""
        client = self._get_client()
        try:
            mv = client.create_model_version(
                name=model_name,
                source=source_path,
                run_id=run_id,
                description=description,
            )
        except Exception as e:
            raise ModelRegistryError(f"register failed: {e}") from e
        return ModelVersion.from_mlflow(mv)

    def list_versions(self, model_name: str) -> list[ModelVersion]:
        client = self._get_client()
        try:
            mvs = client.search_model_versions(f"name='{model_name}'")
        except Exception as e:
            raise ModelRegistryError(f"list_versions failed: {e}") from e
        return [ModelVersion.from_mlflow(mv) for mv in mvs]

    def get_uri(self, model_name: str, stage: ModelStage = ModelStage.PRODUCTION) -> str:
        """Return a URI suitable for a model loader (e.g., `models:/foo/Production`)."""
        return f"models:/{model_name}/{stage.value}"

    def promote(
        self,
        *,
        model_name: str,
        version: str,
        to_stage: ModelStage,
        operator_sub: str,
        operator_jti: str = "",
        archive_existing: bool = True,
    ) -> PromotionAudit:
        """Move a model version to `to_stage`. Validates the transition.

        Returns a `PromotionAudit` the caller writes through its audit logger.
        """
        client = self._get_client()
        # Look up current stage to validate the transition.
        try:
            current = client.get_model_version(name=model_name, version=version)
        except Exception as e:
            raise ModelRegistryError(
                f"get_model_version({model_name}@{version}) failed: {e}"
            ) from e
        from_stage = ModelStage(current.current_stage) if current.current_stage else ModelStage.NONE
        if not _is_allowed(from_stage, to_stage):
            raise ModelRegistryError(
                f"transition refused: {model_name}@{version} {from_stage.value} → {to_stage.value} "
                f"not in allowed set {sorted(s.value for s in _ALLOWED_TRANSITIONS.get(from_stage, set()))}"
            )
        # Production promotions require the higher role at the HTTP edge —
        # this client doesn't check JWT; the api-gateway does. We accept the
        # operator identity here purely for audit.
        if not operator_sub:
            raise ModelRegistryError("operator_sub is required for promotion audit")
        try:
            client.transition_model_version_stage(
                name=model_name,
                version=version,
                stage=to_stage.value,
                archive_existing_versions=archive_existing,
            )
        except Exception as e:
            raise ModelRegistryError(
                f"transition failed: {model_name}@{version} → {to_stage.value}: {e}"
            ) from e
        return PromotionAudit(
            event="model_promotion",
            model_name=model_name,
            version=str(version),
            from_stage=from_stage.value,
            to_stage=to_stage.value,
            operator_sub=operator_sub,
            operator_jti=operator_jti,
            at_iso=datetime.now(tz=UTC).isoformat(),  # noqa: ATMS-CLOCK  audit display
        )
