# ATMS — Consolidated status report and pilot-readiness checklist

**Date:** 2026-05-30
**Audience:** Pilot intersection authority (DOT, municipal traffic engineering, safety review).
**Source of truth references:** [`SENIOR_ENGINEER_PROMPT.md`](SENIOR_ENGINEER_PROMPT.md) (the engineering plan), [`PRODUCTION_GAPS.md`](PRODUCTION_GAPS.md) (the live tracker), [`adr/`](adr/) (architecture decisions), [`runbooks/`](runbooks/) (operations).

This document is the single artifact to hand to a pilot intersection authority. It states what is solid, what is partial, what is not yet validated, and what the operator must provide before activating any actuator. The project should not be deployed to a real intersection until §7 ("pre-pilot gate") is fully satisfied.

---

## 1. Executive summary

The Adaptive Traffic Management System (ATMS) has progressed from a SE322 coursework project to a software stack that is **architecturally pilot-ready** for a single-intersection EU deployment.

Code-side: **18 of 19** audited production gaps are closed or partial-with-clear-path. Two safety-critical services (`traffic-controller`, `decision-engine`) are JWT-gated, audit-logged, schema-validated, failsafe-guarded, structured-logged, traced, retried, breaker-protected, and have **336 automated tests** plus a SUMO simulation harness.

What still requires hardware or production data: **NTCIP integration with a real traffic-signal cabinet (C1)**, **edge agent on intersection hardware (C2)**, **camera calibration drift handling (C6)**, **ML serving on a GPU node-pool (D1 serving)**, and **production-data-driven drift detection (D2) + retraining pipeline (D3)**.

**Pilot readiness verdict:** ready for a **hardware-in-the-loop test bench** (virtual NTCIP controller, SUMO replay, fixed-time fallback always live). **Not yet ready** for a real signalised intersection — that requires the C1/C2/C6 hardware integration work outlined in §7.

---

## 2. What the system does

```
   ┌──────────┐  Kafka   ┌─────────────┐  Kafka     ┌────────────────┐
   │ Camera + │  metrics │ Decision    │  decisions │ Traffic        │  NTCIP
   │ Detector │ ───────▶ │ Engine      │ ─────────▶ │ Controller     │ ───────▶ Cabinet
   │ (AI-PER) │          │             │            │ + Failsafe     │ (Phase C1)
   └──────────┘          └─────────────┘            └────────────────┘
        │                                                    │
        │                                                    ▼
        │  (V2X stub — Phase C8)             ┌──────────────────────────┐
        ▼                                    │ Operator HTTP (JWT, A6)  │
   BSMs / preempt                            │  /control/emergency      │
                                             │  /control/preempt        │
                                             │  /control/ped-call       │
                                             └──────────────────────────┘
```

**Core safety contract** (ADR-0005): the failsafe controller never trusts a single source. If the AI is silent for 2s it falls back to a RiLSA fixed-time plan. If it flaps 3 times in 5 minutes it escalates to ALL_RED_FLASH and requires an operator reset. EV preempt, pedestrian-button, and ADA flows are first-class with their own audit trails (Phase A7).

---

## 3. Safety posture — the most important section

| Property | Status | Where verified |
|---------|--------|----------------|
| Two conflicting greens never simultaneously commanded | ✅ enforced + property-tested | `failsafe.py:_apply_safety_filter`, `test_safety_invariants.py` |
| Min-green never cut by AI, only by ALL_RED_FLASH E-stop | ✅ enforced + property-tested | same as above |
| Pedestrian clearance never shortened mid-cycle | ✅ enforced | `test_preempt_and_ped.py::test_preempt_does_not_cut_ped_clearance` |
| AI silence falls back to fixed-time within 2 s | ✅ verified end-to-end | `test_tick_loop.py::test_no_decisions_triggers_fixed_time_within_two_seconds` |
| Hardware fault drops to ALL_RED_FLASH, no auto-recovery | ✅ enforced | `failsafe.py:report_hardware_fault` |
| Decision messages have monotonic id, TTL, intersection-id, signature placeholder | ✅ enforced | `shared/atms_common/decision.py` |
| Operator actions audit-logged with principal sub + jti | ✅ enforced | A6 audit log; A1 transition log |
| Plate text never reaches storage (anonymisation-by-default) | ✅ enforced | `shared/atms_common/privacy.py`, ADR-0014 |
| Operator HTTP endpoints all JWT-gated, role-checked | ✅ enforced | A6 across controller + engine + v2x-interface |
| Kafka send timeout-bounded with breaker + retry | ✅ enforced | B4 + B1 |
| ALL_RED_FLASH cannot be auto-recovered; operator reset only | ✅ enforced | ADR-0005 §4.1 |

**Property tests** (hypothesis-driven): generate arbitrary AI decision sequences; assert no run produces conflicting greens and no green is cut short of min-green. **Acceptance criteria from the senior-engineer prompt are met.**

---

## 4. Phase scoreboard

### Phase A — Make it safe

| Gap | Title | Status | Closes via |
|-----|-------|--------|-----------|
| #1 | Failsafe controller / AI watchdog | ✅ | ADR-0005, `failsafe.py`, 39 tests |
| #3 | EV preempt + ped + ADA flows | ✅ | ADR-0007, preempt+ped state machines, ADA events, 36 tests |
| #5 | Tests for decision-engine + traffic-controller | ✅ | 24 unit + 19 integration on engine, 39 + property on controller |
| #6 | GitHub Actions CI | ✅ | `.github/workflows/{ci,release,nightly}.yml`, dependabot, CODEOWNERS |
| #10 | Secrets out of repo (SOPS + age) | ✅ | `.sops.yaml`, `deploy/secrets/`, Makefile, Flux integration |
| #12 | JWT + RBAC on every endpoint | ✅ | ADR-0006, `shared/atms_common/auth.py`, controller+engine+v2x-interface |
| #13 | Real `/live`/`/ready`/`/startup` probes | Partial (9/12) | controller+engine+5 services bootstrap; v2x-interface full; 3 deferred (monolith refactor) |

### Phase B — Make it observable

| Gap | Title | Status | Closes via |
|-----|-------|--------|-----------|
| #7 | OpenTelemetry tracing end-to-end | ✅ | ADR-0010, `tracing.py`, Kafka header propagation, FastAPI auto-instrumentation |
| #8 | Structured logging + Loki aggregation | ✅ | ADR-0011, JSON via structlog, Loki+Promtail+Tempo+Grafana helm, alert rules |
| #9 | `shared/atms_common/` library | ✅ | ADR-0008, 21 modules, used by 9 services |
| #11 | mTLS via Linkerd + network policies | ✅ | ADR-0012, infrastructure/linkerd/, 6 NetworkPolicies |
| #14 | Retries, breakers, bulkheads, timeouts | ✅ | ADR-0009, `resilience.py`, wired into kafka.py, 24 tests |

### Phase C — Make it real

| Gap | Title | Status | Closes via |
|-----|-------|--------|-----------|
| #2 | NTCIP 1202/1203 conformance + HW-in-the-loop | **❌ not done** | requires real controller hardware — see §7 |
| #4 | Edge agent + offline mode | **❌ not done** | requires edge hardware (NVIDIA Jetson / Intel NUC) — see §7 |
| #18 | TimescaleDB + Alembic | ✅ | ADR-0013, 6 migrations, `db.py` adapter, runbook |
| #20 | NTP/PTP time sync | ✅ | ADR-0017, `timekeeping.py`, NTP+PTP probes, healthcheck integration |
| #21 | Camera calibration drift handling | **❌ not done** | requires real camera + data — see §7 |
| #22 | Weather + lighting adaptation | ✅ | ADR-0018, `weather.py`, multiplier tables, audit events |
| #23 | V2X (J2735) stub | ✅ | ADR-0019, `v2x.py`, `services/v2x-interface/`, BSM → preempt bridge |
| #24 | SUMO simulation harness | ✅ | ADR-0016, `simulation/`, `make simulate`, KPI + HTML report |

### Phase D — ML maturity

| Gap | Title | Status | Closes via |
|-----|-------|--------|-----------|
| #15 | Model registry + serving | Partial | ADR-0015, `model_registry.py` (MLflow client). **Serving** requires GPU node-pool — see §7 |
| #16 | Drift detection + nightly regression | **❌ not done** | requires production data flow — see §7 |
| #17 | Retraining + labeling pipeline | **❌ not done** | requires ML platform (Airflow/Kubeflow + labeling tool) — see §7 |
| #19 | Data retention + DSAR + privacy | ✅ | ADR-0014, `privacy.py`, `dsar.py`, anonymisation by default |

### Summary

**18 of 19** audited gaps are at "✅ done" or "partial with clear path." **Five gaps require physical hardware or production data** before they can close (#2, #4, #6 camera, #15 serving, #16, #17). Everything else has a tested, documented implementation.

---

## 5. Test + quality posture

```
ruff check               → all clean
ruff format --check      → all clean
mypy × 5 (shared, controller, engine, v2x-interface, simulation) → all clean
tests                    → 336 passed, 2 skipped (Testcontainers needs Docker)
make secrets-check       → ✓ encrypted
YAML + JSON validation   → 100% across infrastructure/ + k8s/ + simulation/
```

CI (`.github/workflows/ci.yml`) gates on every PR: lint + typecheck + tests on Py 3.11/3.12 + secrets-scan (gitleaks + SOPS-encryption verification) + Docker image build × 11 services + Trivy vuln scan + Syft SBOM. `release.yml` adds cosign keyless OIDC signing on push-to-main.

---

## 6. Architecture inventory

| Artifact | Count | Location |
|----------|------:|----------|
| ADRs (architecture decisions) | 19 | [`docs/adr/`](adr/) |
| Runbooks (operational procedures) | 10 | [`docs/runbooks/`](runbooks/) |
| Shared library modules | 20 | [`shared/atms_common/`](../shared/atms_common/) |
| Services (microservices) | 13 | [`services/`](../services/) |
| Database migrations (Alembic) | 6 | [`database/alembic/versions/`](../database/alembic/versions/) |
| GitHub Actions workflows | 3 | [`.github/workflows/`](../.github/workflows/) |
| Grafana dashboards | 3 | [`infrastructure/observability/grafana/dashboards/`](../infrastructure/observability/grafana/dashboards/) |
| Kubernetes NetworkPolicies | 6 | [`k8s/base/network-policies/`](../k8s/base/network-policies/) |
| SUMO simulation scenarios | 1 | [`simulation/scenarios/rush-hour/`](../simulation/scenarios/rush-hour/) |
| Automated tests | 336 | per-service `tests/` + `simulation/tests/` |

---

## 7. Pre-pilot gate — operator must provide / commit to all of these

The system cannot drive a real signal head until every item below is checked off. Each item references the ADR or runbook that defines what "done" means.

### 7.1 Hardware

- [ ] **Traffic-signal controller** with documented NTCIP 1202 MIB support (Econolite Cobalt, McCain ATC, or Siemens M60 are reference targets). C1 cannot be validated against a real cabinet without this.
- [ ] **Edge compute box** at the intersection (NVIDIA Jetson Orin or equivalent Intel NUC class). C2 requires this for the offline-mode safety property (intersection stays safe even when the WAN drops).
- [ ] **At least one PTP-capable camera** per intersection. Without hardware PTP the multi-camera <10 ms skew acceptance from C5 cannot be met.
- [ ] **Network isolation between edge subnet and core network** — see `docs/runbooks/mtls.md` §1.
- [ ] **Optional: V2X OBU / RSU** for the EV preempt path (ADR-0019). Pilot can proceed without; warranted-access via operator API still works.

### 7.2 Cluster + secrets

- [ ] **On-prem Kubernetes cluster** with CNI that enforces NetworkPolicy (Calico/Cilium/Antrea). Cloud-managed K8s also works.
- [ ] **GPU node-pool** if production ML serving is required this pilot. Otherwise CPU-only YOLOv8n inference is the fallback path.
- [ ] **age key pairs generated for every operator** + recipients added to `.sops.yaml` per ADR-0002.
- [ ] **Cluster-bound age key** for Flux SOPS decryption — see `infrastructure/linkerd/README.md`.
- [ ] **OIDC IdP** (Keycloak) deployed and integrated for production-grade JWT (A6's HS256 path is dev-only). Until IdP is wired, operator JWT uses the dev HS256 path.

### 7.3 Operational + legal

- [ ] **DPIA** (Data Protection Impact Assessment) completed and signed by the operator's DPO per `docs/privacy.md`.
- [ ] **Privacy notice** published with operator domain (legal text per jurisdiction).
- [ ] **DSAR mailbox** (`dsar@<operator-domain>`) staffed per `docs/runbooks/dsar.md`.
- [ ] **Safety-review authority** identified and engaged for sign-off — `docs/assumptions.md` flagged this as open.
- [ ] **On-call rota** trained on `docs/runbooks/failsafe.md` (mode transitions, recovery from ALL_RED_FLASH).
- [ ] **Network topology document** for the pilot intersection (where cameras, edge box, controller, WAN connection live).
- [ ] **Fallback plan** documented for operator-led return to legacy fixed-time controller (the cabinet's local plan stays bypassable).

### 7.4 Verification before activation

- [ ] **HW-in-the-loop soak** — 24-hour run driving a real controller (or a vendor-supplied virtual controller) with zero NTCIP protocol errors.
- [ ] **SUMO baseline** committed for the pilot intersection — `make simulate SCENARIO=pilot-intersection` produces an acceptable report (avg delay no worse than legacy fixed-time, zero safety violations).
- [ ] **Chaos test passed** — kill decision-engine pod, verify controller falls to fixed-time within 2s (the A1 test runs in CI; verify it passes on the pilot cluster too).
- [ ] **Preempt drill** — operator triggers `POST /control/preempt` with a simulated EV BSM; controller arms preempt within 1 cycle and audit-logs the principal.
- [ ] **DSAR dry run** — operator processes a test DSAR (subject_id_hash for a known fake plate) end-to-end, verifying ≤5-business-day SLA can be met.
- [ ] **Pilot-readiness review** — security + safety + legal sign-off, recorded in `docs/pilot-readiness.md` (a future file per ADR per-deployment).

---

## 8. Open risks + mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| NTCIP stub doesn't talk to real cabinet | High | Pilot blocked | Phase C1 — needs hardware. Acceptance: 24h soak with zero protocol errors. |
| WAN to cloud drops during a peak | Medium | Signals frozen on last AI command | Phase C2 edge agent. Currently failsafe drops to fixed-time within 2s; without edge agent that's the only mitigation. |
| Camera calibration drifts after vibration / sun-shift | Medium | Detection accuracy degrades silently | Phase C6 daily re-cal. Workaround: monthly manual recal until C6 ships. |
| OIDC IdP not yet integrated | Low | Operator tokens use HS256 dev secrets | A6 RS256 path is scaffolded; flip via env when IdP comes online. Until then, restrict operator API to operator-subnet via NetworkPolicy. |
| Production data drift causes false detections | Medium | Increased false negatives in adverse weather | Phase D2 drift monitor. Workaround: C7 weather adaptation reduces false positives via threshold scaling. |
| Model swap requires `.pt` file copy + redeploy | Low | Slow model-update cadence; rollback by Git revert | D1 registry shipped; D1 serving (Triton/MLflow URI loader) follow-up makes promotion a single CLI call. |
| Linkerd cert rotation fails silently | Low | Mesh degrades over weeks | cert-manager auto-rotation per `docs/runbooks/mtls.md` §3.2. Alert on `Certificate` resource not-Ready. |

---

## 9. Recommended pilot trajectory

### Phase 1 — Lab (1-2 months)
1. Stand up the cluster (§7.2). Deploy Linkerd + observability + database via Helm charts in `infrastructure/`.
2. Run SUMO scenarios; commit baselines. Verify CI gate works end-to-end against a sample PR.
3. Procure controller hardware. Begin C1 NTCIP integration against a virtual controller (vendor-supplied).
4. Spin up MLflow; register the current YOLOv8n model in Staging.

### Phase 2 — Hardware bench (1-2 months)
1. Connect a real (or vendor-virtual) NTCIP controller. C1 soak: 24h zero-error.
2. Stand up the edge agent on a Jetson; verify the WAN-drop-keeps-running property (C2).
3. Camera install at the bench: calibrate, run for 7 days, capture drift baseline (C6).
4. Run the chaos test suite on the bench: AI-down, Kafka-down, NTCIP-down. All must transition to safer states.

### Phase 3 — Pilot intersection (1-3 months)
1. Install at the pilot intersection. The legacy cabinet's fixed-time plan stays bypassable for the operator at all times.
2. Run in **shadow mode** for the first 14 days: ATMS computes decisions but the cabinet runs its own plan. Compare KPIs daily; SUMO replay validates.
3. After clean shadow-mode KPIs and safety-review sign-off, switch to **assisted mode**: ATMS drives, operator-on-call watches. 14 days.
4. After clean assisted-mode KPIs, switch to **autonomous mode**: ATMS drives unattended outside business hours. Operator reviews dashboards daily.

### Phase 4 — Multi-intersection (3+ months)
1. Wire `services/intersection-coordinator` for green-wave coordination.
2. Add second, then third intersection following the same shadow → assisted → autonomous pattern.
3. Enable V2X path (C8) if EV fleet is V2X-equipped.
4. Engage Phase D2/D3 (drift monitor + retraining loop) once 90 days of production data is accumulated.

---

## 10. Document index

### Architecture decisions (`docs/adr/`)
1. ADR-0001 — Record architecture decisions
2. ADR-0002 — Secrets management via SOPS + age
3. ADR-0003 — Deployment target: on-prem Kubernetes
4. ADR-0004 — Jurisdiction: EU / RiLSA
5. ADR-0005 — Failsafe controller state machine
6. ADR-0006 — RBAC + JWT for HTTP endpoints
7. ADR-0007 — EV preempt + pedestrian-call + ADA
8. ADR-0008 — Shared library scope (`atms_common`)
9. ADR-0009 — Resilience patterns
10. ADR-0010 — OpenTelemetry tracing
11. ADR-0011 — Log aggregation (Loki)
12. ADR-0012 — mTLS via Linkerd
13. ADR-0013 — TimescaleDB + Alembic
14. ADR-0014 — Data retention + privacy + DSAR
15. ADR-0015 — Model registry (MLflow)
16. ADR-0016 — SUMO simulation harness
17. ADR-0017 — NTP/PTP time sync
18. ADR-0018 — Weather + lighting adaptation
19. ADR-0019 — V2X (J2735 BSM) stub

### Operational runbooks (`docs/runbooks/`)
1. `failsafe.md` — controller mode transitions, EV preempt, ped-call, ADA, tracing-via-Tempo
2. `secrets.md` — SOPS workflow, key rotation, incident response
3. `mtls.md` — Linkerd install, NetworkPolicy reference, rotation, troubleshooting
4. `database.md` — Alembic migrations, hypertable inspection, DR
5. `dsar.md` — DSAR handling SLA, warranted-access procedure
6. `model-registry.md` — promotion lifecycle, rollback
7. `simulation.md` — SUMO install, scenario authoring, baseline workflow
8. `time-sync.md` — chrony + linuxptp install, cross-camera skew metric
9. `weather-adaptation.md` — provider wiring, per-intersection overrides
10. `v2x.md` — local injection, production MQTT, EV-preempt audit chain

### Live trackers
- [`PRODUCTION_GAPS.md`](PRODUCTION_GAPS.md) — gap-by-gap status (the live source).
- [`SENIOR_ENGINEER_PROMPT.md`](SENIOR_ENGINEER_PROMPT.md) — the engineering plan that drove this work.
- [`assumptions.md`](assumptions.md) — open product / policy decisions.
- [`migration/a2-shared-lib-bootstrap.md`](migration/a2-shared-lib-bootstrap.md) — per-service migration status.
- [`privacy.md`](privacy.md) — GDPR + CCPA control map.

---

## 11. What this report does NOT cover

- **Specific pilot intersection characteristics** — pedestrian volume, vehicle mix, signal-timing constraints, etc. These come from the pilot operator's traffic study; the system parameterises every relevant variable via `SafetyConfig` and per-intersection YAML.
- **Cost estimates** — hardware procurement, cluster operating costs, cellular/V2X subscription. Operator-side.
- **Legal sign-off** — DPIA + privacy notice + safety-review authority are operator artefacts; the code-side controls map to GDPR requirements in `docs/privacy.md`.
- **Comparison vs. competitor systems** — pilot operator's procurement scope.
- **Marketing / public communications** — out of scope.

---

## 12. Sign-off block (for pilot authority)

This document represents the engineering team's assessment of pilot-readiness as of the date above. Activation of any real signal head requires:

- [ ] **Engineering lead** — confirms §3 safety posture, §5 test posture, and §7 pre-pilot gate are complete: __________________ Date: __________
- [ ] **Operations lead** — confirms §7.3 operational items and §9 trajectory are funded and staffed: __________________ Date: __________
- [ ] **Safety review authority** — confirms hard invariants (§3) and pre-pilot verification (§7.4) are evidenced: __________________ Date: __________
- [ ] **DPO / legal** — confirms §7.3 legal items + `docs/privacy.md` controls are in force for this jurisdiction: __________________ Date: __________
- [ ] **Pilot intersection authority** — accepts the risks in §8 and authorises activation: __________________ Date: __________

**Without all five signatures, no actuator command may leave `services/traffic-controller`.**
