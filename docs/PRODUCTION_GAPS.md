# ATMS Production Readiness — Gap Tracker

Source of truth for the productionization roadmap. Every gap from the original audit (1–28) is listed here. When a gap is closed, mark `[DONE]` and add the date and PR link.

Authoritative roadmap: [`SENIOR_ENGINEER_PROMPT.md`](./SENIOR_ENGINEER_PROMPT.md).
Forward plan: [`ROADMAP.md`](./ROADMAP.md).
Pilot readiness: [`STATUS_AND_PILOT_READINESS.md`](./STATUS_AND_PILOT_READINESS.md).
Architecture decisions: [`adr/`](./adr/).

---

## Repository Hygiene (pre-Phase A — 1-day cleanup)

| ID | Item | Status | Owner | Date |
|----|------|--------|-------|------|
| H1 | `.env` in `.gitignore` + `.env.example` shipped | `[DONE]` | — | 2026-05-29 |
| H2 | Untrack stale `venv/`, `__pycache__/`, `*.pt`, `Processed_Videos/` from git | `[DONE]` — repo initialised 2026-07-02; large assets/venvs excluded via .gitignore (756 files / 23 MB tracked) | — | 2026-07-02 |
| H3 | Consolidate `realtime_video_processor.py` + `youtube_decision_processor.py` into `services/video-processor/` | `[DONE]` — 2026-07-02: duplicated legacy per-frame paths deleted (~550 lines, ATMSPipeline single implementation); 2026-07-03: scripts moved to `services/video-processor/tools/` with deprecation shims at root (both paths verified end-to-end on a test clip) | — | 2026-07-03 |
| H4 | Archive stale `docs/PHASE*`, `WEEK*`, `*COMPLETE*`, `*STATUS*` | `[DONE]` (37 files moved) | — | 2026-05-29 |
| H5 | ADR template + `docs/PRODUCTION_GAPS.md` | `[DONE]` | — | 2026-05-29 |
| H7 | Repo-root `pyproject.toml` (ruff + mypy + coverage) | `[DONE]` (A4) | — | 2026-05-29 |
| H8 | `CONTRIBUTING.md`, `.github/CODEOWNERS`, `.github/dependabot.yml` | `[DONE]` (A4) | — | 2026-05-29 |
| H6 | `.gitignore` covers `*.pt`, `*.onnx`, `*.mlpackage`, `Processed_Videos/`, `experiments_out/`, `debug_frame.jpg` | `[DONE]` | — | 2026-05-29 |
| H9 | Helm chart `templates/` is empty — `helm install` deploys zero resources | `[DONE]` — 2026-07-02: generic Deployment/Service/HPA templates for all 9 services (probes, resource limits, secrets via `atms-secrets` not values.yaml); `helm lint` clean, renders 9+9+2 resources | — | 2026-07-02 |
| H10 | Postgres backup with rotation (`scripts/backup_postgres.sh`, `make backup-db`); WAL archiving / offsite still open | `[PARTIAL]` | — | 2026-07-02 |

## Phase A — Make It Safe

| Gap # | Title | Phase Task | Status | Date |
|-------|-------|------------|--------|------|
| 1 | Fail-safe controller / AI watchdog | A1 | `[DONE]` — ADR-0005, failsafe.py, 39 tests green | 2026-05-29 |
| 3 | EV preempt + pedestrian + ADA flows | A7 | `[DONE]` — ADR-0007, preempt+ped-call schemas, failsafe state machine, 36 new tests | 2026-05-30 |
| 5 | Tests for decision-engine + traffic-controller | A3 | `[DONE]` — 74 controller + 43 engine tests; uncovered A1 wire-mapping bug, fixed in same PR | 2026-05-30 |
| 6 | GitHub Actions CI pipeline | A4 | `[DONE]` — `.github/workflows/{ci,release,nightly}.yml`, dependabot, CODEOWNERS, CONTRIBUTING | 2026-05-29 |
| 10 | Secrets out of repo (SOPS + age) | A5 | `[DONE]` — `.sops.yaml`, `deploy/secrets/`, Makefile targets, Flux integration, CI gates, runbook | 2026-05-30 |
| 12 | JWT + RBAC wired on every public endpoint | A6 | `[DONE]` (controller + decision-engine) — ADR-0006, shared/atms_common/auth.py | 2026-05-30 |
| 13 | Real `/live`, `/ready`, `/startup` probes / shared-lib bootstrap | A2 | `[PARTIAL]` (8 of 11) — controller+engine (full incl. HealthRouter); api-gateway, data-aggregator, intersection-coordinator, ntcip-interface, analytics, dashboard (bootstrap). Remaining 3 (video-processor, ai-perception, sensor-fusion) deferred pending refactor — tracked in migration guide. | 2026-05-30 |

## Phase B — Make It Observable and Consistent

| Gap # | Title | Phase Task | Status | Date |
|-------|-------|------------|--------|------|
| 7 | OpenTelemetry tracing end-to-end | B2 | `[DONE]` — ADR-0010, shared/atms_common/tracing.py, Kafka header propagation, FastAPI auto-instrumentation, trace_id in logs, 11 tests | 2026-05-30 |
| 8 | Structured JSON logging + aggregation (Loki) | B3 | `[DONE]` — ADR-0011, bind_decision_id helper, infrastructure/observability/ (loki/promtail/tempo/otel/grafana), 3 dashboards, 4 tests | 2026-05-30 |
| 9 | `shared/atms_common/` library | B1 | `[DONE]` (foundation) — ADR-0008, errors/config/logging/health/kafka + 17 tests; traffic-controller refactored as PoC | 2026-05-30 |
| 11 | mTLS via Linkerd + network policies | B5 | `[DONE]` — ADR-0012, infrastructure/linkerd/ (cert-manager + helm values), 6 NetworkPolicies in k8s/base/network-policies/, runbook docs/runbooks/mtls.md | 2026-05-30 |
| 14 | Retries, circuit breakers, bulkheads, timeouts | B4 | `[DONE]` — ADR-0009, shared/atms_common/resilience.py, wired into kafka producer + consumer, 24 tests | 2026-05-30 |

## Phase C — Make It Real

| Gap # | Title | Phase Task | Status | Date |
|-------|-------|------------|--------|------|
| 2 | NTCIP 1202/1203 conformance + HW-in-the-loop | C1 | `[TODO]` | — |
| 4 | Edge agent + offline mode | C2 | `[TODO]` | — |
| 18 | TimescaleDB migration + Alembic | C4 | `[DONE]` — ADR-0013, alembic + 5 migrations (initial / timescale ext / hypertables / continuous aggregates / retention), shared/atms_common/db.py with HealthCheck integration, runbook docs/runbooks/database.md, 5 tests | 2026-05-30 |
| 20 | NTP/PTP time sync | C5 | `[DONE]` — ADR-0017, shared/atms_common/timekeeping.py (SyncedTimestamp + NTP/PTP probes + HealthCheck integration), 14 tests, docs/runbooks/time-sync.md | 2026-05-30 |
| 21 | Camera calibration drift handling | C6 | `[TODO]` | — |
| 22 | Weather + lighting adaptation | C7 | `[DONE]` — ADR-0018, shared/atms_common/weather.py (WeatherSnapshot + provider + adjustment tables + audit event), 13 tests, docs/runbooks/weather-adaptation.md | 2026-05-30 |
| 23 | V2X (J2735) stub interface | C8 | `[DONE]` — ADR-0019, shared/atms_common/v2x.py (BSMMessage + bsm_to_preempt_request bridge), services/v2x-interface/ skeleton (B1+A6 wired), 24 tests, docs/runbooks/v2x.md | 2026-05-30 |
| 24 | SUMO simulation harness | C3 | `[DONE]` — ADR-0016, simulation/{harness,scenarios,tests}, rush-hour scenario, `make simulate SCENARIO=...`, 26 tests, docs/runbooks/simulation.md | 2026-05-30 |

## Phase D — ML Maturity

| Gap # | Title | Phase Task | Status | Date |
|-------|-------|------------|--------|------|
| 15 | Model registry + serving (MLflow / Triton) | D1 | `[PARTIAL]` — ADR-0015, shared/atms_common/model_registry.py (registry client wrapper + lifecycle validation), 21 tests, docs/runbooks/model-registry.md. Serving (ai-perception → registry-pull) is a follow-up. | 2026-05-30 |
| 16 | Drift detection + nightly accuracy regression | D2 | `[TODO]` | — |
| 17 | Retraining + labeling pipeline | D3 | `[TODO]` | — |
| 19 | Data retention / privacy / DSAR | D4 | `[DONE]` — ADR-0014, shared/atms_common/{privacy,dsar}.py, alembic 0006 (dsar_requests + anonymization_audit + subject_id), 24 tests, docs/runbooks/dsar.md, docs/privacy.md (GDPR/CCPA map) | 2026-05-30 |

## Cross-cutting (covered by phase work)

| Gap # | Title | Where Addressed | Status |
|-------|-------|-----------------|--------|
| 25 | Per-service `venv/` committed | H2 | `[BLOCKED]` |
| 26 | Duplicate root processor scripts | H3 | `[TODO]` |
| 27 | 60+ stale status MDs in `docs/` | H4 | `[DONE]` |
| 28 | No ADRs | H5 | `[DONE]` |

## ADR follow-ups

| Source ADR | Item | Status | Date |
|------------|------|--------|------|
| ADR-0006 (A6) | Purge deprecated `security/jwt_handler.py` + `security/middleware.py` | `[DONE]` — files removed from disk; `security/__init__.py` docstring updated to reflect | 2026-05-30 |
| ADR-0006 (A6) | RS256 / JWKS verification (OIDC IdP cutover) | `[DONE]` — `_verify_rs256` implemented with PyJWKClient; 9 new tests covering happy path / expired / wrong issuer-audience-kid / tampered-signature / wrong-key / JWKS cache; `docker-compose.keycloak.yml` + `deploy/keycloak/atms-realm.json` for dev; `docs/runbooks/oidc-keycloak.md` for cutover | 2026-05-30 |
| ADR-0016 (C3) | CI sim-regression workflow with KPI baseline diff + PR comment | `[DONE]` — `simulation/compare_kpis.py` + 19 tests; `simulation/baselines/rush-hour.json` (placeholder until first canonical SUMO run captures real numbers); `.github/workflows/sim-regression.yml` matrix-per-scenario, posts sticky PR comment; runbook `docs/runbooks/sim-regression.md` covers self-hosted runner provisioning + baseline update procedure | 2026-05-30 |
| ADR-0017 (C5) | Safety-clock lint banning `time.time()` / `datetime.now()` in safety scope | `[DONE]` — `tools/lint_safety_clock.py` + `tools/.safety_clock_legacy.txt` + CI step in `.github/workflows/ci.yml`; 28 tests in `tools/tests/`; 0 violations across 68 scanned files | 2026-05-30 |
| ADR-0008 (B1) | decision-engine `HealthRouter` integration (matching traffic-controller's pattern) | `[DONE]` — shared HealthRouter wired with kafka + engine dep-checks; legacy `/health` retained with deprecation note; 5 new probe tests | 2026-05-30 |
