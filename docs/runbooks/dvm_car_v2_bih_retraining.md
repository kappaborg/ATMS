# Runbook: dvm_car_v2_bih — brand model retraining for Sarajevo pilot

**Audience:** ML engineer + KJP pilot ops lead.
**Status:** Recipe ready; execution triggers when ≥5000 BiH ground-truth crops collected.
**Companion:** [`dvm_car_v1` original](../adr/0020-vehicle-brand-perception.md), [`pilot-deployment.md`](../demos/bosnia-pilot-deployment.md).

## Trigger criteria

Run this retrain when ALL of:

- [ ] ≥ 5000 BiH ground-truth crops collected via `scripts/bosnia_ground_truth_pipeline.py extract`
- [ ] QC agreement rate ≥ 90% on multi-labelled subset
- [ ] ≥ 30 distinct brands represented (with ≥ 50 examples per brand for the top 15)
- [ ] Operator labelling distribution matches BiH fleet stats (BiH Federation
      Statistical Office 2024 reference) within ±5% per top-10 brand

## Pre-flight checklist

```bash
# Disk + RAM
df -h .         # ≥ 80 GB free expected
vm_stat | awk '/free/{f=$3} /inactive/{i=$3} END{print "RAM avail:", (f+i)*4096/1024/1024, "MB"}'

# Baseline preserved (compare against dvm_car_v1)
ls models/car_brand_classification/outputs/dvm_car_v1/weights/best.pt

# Ground truth dataset prepared
ls data/car_brand_dataset_bih/{data.yaml,train,valid,test}

# Pin device — Apple M1 Max via MPS
python3 -c "import torch; print('MPS:', torch.backends.mps.is_available())"

# No competing GPU workloads (MPS doesn't multi-tenant well)
ps aux | grep -E '(torch|tensorflow|cuda)' | grep -v grep
```

## The GO command

```bash
caffeinate -i &  # prevent idle sleep
echo $! > /tmp/caffeinate.pid

ATMS_DATASET_YAML=$(pwd)/data/car_brand_dataset_bih/data.yaml \
ATMS_RUN_NAME=dvm_car_v2_bih \
ATMS_TRAIN_EPOCHS=80 \
ATMS_TRAIN_PATIENCE=15 \
nohup python3 models/car_brand_classification/train_traffic_realistic.py \
    > /tmp/dvm-v2-bih-train.log 2>&1 &
echo $! > /tmp/dvm-v2-bih-train.pid
```

## Expected timeline

| Dataset size | Per-epoch (M1 Max MPS) | 80 epochs |
|---|---:|---:|
| 5,000 crops | ~6 min | ~8 h |
| 10,000 crops | ~12 min | ~16 h |
| 20,000 crops | ~24 min | ~32 h |

Patience=15 typically triggers early stop around epoch 50-60 once
mAP50-95 plateaus. Plan for **24-30 hour overnight run**.

## Monitor

```bash
tail -f /tmp/dvm-v2-bih-train.log

# Per-epoch metrics CSV
watch -n 60 tail -8 models/car_brand_classification/outputs/dvm_car_v2_bih/results.csv

# Current epoch from log
grep -oE 'Epoch [0-9]+/[0-9]+' /tmp/dvm-v2-bih-train.log | tail -1
```

## After training — acceptance gates

### Gate 1: Internal validation (must pass before A/B)

```bash
# Calibration (~5 min)
python3 models/car_brand_classification/calibrate.py dvm_car_v2_bih

# Acceptance criteria for dvm_car_v2_bih:
# - mAP50      ≥ 0.85 on BiH validation set (dvm_car_v1 was 0.872 on UK)
# - ECE        ≤ 0.03 after calibration (matches dvm_car_v1's 0.014-0.026)
# - per-brand precision ≥ 0.70 for the top 10 BiH brands
```

### Gate 2: Field validation against operator-labelled ground truth

```bash
python3 scripts/compute_field_metrics.py \
    --weights models/car_brand_classification/outputs/dvm_car_v2_bih/weights/best.pt \
    --out-tag dvm_car_v2_bih_field

# Acceptance:
# - Field precision  ≥ 70% (dvm_car_v1 on UK videos: 66.7%)
# - Field recall     ≥ 10% (dvm_car_v1: 2.2%; large improvement expected with BiH training)
# - F1               ≥ 0.15 (dvm_car_v1: 0.043)
```

### Gate 3: A/B comparison against dvm_car_v1

```bash
python3 models/car_brand_classification/compare_models.py \
    --baseline models/car_brand_classification/outputs/dvm_car_v1/weights/best.pt \
    --improved models/car_brand_classification/outputs/dvm_car_v2_bih/weights/best.pt \
    --videos $(ls recordings/sarajevo-*.mp4)
# Use the original UK videos AND new Sarajevo recordings.

# Acceptance: v2_bih wins on Sarajevo videos (more commits, higher conf)
#             v2_bih does NOT regress on UK videos (commits stay correct)
```

## Cutover steps (after all gates green)

1. **Pause** pilot operations chamber:
   ```bash
   sudo systemctl stop atms-chamber@sarajevo-marijindvor-001
   ```

2. **Backup** current weights:
   ```bash
   cp models/car_brand_classification/outputs/dvm_car_v1/weights/best.pt \
      models/car_brand_classification/outputs/dvm_car_v1/weights/best.pt.bak
   ```

3. **Point** the site config at the new weights:
   ```yaml
   # services/observability/sarajevo-pilot.yaml
   # (Add to the chamber subsection)
   brand_classification:
     weights_path: models/car_brand_classification/outputs/dvm_car_v2_bih/weights/best.pt
     conf_threshold: 0.50  # validate via calibration first
   ```

4. **Re-run acceptance tests:**
   ```bash
   python3 scripts/pilot_acceptance_tests.py \
       --site-config services/observability/sarajevo-pilot.yaml \
       --output-report /var/log/atms/post-v2bih-acceptance.md
   # ALL GREEN expected; FAIL → rollback to v1
   ```

5. **Restart** chamber with new weights:
   ```bash
   sudo systemctl start atms-chamber@sarajevo-marijindvor-001
   sudo systemctl status atms-chamber@sarajevo-marijindvor-001
   ```

6. **30-day shadow observation:**
   - Run with v1 PRIMARY + v2_bih as shadow via ABTestHarness
   - Watch divergence in Grafana panel #9
   - If divergence resolves in v2's favour, promote v2 → primary

## Rollback procedure

```bash
# If any post-cutover gate fails:
sudo systemctl stop atms-chamber@sarajevo-marijindvor-001

# Restore v1
mv models/car_brand_classification/outputs/dvm_car_v1/weights/best.pt.bak \
   models/car_brand_classification/outputs/dvm_car_v1/weights/best.pt
# Revert YAML edit
git checkout services/observability/sarajevo-pilot.yaml

sudo systemctl start atms-chamber@sarajevo-marijindvor-001
```

Audit log records every chamber decision; rollback doesn't lose forensic data.

## Open questions

- BiH dataset will likely be smaller than DVM-Car's 60k crops. May
  benefit from fine-tuning v1 weights rather than training from
  scratch — Phase 11 follow-up experiment.
- TSP routes (GRAS trolejbus) may need their OWN class since they're
  visually distinct (livery + trolley arms). Phase 12 candidate.
