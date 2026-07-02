# ADR-0015: Model registry — MLflow + promotion lifecycle

**Status:** Accepted
**Date:** 2026-05-30
**Closes (partial):** PRODUCTION_GAPS.md gap #15 (Phase D1 — registry portion; serving is a follow-up)

## Context

Audit gap #15: ATMS ships YOLOv8 + ByteTracker + license-plate + multiview models as **checked-in `.pt` binaries** under `models/` and `multiview_models/`. There is no registry, no versioning, no rollback story, no metric-gated promotion. Replacing `yolov8n.pt` = redeploy + pray.

D1 closes the registry side. Model **serving** (Triton / BentoML) requires a real GPU host and stays a follow-up.

## Decision

### Registry: MLflow Tracking + Model Registry

Selected from a short list:

| Option | Verdict | Why |
|--------|---------|-----|
| **MLflow (self-hosted)** | **Chosen** | OSS, no per-seat cost, simple Postgres + object-storage backend, well-documented promotion lifecycle |
| Weights & Biases | Rejected | Commercial; per-seat pricing scales badly for a municipal operator |
| Vertex AI / SageMaker | Rejected | Cloud-only; our deployment target is on-prem (ADR-0003) |
| DVC + plain Git LFS | Rejected | Tracks artefacts but no lifecycle / promotion / metrics dashboard |

### Promotion lifecycle

Every registered model goes through:

```
None → Staging → Canary → Production → Archived
```

- **Staging**: training pipeline registers a new version. Nightly accuracy regression suite (Phase D2) runs against a held-out labelled set.
- **Canary**: operator manually promotes a Staging model to Canary. Served to **1 intersection** for 24h. Drift + accuracy monitor watches; auto-rollback to Production on metric regression (Phase D2).
- **Production**: operator manually promotes Canary → Production after the 24h soak. Served to all intersections in waves (10% → 50% → 100%).
- **Archived**: any version no longer served. Retained 1 year for audit (per ADR-0014 audit retention).

Promotions are operator actions, JWT-gated by `engineer+` (admin+ for production promotion). Every promotion writes an `audit_log` row.

### Storage backend

- **Tracking DB**: Postgres (the same instance the application uses; separate schema `mlflow`).
- **Artefact store**: S3-compatible object store (MinIO on-prem, or whatever the operator's storage is). Models are stored at `s3://atms-models/<model_name>/<version>/`.
- **MLflow server**: deployed as a K8s Deployment in the `atms` namespace, behind the api-gateway with JWT auth (A6).

### Code-side: `shared/atms_common/model_registry.py`

A thin client wrapper around the `mlflow.client.MlflowClient`:

```python
class AtmsModelRegistry:
    def __init__(self, tracking_uri: str, *, auth_token_provider: Callable | None = None): ...

    def register(self, model_name: str, source_path: str, run_id: str, *, description: str = "") -> ModelVersion: ...
    def promote(self, model_name: str, version: str, to_stage: ModelStage, *, operator_sub: str, operator_jti: str) -> None: ...
    def get_uri(self, model_name: str, stage: ModelStage = ModelStage.PRODUCTION) -> str: ...
    def list_versions(self, model_name: str) -> list[ModelVersion]: ...
```

Properties:
- Failures wrap as `ModelRegistryError(AtmsError)`.
- Promotions are wrapped in a B4 `Retry` with breaker — MLflow REST is internal but still benefits from resilience.
- `promote()` validates stage transitions (`Staging → Canary → Production`; can't skip `Production → Canary`).
- Audit-log emission on every promotion (the operator's `principal_sub` / `principal_jti` propagated).

### What this ADR does NOT do

- **Model serving**: Triton / BentoML / direct in-perception loading. The current `ai-perception` service loads `.pt` files directly; replacing that path is a follow-up PR.
- **Automatic promotion based on metrics**: D2's drift / regression detection is the gate; D2 owns that surface.
- **Cross-team model sharing**: single-team operator for the pilot.

## Consequences

- New runtime dep: `mlflow-skinny` (client-only, no server in the pip install — server runs as its own pod).
- A new ADR or operational decision is needed to wire **serving**: either (a) replace `ai-perception`'s direct `.pt` load with a registry pull at startup, or (b) put a model server (Triton) in front. Picked separately when GPU node-pool is sized.
- Operators learn the MLflow UI for promotion. The runbook explains.
- `services/ai-perception` gains a `MODEL_REGISTRY_URI` env var that, when set, loads from the registry instead of the bundled `.pt`. Default unset = legacy behaviour during migration.
- Phase D2 plugs into the Staging → Canary gate via the nightly accuracy regression workflow.
