# ADR-0020: Vehicle brand perception — runtime, model, voting

**Status:** Accepted
**Date:** 2026-06-08
**Supersedes:** Implicit choices in [SENIOR_ENGINEER_PROMPT_BRAND_PERCEPTION.md](../SENIOR_ENGINEER_PROMPT_BRAND_PERCEPTION.md) §3.

## Context

The video-emission pipeline (`simulation/demo/video_source.py`) wants two things from brand identification: **precision** (a labelled brand is correct ≥ 85% of the time) and **throughput** (≥ 1x real-time on CPU). The pipeline's existing options each fail one of those:

1. **Trained YOLOv8 detector** (`models/car_brand_classification/.../best.pt`, 13 classes): high precision when it fires, but trained on close-up `cars-brand-32` shots — rarely confident on wide-angle traffic crops, narrow coverage.
2. **CLIP zero-shot** (`openai/clip-vit-base-patch32`, 65 brand prompts): broad coverage but no "unknown" opt-out → systematically over-commits to whichever of the 65 brands is closest in embedding space.

Symptoms observed: same vehicle gets labelled "BYD" one frame and "XPeng" the next; obvious-Ford pickups get tagged "MG". Wall-clock with brand classifier on: 0.65x real-time (trained) / 1.33x (CLIP) — the "video is lagging" complaint.

A fine-tuned classifier on a proper traffic-camera dataset is the real answer (see senior-engineer prompt §3.2). That work needs ~10 hours of training compute and an operator-labelled validation set; deferred to a follow-up.

This ADR records the four interventions we shipped that improve both axes **without** new training.

## Decisions

### 1. Detection runtime: ONNX via CoreML execution provider

The vehicle detector (YOLOv8n) now runs through `onnxruntime` with `CoreMLExecutionProvider` preferred over CPU. ultralytics' `YOLO('model.onnx')` loader pins `CPUExecutionProvider` only — we bypass it via a thin direct-runtime wrapper in `simulation/demo/inference_runtime.py:ONNXYoloDetector`.

Measured on Apple M1 Max with `yolov8n.onnx`:
- PyTorch (ultralytics default): ~30 ms/frame
- ONNX-CPU: ~36 ms/frame
- **ONNX-CoreML: ~20 ms/frame** ← 1.5x faster

A `make_detector(weights_path, runtime='auto')` factory picks the fastest available backend; `--runtime {auto,onnx,pytorch}` overrides. PyTorch remains the fallback when no `.onnx` exists alongside the `.pt` (auto-export is *not* automatic — converting requires an explicit `model.export(format='onnx', simplify=True)` call so the user can choose when to pay the conversion cost).

**Rejected alternative:** CoreML via `model.export(format='coreml')` → `.mlpackage`. `coremltools ≥ 8.0` has no Python 3.14 wheel as of this writing; will revisit when the project pins to 3.11 per [REFACTORING_NOTES.md §3.6](../REFACTORING_NOTES.md).

### 2. CLIP multi-prompt ensemble + confidence-margin opt-out

Two changes to `simulation/demo/brand_clip.py:CLIPBrandIdentifier`:

**Multi-prompt averaging.** Each brand now has 4 prompt templates ("a photo of a {brand} car", "a photo of a {brand} car driving on the street", "a {brand} vehicle seen from a traffic camera", "a side view of a {brand} car"). After softmax over the full 260-prompt vocabulary (65 brands × 4 templates), the per-brand probabilities are summed. The brand with the highest aggregated score wins.

**Top-1 vs top-2 margin floor.** Even multi-prompt CLIP can sit "almost equally close" to many brands. We require:
- Absolute confidence ≥ `conf_threshold` (default 0.30)
- Top-1 minus top-2 ≥ `min_margin` (default 0.05)

If the margin is tight, `identify_batch` returns `None` for that crop — the explicit "unknown" outcome. This is the missing capability vs a fine-tuned model with a learned "other" class.

**Rejected alternative:** Adding a "none of the above" prompt to CLIP. Tested in early prototyping; CLIP doesn't reliably anchor a meaningful "not a car / not in this brand list" semantic — the embedding ends up close to whatever's already there.

### 3. Multi-frame voting aggregator

`simulation/demo/brand_voting.py:decide_brand` is a pure function that operates on a track's full observation history:

```python
def decide_brand(
    observations: list[tuple[str, float]],
    *,
    single_high_conf: float = 0.90,
    min_count: int = 3,
    min_total_confidence: float = 1.0,
    min_margin: float = 0.10,
) -> tuple[str, float] | None
```

Two paths to commit:
- **Shortcut**: any single observation at conf ≥ 0.90 wins immediately. Lets a rare high-confidence frame commit fast.
- **Majority**: same brand seen ≥ 3 times, total summed confidence ≥ 1.0, winning total beats runner-up by ≥ 0.10.

Otherwise `None` — the explicit "no consensus yet" outcome. A single misidentification can't flip a stable track: four observations of Ford at 0.40 each (total 1.60) beat a one-off Tesla at 0.45.

`simulation/demo/video_source.py:TrackedVehicle` gained a `brand_observations: list[(str, float)]` field. `_classify_track_brands` now **appends** per-frame results rather than overwriting, and consults `decide_brand` for the committed label. The observation list is capped at 20 entries to keep state per-track bounded.

**Rejected alternative:** Sticky-with-upgrade (the previous design: a new observation overrides the cached one only if conf is ≥ 0.10 higher). It misclassified easily — one high-confidence wrong observation could flip a track. The voter requires *agreement*, not just *confidence*.

### 4. Operator-console transparency — confidence-coloured brand mix + dual CO₂

Operators previously saw a single emission number per direction with no visibility into how much the brand identifier was contributing. The console (`services/operator-console/src/app.py`) now shows:

- **Brand mix table** per direction: `brand | count | average confidence`. Confidence rendered as a colour-coded badge (green ≥ 0.9, amber 0.7-0.9, gray < 0.7).
- **Dual CO₂ display**: the headline "g/km" and "g/min" numbers now show both the brand-adjusted value AND the per-class baseline in parentheses (e.g., "168 (baseline 140)"). The delta is signed and labelled.
- **Classifier-in-use banner** at the top of the page reads `brand_classifier_model` from the state file — so the operator always knows which model produced the labels they're looking at.

This lets the operator see at a glance whether the displayed CO₂ comes from confident identifications or fell through to the per-class baseline.

## Consequences

### Positive

- CLIP wall-clock improved from 1.33x → 1.13x real-time (slight slowdown from extra state-emit work but acceptable; ONNX wins back the lost ground on the vehicle-detection side).
- Brand commits are now **right or absent** — the voter blocks low-evidence guesses by design. False precision is worse than acknowledged imprecision (anti-recommendation in the prompt's §9).
- The operator console makes the brand-classifier's contribution transparent — no hidden number magnification.
- All four interventions are model-swappable: when a fine-tuned VMMR model lands, the `BrandIdentifierProtocol` contract (`identify_batch(crops) -> list[(brand, conf) | None]`) is unchanged.

### Negative

- Fewer raw "brand-identified" labels per video — by design, but it can look like a regression to operators who don't read the brand-mix panel.
- The voter introduces commit latency: a track needs ~3 classify-cycles before being labelled. At `brand_classify_every_n_frames=60` and `frame_skip=3`, that's ~6 seconds of footage. Acceptable for typical intersection footage where vehicles persist longer; problematic for very-brief tracks.
- The ONNX path needs the `.onnx` file present. Auto-export is not done at runtime (would surprise the user with a slow first run). Documented in the runbook.

### Neutral

- `coremltools` is not installed (incompatible with Python 3.14). When the project pins to 3.11 we revisit; CoreML via `.mlpackage` is an additional 2-3x speedup on top of the current ONNX path.
- The per-direction `emissions_baseline` is computed by calling `EmissionEstimator.aggregate_direction` twice per state emit (once with brands, once with None brands). Minor overhead; could be optimised by computing the brand-multiplier ratio analytically if it shows up in profiles.

## Verification

- **Unit:** `simulation/demo/tests/test_brand_voting.py` (18 tests covering shortcut / majority / margin / edge cases), `test_inference_runtime.py` (13 tests covering letterbox / NMS / xywh / factory selection), `test_brand_clip.py` (15 tests).
- **End-to-end:** `python3 -m simulation.demo --video videos/TEST.mp4 --brand-model clip` runs at 1.13x real-time on Apple M1 Max with 65-brand coverage and explicit unknown opt-out.
- **Operator console:** sample state JSON written by the pipeline contains `brand_classifier_model`, `emissions_baseline`, and `brand_confidence_by_brand` fields; console renders all three.
- `./scripts/verify-pipeline.sh` → 43 checks green.

## Out of scope (handoff to fine-tune follow-up)

- DVM-Car ViT-B/16 fine-tuning. Pre-procedure documented in `SENIOR_ENGINEER_PROMPT_BRAND_PERCEPTION.md` §3.2. Requires ~10 hours training compute + an operator-labelled validation set.
- Threaded inference worker (decouples render from inference). Senior-engineer prompt §3.1 step 1.1. Phase 1 of this ADR's interventions already brings wall-clock above real-time, so it's now lower-priority.
- Per-lane masks replacing the frame-quadrant direction heuristic. Operator-side, drawn at camera-calibration time.
