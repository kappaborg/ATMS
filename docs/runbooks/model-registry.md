# Runbook: Model registry (MLflow)

**Audience:** ML engineer + traffic operator promoting models.
**Design:** [ADR-0015](../adr/0015-model-registry-mlflow.md).
**Code:** [`shared/atms_common/model_registry.py`](../../shared/atms_common/model_registry.py).

---

## 1. Lifecycle

```
None  →  Staging  →  Canary  →  Production  →  Archived
                ↘            ↘
                 Archived    Archived
```

| Stage | Who serves it | What gates the promotion forward |
|-------|---------------|----------------------------------|
| `None` | nobody | freshly registered, awaiting first eval |
| `Staging` | nightly eval suite | passes accuracy regression (D2) |
| `Canary` | 1 pilot intersection for 24h | drift + accuracy monitor clean (D2) |
| `Production` | all intersections (wave: 10% → 50% → 100%) | operator wave-promotion |
| `Archived` | nobody | retained 1 year per ADR-0014 |

Backwards transitions are restricted: `Canary → Staging` (re-eval) and `* → Archived` (decommission) only. `Production → Canary` is **not allowed** — to "demote" a Production model, archive it and promote a new Canary.

## 2. Register a new model version

Done by the training pipeline (not the operator):

```python
from shared.atms_common.model_registry import AtmsModelRegistry

reg = AtmsModelRegistry(tracking_uri="https://mlflow.atms.internal")
mv = reg.register(
    model_name="yolov8-detection",
    source_path="s3://atms-models/yolov8/run-42",
    run_id="run-42",
    description="2026-05-30 retrain on June labels, mAP 0.91",
)
print(f"Registered {mv.model_name}@{mv.version} (stage={mv.stage.value})")
```

Verify in the UI: `https://mlflow.atms.internal/#/models/yolov8-detection`.

## 3. Promote (operator action)

Operator must have a JWT with `engineer+` role; promotion to `Production` requires `admin`.

### To Staging

The training pipeline does this automatically after register. Manual override:

```bash
curl -X POST https://api.atms.internal/admin/model/promote \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -d '{"model_name":"yolov8-detection","version":"4","to_stage":"Staging"}'
```

(The api-gateway HTTP edge is a D1 follow-up PR; the client wrapper is available now.)

### To Canary
After D2 accuracy regression passes:

```bash
curl -X POST https://api.atms.internal/admin/model/promote \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -d '{"model_name":"yolov8-detection","version":"4","to_stage":"Canary",
       "justification":"REQ-1234: passed nightly eval, mAP +1.2pt vs prod"}'
```

The model is now served to **one** pilot intersection. Watch the drift + accuracy dashboard for 24h.

### To Production

After the 24h Canary soak with clean drift signals:

```bash
curl -X POST https://api.atms.internal/admin/model/promote \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"model_name":"yolov8-detection","version":"4","to_stage":"Production",
       "justification":"REQ-1234: 24h canary clean, advancing to prod wave"}'
```

The wave-out (10% → 50% → 100%) is operator-driven. Pause between waves for at least one full traffic cycle.

## 4. Rollback

```bash
# Roll back to the previously-Production version.
curl -X POST https://api.atms.internal/admin/model/promote \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"model_name":"yolov8-detection","version":"3","to_stage":"Production",
       "justification":"INC-5678: regression on intersection 7"}'

# Archive the bad version.
curl -X POST https://api.atms.internal/admin/model/promote \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"model_name":"yolov8-detection","version":"4","to_stage":"Archived",
       "justification":"INC-5678: rolled back"}'
```

Audit log (D4 + A6) captures every promotion with the operator's `sub` and `jti`.

## 5. Inspect

```python
versions = reg.list_versions("yolov8-detection")
for v in versions:
    print(f"  v{v.version}: {v.stage.value:<12} ({v.source})")
```

Or via the MLflow UI.

## 6. What this runbook does NOT cover

- **Serving** — the `ai-perception` service still loads `.pt` files at startup. Replacing that path with a registry-pull is a follow-up PR (ADR-0015 §Consequences). Until that PR lands, "promote to Production" updates the registry but does **not** swap the served model. Document this clearly in operator training.
- **D2 drift + accuracy monitors** — separate ADR + service.
- **Retraining pipeline (D3)** — separate ADR + Airflow / Kubeflow pipeline.
