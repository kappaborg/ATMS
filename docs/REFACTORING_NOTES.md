# Refactoring + Modularisation Notes

**Audience:** Engineering lead / senior reviewer planning the next round of structural improvements.
**Status as of 2026-06-05:** software pipeline complete and verified (`scripts/verify-pipeline.sh` → 43/43 green); 465 tests passing; 14 services, 22 shared modules, 19 ADRs.

This document is a focused critique of the **codebase shape** after the production rebuild. It pulls back from individual features and looks at where structure could be tighter, where modules earn their existence, and where the seams between layers leak.

The recommendations are ordered by **leverage** — what cleanup has the biggest payoff per engineer-day. Not every item should land; treat the list as a menu.

---

## 1. The picture today

```
Traffic/
├── shared/atms_common/        ✓ 22 well-bounded modules; THE library
├── services/                  ⚠ 14 services, 3 monoliths, mixed conventions
│   ├── traffic-controller/    ✓ reference impl — modular, tested
│   ├── decision-engine/       ✓ thin wrapper; clean
│   ├── v2x-interface/         ✓ small + tidy
│   ├── operator-console/      ✓ new; standalone
│   ├── api-gateway/           ✓ B1 bootstrap, modest size
│   ├── analytics/             ✓ B1 bootstrap
│   ├── data-aggregator/       ✓ B1 bootstrap
│   ├── intersection-coord/    ✓ B1 bootstrap (full wiring is Phase 4)
│   ├── ntcip-interface/       ✓ stub; HW-blocked
│   ├── dashboard/             ✓ legacy UI
│   ├── ai-perception/         ✗ 1999 LoC monolith; emission/OCR/yolo/kafka all in src/
│   ├── video-processor/       ✗ 1981 LoC monolith
│   └── sensor-fusion/         ✗ multi-file but spaghetti
├── ai_decision_system.py      ⚠ legacy SE322 module at repo root
├── atms_core/                 ⚠ legacy SE322 pipeline (kept for reference)
├── simulation/                ✓ harness + demo + scenarios — well-organised
├── tools/                     ✓ lint scripts + tests
├── infrastructure/            ✓ Linkerd, observability configs
├── k8s/                       ✓ NetworkPolicies
├── database/alembic/          ✓ migrations
├── docs/                      ✓ active (ADR, runbook, demo) + legacy archives
├── security/                  ⚠ 3 legacy helpers; api-gateway still imports rate_limiter
├── deploy/                    ✓ secrets, keycloak
├── scripts/                   ✓ verification + utilities
├── tests/                     ⚠ legacy SE322 black-box tests (mostly unused)
└── 6 × docker-compose*.yml    ✓ properly layered
```

The good news: **the production-grade core is healthy**. The shared library is well-bounded, the safety-critical services (`traffic-controller`, `decision-engine`, `v2x-interface`) are modular and tested, observability and CI are tight.

The areas asking for attention are all at the seam between the new architecture and the SE322 legacy.

---

## 2. The five highest-leverage refactors

### 2.1 Break up the three monoliths (~3 engineer-weeks)

`services/ai-perception/`, `services/video-processor/`, `services/sensor-fusion/` each ship a single `src/main.py` of 1900–2000 lines that does detection + tracking + Kafka + OTel + license-plate handling + emissions + optimisation all in one file. They are on the **A2-pending list** in `PRODUCTION_GAPS.md` for a reason: they can't be touched safely without test coverage, and they can't be tested cleanly without breakup.

**Recommended structure** (per service, mirroring traffic-controller's layout):

```
services/<name>/
├── src/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + lifecycle (~150 LoC)
│   ├── pipeline.py          # the processing graph (one class)
│   ├── kafka_io.py          # producer + consumer wiring (use shared/atms_common/kafka.py)
│   ├── stages/
│   │   ├── detection.py     # YOLOv8 wrapper
│   │   ├── tracking.py      # ByteTrack wrapper
│   │   ├── classification.py # car-brand classifier (NEW seam for emissions feature)
│   │   ├── plate_ocr.py     # license plate detection + OCR
│   │   └── emissions.py     # imports shared/atms_common/emissions.EmissionEstimator
│   └── adapters/
│       └── camera.py        # RTSP / mjpeg / file ingestion
├── tests/
│   ├── unit/
│   └── integration/
├── requirements.txt
└── Dockerfile
```

**Why this is high leverage:**
- These three services are the **biggest single source of CO₂ data** that the new emissions feature consumes. Until they're refactored, the production emission pipeline is gated on either touching the monoliths (risky) or routing detections through a side-channel service (architectural debt).
- The 27-file legacy entry in `tools/.safety_clock_legacy.txt` (the safety-clock-lint exclusions for unrefactored code) goes away when these three services are clean.
- The A2 partial status in PRODUCTION_GAPS.md closes.

**Approach:** the refactor is mechanical, not algorithmic. The existing 1999 LoC is mostly already in logical sections separated by `# === DETECTION ===` style comment banners. Lift each section to its own file with a small wrapper class, then re-import in main.py. Coverage should follow from extracting each stage's tests in parallel.

### 2.2 Retire the repo-root legacy modules (~1 week)

`ai_decision_system.py` and `atms_core/` live at the **repo root** alongside the new architecture. They are the SE322-era decision logic that the production `services/decision-engine` wraps via `importlib`:

```python
# simulation/harness/runner.py (current)
from ai_decision_system import AIDecisionEngine
```

Two problems:
1. Repo-root Python files are an anti-pattern — they pollute the import namespace and force `sys.path.insert(0, str(_REPO_ROOT))` boilerplate in every service that needs them.
2. The legacy code has its own internal coupling (`atms_core/pipeline.py` imports `emission.emission_calculator`, `tracking.bytetrack_simple`, etc. from the **inside** of `services/ai-perception/src/`). This is upside-down: a "core" library should not depend on a service's internals.

**Recommended:**

| Step | Action |
|---|---|
| 1 | Move `ai_decision_system.py` to `shared/atms_common/legacy_decision.py`. Update all imports. |
| 2 | Move `atms_core/pipeline.py` to `shared/atms_common/legacy_pipeline.py`. Update all imports. |
| 3 | Inline `atms_core/model_factory.py` into the one or two callers; the factory has only a handful of consumers and the indirection costs more than it saves. |
| 4 | Add a deprecation banner to each: `# DEPRECATED: this is the SE322 module, kept for sim-harness compatibility. New code uses shared/atms_common/decision.py.` |
| 5 | Plan to delete after 2.1 lands (the ai-perception monolith refactor moves the dependents). |

This is a 1-week PR with no behaviour changes, just imports.

### 2.3 Split the `traffic-controller` service further (~1 week)

`services/traffic-controller/src/main.py` is 700+ lines now. It started small but accumulated. It's still tested + functional, but breaking it up makes the next round of changes easier:

```
services/traffic-controller/src/
├── main.py                  # FastAPI + lifecycle (~150 LoC)
├── service.py               # TrafficControllerService class
├── failsafe.py              # unchanged — already self-contained
├── api/
│   ├── status.py            # GET /, /status, /health, /signals
│   ├── control.py           # POST /control/emergency, /control/recover
│   ├── preempt.py           # POST /preempt/arm
│   └── ped.py               # POST /ped_call/request
├── adapters/
│   └── kafka_consumer.py    # decision-message ingest
└── signals/
    └── traffic_signal.py    # the display-proxy TrafficSignal class
```

The `failsafe.py` module is already well-factored — leave it alone. Everything else can be teased out one router per file. The same pattern applies to `decision-engine` and any future service that grows past ~500 LoC.

### 2.4 Promote shared concerns out of services and into the library (~2-3 days)

A handful of patterns are reimplemented per service that should live once in `shared/atms_common/`:

| Concern | Currently | Should be |
|---|---|---|
| `_build_verifier()` JWT setup boilerplate | Copied verbatim in 3 service `main.py` files | Helper: `shared.atms_common.auth.build_verifier_from_env()` |
| `_audit_log(event: dict)` operator-action logger | Copied in 3 services | `shared.atms_common.logging.build_audit_logger(service_name)` |
| `configure_logging + configure_tracing + instrument_fastapi` bootstrap block | Same 15 lines in every service | `shared.atms_common.bootstrap.configure(service: str, version: str)` |
| HS256 dev-token issuance for tests | Lives in `shared.atms_common.auth.issue_hs256_test_token` ✓ already done | ✓ |
| `rate_limiter` from `security/` | Only api-gateway uses it | Move to `shared/atms_common/rate_limit.py` and delete `security/` |

A single `shared.atms_common.bootstrap.configure(service, version)` function would remove **~60 lines of identical boilerplate from every new service** and standardise the env-var conventions. Today every new service is a copy-paste of traffic-controller's bootstrap.

### 2.5 Collapse the four legacy doc archives (~1 day)

```
docs/historical/
docs/archived/
docs/technical/
docs/user-guides/
```

All four are SE322-era documentation in various states of staleness. They contain:
- 60+ status MDs (`WEEK3_*.md`, `PHASE*_COMPLETE.md`, etc.)
- An outdated SRS PDF (`docs/technical/ATSRS.pdf`)
- Quick-start guides that reference files that no longer exist (which is why they had to be excluded from `scripts/verify-pipeline.sh` §7's cross-ref check)

**Recommended:** one folder, one README:

```
docs/legacy-se322/
├── README.md       # "These are the SE322-era documents. New work uses docs/."
├── status-mds/     # the old WEEK_*/PHASE_*/COMPLETE_* files
├── srs/            # ATSRS.pdf + the comprehensive SRS markdown
└── user-guides/    # original setup/troubleshooting guides
```

Then drop the four `EXCLUDE_DIRS` entries from `scripts/verify-pipeline.sh` (replace with the single `docs/legacy-se322`).

---

## 3. Smaller wins (each ≤ half a day)

### 3.1 Make `services/` import paths consistent
Some services use `sys.path.insert(0, str(_PROJECT_ROOT))` at the top of `main.py` to find `shared.*`. Others have it in their Dockerfile via `PYTHONPATH`. Pick one (a `services/*/pyproject.toml` with `[tool.setuptools.packages.find]` pointing at `../shared` is the cleanest). Today's mix means dev-running a service requires reading the file to know what path tricks are in play.

### 3.2 Standardise the per-service test layout
`tests/unit/` + `tests/integration/` is the pattern in traffic-controller. Other services have either `tests/` flat or no tests at all. Adopt the same skeleton everywhere; the CI matrix becomes simpler.

### 3.3 Move `tools/` into the shared library
`tools/lint_safety_clock.py` is the only file there. It's a self-contained AST checker. It would slot just as well under `shared/atms_common/lint/safety_clock.py` with a small `python -m shared.atms_common.lint.safety_clock` entry point.

### 3.4 Make the demo orchestrator stateless w.r.t. `/tmp`
The state-emitter writes to `/tmp/atms-demo-state.json` by default. Move the default to an explicit, opt-in path or pass it as an arg. `/tmp` defaults are macOS-cleanup-prone (which bit us in the verification work).

### 3.5 Consolidate the Dockerfiles
13 services × 1 Dockerfile each = a lot of near-identical files. A `services/_base/Dockerfile` that does:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY shared /app/shared
COPY services/${SERVICE}/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/${SERVICE}/src /app/src
CMD ["python", "-m", "src.main"]
```
plus per-service `Dockerfile`s that just `FROM atms/base:latest` would cut ~70% of the Dockerfile boilerplate.

### 3.6 Pin Python everywhere
Some services pin Python 3.11. Others use 3.12. The system Python on the dev machine is 3.14. CI runs on whatever GitHub gives it. Pin to **3.11** (the wheels in `eclipse-sumo`, `aiokafka`, `pyjwt`, `cryptography` are all on the boring side of the supported matrix here).

---

## 4. Things to leave alone

| Don't touch | Why |
|---|---|
| `services/traffic-controller/src/failsafe.py` | Property-tested, safety-critical, working. Any structural change is a re-validation cycle. |
| The conflict matrix in `shared/atms_common/safety.py` | Same reason. Touch only via ADR. |
| The 19 ADRs | They're the design rationale archive. Don't rewrite them — supersede with new ADRs. |
| The 6 Alembic migrations | They are history. Add new migrations, never edit old ones. |
| The Linkerd / NetworkPolicy YAML | These are minimal and correct; further tweaking only when an operator-specific concern arises. |
| The `tools/.safety_clock_legacy.txt` allow-list | The list is the punch list — removing entries means the file's been refactored. Don't bulk-edit; remove as the monolith refactor lands per-file. |

---

## 5. The modularisation principle worth keeping

The shared library demonstrates the right pattern and the rest of the codebase should follow it: **each module has one reason to change, all dependencies point downward, and the base modules (errors, config, clock) have no third-party imports**.

- `errors.py` is now a clean base module (after the `AuthError` re-export was removed in this conversation's verification pass).
- `clock.py` is pure-stdlib.
- `config.py` only depends on pydantic-settings.
- `safety.py` depends on `clock.py` and `decision.py` — both lower in the graph.
- `auth.py` depends on `errors.py` (one-way).
- `health.py` depends on `errors.py` (one-way).

Higher-level modules (`kafka.py`, `tracing.py`, `db.py`) compose the lower ones. There is **no cycle**. The new `emissions.py` follows the same shape.

The three monolith services break this principle the most — they import from inside their own deep submodules, and the SE322 `atms_core` imports from inside `services/ai-perception/`. That's the seam to repair first.

---

## 6. A pragmatic next-quarter plan

If the team has ~6 engineer-weeks to invest in cleanup before the hardware rollout:

| Week | Item | Effort |
|---|---|---|
| 1 | §2.4 Shared bootstrap helper + audit logger + JWT verifier builder | 3 days |
| 1 | §3.5 Base Dockerfile + per-service simplification | 2 days |
| 2 | §2.5 Consolidate legacy docs into `docs/legacy-se322/` | 1 day |
| 2–3 | §2.1 ai-perception monolith refactor (the biggest of the three) | ~7 days |
| 4 | §2.1 video-processor monolith refactor | ~5 days |
| 4 | §2.2 Retire `ai_decision_system.py` and `atms_core/` repo-root pollution | ~3 days |
| 5 | §2.1 sensor-fusion monolith refactor | ~4 days |
| 6 | §2.3 traffic-controller split into routers | ~3 days |
| 6 | §3.1, §3.2, §3.3, §3.6 polish | ~3 days |

After that 6 weeks, the codebase looks like this:

- **No repo-root Python files.** All code is under `services/`, `shared/`, `simulation/`, `tools/`, `scripts/`.
- **Every service has the same shape.** `src/main.py` (~150 LoC) + `src/{api,stages,adapters}/` + `tests/{unit,integration}/`.
- **Every service uses the shared bootstrap** — adding a new service is one `cookiecutter`-style template apply.
- **`tools/.safety_clock_legacy.txt` is empty** (the three monoliths are refactored and their wall-clock callsites are either gone or have explicit `# noqa: ATMS-CLOCK` markers).
- **Five legacy doc archives become one** (`docs/legacy-se322/`).
- **The emissions feature is fully integrated** — ai-perception classifies, looks up via `shared.atms_common.emissions`, emits to Kafka, decision-engine consumes real values.

This is the structural ceiling for a software-only push. Beyond it, every remaining improvement requires real hardware feedback.

---

## 7. What I would NOT do (anti-recommendations)

- **Don't move to a monorepo build tool (Bazel, Pants).** The repo is small enough that pip + docker-compose works. Bazel would add complexity without removing any.
- **Don't refactor the failsafe state machine.** It's the most carefully designed thing in the codebase. Future invariants land as new ADRs + new tests, not as structural changes.
- **Don't introduce a service-mesh sidecar pattern beyond Linkerd.** Service-to-service auth is solved (Linkerd mTLS); adding Envoy / Istio buys nothing.
- **Don't centralise on FastAPI dependency injection containers (`punq`, `injector`).** The current pattern of building dependencies at the top of `main.py` and threading them through is explicit and testable. DI containers obscure that.
- **Don't abstract Kafka behind a generic message-bus interface.** Kafka is a deliberate choice (ordering, partitioning, durability). Pretending it's swappable would lose those guarantees.
- **Don't split the shared library into multiple PyPI packages yet.** It's 22 modules; we're nowhere near the size where splitting helps. Revisit at 50+.
