# ATMS — Project Summary (latest)

_Last updated: 2026-07-08_

A government-grade **Adaptive Traffic Management System**: fixed cameras →
on-device AI detection → explainable signal-timing decisions → road-safety
analytics with photographic evidence. Runs as a desktop operator panel
(Tauri/Svelte) backed by a self-contained Python gateway, deployable
anywhere via Docker.

---

## 1. Where we are — status at a glance

| Area | Status |
|---|---|
| **Core control** (adaptive, predictive, emissions-aware, green-wave) | ✅ built & benchmarked |
| **Priority vehicles** (EVP, transit, pedestrian, emergency-vehicle detection) | ✅ built |
| **Driver-anomaly suite** (stopped, speeding, wrong-way, red-light, reckless, drift) | ✅ built & hardened |
| **License-plate evidence** (per-country validation, consensus, DSAR, retention) | ✅ built |
| **Detection pipeline integrity** (dedup, teleport gates, deep ReID, parked-vs-stalled) | ✅ hardened & verified |
| **Multi-stream performance & per-camera tuning** (confidence floor, bounded latency, SAHI) | ✅ solved & verified |
| **Live camera ingestion** (RTSP / USB / file / YouTube-live / municipal HLS) | ✅ working (4 live feeds) |
| **Security** (RBAC, audit, path-traversal fix, SSRF confinement) | ✅ reviewed & fixed |
| **Deployment** (Docker image + compose + bare-metal setup) | ✅ verified in-container |
| **Pilot paperwork** (validation protocol, DPIA, capability one-pager) | ✅ drafted |
| **Field speed validation** | ⏳ the user's next milestone (protocol provided) |
| **Physical signal control** (NTCIP, conflict monitor, HA) | 🔲 hardware/contract tier |

**Tests:** panel-gateway **135/135**, decision-engine **77/77**, benchmarks **11/11**; frontend `svelte-check` **0 errors / 0 warnings**. Rust build clean.

**Current phase: pilot-readiness / pre-deployment.** The software is
feature-complete and hardened; remaining work is validation-in-the-field and
hardware integration, not more features.

---

## 2. What the system does

- **Adaptive signal control** reacting to live demand, with a **15-min
  congestion forecast**; every decision carries a human-readable reason
  (auditable AI). A hard failsafe layer owns signal safety — the AI advises,
  it can never make an intersection unsafe.
- **Emissions-aware**: CO₂ is a first-class decision factor; measured CO₂ and
  estimated savings are reported per camera and exportable.
- **Priority for people**: emergency-vehicle preemption (one-click, with
  automatic flashing-light detection alerts), transit (bus) priority,
  pedestrian clearance protection, green-wave corridor coordination.
- **Safety analytics with evidence**: each violation logged once with a photo
  snapshot and (for violators only) a validated plate; auto-purged per
  retention policy.
- **Operations**: multi-intersection console, multi-operator accounts with
  roles + audit trail, unattended 24/7 recording, live-stream ingestion,
  per-camera small-object mode (SAHI) and per-camera confidence tuning.

## 3. Measured results (re-verified from code)

| Metric | Result |
|---|---|
| Delay vs fixed-time (imbalanced demand, sim) | **−80% delay, −69% idle CO₂, +529 veh/h served** |
| Delay vs fixed-time (heavy demand, sim) | **−18% delay** |
| Green-wave corridor vs uncoordinated | **58% fewer stops** (2.1 vs 5.0/veh) |
| Decision latency | ~35 µs |
| Multi-stream latency (whole-frame cams, 4 up) | **~175 ms / 5–6 fps** (was 1782 ms / 1 fps) |
| Pipeline integrity | 0 duplicate boxes / 908 live frames; glitch-induced false violations eliminated |

_Delay/CO₂ figures are simulation results; a pilot measures its own before/after via the history export._

---

## 4. How we got here — the work, in order

**Feature build-out**
- Reckless/erratic (weaving), drift/loss-of-control (physics-based lateral-G),
  license-plate capture for violators.
- Per-country plate validation (default **Bosnia & Herzegovina**, EU fallback)
  with OCR disambiguation + multi-frame consensus — designed to report **no
  plate rather than a wrong plate**.
- Persisted violation evidence log (snapshots, CSV export, Violations tab).
- SAHI sliced inference for aerial/small-object detection; congestion gate so
  red-light/jam waiting isn't flagged as incidents.
- Emergency-vehicle detection via flashing blue/red light bar (alert-only,
  never auto-preempts); live web-stream ingestion (YouTube-live → HLS).
- macOS auto-start at login; violation-snapshot CSP fix.

**Detection-integrity hardening** (the "why is a parked car speeding?" arc)
- **Parked vs stalled**: a stop is only an incident if the vehicle was seen
  moving and is stopped in the roadway.
- **Teleport gates**: track identity glitches (occlusion box-jumps, ID
  switches) can no longer poison speed / reckless / red-light / drift; sustained
  violations only.
- **Deep ReID**: MobileNetV3 appearance fingerprints recover a vehicle's
  identity across occlusions (conservative — never wrong-merges).
- **Detection dedup**: one box per physical vehicle (kills car+truck double
  boxes).

**Productization & governance**
- Untracked PII (snapshots/plate DB) from git; wired evidence **retention**
  (was documented but never enforced) + DSAR endpoints (query by plate,
  single-record erasure).
- **Docker** image (weights baked in, non-root, `/data` volume) + compose +
  bare-metal setup script; `DEPLOYMENT.md`. Verified end-to-end in-container.
- **Pilot package** in `docs/pilot/`: field **validation protocol**, **DPIA**
  draft, **capability** one-pager.
- **Security review**: fixed a path-traversal (unvalidated `camera_id` →
  snapshot path); confirmed SQL/SSRF/auth/subprocess safe.

**Multi-camera reality** (latest)
- Fixed night under-detection — root cause was the **tracker's new-track
  threshold**, not the detector (`PANEL_TRACK_NEW`); made model/confidence
  tunable.
- **Per-camera confidence floor** (in-app − / + stepper) to drop wrong boxes on
  noisy scenes (water/reflections/foliage).
- **Bounded multi-stream latency**: non-blocking shared-detector lock — a busy
  (SAHI) camera no longer makes the others queue.

---

## 5. Live cameras currently configured

| Camera | Location | Notes |
|---|---|---|
| `live2` | Nanai Rd, Patong, Phuket 🇹🇭 | night street; SAHI on, confidence 0.30 |
| `sarajevo` | Municipality Centar, Sarajevo 🇧🇦 | confidence 0.45 |
| `istanbul` | Dragos, Istanbul 🇹🇷 | IBB municipal HLS (direct); confidence 0.55 |
| `rio` | Copacabana Posto 3, Rio 🇧🇷 | beach promenade; confidence 0.50 |

_Note: commercial token-gated portals (skylinewebcams, tvkur/Kocaeli) cannot be
ingested without a browser session — documented honest limitation. Municipal
Wowza/HLS `.m3u8` feeds (like IBB) work natively._

---

## 6. Key operational knobs (env / per-camera)

- **Per camera (in-app or API):** SAHI on/off, confidence floor, calibration
  (ground plane, approach zones, stop-lines).
- **Env:** `PANEL_MODEL` (yolov8n/s/m), `PANEL_CONFIDENCE`, `PANEL_TRACK_NEW`,
  `PANEL_MIN_CONFIDENCE`, `PANEL_INFER_WAIT_MS`, `PANEL_DETECT_INTERVAL_MS`,
  `PANEL_USE_SAHI`/`PANEL_SAHI_SLICE`, `PANEL_REID`, `PANEL_PLATE_COUNTRY`,
  `PANEL_READ_PLATES`, `PANEL_VIOLATION_RETENTION_DAYS`, `PANEL_ALWAYS_RECORD`,
  `PANEL_USERS`/`PANEL_AUTH_SECRET` (RBAC).
- **Ops lesson:** `launchctl kickstart -k` restarts the process but does **not**
  reload new plist env vars — use `launchctl unload && load`.

---

## 7. Honest boundaries & residual risks

- Speed / emissions / drift accuracy depends on **per-camera calibration**;
  uncalibrated cameras report no speed by design.
- Violation outputs are **operator alerts / analytics**, not court evidence;
  plate capture needs ANPR-grade camera placement to perform well.
- SAHI is ~1 fps (tiled inference) — enable only where small-object recall
  matters.
- ID-switch between two similar moving vehicles can still briefly
  mis-attribute (mitigated by ReID + consensus, not eliminated).
- Controlling physical signals requires NTCIP-conformant controller
  integration + a certified conflict monitor (out of current scope).
- **Git history note:** an early commit put runtime PII in history; the user
  force-pushed a scrub. Runtime state is now gitignored.

---

## 8. Next steps

1. **Field speed validation** (the user's milestone) — run
   `docs/pilot/VALIDATION_PROTOCOL.md`: ≥20 GPS-referenced runs per camera,
   pass = MAE ≤ 10%, bias ≤ 5%. This makes every measured output defensible.
2. **Pilot conversation** — complete the DPIA `[CONTROLLER]` fields; use the
   capability one-pager + benchmark numbers.
3. **Hardware/contract tier** (when a pilot is secured) — NTCIP controller
   integration, conflict monitor, HA/redundancy, ANPR-grade camera placement.
4. **Research-tier upgrades** (optional) — trained emergency-vehicle
   classifier, oriented-bbox model for true slip-angle drift, WebRTC video.

---

## 9. Repository map

- `services/panel-gateway/` — the FastAPI gateway (detection→decision→evidence),
  Dockerfile, requirements, setup.sh, tests.
- `panel/` — Tauri/Svelte desktop operator app.
- `services/ai-perception/`, `services/decision-engine/`, `ai/`,
  `shared/atms_common/` — shared detection/tracking, decision engine,
  predictors, privacy tooling.
- `deploy/` — docker-compose + LaunchAgent.
- `docs/pilot/` — validation protocol, DPIA, capability summary.
- `DEPLOYMENT.md` — how to run it anywhere (Docker + bare metal + security).
- `benchmarks/` — control + corridor benchmark scripts.
</content>
