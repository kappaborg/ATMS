# Senior Engineer Prompt — Real-Time Brand-Accurate Vehicle Perception

**Track:** ATMS perception / emissions
**Owner:** ML/Perception engineer
**Estimated effort:** 3–5 weeks
**Companion docs:** [`PROJECT_SUMMARY.md`](PROJECT_SUMMARY.md) · [`REFACTORING_NOTES.md`](REFACTORING_NOTES.md) · [`demos/pilot-pitch.md`](demos/pilot-pitch.md)
**Related code:** [`simulation/demo/video_source.py`](../simulation/demo/video_source.py) · [`simulation/demo/brand_clip.py`](../simulation/demo/brand_clip.py) · [`shared/atms_common/emissions.py`](../shared/atms_common/emissions.py)

## Status — 2026-06-08

| Phase | Status | Artefacts |
|---|---|---|
| 1. Speed via ONNX | **PARTIAL DONE** — ONNX runtime + CoreML execution provider (Apple Silicon) shipped via `simulation/demo/inference_runtime.py`. Threaded worker deferred. CoreML-via-mlpackage blocked on Python 3.14 (coremltools incompatible). | See [ADR-0020 §1](adr/0020-vehicle-brand-perception.md). |
| 2. Accuracy via fine-tune | **OPT-OUT GATES SHIPPED, FINE-TUNE DEFERRED** — multi-prompt CLIP + top-1/top-2 margin opt-out in `simulation/demo/brand_clip.py`. The actual DVM-Car fine-tuning needs ~10h training compute; see §3.2 below. | See [ADR-0020 §2](adr/0020-vehicle-brand-perception.md). |
| 3. Multi-frame voting | **DONE** — `simulation/demo/brand_voting.py` + integration into `TrackedVehicle.brand_observations` + 18 unit tests. | See [ADR-0020 §3](adr/0020-vehicle-brand-perception.md). |
| 4. Operator console UX | **DONE** — brand-mix panel with confidence colours + dual CO₂ display + classifier-in-use banner in `services/operator-console/src/app.py`. | See [ADR-0020 §4](adr/0020-vehicle-brand-perception.md). |
| Confusion matrix + ground truth | **PENDING** — needs the operator's 200-vehicle labelled set (§2.2). | — |
| Threaded inference worker | **DEFERRED** — ONNX speedup already pushed wall-clock above real-time. | §3.1 step 1.1 below. |

---

## 1. Why this work exists

The ATMS demo currently uses one of two brand identifiers on top of YOLOv8n vehicle detection:

1. **Trained model** (`models/car_brand_classification/.../best.pt`) — 13 classes, trained on the close-up `cars-brand-32` dataset. Identifies real brands correctly when it fires, but fires rarely on wide-angle traffic crops. Coverage gaps include Tesla, Ford, VW, Audi, Volvo, all French brands, and most Korean models beyond Kia.
2. **CLIP zero-shot** (`openai/clip-vit-base-patch32` with 65 brand prompts) — broader nominal coverage but **systematically wrong** on real traffic: generic sedans get labelled "BYD" or "XPeng" because CLIP's softmax always assigns the closest of the 65 brands, with no "unknown" opt-out. The confidence numbers are uncalibrated.

The result: the operator console shows emission numbers that *look* brand-aware but the brand labels are mostly noise, and the wall-clock cost of inference puts the pipeline at **1.3x real-time** at best — anything slower than 1x means the live demo visibly buffers.

Both problems converge on the same engineering principle: **emission accuracy is downstream of brand accuracy**. The per-class baseline (car/truck/bus) is robust; the brand multiplier (Tesla 0.30 × … × Lamborghini 1.50) is the variance-injector. A wrong brand inflates or deflates per-vehicle CO₂ by up to 5x. For the pilot pitch we need brand identifications that are either **right** or **explicitly absent** — never confidently wrong.

## 2. Acceptance criteria

The work is done when ALL of the following hold on the `videos/TEST.mp4` test clip + a captured 60-second real-camera clip the operator provides:

### 2.1 Performance

- Pipeline wall-clock for live processing: **≥ 1.0x real-time** with brand identification enabled, on CPU, on the existing Mac dev box.
- p95 per-frame latency (detect + track + brand): **≤ 100 ms** at the inference cadence.
- Brand-classifier model load time: **≤ 5 s** (or pre-warmed).
- Memory footprint: **≤ 2 GB** resident (excluding YOLOv8 model).

### 2.2 Accuracy — measured against an operator-labelled 200-vehicle ground-truth set

- **Brand recall** (% of vehicles where the system produces ANY brand label): ≥ 60% for vehicles where bbox is ≥ 80×80 px and the brand is in the supported set.
- **Brand precision** (% of produced labels that are correct): **≥ 85%**. This is the headline metric — operator console must be trustworthy.
- **Top-3 accuracy** (correct brand in the system's top-3): ≥ 90% for the same population.
- **Unknown opt-out rate**: vehicles that should NOT be labelled (occluded, brand not in supported set, image too low-res) must be returned as `brand=None` ≥ 80% of the time. No silent guessing.
- **Confidence calibration**: when the model reports confidence ≥ 0.7, precision must be ≥ 95%.

### 2.3 Emissions

- Per-direction `average_emission_g_per_km` reported by the system must be within **±10%** of the value computed from the ground-truth brand labels (operator's labelled set, run offline).
- The state file's `brand_identified_count` should accurately reflect labels above the chosen confidence threshold.

### 2.4 Operator UX

- `--brand-model {trained, clip, vmmr, ensemble}` flag selects the identifier; default is whichever passes all the above.
- A new `--brand-confidence-min 0.7` flag overrides the per-model default threshold.
- The Streamlit operator console (`services/operator-console/src/app.py`) shows a per-direction **brand-mix table** with counts + a "confidence" column.
- The state file gains a `brand_classifier_model: str` field so the dashboard can show which model produced the labels.

## 3. Recommended approach (prioritised)

### Phase 1 — Lift the speed floor (1 week)

Decouple inference from video playback. Today, each loop iteration does `read → detect → track → classify → emit → display`, all on one thread. The display can run at 30 fps independent of the inference rate.

| Step | Action | Why |
|---|---|---|
| 1.1 | Add a `Thread`/`Process`-isolated `InferenceWorker` that pulls frames from a bounded `queue.Queue` and pushes results to another queue. | Render loop never waits on inference. |
| 1.2 | Replace ultralytics' PyTorch backend with **ONNX Runtime** (`onnxruntime`) loading `yolov8n.onnx`. Convert once via `model.export(format='onnx')`. | 2-3x faster on CPU than PyTorch (`torch.jit` already optimised; ONNX skips Python overhead). |
| 1.3 | On Apple Silicon, switch ONNX Runtime to the **CoreML execution provider** (`onnxruntime-coreml`). Falls back to CPU on other platforms. | 5-10x faster on M-series Macs. |
| 1.4 | Replace `cv2.VideoCapture` reads in the main thread with a `cv2.VideoCapture` + `FFMPEG` background reader that pre-buffers ~10 frames. | Eliminates I/O stall between frames. |

**Done when:** end-to-end wall-clock on the same test clip is **≥ 1.5x real-time** with brand classification enabled.

### Phase 2 — Fix brand accuracy with a purpose-built model (2-3 weeks)

CLIP zero-shot is the wrong tool for this job. The right tool is a model **fine-tuned on a traffic-camera-style vehicle-make dataset**. The repo already has the dataset setup script: [`models/car_brand_classification/setup_dvm_dataset.py`](../models/car_brand_classification/setup_dvm_dataset.py) prepares the **DVM-Car** dataset (1.5M car images, 281 makes, 7K models).

| Step | Action | Why |
|---|---|---|
| 2.1 | Run `setup_dvm_dataset.py` to download DVM-Car (~30 GB). Aggregate the 281 makes down to the ~70-brand list in `shared/atms_common/emissions.py:_DEFAULT_BRAND_MULTIPLIERS`. | One make-recognition model with strong coverage. |
| 2.2 | Fine-tune a **ViT-B/16** (or **EfficientNet-B3**) classifier on the aggregated dataset. Use the `timm` library — same tooling the SE322 work used. 25 epochs at batch=128 on an M-series GPU. | Purpose-built > zero-shot. |
| 2.3 | Calibrate the model's confidence outputs via temperature scaling on a held-out 5% split. | The confidence threshold becomes meaningful. |
| 2.4 | Add a final **"unknown / other"** class trained on (a) low-resolution crops, (b) brands intentionally held out from training, (c) non-car detections. ~10% of training data. | Lets the model OPT OUT, the missing capability in CLIP. |
| 2.5 | Wire as a new `VMMRBrandIdentifier` in `simulation/demo/brand_vmmr.py`, following the existing `identify_batch(crops) -> list[(brand, conf) | None]` contract. The pipeline doesn't change. | Drop-in replacement; `--brand-model vmmr`. |
| 2.6 | Compute and ship a confusion matrix on the operator's labelled 200-vehicle set. Commit as `docs/perception/brand_confusion_matrix.csv`. | Operator transparency. |

**Done when:** brand precision ≥ 85% AND brand recall ≥ 60% on the operator's labelled set, per §2.2.

### Phase 3 — Ensemble + multi-frame voting (1 week)

Even a fine-tuned model is wrong sometimes per single frame. The tracker gives us multiple looks at the same vehicle — exploit it.

| Step | Action | Why |
|---|---|---|
| 3.1 | Modify `_classify_track_brands` so each classification appends to `TrackedVehicle.brand_observations: list[(brand, conf)]` rather than overwriting `brand`. | Multi-observation history. |
| 3.2 | Add a `decide_brand(observations) -> (brand, conf) \| None` aggregator: weighted vote where weights are per-observation confidence; require ≥ 3 observations of the same brand OR a single observation ≥ 0.90 to commit. | One frame of "Tesla" doesn't override 4 frames of "Ford". |
| 3.3 | Add an `EnsembleBrandIdentifier` that runs the fine-tuned VMMR model as the primary, falls back to CLIP for vehicles VMMR returned `unknown`. | Best of both: purpose-built precision + zero-shot coverage. |
| 3.4 | Add a unit test that feeds a synthetic stream of (mostly-Ford, occasionally-Tesla-misclassification) observations and asserts the aggregator picks Ford. | Tested aggregator. |

**Done when:** running the same test clip end-to-end shows **≥ 30% fewer brand mis-identifications** vs Phase 2 alone, measured by the operator's labelled set.

### Phase 4 — Re-grade the brand confidence on the operator console (3 days)

| Step | Action |
|---|---|
| 4.1 | Add a per-direction **brand-mix breakdown panel** to `services/operator-console/src/app.py` — a small table showing each brand + count + average confidence. |
| 4.2 | Colour-code by confidence: green ≥ 0.9, amber 0.7–0.9, red < 0.7 (or hidden). |
| 4.3 | Show the per-direction CO₂ **with and without brand-multiplier applied** so the operator sees the uncertainty band. |
| 4.4 | Add a "brand-classifier model in use" label at the top of the page. |

**Done when:** the operator can look at the console and tell at a glance whether the emission numbers come from reliable brand identifications or fall-through-to-baseline.

## 4. Out of scope (defer)

- **Vehicle-model-year identification.** Make is enough for emission lookup. Model+year would let us index against EPA's per-year fuel-economy database, but the gain is ~5% emission-accuracy at 10x the training-data cost.
- **License-plate-derived brand lookup** (DVLA-style API). Real-time API calls are too slow and have legal/privacy implications. ATMS already anonymises plates per ADR-0014; reversing that is out of scope.
- **Real-world A/B test against a measured-emissions baseline.** Requires a co-located OBD-II logger or a downstream air-quality sensor; this is C6 hardware-pilot work, not perception work.
- **Multi-camera identity stitching** (the same vehicle seen at two intersections). Phase 4 multi-intersection rollout territory; see `docs/ROADMAP.md`.
- **Detection of generic vehicle "trim level" beyond make.** Same reason as model-year above.

## 5. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| DVM-Car dataset is too North-America-skewed for EU pilot footage | Medium | Medium | Hold out an EU-sourced validation set before training; if recall drops > 20%, supplement with [Stanford Cars](https://ai.stanford.edu/~jkrause/cars/car_dataset.html) (US) + [CompCars](http://mmlab.ie.cuhk.edu.hk/datasets/comp_cars/) (China) + a labelled crop from `videos/T*.mp4`. |
| CoreML execution provider not maintained on Intel Macs | Low | Low | Phase 1.3 falls back to CPU; the dev box happens to be Apple Silicon. |
| Fine-tuning compute is not available on the dev box | Medium | High | Move the training step to a one-day rental of a single L40S on RunPod / Lambda Labs (~$30). Local inference still works on Mac. |
| Operator labels disagree with the ground truth (the operator is themselves uncertain about brand from footage) | High | Medium | Triple-label any vehicle the operator marks "unsure"; drop those from the test set. Document the resulting set in `docs/perception/groundtruth-200.csv`. |
| The fine-tuned model overfits to dataset-specific image processing artefacts | Medium | Medium | Train with heavy augmentation (jitter, blur, JPEG compression, weather). Validate on raw video frames before any preprocessing. |
| Per-brand emission multipliers in `emissions.py` are off vs. real-world local fleet | Low | Medium | A separate pilot work item; the multiplier table is data, not code. Pilot operator overrides via `load_emission_table()`. |

## 6. Test strategy

### 6.1 Synthetic / unit

- All new code under `simulation/demo/brand_vmmr.py`, `simulation/demo/brand_ensemble.py`, `simulation/demo/_track_voting.py` gets unit tests in `simulation/demo/tests/`.
- Aggregator test (§3.4 above) is the only meaningful logic-level test for the voting step.
- Confusion matrix regenerated as a deterministic asset (committed CSV).

### 6.2 End-to-end / regression

- Add a `simulation/baselines/perception_brands.json` capturing the expected brand counts on `videos/TEST.mp4` after Phase 2 lands. CI fails if the count drops > 10%.
- The existing `scripts/verify-pipeline.sh` already catches lint / type / unit-test regressions; extend it with a "perception fidelity" check that runs `simulation.demo --video videos/TEST.mp4 --frame-skip 5` and compares against the baseline.
- The operator's labelled 200-vehicle ground-truth set lives under `docs/perception/groundtruth-200.csv` and is the source of truth for the precision/recall numbers in PR descriptions.

### 6.3 Manual

- Each PR description includes a side-by-side screenshot: operator console with the new model vs. the previous default, same video, same timestamp. Shows the brand-mix breakdown and total CO₂ rate.

## 7. Estimated calendar

| Phase | Days | Calendar (working days) |
|---|---|---|
| 1. Speed floor (threading + ONNX + CoreML) | 5 | week 1 |
| 2. Fine-tune VMMR model (dataset prep + training + integration) | 10-12 | weeks 2-3 |
| 3. Ensemble + multi-frame voting | 4 | week 4 (front half) |
| 4. Operator console UI updates | 3 | week 4 (back half) |
| Total | **22-24** | **~5 weeks** |

One engineer full-time. If pair-programming is available, weeks 2-3 can compress because dataset prep + training infra setup are parallelisable with first-cut integration.

## 8. Deliverables

When this work is signed off:

1. `simulation/demo/brand_vmmr.py` — production-grade brand identifier
2. `simulation/demo/brand_ensemble.py` — multi-model dispatcher
3. `simulation/demo/inference_worker.py` — threaded inference pipeline (Phase 1)
4. `services/operator-console/src/app.py` — updated with brand-mix panel
5. `docs/perception/brand_confusion_matrix.csv` — fine-tuned model's confusion matrix
6. `docs/perception/groundtruth-200.csv` — operator-labelled ground truth
7. `docs/perception/training-notes.md` — DVM-Car prep + training procedure (so the next engineer can re-train)
8. `simulation/baselines/perception_brands.json` — regression baseline
9. New ADR `docs/adr/0020-vehicle-brand-perception.md` documenting the architecture and the why (CLIP zero-shot rejected, VMMR fine-tune chosen, ensemble logic, confidence calibration approach)
10. `simulation/demo/tests/test_brand_voting.py` + `test_brand_ensemble.py` — full unit coverage
11. Updated `docs/demos/pilot-pitch.md` §0.4 with the new brand-model options and recommended defaults
12. Updated `docs/REFACTORING_NOTES.md` §3.x to note the perception layer is now first-class

## 9. Anti-recommendations (don't do these)

- **Don't try to make CLIP work better with prompt engineering alone.** The zero-shot tradeoff is fundamental; adding more prompts gives marginal gains. Fine-tuning is the structural answer.
- **Don't ship a "brand-aware" emission number without a confidence floor.** If brand precision is < 85%, default-disable the brand multiplier in the pipeline and report per-class baseline only. False precision is worse than acknowledged imprecision.
- **Don't store cropped vehicle imagery to disk** for training data without an explicit privacy/DPIA review (ADR-0014). The HMAC-anonymised plate path is what we ship; raw imagery for retraining needs a separate operator opt-in and a retention policy.
- **Don't refactor the rest of the perception stack** as part of this work. The `services/ai-perception/` monolith refactor is a separate item on `docs/REFACTORING_NOTES.md` §2.1; let it stay separate.

---

**TL;DR for the engineer picking this up:** Speed comes from threading + ONNX/CoreML (Phase 1, 1 week). Accuracy comes from fine-tuning on DVM-Car, not from better prompts (Phase 2, 2-3 weeks). Reliability comes from multi-frame voting + an "unknown" opt-out (Phase 3, 1 week). Operator trust comes from showing confidence transparently (Phase 4, 3 days). Total ~5 weeks for one engineer, $30 of cloud compute, no new hardware procurement.
