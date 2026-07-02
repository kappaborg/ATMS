## ATMS Research-Ready MVP – Improvement Plan

This file defines the minimum set of changes we will implement to make the ATMS project clean, testable, and ready for a research paper.

We will execute these steps **in order**, updating this checklist as we go.

---

### Phase 0 – Scope & Modes

- [x] **0.1 Define two run modes**
  - `deployment`: live Kafka/NTCIP integration, real-time dashboard
  - `experiment`: offline video/Kafka replay, deterministic configs, rich logging
- [x] **0.2 Add a central `atms_config` module**
  - Single source of truth for:
    - Model paths
    - Device selection
    - Thresholds (confidence, IoU, speed, emission) (added in Phase 2)
    - Run mode (`deployment` vs `experiment`)

---

### Phase 1 – Unified Perception & Decision Pipeline

- [x] **1.1 Extract a shared pipeline core**
  - Create `atms_core/pipeline.py` with a reusable class, e.g. `ATMSPipeline`, that:
    - Accepts frames or detection messages
    - Runs detection → tracking → speed → emissions → decision
    - Returns a structured `PipelineResult`
- [x] **1.2 Refactor `realtime_video_processor.py` to use `ATMSPipeline`**
- [x] **1.3 Refactor `youtube_decision_processor.py` to use `ATMSPipeline`**
- [x] **1.4 Refactor `services/ai-perception/src/main.py` to call `ATMSPipeline`**
- [x] **1.5 Remove duplicated model-initialization logic**

---

### Phase 2 – Configuration & Threshold Hygiene

- [x] **2.1 Move magic numbers into config**
  - Confidence thresholds, distance-aware multipliers
  - Speed calculator options (min track length, which methods are enabled)
  - Emission base factors and speed multipliers
- [x] **2.2 Log the full effective configuration at startup**
- [x] **2.3 Add simple validation for config (e.g. ranges, required fields)**

---

### Phase 3 – Evaluation & Ablation Harness

- [x] **3.1 Create `experiments/` folder with standardized structure**
  - `experiments/configs/` – YAML/JSON configs for runs
  - `experiments/results/` – CSV/JSON outputs with metrics
- [x] **3.2 Add `scripts/eval_speed_and_emissions.py`**
  - Runs ATMSPipeline on labeled or semi-labeled videos
  - Outputs:
    - Per-vehicle predicted speed & emission
    - Error metrics if ground truth available
- [x] **3.3 Add ablation flags**
  - CLI / config toggles:
    - `use_kalman`, `use_cvm`, `use_wls`
    - `use_distance_aware_filtering`
    - `use_enhanced_emission_model`
- [x] **3.4 Add a minimal `experiments/README.md` describing how to run evaluations**

---

### Phase 4 – Decision Engine & RL Clarification

- [ ] **4.1 Decide mode for first paper**
  - For now: **rule-based decision engine as default**, RL marked as experimental
- [ ] **4.2 Add a simple offline decision evaluation script**
  - `scripts/eval_decision_engine.py`:
    - Replays recorded traffic metrics
    - Compares:
      - Fixed-time baseline
      - Current rule-based engine
    - Produces delay / throughput / simple emission metrics
- [ ] **4.3 Clearly separate RL code paths**
  - Guard RL with a feature flag (`ENABLE_RL` in config)
  - If disabled, RL modules are not imported / initialized

---

### Phase 5 – Analytics & Logging for Research

- [ ] **5.1 Define a standard log/event schema**
  - Per-frame / per-decision records:
    - Timestamp, intersection id
    - Phase, vehicles per direction, emissions per direction
    - Chosen action + reason + confidence
- [ ] **5.2 Implement CSV/Parquet logging in experiment mode**
- [ ] **5.3 Ensure analytics modules (`TrafficPatternAnalyzer`, etc.) consume this schema**

---

### Phase 6 – Cleanup & Documentation

- [ ] **6.1 Remove or downgrade unverified accuracy claims in docstrings**
- [ ] **6.2 Add `docs/EXPERIMENTS_OVERVIEW.md`**
  - Lists available experiments and what research questions they answer
- [ ] **6.3 Ensure `README.md` explains run modes, configs, and evaluation entry points**

---

### Execution Notes

- We will now implement these steps **sequentially**, starting with:
  - Phase 0 (config + run modes)
  - Phase 1 (unified pipeline core)
- After each meaningful change, we will:
  - Run linting/tests where available
  - Keep behavior of `deployment` mode backward-compatible

