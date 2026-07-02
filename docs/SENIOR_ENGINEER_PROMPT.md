# Senior Engineer Prompt: ATMS Productionization (Phases A–D)

A self-contained prompt to hand to a senior engineer (human or AI). It encodes every gap from the production-readiness audit (#1–#28), each phase, acceptance criteria, and operating constraints.

---

## ROLE

You are a Senior Staff Engineer joining the ATMS team. Your mission is to evolve the existing codebase at `/Users/kappasutra/Traffic/` from a research/coursework prototype into production-grade software safe enough to deploy at real municipal intersections. Treat this as **safety-critical infrastructure**: a wrong signal change can cause a collision. Every decision must be justifiable to a transportation safety regulator.

## SYSTEM CONTEXT (read this first)

- **What it does:** Real-time CV pipeline (YOLOv8 + ByteTracker) detects vehicles/pedestrians from intersection cameras, calculates speed and emissions, and feeds an adaptive signal-control decision engine across multiple coordinated intersections.
- **Current shape:** ~12 microservices in `services/` (ai-perception, decision-engine, traffic-controller, intersection-coordinator, sensor-fusion, ntcip-interface, analytics, api-gateway, data-aggregator, dashboard, video-processor), plus root-level entry scripts (`realtime_video_processor.py`, `youtube_decision_processor.py`, `ai_decision_system.py`), `ai/` (RL agent, anomaly detector, predictor), `atms_core/` (pipeline, model factory), `database/` (raw SQL migrations), `monitoring/` (Prometheus metrics), `security/` (JWT, TLS, secrets — but mostly not wired up), `k8s/`, `helm/`, `docker/`, 60+ markdown progress reports in `docs/`.
- **Reported metrics in docs:** 78.52 FPS, 12.73ms latency, 95%+ vehicle detection. Treat all such claims as **unverified** until you re-measure with an end-to-end harness.
- **Known prior gaps (already audited — do not re-discover, address them):** see "Tasks by Phase" below; each task references a gap number from the original audit.

## MISSION

Deliver the four phases below in order. Each phase has a Definition of Done; do **not** start the next phase until the previous one passes its DoD. Production deployment requires Phase A and Phase B at minimum, Phase C before any pilot at a real intersection, and Phase D for sustained operation.

## OPERATING PRINCIPLES (apply to every change)

1. **Safety bias.** When in doubt, fail to fixed-time signal plans, not to "best guess." Never invent fallbacks that touch actuators without explicit safety review.
2. **Small, reversible PRs.** No PR larger than ~500 lines of net change. Every PR must be revertable cleanly.
3. **Tests before merge.** Every new behavior ships with tests. Bug fixes ship with a regression test that fails on the unfixed code.
4. **No mocked DB / Kafka in integration tests.** Use Testcontainers (or equivalent) to spin up real Postgres/Kafka in CI.
5. **No new abstractions without two existing call sites.** Don't speculate about future flexibility.
6. **Write ADRs.** Any decision that changes architecture (tech choice, protocol, data model) goes in `docs/adr/NNNN-title.md` before code.
7. **Update the audit.** As you close each gap, mark it `[DONE]` in `docs/PRODUCTION_GAPS.md` (create this file from the audit).
8. **Verify documented claims.** When you touch a subsystem whose docs make a quantitative claim (FPS, accuracy, uptime), re-measure it. If false, update the docs in the same PR.
9. **No `--no-verify`, no destructive git ops, no force-push to main.** Hook failures are signals, not obstacles.
10. **Conventional commits, signed, with co-author trailer.**

## CROSS-CUTTING STANDARDS (set up in Phase A, enforce thereafter)

- **Language baseline:** Python 3.11, `pyproject.toml` per service, `ruff` (lint+format), `mypy --strict` where feasible, `pytest` + `pytest-asyncio`, `coverage` with 80% floor for new code.
- **Logging:** Structured JSON via `structlog`, every log line carries `service`, `trace_id`, `span_id`, `intersection_id` (when applicable).
- **Tracing:** OpenTelemetry SDK, OTLP exporter, traces wrap every Kafka produce/consume and HTTP call.
- **Metrics:** Prometheus, `/metrics` endpoint on every service, four golden signals (latency, traffic, errors, saturation) plus domain SLIs (frames/sec, decision-loop period, NTCIP write success rate, AI-watchdog age).
- **Config:** Pydantic `BaseSettings`, env-driven, validated at startup. Secrets pulled from Vault (or SOPS for on-prem); **never** from `.env` in production.
- **Errors:** Domain exceptions in `shared/atms_common/errors.py`. No bare `except Exception:` outside top-level boundaries.
- **HTTP:** FastAPI, async, `httpx` client with timeouts + retries + circuit breaker (`tenacity` + a small `circuitbreaker` wrapper).
- **Kafka:** `aiokafka` with idempotent producer, manual offset commits, consumer groups per service, dead-letter topic per consumer.

## REPOSITORY HYGIENE (do before Phase A — 1-day cleanup)

(Addresses audit gaps #10, #25, #26, #27, #28)

- [ ] Add `.env` to `.gitignore`. Add `.env.example` with empty values + comments.
- [ ] `git ls-files | grep -E '(venv|__pycache__|\.pt$|Processed_Videos)'` — untrack everything that shouldn't be in version control.
- [ ] Move `realtime_video_processor.py` and `youtube_decision_processor.py` into `services/video-processor/src/` as one consolidated module; delete the duplicate. Keep root scripts only as thin CLI entry points.
- [ ] Move every `docs/PHASE*`, `docs/WEEK*`, `docs/*COMPLETE*.md`, `docs/*STATUS*.md` into `docs/archived/`. Keep only living docs at top level.
- [ ] Create `docs/adr/0001-record-architecture-decisions.md` (Michael Nygard template). Create `docs/PRODUCTION_GAPS.md` populated from the audit.
- [ ] Verify `.gitignore` actually covers `*.pt`, `*.onnx`, `*.mlpackage`, `Processed_Videos/`, `experiments_out/`, `debug_frame.jpg`.

---

## PHASE A — Make It Safe (4–6 weeks)

**Goal:** Prevent the system from causing harm. After Phase A, an AI failure or cloud outage must not freeze a signal, leak credentials, or silently degrade.

### A1. Fail-safe controller and AI watchdog (gap #1) — **highest priority**
- Build `services/traffic-controller/src/failsafe.py` with three modes: `AI_ADAPTIVE` (normal), `FIXED_TIME` (fallback timing plan loaded from config), `ALL_RED_FLASH` (emergency).
- AI watchdog: if no valid decision message received within `MAX_AI_STALENESS_MS` (default 2000ms), transition to `FIXED_TIME`. If three transitions in five minutes, transition to `ALL_RED_FLASH` and page on-call.
- Every decision message must carry a monotonic `decision_id`, `producer_timestamp`, and `valid_until`. Controller rejects decisions past `valid_until`.
- Acceptance: kill the decision-engine pod mid-run; controller must transition to fixed-time within 2s and emit a `mode_transition` metric + structured log. Test via integration harness.

### A2. Real health/readiness/liveness probes (gap #13)
- For every service: `/live` (process up), `/ready` (dependencies reachable: Kafka, DB, model loaded, NTCIP socket bound), `/startup` (long-running init done).
- K8s manifests in `k8s/base/` updated with correct probes, startup timeouts that match model-load reality.
- Acceptance: `kubectl rollout status` succeeds; chaos test (kill Kafka) flips `/ready` to 503 within 5s.

### A3. Tests for safety-critical services (gap #5)
- `services/decision-engine/tests/` and `services/traffic-controller/tests/` must reach 80% line coverage and 100% coverage of state-transition code.
- Property-based tests (`hypothesis`) for the decision policy: invariants like "never green on conflicting phases simultaneously," "minimum green time always honored," "pedestrian clearance never shortened."
- Acceptance: `make test-service SERVICE=decision-engine` and `SERVICE=traffic-controller` both green with ≥80% coverage report.

### A4. GitHub Actions CI (gap #6)
- `.github/workflows/ci.yml`: lint (ruff), typecheck (mypy), unit tests (pytest), integration tests (Testcontainers), container build, image scan (Trivy), SBOM generation (Syft), image signing (cosign).
- Required status checks on `main`; PRs blocked on red CI.
- Acceptance: a deliberately broken PR fails CI; a clean PR passes within ~10 min.

### A5. Secrets out of the repo (gap #10)
- Add `.env` to `.gitignore`; ship `.env.example` with empty values.
- Stand up SOPS + age (lightweight) **or** Vault (full) and document the chosen path in an ADR.
- All services load secrets from the chosen system at startup; no fallback to plaintext files in prod profile.
- Acceptance: `grep -rE '(PASSWORD|SECRET|TOKEN)=\S' --include='*.py' --include='*.yml'` returns no real values; CI step enforces this.

### A6. Wire up JWT + RBAC on every public endpoint (gap #12)
- `security/jwt_handler.py` and `security/middleware.py` already exist — mount them on every FastAPI app in `services/api-gateway/`, `services/dashboard/`, and any other externally reachable surface.
- Define roles: `viewer`, `operator`, `engineer`, `admin`. Decision-mutating endpoints require `engineer+`.
- Acceptance: unauthenticated request to a protected endpoint returns 401; viewer role on a write endpoint returns 403; integration test enforces both.

### A7. Emergency vehicle + pedestrian + ADA flows (gap #3)
- Add `EMERGENCY_VEHICLE` detection class to the perception pipeline (siren-strobe heuristic or class extension to the detector).
- Implement preempt path in decision-engine: on EV detected approaching, force green on EV's approach, all-red on conflicts, restore normal cycle after clearance.
- Pedestrian: accept push-button input via NTCIP MIB (`ped-call`), guarantee minimum walk + flashing-don't-walk per MUTCD timing.
- ADA: emit accessible-walk indication signal (controller MIB), audible/tactile-ready event on the event bus.
- Acceptance: simulated EV scenario in test harness triggers preempt within one decision cycle and restores cleanly.

**Phase A Definition of Done**
- All A1–A7 acceptance criteria met.
- `docs/PRODUCTION_GAPS.md` shows gaps #1, #3, #5, #6, #10, #12, #13, plus repo hygiene items, marked `[DONE]`.
- Runbook `docs/runbooks/failsafe.md` exists explaining all three controller modes and how to recover.
- A red-team-style test (chaos: kill Kafka, kill decision-engine, expire JWT, drop NTCIP packets) is part of CI nightly.

---

## PHASE B — Make It Observable and Consistent (4–6 weeks)

**Goal:** When something goes wrong at 2am, the on-call engineer can find the cause in minutes. After Phase B, every request is traceable, every service speaks the same idiom, and security is uniform.

### B1. Shared library `shared/atms_common/` (gap #9)
- Extract: `Config` (Pydantic settings), `Logger` (structlog wrapper), `Tracing` (OTel bootstrap), `KafkaProducer` / `KafkaConsumer` (idempotent + DLQ), `HealthEndpoints`, `HttpClient` (timeouts/retries/circuit-breaker), `Errors`, `Metrics`.
- Each service replaces its bespoke versions; no service may import logging/Kafka/HTTP directly.
- Acceptance: `grep -rE 'logging\.getLogger|aiokafka\.AIOKafkaProducer\(' services/` returns matches only inside `atms_common`.

### B2. OpenTelemetry tracing end-to-end (gap #7)
- OTel SDK in `atms_common`, OTLP exporter (Tempo or Jaeger), context propagation via Kafka headers (`traceparent`).
- Every Kafka produce/consume, every HTTP call, every model inference is a span.
- Acceptance: pick a random frame in Grafana Tempo; see camera-ingest → detection → tracking → decision → controller → NTCIP write as a single trace.

### B3. Structured logging + log aggregation (gap #8)
- All logs JSON via structlog, fields include `service`, `version`, `trace_id`, `span_id`, `intersection_id`, `decision_id`.
- Ship to Loki (or ELK if already in infra); Grafana dashboards for log volume per service.
- Acceptance: query "decisions affecting intersection X in the last 10 minutes" returns a coherent timeline across all services.

### B4. Resilience patterns everywhere (gap #14)
- `tenacity` retries with exponential backoff + jitter on all Kafka/DB/HTTP/NTCIP calls.
- Circuit breaker around NTCIP writes and external dependency calls.
- Bulkheads (separate thread/async pools) for AI inference vs control loop so one cannot starve the other.
- Per-call timeouts; no unbounded `await`.
- Acceptance: chaos test (introduce 50% packet loss to NTCIP) — system degrades gracefully, breaker opens, fail-safe engages, no thread starvation.

### B5. mTLS between services (gap #11)
- Install Linkerd (lightest mesh; or Istio if already chosen). Auto-injected sidecars, identity per service, automatic certificate rotation.
- Service-to-service NetworkPolicies in `k8s/base/network-policies/` (currently empty) — default deny, explicit allow.
- Acceptance: `linkerd viz authz` shows every cross-service edge is mTLS-encrypted and authorized; an unauthorized pod cannot reach decision-engine.

**Phase B Definition of Done**
- Gaps #7, #8, #9, #11, #14 marked `[DONE]`.
- Single Grafana dashboard ("ATMS Overview") shows traffic, latency, errors, saturation across all services.
- Service code-base has uniform structure: `services/<name>/src/{api,config,domain,adapters}/`, `tests/{unit,integration}/`, `Dockerfile`, `pyproject.toml`.
- `docs/architecture/overview.md` updated with current state diagram and traced dataflow.

---

## PHASE C — Make It Real (8–12 weeks)

**Goal:** Behave correctly when connected to real traffic-controller hardware, real cameras, and an unreliable WAN. After Phase C, a pilot intersection is feasible.

### C1. NTCIP 1202/1203 conformance + real hardware (gap #2)
- Implement real SNMP GET/SET against the NTCIP 1202 MIB (phase status, phase control, detector status, ped-call, preempt). Use `pysnmp` or equivalent.
- Build a conformance test suite that exercises every MIB OID the system reads or writes; run nightly in CI against a virtual controller (e.g., `econolite-virtual` or a SUMO-coupled stub).
- IPsec or Wireguard overlay between controller and ATMS edge node (NTCIP itself is unencrypted).
- Hardware-in-the-loop test with at least one real controller model (Econolite Cobalt, McCain ATC, or Siemens M60) before claiming Phase C done.
- Acceptance: green-yellow-red-walk cycle on real hardware driven by ATMS for 24h with zero protocol errors, full audit log.

### C2. Edge / offline mode (gap #4)
- New service `services/edge-agent/` deployable to a small box (NVIDIA Jetson / Intel NUC) physically at the intersection.
- Edge agent: local YOLOv8 inference, local fail-safe controller, local fixed-time plans, local 24h decision buffer.
- Cloud sync: when WAN up, edge ships telemetry and pulls policy updates. When WAN down, edge operates autonomously indefinitely.
- Cloud's role narrows to: coordination across intersections, analytics, model distribution. Cloud is **never** in the actuation path.
- Acceptance: pull network cable from edge box for 1 hour; intersection continues operating safely; on reconnect, telemetry backfills and policy diffs apply cleanly.

### C3. Simulation harness — SUMO or CARLA (gap #24)
- Wire `services/decision-engine` to a SUMO simulator (lighter than CARLA, sufficient for signal-control policy testing).
- Build replay scenarios: rush hour, accident-induced congestion, EV preempt, ped-button storm, weather degradation, camera failure.
- Every PR that touches decision logic must show simulation deltas (avg delay, max queue, throughput, conflict count) vs baseline.
- Acceptance: `make simulate SCENARIO=rush-hour` produces a reproducible HTML report with KPIs.

### C4. TimescaleDB migration (gap #18)
- Add TimescaleDB extension to Postgres; convert detection/measurement tables to hypertables with retention + continuous aggregates.
- Alembic for schema migrations (replace raw `.sql` runner).
- Acceptance: 1M synthetic detections written in <60s; 24h rollup query <2s; old data auto-drops per retention policy.

### C5. Time synchronization (gap #20)
- NTP at the system level baseline; PTP (IEEE 1588) on the edge subnet between camera, edge agent, and controller where hardware supports it.
- Every frame timestamp uses a monotonic source corrected against PTP/NTP; `time.time()` is forbidden in the decision path.
- Acceptance: multi-camera scenario shows <10ms cross-camera timestamp skew under load.

### C6. Camera calibration drift handling (gap #21)
- Auto-recalibration job runs daily per camera using detected lane markings / fixed scene features.
- Emit `calibration_confidence` metric; alert when below threshold for >24h.
- Acceptance: deliberately nudge a test camera by 2°; system detects drift within one cycle, raises alert, and re-calibrates.

### C7. Weather / lighting adaptation (gap #22)
- Integrate a weather API (OpenWeatherMap or local DOT source) per intersection.
- Adjust detection thresholds and decision-policy aggressiveness based on visibility (rain/fog) and lighting (dawn/dusk/night).
- Train or fine-tune a night-specific model; switch via the model registry (Phase D).
- Acceptance: A/B replay of the same traffic under day vs simulated night shows the system holds detection recall ≥90% on both.

### C8. V2X stub interface (gap #23)
- `services/v2x-interface/` skeleton consuming SAE J2735 BSM messages over MQTT (simulated for now), publishing into the event bus.
- Decision-engine can optionally weight V2X-reported vehicles alongside camera-detected ones.
- Acceptance: simulated BSM stream from a SUMO scenario contributes correctly to the decision input set; no impact when feed is absent.

**Phase C Definition of Done**
- Gaps #2, #4, #18, #20, #21, #22, #23, #24 marked `[DONE]`.
- A pilot-readiness review document exists (`docs/pilot-readiness.md`) signed off by safety review.
- 7-day soak test on hardware-in-the-loop completes with zero safety incidents.

---

## PHASE D — ML Maturity (ongoing)

**Goal:** Models improve continuously without anyone manually swapping `.pt` files. After Phase D, model updates are routine, auditable, and reversible.

### D1. Model registry + model serving (gap #15)
- Stand up MLflow Tracking + Model Registry (or BentoML / Triton if preferred — record choice in ADR).
- All models (`yolov8n.pt`, license plate, multiview, RL agent) versioned in the registry with metadata: training dataset hash, eval metrics, intended use, approved environments.
- Serving via Triton Inference Server (GPU-shareable) or BentoML; perception service calls the model server, never loads a `.pt` itself.
- Rollout: shadow → 1 canary intersection → 10% → 100%, with automated rollback on metric regression.
- Acceptance: promote a new detection model from registry to one canary intersection via a single CLI command; rollback within 30s if recall drops >5%.

### D2. Drift detection (gap #16)
- Production drift monitor: tracks input distribution (image brightness/contrast histograms) and output distribution (class mix, confidence histogram) vs a reference set.
- Nightly accuracy regression: replay a held-out labeled set, compare mAP/precision/recall to last-known-good, alert on regression >threshold.
- Acceptance: a deliberately degraded model fails the nightly eval and is blocked from promotion.

### D3. Retraining + labeling pipeline (gap #17)
- Continuous data collection from production (opt-in, anonymized per Phase D4) into a labeling queue.
- Labeling tool: Label Studio (self-hosted) or CVAT. Active learning picks uncertain frames.
- Scheduled retrain (weekly or on data threshold) → eval → registry promotion candidate.
- Acceptance: end-to-end retrain triggered from labeled batch produces a registered model artifact with full lineage.

### D4. Data retention and privacy (gap #19)
- License plate text anonymized by default (`PlateAnonymizer` on by default; raw plates only with explicit warranted-access role + audit log).
- Per-data-type TTL policy: raw video 7 days, anonymized detections 90 days, aggregated metrics 2 years (configurable per municipal contract).
- DSAR (Data Subject Access Request) endpoint: given a plate or face hash, return/erase all records.
- Encryption at rest for raw video; KMS-managed keys.
- Acceptance: DSAR test request returns within SLA; audit log shows every raw-plate access; storage usage shrinks per TTL after 1 week.

**Phase D Definition of Done**
- Gaps #15, #16, #17, #19 marked `[DONE]`.
- A model can go from "new training data" → "deployed and serving 100% of traffic" with no manual file copying, full audit trail, automated rollback path.
- Privacy posture passes a documented review (GDPR/CCPA checklist in `docs/privacy.md`).

---

## DELIVERABLES PER PHASE

Each phase ends with:
1. **PR series** (small, reviewable, each green in CI) — merged to `main`.
2. **Updated `docs/PRODUCTION_GAPS.md`** with the closed gaps marked `[DONE]` and dated.
3. **ADRs** in `docs/adr/` for every architectural decision made.
4. **Runbooks** in `docs/runbooks/` for every new operational capability (fail-safe modes, mTLS cert rotation, model rollback, DSAR handling, etc.).
5. **Phase report** in `docs/phase-reports/phase-{A,B,C,D}.md`: what shipped, what got cut, what to watch in production, measured KPIs.
6. **Demo**: live walkthrough of new capabilities (chaos test, trace query, simulation run, model rollout — appropriate to phase).

## OUT OF SCOPE (do not start)

- Mobile apps, public-facing dashboards beyond the existing one, marketing site, billing/SaaS multitenancy.
- Rewrites in another language. Stay in Python until you have evidence (profiling, sustained CPU >80%) that Rust/Go is justified for a specific service.
- New ML model architectures unless an existing model fails a documented benchmark.
- Refactors that aren't on the gap list.

## WHAT TO DO FIRST

1. Read this entire prompt.
2. Read `docs/PROJECT_REPORT.md`, `atms_config.py`, `services/decision-engine/src/main.py`, `services/traffic-controller/src/main.py`, `services/ai-perception/src/main.py` — these define the current contract.
3. Run repo hygiene (1 day).
4. Open a PR for **Phase A, task A1 (fail-safe controller)** — the single most important gap. Do not parallelize until A1 is merged.
5. From A2 onward you may parallelize within a phase but never across phases.

## QUESTIONS YOU MUST ANSWER BEFORE STARTING (write down assumptions in `docs/assumptions.md`)

- Which jurisdictions will the pilot run in? (Drives MUTCD/local-DOT compliance specifics.)
- Which controller hardware will the pilot use? (Drives NTCIP MIB specifics.)
- Cloud or on-prem K8s? (Drives mesh choice, secrets choice.)
- GDPR or CCPA or both? (Drives privacy work in D4.)
- Who is the safety-review authority? (Drives sign-off process at end of Phase C.)

If you don't have answers, **stop and ask the product owner before writing code that depends on them.**

---

**End of prompt.**
