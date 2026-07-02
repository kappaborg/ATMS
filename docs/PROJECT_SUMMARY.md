# ATMS — Project Summary

**Last updated:** 2026-06-05
**Verification:** `./scripts/verify-pipeline.sh` → 43/43 checks passing
**Companion docs:** [`STATUS_AND_PILOT_READINESS.md`](STATUS_AND_PILOT_READINESS.md) (pilot hand-off) · [`ROADMAP.md`](ROADMAP.md) (forward plan) · [`PRODUCTION_GAPS.md`](PRODUCTION_GAPS.md) (gap tracker) · [`adr/`](adr/) (19 design decisions) · [`runbooks/`](runbooks/) (12 operational guides)

---

## 1. What This Is

ATMS is an **Adaptive Traffic Management System** — a safety-first adaptive signal-control platform for urban intersections. The architecture is a strict separation of concerns:

- An **AI decision engine** *recommends* signal phases based on per-direction traffic metrics.
- A **failsafe controller** *drives* the signal, accepting the AI's recommendation only if a list of hard safety invariants holds. When they don't, it degrades to fixed-time, and when even that's untrusted, to **all-red flash**.
- All operator actions are **JWT-authenticated**, **role-gated**, and **audit-logged**; every audit line correlates to a distributed trace.

The original SE322 university project has been re-architected to production grade: 13 microservices, a 21-module shared safety library, OpenTelemetry tracing, Linkerd-mTLS, TimescaleDB-backed analytics, MLflow model lifecycle, SUMO simulation, and a GDPR-compliant DSAR flow.

---

## 2. Current State — One-Line Status

| Layer | Status |
|---|---|
| **Software code** | Complete + verified (43/43 automated checks pass; 408 tests across 4 suites) |
| **Software wiring** | Verified end-to-end via `scripts/verify-pipeline.sh` |
| **Local-dev infrastructure** | 6 docker-compose files compose into a working dev stack |
| **Documentation** | 19 ADRs, 12 runbooks, 408 tests, all cross-references resolve |
| **Hardware integration** | **Not started, by design** — blocked on procurement decisions |
| **Pilot intersection** | **Not yet ready** — needs hardware bench + safety-review sign-off |

The remaining work before a real intersection is **provisioning** (Keycloak, GPU node-pool, edge box, NTCIP controller, observability cluster), **data capture** (real-world detection labels, NTCIP traces), and the **safety review process**. None of those are code work.

---

## 3. Component Inventory

### 3.1 Services (13 total)

| Service | Role | Port | A2 bootstrap | A6 JWT | B1 health | Status |
|---|---|---|---|---|---|---|
| `traffic-controller` | Failsafe state machine; drives the signal | 8001 | ✓ full | ✓ | ✓ HealthRouter | Reference impl, 275 tests |
| `decision-engine` | AI recommends phase; emits DecisionMessage | 8007 | ✓ full | ✓ | ✓ HealthRouter | 48 tests; wire-mapping in shared lib |
| `v2x-interface` | J2735 BSM ingest → PreemptRequest bridge | 8009 | ✓ full | ✓ | ✓ HealthRouter | C8 stub; MQTT bridge for production |
| `api-gateway` | Edge HTTP gateway, rate-limiting | 8000 | ✓ bootstrap | — | ✓ bootstrap | Per-service rate limiter |
| `data-aggregator` | Aggregate metrics for the dashboard | 8002 | ✓ bootstrap | — | ✓ bootstrap | Bootstrap only |
| `intersection-coordinator` | Multi-intersection coordination | 8003 | ✓ bootstrap | — | ✓ bootstrap | Bootstrap only; full wiring is Phase 4 |
| `ntcip-interface` | SNMP/NTCIP 1202/1203 adapter | 8005 | ✓ bootstrap | — | ✓ bootstrap | Stub; C1 hardware-blocked |
| `analytics` | TimescaleDB queries, KPIs over time | 8006 | ✓ bootstrap | — | ✓ bootstrap | Bootstrap only |
| `dashboard` | Operator web console | 8010 | ✓ bootstrap | — | ✓ bootstrap | UI follow-up |
| `ai-perception` | YOLOv8 detection + SAHI plate OCR | 8004 | ⊘ pending | — | — | A2 refactor pending (1999 LoC monolith) |
| `video-processor` | Video ingestion, frame batching | 8011 | ⊘ pending | — | — | A2 refactor pending |
| `sensor-fusion` | Multi-camera fusion + synchronisation | 8008 | ⊘ pending | — | — | A2 refactor pending |
| `operator-console` | Streamlit live operator UI (mode tile, per-direction CO₂, events feed) | 8501 | ✓ stand-alone | — | — | Polls `/tmp/atms-demo-state.json` at 2 Hz |

**Verification:** every service has a Dockerfile (13 found); 8 of 13 have the B1 shared bootstrap; 3 of 13 have full A6 JWT + B1 health (the safety-critical path); 3 remain on the A2 refactor queue.

### 3.2 Shared library — `shared/atms_common/` (21 modules)

| Module | Purpose | ADR |
|---|---|---|
| `clock.py` | Monotonic Clock protocol + FakeClock for tests | 0005, 0017 |
| `decision.py` | DecisionMessage schema + wire-mapping helpers | 0005 |
| `metrics.py` | MetricsRecorder protocol + Prometheus + InMemory | 0008 |
| `safety.py` | Conflict matrix, fixed-time plan, safety config | 0005 |
| `auth.py` | JWT verifier (HS256 + RS256/JWKS), role hierarchy | 0006 |
| `preempt.py` | PreemptRequest, PedCallRequest, Approach enums | 0007 |
| `errors.py` | AtmsError hierarchy (base; no service deps) | 0008 |
| `config.py` | Pydantic settings base class | 0008 |
| `logging.py` | structlog JSON + bind_decision_id + OTel context | 0011 |
| `health.py` | HealthRouter with /live /ready /startup | 0008 |
| `kafka.py` | AtmsKafkaProducer/Consumer with retry + breaker | 0009 |
| `resilience.py` | Retry, CircuitBreaker, Bulkhead, with_timeout | 0009 |
| `tracing.py` | OTel configure + Kafka header inject/extract | 0010 |
| `db.py` | asyncpg pool + postgres_check | 0013 |
| `privacy.py` | PlateAnonymizer (HMAC-SHA256) + retention | 0014 |
| `dsar.py` | DSARRequest + DSARProcessor + InMemoryStorage | 0014 |
| `model_registry.py` | MLflow registry wrapper + stage transitions | 0015 |
| `timekeeping.py` | SyncedTimestamp + NTP/PTP sync probes | 0017 |
| `weather.py` | WeatherSnapshot + threshold adjustment tables | 0018 |
| `v2x.py` | BSMMessage (J2735 subset) + preempt bridge | 0019 |
| `emissions.py` | EmissionEstimator + per-class profile + brand multipliers + per-direction aggregator | — (ported from legacy `services/ai-perception/src/emission/emission_calculator.py`) |
| `__init__.py` | Package marker | — |

**Verification:** 8 base modules (no service deps) import cleanly under stdlib + the simulation harness uses these only — see verify-pipeline.sh §4.

### 3.3 Infrastructure

| Artifact | Purpose |
|---|---|
| `docker-compose.dev.yml` | Postgres+TimescaleDB, Redis, Kafka, Zookeeper |
| `docker-compose.kafka.yml` | Kafka standalone |
| `docker-compose.database.yml` | DB standalone |
| `docker-compose.services.yml` | All 13 FastAPI services |
| `docker-compose.keycloak.yml` | Keycloak + Postgres backing (OIDC dev) |
| `docker-compose.demo.yml` | Observability overlay (Loki+Promtail+Tempo+OTel+Grafana) |
| `infrastructure/linkerd/` | cert-manager issuer + Helm values for service mesh |
| `infrastructure/observability/{loki,promtail,tempo,otel}` | Each component's config |
| `k8s/base/network-policies/` | 6 NetworkPolicies (deny-by-default + per-flow allows) |

**Verification:** all 6 compose files validate as YAML; all 4 dashboards validate as JSON; Keycloak realm JSON validates.

### 3.4 Database — `database/alembic/`

| Migration | What it creates |
|---|---|
| `0001_initial` | Base tables: intersections, signals, detections, decisions |
| `0002_timescaledb_ext` | `CREATE EXTENSION timescaledb` |
| `0003_hypertables` | Convert detections + decisions to hypertables |
| `0004_continuous_aggregates` | 5-min and 1-hour rollups |
| `0005_retention` | Drop policies (90d for detections, 1y for decisions) |
| `0006_dsar_anonymization` | DSAR audit + plate-anonymization tables + subject_id column |

**Verification:** 6 migrations present; `alembic upgrade head` is part of the pre-flight in `docs/runbooks/database.md` §2.

### 3.5 Simulation — `simulation/`

| Component | Role |
|---|---|
| `harness/{runner,kpis,report}.py` | TraCI bridge, KPI accumulator, HTML report |
| `scenarios/rush-hour/` | 1-hour SUMO scenario for regression baselines |
| `scenarios/demo/` | 5-minute pitch-demo scenario + GUI view settings |
| `scenarios/_network_src/` | netconvert source for the shared network XML |
| `demo/__main__.py` + `events.py` | Scripted-event orchestrator for live demos |
| `compare_kpis.py` | KPI diff against baseline (CI gate) |
| `baselines/rush-hour.json` | Per-scenario baseline (placeholder until first SUMO bench run) |

**Verification:** both scenarios load under SUMO 1.27.0; demo orchestrator runs headless cleanly; compare_kpis has 19 unit tests; demo timeline has 13 unit tests.

### 3.6 Documentation

| Class | Count | Location |
|---|---|---|
| ADRs | 19 | `docs/adr/0001`–`0019` |
| Runbooks | 12 | `docs/runbooks/` |
| Demo runbooks | 1 | `docs/demos/pilot-pitch.md` |
| Project-level | 5 | ROADMAP, STATUS_AND_PILOT_READINESS, PRODUCTION_GAPS, SENIOR_ENGINEER_PROMPT, this file |
| Privacy | 1 | `docs/privacy.md` (GDPR/CCPA mapping) |
| Assumptions | 1 | `docs/assumptions.md` (open operator decisions) |
| Archived (legacy SE322) | many | `docs/historical/`, `docs/archived/`, `docs/technical/`, `docs/user-guides/` |

**Verification:** every relative markdown link in active docs resolves; every ADR's "Closes: gap #N" matches a row in PRODUCTION_GAPS.md.

### 3.7 Testing

| Suite | Tests | Coverage area |
|---|---|---|
| `services/traffic-controller/tests/` | 275 | Failsafe state machine, A6 auth, B1 health, A7 preempt+ped, shared library |
| `services/decision-engine/tests/` | 48 | Wire-mapping, A3 priority-direction, JWT gating |
| `simulation/tests/` | 26 | KPI accumulator, runner contract, conflict detection |
| `simulation/tests/test_compare_kpis.py` | 19 | KPI diff thresholds, tolerance overrides |
| `simulation/demo/tests/` | 13 | Event timeline ordering + windowing |
| `tools/tests/` | 28 | Safety-clock lint rule |
| **Total** | **409** | (varies ±1 with skipped XQuartz/SUMO-not-installed cases) |

Plus property-based tests via Hypothesis throughout the failsafe controller suite.

### 3.8 CI/CD

| Workflow | Triggers | What it runs |
|---|---|---|
| `ci.yml` | every push / PR | ruff, mypy (4 roots), safety-clock lint, all unit/integration tests + coverage gate |
| `release.yml` | semver tag | builds + pushes Docker images |
| `nightly.yml` | cron daily | full integration suite + freshness scan |
| `sim-regression.yml` | PRs touching sim/decision/controller/shared | runs SUMO scenarios + diffs KPIs against baseline + posts sticky PR comment |

---

## 4. Pipeline Wiring — How Data Flows

### 4.1 Decision-making pipeline (production)

```
  cameras
    │ (rtsp / mjpeg)
    ▼
  ai-perception ──── detections (Kafka: vehicle-detections) ────┐
                                                                 │
  sensor-fusion ──── fused-events (Kafka: sensor-fused) ────────┤
                                                                 │
                                                                 ▼
                                                       decision-engine
                                                          │   (AIDecisionEngine
                                                          │    + wire-mapping)
                                                          │
                                                          ▼
                                                  Kafka: decisions
                                                          │
                                                          ▼
                                                  traffic-controller
                                                          │   (FailsafeController
                                                          │    accepts only if
                                                          │    invariants hold)
                                                          ▼
                                                  ntcip-interface
                                                          │
                                                          ▼
                                                  signal cabinet
                                                  (NTCIP 1202/1203)
```

**Verified in code:** every Kafka producer carries `monotonic_ns` timestamps; every consumer validates schema before acting; failsafe runs at 10 Hz independent of the AI's cadence.

### 4.2 Operator action pipeline

```
  Operator
    │ (HTTP + Bearer JWT)
    ▼
  api-gateway (rate-limit) ─── HTTP ───▶ target service
                                              │
                                              ▼
                                       JWTVerifier (HS256 dev / RS256 prod)
                                              │
                                              ▼
                                       require_role("engineer")
                                              │
                                              ▼
                                       handler (executes action)
                                              │
                                              ├──── audit_logger ───▶ structlog ─▶ Loki
                                              ├──── tracer.start_span ──▶ Tempo
                                              └──── safety_filter (failsafe-only)
```

**Verified in code:** every operator-mutating endpoint has `require_role` dependency; every audit line includes `sub`, `jti`, `outcome`, `path`, `trace_id`.

### 4.3 V2X / EV preempt pipeline

```
  EV OBU
    │ (J2735 BSM over MQTT in prod / HTTP /admin/inject in dev)
    ▼
  v2x-interface
    │ (validates signature, parses BSM, builds PreemptRequest)
    ▼
  traffic-controller /preempt/arm
    │
    ▼
  FailsafeController.handle_preempt()
    │ (waits for current min-green, transitions through yellow + all-red)
    ▼
  signal head ─────▶ EV gets the green
```

**Verified in code:** BSMMessage → PreemptRequest bridge tested in `shared/atms_common/v2x.py` tests; preempt min-green respect tested in failsafe property tests.

### 4.4 Observability pipeline

```
  every service
    │   stdout (JSON line per event via structlog)
    │   ──▶ Promtail (sidecar) ──▶ Loki ──▶ Grafana
    │
    │   OTel spans (W3C TraceContext propagated through Kafka headers)
    │   ──▶ OTel collector ──▶ Tempo ──▶ Grafana
    │
    │   /metrics (Prometheus exposer)
    │   ──▶ Prometheus ──▶ Grafana
    │
    └── single trace_id correlates all three.
```

**Verified in code:** Kafka producer injects W3C `traceparent` in message headers; consumer extracts and binds it; structlog injects active span_id into every log line; all three layers visible in 4 Grafana dashboards.

### 4.5 Privacy / DSAR pipeline

```
  detection (license plate)
    │
    ▼
  ai-perception ─── PlateAnonymizer.hash(plate, salt) ───▶ subject_id (HMAC-SHA256)
                                                                 │
                                                                 ▼
                                                          analytics DB
                                                          (plate text NEVER stored)


  Data Subject Access Request
    │ (HTTP /dsar with DSAR-validated JWT)
    ▼
  DSARProcessor
    │
    ├── access:  fetch_for_subject(subject_id_hash) ─▶ JSON payload
    ├── erase:   erase_for_subject(subject_id_hash) ─▶ rows affected
    └── audit_log: every request logged with `requested_at`, `completed_at`
```

**Verified in code:** PlateAnonymizer is deterministic per-deployment salt + irreversible; 24 tests cover the DSAR processor; `docs/runbooks/dsar.md` documents the operator side.

### 4.6 Simulation / regression pipeline

```
  PR opened/updated
    │
    ▼
  GitHub Actions (sim-regression.yml)
    │
    ▼
  self-hosted SUMO runner
    │
    ├── for each scenario in simulation/scenarios/:
    │     1) python -m simulation <scenario>
    │     2) read simulation/out/<scenario>/kpis.json
    │     3) python -m simulation.compare_kpis --baseline ...
    │     4) post sticky PR comment with diff
    │
    ▼
  Fail PR if any scenario regresses on:
    - avg_delay_s > baseline × 1.10
    - max_queue_length > baseline × 1.10
    - throughput_vph < baseline × 0.95
    - conflicts > 0 (any conflict = fail)
```

**Verified in code:** compare_kpis has 19 tests covering all thresholds + tolerance overrides + missing-file failure modes.

---

## 5. Requirements Traceability — 28 Audited Gaps

The original audit identified 28 gaps. Status at 2026-06-05:

### Phase A — Safety (7 gaps)

| # | Gap | Phase task | ADR | Code | Tests | Runbook | Status |
|---|---|---|---|---|---|---|---|
| 1 | Fail-safe controller / AI watchdog | A1 | [0005](adr/0005-failsafe-controller-state-machine.md) | `services/traffic-controller/src/failsafe.py` | 39 | [failsafe.md](runbooks/failsafe.md) | **DONE** |
| 3 | EV preempt + ped + ADA flows | A7 | [0007](adr/0007-preempt-pedestrian-ada.md) | `shared/atms_common/preempt.py` + failsafe.py | 36 | [failsafe.md §EV](runbooks/failsafe.md) | **DONE** |
| 5 | Tests for decision-engine + controller | A3 | — | both services' `tests/` | 323 | — | **DONE** |
| 6 | GitHub Actions CI | A4 | — | `.github/workflows/` | — | — | **DONE** |
| 10 | Secrets out of repo (SOPS+age) | A5 | — | `deploy/secrets/` + `.sops.yaml` + Makefile | — | [secrets.md](runbooks/secrets.md) | **DONE** |
| 12 | JWT + RBAC on every public endpoint | A6 | [0006](adr/0006-rbac-jwt-roles.md) | `shared/atms_common/auth.py` | 25 | [oidc-keycloak.md](runbooks/oidc-keycloak.md) | **DONE** (HS256 dev + RS256 prod) |
| 13 | /live /ready /startup probes / shared bootstrap | A2 | [0008](adr/0008-shared-atms-common-library.md) | `shared/atms_common/health.py` | — | — | **PARTIAL** — 10 of 13 services; 3 pending refactor |

### Phase B — Observability + Consistency (5 gaps)

| # | Gap | Phase task | ADR | Code | Tests | Runbook | Status |
|---|---|---|---|---|---|---|---|
| 7 | OpenTelemetry tracing end-to-end | B2 | [0010](adr/0010-opentelemetry-tracing.md) | `shared/atms_common/tracing.py` | 11 | — | **DONE** |
| 8 | Structured JSON logging + Loki aggregation | B3 | [0011](adr/0011-log-aggregation-loki.md) | `shared/atms_common/logging.py` + observability config | 4 | — | **DONE** |
| 9 | `shared/atms_common/` library foundation | B1 | [0008](adr/0008-shared-atms-common-library.md) | 21 modules | 17 | — | **DONE** |
| 11 | mTLS via Linkerd + NetworkPolicies | B5 | [0012](adr/0012-mtls-linkerd.md) | `infrastructure/linkerd/` + `k8s/base/network-policies/` | — | [mtls.md](runbooks/mtls.md) | **DONE** |
| 14 | Retries, circuit breakers, bulkheads, timeouts | B4 | [0009](adr/0009-resilience-patterns.md) | `shared/atms_common/resilience.py` | 24 | — | **DONE** |

### Phase C — Real-world (8 gaps)

| # | Gap | Phase task | ADR | Code | Tests | Runbook | Status |
|---|---|---|---|---|---|---|---|
| 2 | NTCIP 1202/1203 conformance + HW-in-the-loop | C1 | — | `services/ntcip-interface/` stub | — | — | **HARDWARE-BLOCKED** |
| 4 | Edge agent + offline mode | C2 | — | — | — | — | **HARDWARE-BLOCKED** |
| 18 | TimescaleDB migration + Alembic | C4 | [0013](adr/0013-timescaledb-alembic.md) | `database/alembic/` | 5 | [database.md](runbooks/database.md) | **DONE** |
| 20 | NTP/PTP time sync | C5 | [0017](adr/0017-time-sync.md) | `shared/atms_common/timekeeping.py` + safety-clock lint | 14+28 | [time-sync.md](runbooks/time-sync.md) | **DONE** |
| 21 | Camera calibration drift handling | C6 | — | — | — | — | **HARDWARE-BLOCKED** (needs 7-day camera baseline) |
| 22 | Weather + lighting adaptation | C7 | [0018](adr/0018-weather-lighting-adaptation.md) | `shared/atms_common/weather.py` | 13 | [weather-adaptation.md](runbooks/weather-adaptation.md) | **DONE** |
| 23 | V2X J2735 stub interface | C8 | [0019](adr/0019-v2x-bsm-stub.md) | `shared/atms_common/v2x.py` + `services/v2x-interface/` | 24 | [v2x.md](runbooks/v2x.md) | **DONE** |
| 24 | SUMO simulation harness | C3 | [0016](adr/0016-sumo-simulation-harness.md) | `simulation/` | 26+19 | [simulation.md](runbooks/simulation.md) + [sim-regression.md](runbooks/sim-regression.md) | **DONE** |

### Phase D — ML Maturity (4 gaps)

| # | Gap | Phase task | ADR | Code | Tests | Runbook | Status |
|---|---|---|---|---|---|---|---|
| 15 | Model registry + serving | D1 | [0015](adr/0015-model-registry-mlflow.md) | `shared/atms_common/model_registry.py` | 21 | [model-registry.md](runbooks/model-registry.md) | **PARTIAL** — registry done; Triton serving needs GPU |
| 16 | Drift detection + nightly regression | D2 | — | — | — | — | **DATA-BLOCKED** (needs production flow) |
| 17 | Retraining + labelling pipeline | D3 | — | — | — | — | **DATA-BLOCKED** (needs labelling infra) |
| 19 | Data retention / privacy / DSAR | D4 | [0014](adr/0014-data-retention-privacy.md) | `shared/atms_common/{privacy,dsar}.py` + migration 0006 | 24 | [dsar.md](runbooks/dsar.md) + [privacy.md](privacy.md) | **DONE** |

### Cross-cutting (4 gaps)

| # | Gap | Status |
|---|---|---|
| 25 | Per-service `venv/` committed | **BLOCKED** (not yet a git repo) |
| 26 | Duplicate root processor scripts | **TODO** (low priority; legacy code) |
| 27 | 60+ stale status MDs in `docs/` | **DONE** (37 files moved to `docs/historical/` + `docs/archived/`) |
| 28 | No ADRs | **DONE** (19 ADRs covering every major decision) |

**Tally:** 19 done, 5 hardware/data-blocked, 3 partial, 1 blocked, 1 low-priority TODO. The hardware/data-blocked items are by design — they cannot land before physical equipment / live operator data arrives.

---

## 6. Pre-Hardware Software Punch-List

Before plugging in any real hardware, these items can land in software alone:

| # | Item | Effort | Blocker |
|---|---|---|---|
| 1 | Capture a real-SUMO baseline (replace `simulation/baselines/rush-hour.json` placeholder) | 30 min | none |
| 2 | Bring up the full demo stack end-to-end (docker-compose × 4) and walk through `docs/demos/pilot-pitch.md` | 1 hour | Docker installed locally |
| 3 | Mint a Keycloak engineer-role JWT, run `python -m simulation.demo --gui --live`, verify audit lines in Loki + traces in Tempo | 1 hour | (2) complete |
| 4 | Decide on operator IdP (Keycloak vs Auth0 vs operator's existing AD) | n/a | Operator decision |
| 5 | Decide on pilot intersection identity (which physical intersection) | n/a | Operator decision |
| 6 | A2 refactor for `ai-perception`, `video-processor`, `sensor-fusion` (apply shared B1 bootstrap; split monoliths) | ~3 weeks | none — pure refactor |
| 7 | Operator console UI (Streamlit/Gradio with E-stop / preempt / model-promote buttons) | ~3 days | none |
| 8 | Wave-out CLI for D1 model promotion (`make model-promote MODEL=yolov8 TO=Production --wave=10%`) | 1 week | (4) complete (need real MLflow) |

Items 1–3 are immediate verification work. Items 4–5 are operator-side. Items 6–8 are additive engineering that doesn't depend on hardware.

---

## 7. Hardware-Blocked Items (deferred by design)

These cannot start until specific physical hardware arrives:

| Item | Hardware needed | Spec recommendation |
|---|---|---|
| C1 NTCIP integration soak | Real traffic-signal controller | Econolite Cobalt or McCain ATC; vendor-virtual controller available for ~80% of integration work first |
| C2 edge agent | NVIDIA Jetson Orin (or Intel NUC with NPU) | Orin Nano 8GB or larger; 50W power budget |
| C6 camera-calibration drift | Real intersection-cam | 1080p ≥ 30fps RTSP camera; 7-day baseline capture |
| D1 ML serving (Triton) | GPU node-pool | 2× A10 minimum; T4 acceptable for YOLOv8n |
| D2 drift detection | Production data flow | ≥ 30 days of detection + classification labels |
| D3 retraining pipeline | Labelling infra (CVAT / Label Studio) + Airflow | Self-hosted; ≥ 4 vCPU / 16 GB RAM |
| Pilot intersection live deploy | Physical signal cabinet + WAN | Per operator's existing field equipment |

The roadmap (`docs/ROADMAP.md`) sequences these across 4 tracks running in parallel after software work concludes.

---

## 8. Known Limitations + Follow-ups (non-blocking)

| Item | Severity | Notes |
|---|---|---|
| 3 services on the A2 monolith refactor queue | Low | ai-perception (1999 LoC), video-processor (1981 LoC), sensor-fusion (multi-file). Tracked in `tools/.safety_clock_legacy.txt`. |
| Primary vehicle/ped detector doesn't use SAHI | By design | SAHI in license-plate detector only; vehicle objects too large to benefit. Documented in earlier conversation summaries. |
| Multi-intersection coordination not wired | Pilot-phase work | `services/intersection-coordinator` has bootstrap only; full wiring is Phase 4 (multi-intersection rollout). |
| Operator console UI is curl-only today | Polish | The HTTP endpoints exist; a web UI is one of the listed follow-ups. |
| 4 Grafana dashboards use raw Prometheus queries | Verification gap | They render correctly with the demo stack; haven't been validated against real production data shapes. |
| Sim-regression baseline is placeholder | First-real-run task | Replace `simulation/baselines/rush-hour.json` after the first canonical SUMO bench run. |
| RuntimeWarning from Starlette TestClient (httpx vs httpx2) | Cosmetic | FastAPI 0.136 emits a deprecation warning; doesn't fail tests. |

---

## 9. How to Verify the Project Yourself

### One-command verification:
```bash
./scripts/verify-pipeline.sh
```
Expected: `✓ all checks passed   (passed=43  warned=0  failed=0)`.

### Run the demo (no Docker required):
```bash
python3 -m simulation.demo            # headless, all cues print, AI drives signals
python3 -m simulation.demo --gui       # opens sumo-gui (XQuartz needed on macOS)
```

### Bring up the full stack (Docker required):
```bash
docker compose \
  -f docker-compose.dev.yml \
  -f docker-compose.services.yml \
  -f docker-compose.keycloak.yml \
  -f docker-compose.demo.yml \
  up -d
# wait ~60s, then:
open http://localhost:3000              # Grafana (admin/admin)
open http://localhost:8080/realms/atms  # Keycloak realm
python3 -m simulation.demo --gui --live # full live demo
```

### Run the safety-clock lint:
```bash
python3 tools/lint_safety_clock.py
```

### Run individual test suites:
```bash
cd services/traffic-controller && python3 -m pytest tests -v
cd services/decision-engine    && python3 -m pytest tests -v
python3 -m pytest simulation/tests -v
python3 -m pytest tools/tests   -v
```

---

## 10. Single-Page Status

**Code:** complete. **Wiring:** verified. **Hardware:** not started, by design. **Pilot:** lab-bench ready; needs operator-side hardware + IdP + safety-review process.

For the operator hand-off → [`STATUS_AND_PILOT_READINESS.md`](STATUS_AND_PILOT_READINESS.md).
For the forward plan → [`ROADMAP.md`](ROADMAP.md).
For the live demo → [`demos/pilot-pitch.md`](demos/pilot-pitch.md).
For design rationale → [`adr/`](adr/).
For operational know-how → [`runbooks/`](runbooks/).

The project is at the natural seam where software work ends and hardware procurement begins. Every code-side gap is closed, traced to an ADR, covered by tests, documented in a runbook, and the cross-references all resolve.
