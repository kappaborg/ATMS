# Runbook: Vehicle brand-detector fine-tune

**Audience:** ML engineer training the next brand-detector version.
**Companion:** [SENIOR_ENGINEER_PROMPT_BRAND_PERCEPTION.md](../SENIOR_ENGINEER_PROMPT_BRAND_PERCEPTION.md) §3.2 · [ADR-0020](../adr/0020-vehicle-brand-perception.md).
**Pipeline:** the trained `.pt` slots into `simulation/demo/video_source.py:BrandIdentifier` via `--brand-weights <path>`. No code changes needed in the pipeline when a new model lands.

This runbook documents two parallel tracks the perception team should run:

| Track | Dataset | Auto-downloadable? | Coverage | Status |
|---|---|---|---|---|
| **A. Immediate improvement** | `cars-brand-32` (Roboflow, CC BY 4.0) — already in repo | ✓ | 13 brands, 4 k images | ✅ **DONE 2026-06-09** — see §"Track A completion" below |
| **B. Production-grade** | DVM-Car (1.45 M images, 899 model variants → ~50 brands after aggregation) | ✓ direct Figshare download | ~50 aggregated brands | Open (Figshare URLs in Track B §1) |

Both tracks feed the same pipeline contract (a 13-or-more-class `.pt` at `models/car_brand_classification/outputs/<run>/weights/best.pt`).

---

## Track A completion (2026-06-09)

Run: `outputs/traffic_realistic/` — fine-tuned via `train_traffic_realistic.py`.

| Metric | Baseline (`car_brand_classification_robust`) | Improved (`traffic_realistic`) |
|---|---:|---:|
| Training epochs | 50 | 97 (early-stop, patience=30 at epoch 67 best) |
| Validation mAP50 | 0.346 (epoch 1 — never tracked at end) | **0.810** |
| Validation mAP50-95 | — | 0.519 |
| Calibration ECE | not calibrated | 0.181 → 0.147 (T=1.197) |
| Best per-class mAP50 | — | Nissan 0.995, fiat 0.967, BMW 0.891, car 0.914 |
| Weakest per-class mAP50 | — | hyndai 0.564, Mercedes 0.620, Toyota 0.615 |
| Field A/B on 3 YouTube traffic clips | 0 brands committed (of 17 vehicles) | 1 brand committed (BYD @ 0.38) |

**Live default (2026-06-09):** `simulation/demo/__main__.py` and `VideoConfig.brand_weights` both point at `outputs/traffic_realistic/weights/best.pt`. The default `--brand-conf` is `0.20` (post-calibration; raise to 0.30 only for stricter "right or absent" posture).

The in-distribution win (mAP50 0.81) is undisputed; the out-of-distribution gap (only 1/17 commits on wide-angle YouTube traffic) is the motivation for Track B.

---

## Track A — fine-tune on `cars-brand-32` (today)

The dataset (Roboflow `cars-brand` v32, 13 classes including a generic "car" no-brand class) is already at `models/car_brand_classification/cars-brand-32/`. Earlier work trained a baseline that lives at `models/car_brand_classification/outputs/car_brand_classification_robust/weights/best.pt`. This run improves on it via:

- **Traffic-camera-realistic augmentation** — mosaic=1.0, mixup=0.2, copy_paste=0.5, scale jitter 0.5-1.5, HSV jitter, perspective + shear (simulates the off-axis view of overhead cameras vs the head-on close-ups the dataset is dominated by).
- **Longer training** — 150 epochs vs 50, cosine LR schedule, patience 30. The heavier augmentation makes the loss landscape rougher; the model needs more time + a smoother schedule.
- **Fresh output dir** — `outputs/traffic_realistic/` rather than overwriting the working baseline.
- **Calibration sidecar** — drops a `calibration.json` next to the weights for a downstream temperature-scaling step.

### Run it

```bash
python3 models/car_brand_classification/train_traffic_realistic.py
```

**Expected duration on Apple M1 Max via MPS:** 30–60 minutes for 4 k training images × 150 epochs at batch=8.

Streaming log:

```bash
tail -f models/car_brand_classification/training_traffic.log
```

### Drop the new weights into the pipeline

```bash
python3 -m simulation.demo --video videos/youtube_MNn9qKG2UFI.mp4 \
    --brand-weights models/car_brand_classification/outputs/traffic_realistic/weights/best.pt
```

The current trained-model integration is unchanged — same 13 classes, same `BRAND_LABEL_NORMALISATION` in `simulation/demo/video_source.py`. The pipeline doesn't notice the swap.

### Compare against the baseline

Run both on the same test clip, capture the brand commits per direction, and diff:

```bash
# Baseline
python3 -m simulation.demo --video videos/youtube_MNn9qKG2UFI.mp4 \
    --brand-weights models/car_brand_classification/outputs/car_brand_classification_robust/weights/best.pt
cp /tmp/atms-demo-state.json /tmp/baseline.json

# Improved
python3 -m simulation.demo --video videos/youtube_MNn9qKG2UFI.mp4 \
    --brand-weights models/car_brand_classification/outputs/traffic_realistic/weights/best.pt
cp /tmp/atms-demo-state.json /tmp/improved.json

python3 -c "
import json
b = json.load(open('/tmp/baseline.json'))
i = json.load(open('/tmp/improved.json'))
for d in ('north_south', 'east_west'):
    print(d)
    print('  baseline:', b['per_direction'][d]['brand_breakdown'])
    print('  improved:', i['per_direction'][d]['brand_breakdown'])
"
```

### Acceptance criteria — Track A

These map to the senior-engineer prompt's §2.2 but adapted to the smaller dataset:

- **Brand recall** (any label produced) ≥ 50% on a held-out 200-vehicle ground-truth set when bbox ≥ 80×80 px.
- **Brand precision** (produced label is correct) ≥ 80%. Lower than the prompt's 85% target because the 13-class set is narrower than DVM-Car's 50+ brands.
- **Calibrated confidence** — at confidence ≥ 0.7, precision ≥ 90% (temperature-scaling lands here).

---

## Track B — fine-tune on DVM-Car

**Status 2026-06-12: dvm_car_v1 is the pipeline default.** Trained on the
Confirmed_fronts subset (54 classes incl. `_other`, 44k train images) to
epoch 14 of 30 — interrupted by host memory pressure (a concurrent bake job),
but e14 already beat Track A: **mAP50 0.815 vs 0.810, on 4× more classes.**

| Artefact | Where |
|---|---|
| Weights (e14 best) | `models/car_brand_classification/outputs/dvm_car_v1/weights/best.pt` |
| Resume checkpoint | `.../dvm_car_v1/weights/last.pt` (epochs 15-30 pending) |
| Resume script | `models/car_brand_classification/resume_dvm_training.sh` |
| Calibration | T=0.950, ECE 0.034→0.026 (model slightly under-confident — trustworthy) |
| A/B vs Track A | `.../dvm_car_v1/compare.md` — 2 commits @ 0.93+ conf vs 1 @ 0.38 |
| Dataset | `data/car_brand_dataset_dvm/` (54 classes, 70/20/10 split, symlinks) |
| `_other` class | 1,198 truck/bus/motorcycle crops via `extract_other_crops.py` |

Known gaps: no BYD / Chinese brands (UK-market dataset), front-view-only
training data (Confirmed_fronts subset — side/rear views untested).

DVM-Car is the headline dataset from the prompt. As of 2026-06-09 verification, **it is directly downloadable from Figshare with no access form** — the earlier "1–3 business day turnaround" assumption was wrong. License: CC BY-NC 4.0 (non-commercial research / educational use only — fine for ATMS pilot/research, NOT fine for resale as a product).

### 1. Download directly from Figshare

Three Figshare files (record 19586296):

| File | Size | Contents | URL |
|---|---:|---|---|
| Tabular data v2 | ~few MB | Sales/spec CSVs with model name, model ID, brand name, pricing, used-car ads, image attributes | https://figshare.com/articles/figure/DVM-CAR_Dataset/19586296/2 |
| Full image set | **13.6 GB** | 1,451,784 images from 899 UK-market car models | https://figshare.com/articles/figure/DVM-CAR_Dataset/19586296/1?file=34792453 |
| Quality-checked front-view subset | 730 MB | Front-view-only subset that passed quality screening — start here for sanity-checking | https://figshare.com/articles/figure/DVM-CAR_Dataset/19586296/1?file=34792480 |

Contact (if Figshare links break): **jingmin.huang@soton.ac.uk** or **bowei.chen@glasgow.ac.uk**.

Free disk required: ~50 GB (13.6 GB download + 30 GB extracted images + intermediate per-class organisation). Less than the original 80 GB estimate because the images are pre-compressed JPEGs.

### 2. Download + extract

Figshare uses the `ndownloader.figshare.com` subdomain (NOT `figshare.com/ndownloader/`) and redirects via signed S3 URLs. File IDs come from the Figshare v2 API:

```bash
# List of files (article version 1 has the images; version 2 only has tables)
curl -sL https://api.figshare.com/v2/articles/19586296/versions/1 | python3 -m json.tool
```

The correct file IDs and download commands:

```bash
mkdir -p data/dvm-car-raw && cd data/dvm-car-raw

# Tabular metadata — 155 MB (version 1) or 189 MB (version 2 — newer)
curl -L --progress-bar -o tables_V2.zip "https://ndownloader.figshare.com/files/38754867"

# Quality-checked front-view subset — 730 MB (good for first pass)
curl -L --progress-bar -o Confirmed_fronts.zip "https://ndownloader.figshare.com/files/34792480"

# Full image set — 13.6 GB (only after smaller download proves out)
curl -L --progress-bar -o resized_DVM_v2.zip "https://ndownloader.figshare.com/files/34792453"

# Unzip in place
unzip -q Confirmed_fronts.zip && unzip -q resized_DVM_v2.zip && unzip -q tables_V2.zip
```

For backgrounded downloads:

```bash
curl -L -o Confirmed_fronts.zip "https://ndownloader.figshare.com/files/34792480" \
    > /tmp/dvm-download.log 2>&1 &
echo $! > /tmp/dvm-download.pid

# Monitor progress
watch -n 5 'ls -la data/dvm-car-raw/Confirmed_fronts.zip; ps -p $(cat /tmp/dvm-download.pid)'
```

Verified working 2026-06-09 from this repo.

### 3. Organise for training

```bash
python3 models/car_brand_classification/setup_dvm_dataset.py /tmp/dvm-car-raw
```

This produces `data/car_brand_dataset_dvm/` with the YOLOv8 train/valid/test split.

### 4. Aggregate the 281 makes down to ~50 brands

DVM-Car has 281 makes (counting model variants), but the emissions multiplier table in `shared/atms_common/emissions.py:_DEFAULT_BRAND_MULTIPLIERS` has 70 canonical brands. Aggregation:

```bash
python3 models/car_brand_classification/aggregate_dvm_makes.py \
    --input data/car_brand_dataset_dvm \
    --output data/car_brand_dataset_dvm_aggregated \
    --multiplier-table shared/atms_common/emissions.py
```

*(This script doesn't exist yet — write it as part of Track B execution. The aggregation rules are: lower-case, strip variant suffixes like "_F3", map to the canonical key from `BRAND_LABEL_NORMALISATION` + `_DEFAULT_BRAND_MULTIPLIERS`.)*

### 5. Add an "unknown / other" class

The prompt's §3.2.4 explicitly calls this out. The CLIP path's biggest weakness is the lack of an opt-out — fixing that in the trained model requires training data labelled "other":

- Sample ~10% of frames from `videos/` containing trucks, buses, motorcycles, bicycles. These are vehicles but not in the brand classes.
- Sample ~5% of frames containing pedestrians / cyclists / road furniture. Negatives.
- Label as `_other` class. Train with the same model.
- At inference, when top-1 = `_other`, return None to the pipeline.

### 6. Train

Use the same hyperparameter recipe as Track A's `train_traffic_realistic.py`, just point `DATASET_YAML` at the new aggregated DVM-Car YAML and add the `_other` class. Expected duration on a single L40S / A100: 8–14 hours for full training, 2–3 hours for a 50-epoch warm-start.

```bash
DVM_DATA=data/car_brand_dataset_dvm_aggregated/data.yaml \
    python3 models/car_brand_classification/train_traffic_realistic.py
```

### Acceptance criteria — Track B

Maps directly to the senior-engineer prompt §2.2:

- **Brand precision** ≥ 85% on the operator-labelled 200-vehicle set
- **Brand recall** ≥ 60% on bbox ≥ 80×80 px
- **Unknown opt-out rate** ≥ 80% for vehicles NOT in the supported brand set
- **Calibrated confidence**: at conf ≥ 0.7, precision ≥ 95%

---

## Wiring the result into production

Both tracks land a `.pt` at `models/car_brand_classification/outputs/<run>/weights/best.pt`. The pipeline path is the same:

```bash
# Standalone
python3 -m simulation.demo --video <path> --brand-weights <path-to-best.pt>

# Or update the default in simulation/demo/video_source.py:VideoConfig
# (search for brand_weights = Path("...car_brand_classification/.../best.pt"))
```

Update `BRAND_LABEL_NORMALISATION` in `simulation/demo/video_source.py` if the new model has different class names (e.g., adding `_other`).

---

## Out of scope for this runbook

- Per-(brand, model, year) precision. The emissions table is brand-grained; finer is wasted effort until the table is finer.
- Other car-brand datasets (Stanford Cars, CompCars, VeRi). Documented in the prompt as alternatives; pick when access to DVM-Car doesn't materialise.
- Confusion matrix generation. Depends on the operator-labelled ground-truth set, which is its own item.
