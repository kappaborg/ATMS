# ATMS Roadmap

**Date:** 2026-05-31
**Where we are:** [`STATUS_AND_PILOT_READINESS.md`](STATUS_AND_PILOT_READINESS.md) — 18 of 19 audited gaps closed code-side; remaining work is hardware-, data-, or refactor-blocked.
**Showcase the project:** [`demos/pilot-pitch.md`](demos/pilot-pitch.md) — single-command live demo of the failsafe controller + EV preempt + audit trail, no hardware required.

This roadmap names the **four tracks** that run in parallel from here, and for each names the next concrete PR. It is the work plan a new engineer or the engineering lead can pick up tomorrow.

---

## Four tracks, run in parallel

```
                    months 1–2          months 2–4         months 4–7          months 7+
                    ────────────────    ───────────────    ────────────────    ───────────
TRACK 1  Pilot      Lab bring-up   →    HW bench (C1)  →   Pilot intersection→ Multi-intersection
                    (cluster + sim)     (NTCIP soak)       (shadow → live)     (green-wave)

TRACK 2  Hardware                        C1 NTCIP       →   C6 calibration  →   (steady state)
                                         C2 edge agent      drift detection

TRACK 3  ML         MLflow stand-up →   D1 serving     →   D2 drift +     →    D3 retraining
                    + register YOLOv8    (Triton + canary)   nightly regress    pipeline

TRACK 4  Refactor   A2 monoliths    →   decision-engine →  api-gateway     →   docs cleanup
+ polish            (incremental)        HealthRouter       operator UI         every-quarter
```

Tracks 1 and 2 are coupled — pilot waits on hardware. Tracks 3 and 4 are independent and can be done by separate engineers concurrently.

---

## TRACK 1 — Pilot rollout (the unifying timeline)

The trajectory from [`STATUS_AND_PILOT_READINESS.md`](STATUS_AND_PILOT_READINESS.md) §9.

### Phase 1 — Lab bring-up (~6-8 weeks)

**Goal:** Cluster running, observability live, tests green against real infrastructure.

| Task | Owner role | Deliverable |
|------|------------|-------------|
| Provision on-prem K8s cluster (CNI must support NetworkPolicy) | SRE | Cluster bootstrap log |
| Install cert-manager, then Linkerd (`infrastructure/linkerd/`) | SRE | `linkerd check` all green |
| Install Loki + Promtail + Tempo + OTel collector (`infrastructure/observability/`) | SRE | Grafana ATMS-Overview dashboard live |
| Install Postgres + TimescaleDB + run Alembic migrations | SRE | `alembic upgrade head` clean |
| Install Kafka (`docker-compose.kafka.yml` → Helm) | SRE | Topics created, ACLs scoped |
| Deploy MLflow (Postgres backing + S3-compatible artefact store) | ML Engineer | MLflow UI reachable |
| Wire Keycloak (or chosen OIDC IdP) | Security | A6 JWT flipped from HS256 → RS256 |
| Generate operator age keys; populate `.sops.yaml` recipients | Ops Lead | `make secrets-decrypt ENV=staging` works for each operator |
| Build per-intersection SUMO baseline | Traffic Eng | `simulation/baselines/<intersection>.json` committed |
| Set up GitHub-hosted SUMO runner for sim-regression CI | SRE | `.github/workflows/sim-regression.yml` shipped |

### Phase 2 — Hardware bench (~6-8 weeks, requires hardware in Track 2)

**Goal:** Real controller + edge box + camera driving a non-actuating intersection.

| Task | Deliverable |
|------|-------------|
| C1 NTCIP soak against vendor-virtual controller — 24h zero error | Soak log, dashboard screenshot |
| C2 edge agent installed on Jetson; survives 1h cable-pull | Chaos test log |
| C6 camera calibration baseline captured over 7 days | Drift-baseline plot |
| Full chaos suite on the bench: kill engine / Kafka / NTCIP, observe transitions | Pass log in CI nightly |
| Property-test the controller against the **real** TL state strings | Same `test_safety_invariants.py` against bench |

### Phase 3 — Pilot intersection (~8-12 weeks)

**Goal:** ATMS drives a real signal head with operator-on-call.

1. **Days 1-14: Shadow mode.** ATMS computes decisions; cabinet runs its own plan. Daily KPI comparison via SUMO replay.
2. **Days 15-28: Assisted mode.** ATMS drives, operator-on-call watches. Pause if any safety violation.
3. **Days 29+: Autonomous mode.** Off-hours unattended.

Per-step gate: KPIs no worse than legacy, zero conflicts, zero unrecovered `ALL_RED_FLASH`.

### Phase 4 — Multi-intersection (months 7+)

1. Wire `services/intersection-coordinator` for green-wave coordination.
2. Add intersections 2 and 3 following the same shadow → assisted → autonomous pattern.
3. Enable V2X path (C8) if EV fleet is V2X-equipped.
4. Engage D2/D3 once 90 days of production data is accumulated.

---

## TRACK 2 — Hardware integration

### C1 — NTCIP 1202/1203 conformance + real cabinet

**Blocker:** physical traffic-signal controller.

**Approach:**
- Replace `services/ntcip-interface/src/main.py` stub with `pysnmp` (or vendor SDK) calls.
- Implement the OID subset: phase status, phase control, ped-call, preempt, hardware-fault read.
- IPsec or Wireguard overlay between controller and edge agent (NTCIP itself is unauthenticated).
- Conformance test suite in CI against a virtual controller (Econolite supplies one).
- Acceptance: green-yellow-red-walk cycle on real hardware for 24h with zero protocol errors.

**Reference targets:** Econolite Cobalt, McCain ATC, Siemens M60. Vendor selection drives the MIB-version pick.

**Estimate:** 6–10 weeks for one vendor model; +2 weeks per additional vendor.

### C2 — Edge agent + offline mode

**Blocker:** physical edge box (NVIDIA Jetson Orin or Intel NUC).

**Approach:**
- New service `services/edge-agent/` deployable as a single container on the edge box.
- Runs local YOLOv8 inference, local failsafe controller, local fixed-time plans, local 24h decision buffer.
- WAN-up: ships telemetry to the cluster, pulls policy updates.
- WAN-down: operates autonomously indefinitely.
- Cloud's role narrows to: coordination, analytics, model distribution. **Cloud is never in the actuation path.**

**Acceptance:** pull network cable for 1h; intersection continues operating; on reconnect, backfill cleanly.

**Estimate:** 8–12 weeks.

### C6 — Camera calibration drift handling

**Blocker:** real camera + 30 days of footage.

**Approach:**
- Auto-recalibration job runs daily using detected lane markings / fixed scene features (e.g., stop-line position).
- Emit `calibration_confidence` metric per camera; alert when below threshold for >24h.

**Acceptance:** deliberately nudge a test camera by 2°; system detects within one cycle, alerts, re-calibrates.

**Estimate:** 4–6 weeks after data is flowing.

---

## TRACK 3 — ML maturity

### D1 serving (completes the partial D1)

**Blocker:** GPU node-pool.

**Approach:**
- Stand up Triton Inference Server (or BentoML — ADR decision when GPUs are sized).
- Replace `ai-perception`'s direct `.pt` load with a registry-pull at startup:
  ```python
  model_uri = registry.get_uri("yolov8-detection", ModelStage.PRODUCTION)
  ```
- Wave-out promotion: `Staging → Canary (1 intersection) → 10% → 100%` controlled via the registry promote API.
- Automated rollback on metric regression (depends on D2).

**Acceptance:** promote a new detection model from registry to one canary intersection via a single CLI command; rollback within 30s if recall drops >5%.

**Estimate:** 4–6 weeks.

### D2 — Drift detection

**Blocker:** production data flow (≥30 days of detections).

**Approach:**
- Production drift monitor: tracks input distribution (image brightness/contrast histograms) and output distribution (class mix, confidence histograms) vs. a reference set.
- Nightly accuracy regression: replay a held-out labelled set, compare mAP/precision/recall to last-known-good, alert + auto-block promotion on regression.

**Acceptance:** deliberately degrade a model; nightly eval fails it; promotion is blocked.

**Estimate:** 6–10 weeks (most of it is data prep + labelling backlog).

### D3 — Retraining + labelling pipeline

**Blocker:** labelling tool + ML platform.

**Approach:**
- Continuous data collection from production (opt-in, anonymised per D4) into a labelling queue.
- Labelling: Label Studio or CVAT (self-hosted). Active learning selects uncertain frames.
- Scheduled retrain (weekly or on data threshold) → eval → registry promotion candidate.

**Acceptance:** end-to-end retrain triggered from a labelled batch produces a registered model artefact with full lineage.

**Estimate:** 8–12 weeks.

---

## TRACK 4 — Refactor + polish

These are independent and can be parallelised. None blocks the pilot, but each removes friction or a future hazard.

### A2 monolith refactor (the 3 stragglers)

| Service | LoC | Approach |
|---------|----:|----------|
| `services/ai-perception/src/main.py` | 1999 | Split into `detection/`, `tracking/`, `kafka/`, `optimization/` modules. Apply B1 bootstrap. Land in 3 small PRs. |
| `services/video-processor/src/main.py` | 1981 | Consolidate the two near-duplicate root scripts into this. Apply B1 bootstrap. |
| `services/sensor-fusion/src/` | multi-file | Add B1 bootstrap to the existing `main.py`; the subdir structure is already healthy. |

Each: ~1 week of careful work. Status: gated on whether these services actually ship in the pilot — operator decision.

### decision-engine `HealthRouter` integration

Right now decision-engine has the shared logging + tracing but uses its hand-rolled `/health` endpoint. Replace with `HealthRouter` + per-dependency checks (Kafka producer state, AI engine availability). ~1-day PR.

### `services/api-gateway` operator UI

The control endpoints (preempt, ped-call, DSAR, model promotion) currently require curl. Build a small web UI for the operator console — read-only dashboards link out; operator actions land here. ~2-3 weeks; could be a small React/Vue app.

### `services/intersection-coordinator` full wiring

Today coordinator has B1 bootstrap only. Full multi-intersection coordination logic is Phase 4 pilot work. Lay the schema + Kafka topic groundwork now: ~1-week PR.

### Misc follow-ups

- **Wave-out promotion CLI**: `make model-promote MODEL=yolov8 TO=Production --wave=10%`. ~1 week.
- **CI sim-regression workflow**: shipped as a TODO in ADR-0016; self-hosted SUMO runner. ~1 week.
- ~~**`security/jwt_handler.py` + `middleware.py` purge**~~: `[DONE 2026-05-30]` — files removed from disk; `security/__init__.py` updated; ADR-0006 follow-up closed.
- ~~**Lint rule banning `time.time()` in safety modules**~~: `[DONE 2026-05-30]` — `tools/lint_safety_clock.py` + `tools/.safety_clock_legacy.txt` + CI step shipped; 28 tests in `tools/tests/`.

---

## Critical-path open decisions

Items the operator / business must decide before unblocking the corresponding track:

1. **Pilot intersection identity.** Which physical intersection? Drives C1 vendor choice, C6 camera install, simulation baseline.
2. **Controller hardware vendor.** Econolite vs McCain vs Siemens. Drives the NTCIP MIB specifics.
3. **Edge hardware vendor.** Jetson Orin vs Intel NUC. Drives the C2 service image base.
4. **OIDC IdP choice.** Keycloak (recommended; OSS) vs Auth0 vs operator's existing AD/SSO.
5. **GPU node-pool sizing for ML serving.** Drives D1 serving timeline.
6. **V2X enablement.** Whether the operator's EV fleet has OBUs ready. Drives whether C8 lights up in pilot.
7. **Warranted-access enablement.** Default off per ADR-0014 §4; legal sign-off needed before turning on.
8. **Safety-review authority.** Named in `docs/assumptions.md` as open. Drives Phase 2 bench sign-off process.

Each blocks a specific track. List the answers in `docs/assumptions.md` as they come in.

---

## The next 5 concrete PRs (no hardware needed)

Status update — three of the original five shipped 2026-05-30:

| # | Item | Status |
|---|------|--------|
| 1 | **OIDC IdP integration** — flip A6 HS256 dev → RS256 production. | `[DONE 2026-05-30]` — `_verify_rs256` implemented with PyJWKClient; `docker-compose.keycloak.yml` + `deploy/keycloak/atms-realm.json` for dev; runbook `docs/runbooks/oidc-keycloak.md`; 9 new RS256 tests |
| 2 | **decision-engine HealthRouter** — replace bespoke `/health` with shared router; Kafka + AI-engine dep-checks. | `[DONE 2026-05-30]` — 5 new probe tests |
| 3 | **CI sim-regression workflow** — `.github/workflows/sim-regression.yml` triggers SUMO + KPI diff to PR. | `[DONE 2026-05-30]` — workflow + `simulation/compare_kpis.py` (19 tests) + placeholder baseline + `docs/runbooks/sim-regression.md`. Self-hosted `sumo-runner` provisioning is the operator-side prerequisite. |
| 4 | **Safety-clock lint** — ban `time.time()` / `datetime.now()` in safety scope per ADR-0017. | `[DONE 2026-05-30]` — `tools/lint_safety_clock.py` + CI step + 28 tests + 0 violations |
| 5 | **`security/jwt_handler.py` + `middleware.py` purge** — ADR-0006 follow-up. | `[DONE 2026-05-30]` — files already gone; tracking docs updated |

**All five next-5 items shipped 2026-05-30.** The remaining unblockers are operator-side: a Keycloak (or other OIDC IdP) instance for the RS256 cutover, a self-hosted `sumo-runner` for sim-regression CI, and a captured-from-real-SUMO baseline to replace the placeholder. None of those are code work — they're "decide and provision" tasks.

---

## What this roadmap explicitly defers

- **CARLA simulation.** SUMO (C3) is sufficient for signal-control policy testing. CARLA's autonomous-vehicle-perception focus is overkill until V2X / sensor fusion grows up.
- **Multi-cluster federation.** Single-cluster suffices for the pilot operator's whole metro area at current scales.
- **Public-facing API.** ATMS is operator-only. Any public traffic-data exposure would be a separate service + a separate ADR.
- **Cross-jurisdiction expansion.** EU/RiLSA is the baseline (ADR-0004). Non-EU requires a new ADR + jurisdiction-specific timing tables.
- **Hardware-in-the-loop CI** for NTCIP. C1 conformance happens against a virtual controller in CI; real-hardware HIL happens manually at the bench.

---

## How to use this roadmap

- **Engineering lead:** the next-five-PRs section is the immediate work queue. Beyond that, sequence the four tracks per the team's parallel-engineer capacity.
- **Pilot authority:** Track 1's phases map to the sign-off blocks in `STATUS_AND_PILOT_READINESS.md` §12. Each phase has a clear go/no-go gate.
- **Operator:** the "Critical-path open decisions" section is the list of choices you owe back to the engineering team. Each unblocks specific work.
- **Reviewer:** ADRs in `docs/adr/` are the design rationales for everything proposed here. Runbooks in `docs/runbooks/` are the operational consequences.

This roadmap is **a living document**. Update `PRODUCTION_GAPS.md` as items close, and revise this file when the pilot intersection authority and the four open decisions above are settled.
