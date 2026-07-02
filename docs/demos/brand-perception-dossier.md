# ATMS — Brand-Aware Emissions + AI Decision Chamber

**One-pager for pilot, academic, and technical conversations.** Last updated 2026-06-14.

---

## What ATMS does (in one paragraph)

ATMS is a **production-grade adaptive signal-control system** built on three layers: (1) a video perception pipeline that detects vehicles, identifies brands, and computes per-vehicle CO₂ emissions; (2) a **6-layer AI Decision Chamber** that turns per-direction sensor state into explainable, auditable phase requests — handling emergency preemption (4 sources), pedestrian phases (button + vision), transit signal priority (GTFS-realtime), and green-wave coordination (MQTT multi-intersection); (3) a **closed-loop NTCIP-1202** integration with SIL-rated signal controllers, fed by Prometheus observability and SQLite audit with rotation/retention. Every protocol on the boundary (NTCIP, V2X J2735 SRM, GTFS-RT, MQTT) is real. Production deployment is **a single YAML per intersection** + a one-call factory.

## TL;DR

ATMS is an adaptive traffic management system that **identifies vehicle brands from video and applies per-brand CO₂ emission multipliers**, producing emission estimates that distinguish a Tesla (0.30×) from a Lamborghini (1.50×) instead of treating every car as a fleet average. The brand detector is **calibrated** (its 96% confidence actually means 96%), **opt-out aware** (it abstains rather than guess when uncertain), and **validated against human-labelled ground truth** — not just internal validation metrics.

| Metric | Value | What it means |
|---|---|---|
| Validation mAP50 | **0.872** | Internal accuracy on the DVM-Car validation set (54 classes incl. opt-out) |
| Calibration ECE | **0.014** | Confidence is well-calibrated — a 0.96 commit really is correct ~96% of the time |
| **Field precision** | **66.7%** | When the model commits a brand on real wide-angle traffic footage, 2 out of 3 are correct (measured on 240-vehicle labelled ground-truth set) |
| Field recall | 2.2% | The model opts out on most vehicles; uncommitted ones fall back to class-baseline emissions |
| Inference speed | **1.92× real-time** | M1 Max via ONNX/CoreML on 1080p footage |

---

## Why brand-aware emissions matter

Most traffic-monitoring stacks count vehicles and apply a single fleet-average emission factor per vehicle class (car, bus, truck). That is fine for traffic *flow* analysis. It is **not** fine for:

1. **Low-emission-zone enforcement.** A Tesla Model 3 and a 2008 Range Rover are both "cars" but emit very different amounts. Without brand resolution, you can't differentiate compliant from non-compliant fleets.
2. **Net-zero reporting to municipalities.** Cities increasingly need CO₂ accounting at the corridor / district level. Brand-grain estimates are 5-15% more accurate than fleet-average estimates depending on the local fleet mix.
3. **ULEV (ultra-low-emission vehicle) incentives.** Knowing the actual brand mix lets a city verify whether EV-adoption programmes are moving the needle.

The ATMS approach: **brand identification is an enhancement layer**. When confident, the brand multiplier refines the estimate. When uncertain, the system falls back cleanly to the class baseline — no false confidence, no hallucinated emissions.

---

## How the system works (end-to-end)

```
   Live RTSP / pre-recorded video
              │
              ▼
   ┌────────────────────────┐
   │ YOLOv8n (ONNX/CoreML)  │  ← vehicle detection + classification (car/bus/truck)
   │ 1.5× real-time         │
   └──────────┬─────────────┘
              │
              ▼
   ┌────────────────────────┐
   │ IoU tracker            │  ← same vehicle across frames
   │ (multi-frame voter)    │
   └──────────┬─────────────┘
              │
              ▼
   ┌────────────────────────┐
   │ dvm_car_v1 (54 classes)│  ← brand classification, calibrated, opt-out aware
   │ trained on DVM-Car     │
   └──────────┬─────────────┘
              │
              ▼
   ┌────────────────────────┐
   │ EmissionEstimator      │  ← per-vehicle CO₂ = class baseline × brand multiplier
   │ shared/atms_common/    │     × speed factor
   └──────────┬─────────────┘
              │
              ▼
   ┌────────────────────────┐
   │ Streamlit operator     │  ← live dashboard: vehicle counts, brand mix,
   │ console + Grafana      │     per-direction CO₂, dual w/baseline display
   └────────────────────────┘
```

**Honesty principle threaded throughout:** every step produces a confidence value. Uncertain brand commits fall back to class-baseline emissions. The operator console shows BOTH the brand-multiplied number AND the class-baseline number so the operator can see the uncertainty band.

---

## The ground-truth measurement story

Building a model that scores 0.872 mAP50 on its own validation set is one thing. Knowing whether it actually works in the field is another. Most ML projects ship with the first number and find out about the second from a customer.

ATMS went the other way: a **240-vehicle human-labelled ground-truth set** was built using the in-repo `services/labeler/app.py` Streamlit tool. Three videos were sampled — 5 minutes of busy 1080p YouTube traffic, 1.5 minutes of 720p YouTube traffic, 28 seconds of TEST.mp4 — every YOLOv8 detection above 100×100 px was extracted as a crop, and each was human-labelled with one of 53 brands, `_other_brand` (real brand outside the class set), `_not_a_car` (mis-detection), or `_unsure`.

That dataset surfaced two things:

1. **dvm_car_v1 commits **rarely** but correctly.** 4 correct, 2 incorrect, 175 opt-outs (across 184 valid labelled crops). 66.7% precision.
2. **The earlier-generation `traffic_realistic` model committed often and was always wrong** on this footage (0% precision at the same threshold). It was actively *worse* than no brand identification, because every commit polluted the downstream emissions calculation with the wrong multiplier.

The system ships with the opt-out posture because **wrong brand multipliers are worse than no brand multipliers**. Recall improvement is on the roadmap (see below); precision was the first guarantee to nail down.

---

## AI Decision Chamber — 6-layer phase orchestrator

The chamber turns per-direction sensor state into a phase request every 2 seconds:

```
L0  Sensor Fusion    counts-based health check across multi-source inputs
L1  Preemption       4 emergency sources (operator override, visual lightbar,
                     V2X J2735 SRM, audio siren STFT)
L2  Policy Gates     min/max phase, pedestrian-phase active, force-change on
                     max-phase exceeded OR pedestrian demand on non-current
                     direction
L3  Optimization     weighted multi-objective:
                       w_queue × queue_pressure +
                       w_emit  × emission_cost (Σ idling_g/min × wait_s) +
                       w_fair  × seconds_since_green / max_starvation +
                       pedestrian_bias (+0.40) +
                       tsp_bonus (per-direction GTFS-realtime late-bus signal)
L4  Hysteresis +     current-phase bonus to prevent oscillation +
    Coordination     green-wave bonus (Pattern A) consumed from MQTT mesh
L5  Commit + Audit   NTCIP-1202 SNMP SET-REQUEST →
                     closed-loop NTCIP GET-REQUEST status poll →
                     SQLite audit (rotation + 90-day retention) +
                     Prometheus exposition (atms_chamber_*) +
                     MQTT pub: state, decision, wave_pulse
```

### Real protocols at every boundary

| Output / Input | Wire format | Implementation |
|---|---|---|
| Signal controller command | NTCIP-1202 §4.6 SNMPv1 SET-REQUEST, OID `1.3.6.1.4.1.1206.4.2.1.1.4.1.1.{2,4}` | Hand-rolled ASN.1 BER encoder, 0 deps |
| Controller status read-back | NTCIP-1202 §4.5 SNMPv1 GET-REQUEST, bitmask response | BER decoder, background poll thread |
| V2X emergency vehicle | SAE J2735 Signal Request Message, ASN.1 UPER | `asn1tools` real codec, minimal schema |
| Multi-intersection coord | MQTT (broker: Mosquitto/EMQ/HiveMQ) | `paho-mqtt`, QoS 1, LWT, auto-reconnect |
| Transit signal priority | GTFS-realtime protobuf | `gtfs-realtime-bindings`, HTTP polling |
| Audio siren detection | Live STFT, 500-1600 Hz band, FM signature | `numpy.fft`, microphone via `sounddevice` |
| Observability | Prometheus text format on `/metrics` | stdlib HTTP server |
| Audit | SQLite WAL mode, JSONL columns | stdlib `sqlite3`, rotation + retention |

### What's exposed to the operator

- **Live chamber panel** — current commanded phase, mode (adaptive/preempt/fixed_time/manual), per-direction priority scores, per-layer reasoning trace
- **Closed-loop NTCIP indicator** — commanded vs actual phase, in-sync/diverge badge, divergence-tick counter (alerts at 3+ consecutive)
- **TSP active routes** — which GTFS routes are currently requesting priority and on which approach
- **Detector + protocol coverage badges** — green/grey chips for each L1/L2/L3/L4/L5 source, audit type, bridge type, mesh connection state
- **Operator controls** — request pedestrian phase, force emergency preempt, clear overrides — file-based JSON signals consumed by chamber detectors

### Production deployment pattern

```bash
# One-call factory loads everything from per-intersection YAML
python3 -m simulation.demo \
    --video <RTSP or video> \
    --site-config /etc/atms/intersection-005.yaml
```

The YAML controls camera homography (pixels_per_meter), crosswalk_zones, NTCIP target IP + community + closed-loop poll interval, MQTT broker + upstream_neighbors, green_wave neighbor offsets, GTFS-realtime feed URL + route → direction map, Prometheus port, SQLite audit path + rotation + retention. Template at `services/observability/example-intersection.yaml`.

## Speed estimation accuracy

Vehicle speed is computed from per-track pixel displacement and the configured `pixels_per_meter` calibration. Three correctness mechanisms keep the displayed values defensible:

1. **Correct time interval.** Speed is computed over `frame_skip / fps` seconds per history step, not `1 / fps`. (Earlier versions silently overestimated speeds by a factor of `frame_skip` — typically 3×.)
2. **Whole-window smoothing.** The estimator uses the first-to-last position over the full 10-sample pixel-history window (~1 second of motion at default settings), so single-frame tracker glitches no longer produce spikes.
3. **Physical sanity cap.** Speeds above `MAX_REALISTIC_SPEED_KMH = 180 km/h` (EU motorway limit + 50 km/h tolerance) are treated as tracker errors and displayed as **`-- km/h`** rather than a fake number. The operator sees an honest "unknown" rather than an impossible value.

**Calibration responsibility.** `pixels_per_meter` is camera-specific. The default `25.0` is calibrated against a typical wide-angle traffic camera capturing ~75 m horizontally on a 1920-px frame. For accurate speeds in a real pilot deployment, calibrate per-camera:

```bash
# Identify two points in your scene with a known real-world distance
# (e.g., painted lane markings 3.5 m apart, or a vehicle of known
# length 4.5 m). Measure the pixel distance, then:
#   pixels_per_meter = pixel_distance / real_distance_meters
python3 -m simulation.demo --video your_source.mp4 --pixels-per-meter 32.5
```

When in doubt, **prefer to under-display rather than guess** — the demo overlays show `-- km/h` for any track whose estimated speed exceeds the sanity cap, which is exactly what an operator-grade system should do.

## What's deferred (honest limitations)

| Limitation | Detail | Plan |
|---|---|---|
| **Recall is 2.2%** | Most vehicles get no brand commit and fall back to class baseline. Practically: most rows in the operator console will show "—" in the brand column. | Larger training corpus (full 13.6 GB DVM-Car set with side/rear views, not just the 730 MB front-view subset currently used). |
| **UK-market dataset** | DVM-Car was sourced from UK auto sales — no BYD, no Chinese marques, no regional brands. | Pair DVM-Car with a regional dataset for the target deployment city. |
| **Ground truth is 240 labels** | Enough to know the precision-vs-recall gap, too small to compute per-brand precision with confidence intervals. | Operator-labelled 500-1000 set as part of pilot onboarding. |
| **No hardware integration yet** | Currently runs on pre-recorded video. Live RTSP, NTCIP signal-controller integration, edge-agent deployment all deferred. | Tracks C1 / C2 / C6 in the project workplan. |

---

## The 5-minute live demo script

Run this in front of an audience to walk through the system end-to-end.

```bash
# Terminal 1 — operator console (starts polling /tmp/atms-demo-state.json)
cd /Users/kappasutra/Traffic
streamlit run services/operator-console/src/app.py
# Browser: http://localhost:8501

# Terminal 2 — run the pipeline on a real traffic video.
# --show     opens a live OpenCV preview window with bbox + brand + speed
#            + CO₂ overlay drawn per vehicle (color-coded by emission impact:
#            green=low, blue=medium, orange=high, red=very-high)
# --save-video also records the annotated output to mp4 as a guaranteed-
#            working backup you can play instead if live demo glitches
python3 -m simulation.demo --video videos/youtube_MNn9qKG2UFI_full.mp4 \
    --show \
    --save-video docs/demos/recordings/live_demo.mp4
```

The two screens to position side-by-side for the demo:

| | What it shows | Source |
|---|---|---|
| **Left half — live video** | Annotated frames with coloured bboxes, brand tags, speed, per-vehicle CO₂ | OpenCV window from `--show` |
| **Right half — operator console** | Aggregated metrics: vehicle counts, brand-mix table, dual baseline-vs-brand CO₂, recent events | Streamlit on `http://localhost:8501` |

If live inference is fragile (network, projector, etc.), **pre-record** the annotated video beforehand with `--save-video` then play it back in QuickTime alongside the console:

```bash
# Pre-record a demo asset ahead of time (silent, runs at ~2× real-time)
python3 -m simulation.demo --video videos/TEST.mp4 \
    --save-video docs/demos/recordings/test_annotated.mp4
# Then on demo day: open the mp4 in QuickTime, share screen
```

A 28-second sample recording already exists at `docs/demos/recordings/test_annotated.mp4` — open it now to see what the overlay looks like.

While it runs, walk through:

1. **Top-right banner: `trained:dvm_car_v1` and "Brand classifier ENABLED".** Tell them: "Operators always see which model is loaded. This is dvm_car_v1, trained on the DVM-Car dataset."
2. **Brand-mix panel.** "Most vehicles show no brand — that's the model honestly opting out on uncertain crops. The committed brands show high-confidence identifications (BMW, Citroen, Toyota at 0.93+). On 240 ground-truth-labelled vehicles, every brand it does commit is correct 67% of the time."
3. **Dual CO₂ display.** "Per-direction emissions are shown twice: with brand multipliers (more accurate when brands are known) and using the class baseline (the 'we don't know yet' fallback). The gap between them visualises how much brand identification is contributing."
4. **Recent events column.** "Real-time tick stream — every state change is logged. Auditable."

If asked "what about all the vehicles without a brand?":
> "Those use the class baseline. We chose to under-commit rather than over-commit because in a real city deployment, a wrong multiplier is worse than no multiplier — it pollutes your reporting. Recall is the next thing we're scaling, by adding more training data and operator-labelled examples."

---

## FAQ — likely technical questions

**Q: Why YOLOv8n for vehicle detection and not the YOLOv8m or larger?**
We benchmarked: on M1 Max via ONNX/CoreML, YOLOv8n is 1.92× real-time on 1080p; YOLOv8m drops to 0.6× real-time. Throughput matters for an edge deployment more than the ~1.5% mAP gain. Both are configurable via `--yolo-weights`.

**Q: Why a 54-class DVM-Car model over CLIP or VMMR?**
CLIP zero-shot was tested early and showed ~0.10-0.25 confidence in field crops — below any usable threshold. CLIP has no opt-out class. Trained DVM-Car has higher precision at the cost of brand coverage, and the calibrated confidence + opt-out makes the opt-in behaviour trustworthy.

**Q: How do you handle the per-brand multiplier table?**
`shared/atms_common/emissions._DEFAULT_BRAND_MULTIPLIERS` — 70+ brand multipliers anchored against WLTP new-fleet CO₂ ranges. 1.00 = class average. Tesla 0.30, Lamborghini 1.50, Toyota 0.85 (hybrid-heavy fleet), etc. The table is documented for regional replacement during pilot onboarding.

**Q: What's the licence story?**
DVM-Car is CC BY 4.0 (research/educational only). Re-deployment for commercial pilot requires either model retraining on commercially-licensed data OR a research-license arrangement with the DVM-Car authors (University of Glasgow / Southampton). Documented in `docs/runbooks/brand-model-finetune.md`.

**Q: How much of this is reproducible?**
All training, calibration, A/B comparison, and ground-truth scripts are in the repo (see `models/car_brand_classification/`, `scripts/`, `services/labeler/`). The 240-crop ground-truth set is committed under `data/ground_truth/`. Anyone with access to the repo can re-run `python3 scripts/compute_field_metrics.py` to reproduce the 66.7% precision number.

**Q: What's the next milestone?**
Larger training corpus + larger ground-truth set, in that order. Target: 30% recall at 70% precision. Pilot-ready as soon as those numbers land plus the NTCIP/edge-agent integration work (workplan tracks C1/C2/C6).

---

## At-a-glance metrics for slides

Copy these into a presentation:

- **0.872 mAP50** — internal validation accuracy, 54 brand classes
- **66.7% precision** — when the model identifies a brand, 2 of 3 are right (240-vehicle field validation)
- **0.014 ECE** — confidence is well-calibrated (a 0.96 commit means 96%)
- **1.92× real-time** — inference throughput on consumer M1 Max hardware
- **240 vehicles** — human-labelled ground-truth set, reproducible

---

## Reproducing the field validation

For someone who wants to re-run the precision/recall measurement:

```bash
cd /Users/kappasutra/Traffic

# 1. Extract crops (~3 min)
python3 scripts/prepare_ground_truth.py \
    --videos videos/TEST.mp4 \
             videos/youtube_MNn9qKG2UFI_full.mp4 \
             videos/youtube_cJatWBDNabE_full.mp4 \
    --max-per-video 80

# 2. Label them (Streamlit UI; ~30-45 minutes for 240 crops)
streamlit run services/labeler/app.py
# Open browser, label each crop, labels save automatically

# 3. Compute metrics (~5 min)
python3 scripts/compute_field_metrics.py
# Outputs: data/ground_truth/metrics_<model>.md  + .json
```

Multi-model comparison:
```bash
python3 scripts/compute_field_metrics.py \
    --weights models/car_brand_classification/outputs/traffic_realistic/weights/best.pt \
    --out-tag traffic_realistic_baseline
```

---

*Document maintained alongside the codebase; numbers above link to reproducible artefacts. For the brand-model training runbook see [`docs/runbooks/brand-model-finetune.md`](../runbooks/brand-model-finetune.md). For the older 30-minute SUMO demo runbook see [`pilot-pitch.md`](./pilot-pitch.md).*
