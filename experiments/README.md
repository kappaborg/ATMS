## Experiments

This folder contains **reproducible, offline experiment runs** for ATMS.

### Directory layout

- `experiments/configs/`: versionable run configs (JSON)
- `experiments/results/`: generated outputs (CSV/JSON) — do not hand-edit

### Conventions

- **Determinism**: prefer `ATMS_RUN_MODE=experiment` and keep Kafka disabled.
- **Config-first**: all parameters must live in a config file (not hard-coded).
- **One run = one folder** under `experiments/results/<run_id>/` containing:
  - `config.json` (the exact config used)
  - `detections.csv` (per-object per-frame outputs)
  - `summary.json` (aggregate metrics + run metadata)

### Quickstart (speed + emissions)

Run evaluation on a local video:

```bash
ATMS_RUN_MODE=experiment ATMS_ENABLE_KAFKA=false \
python3 scripts/eval_speed_and_emissions.py \
  --config experiments/configs/speed_emissions_baseline.json \
  --video /path/to/video.mp4
```

