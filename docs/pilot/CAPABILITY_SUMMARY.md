# ATMS — Capability Summary (one page)

**Adaptive, explainable, emissions-aware traffic management with built-in
road-safety analytics — deployable on a single edge box.**

## What it does

- **Adaptive signal control** that reacts to live demand and *predicts*
  congestion 15 min ahead; every decision carries a human-readable reason
  (auditable AI). A hard failsafe layer owns signal safety — the AI advises,
  it can never make an intersection unsafe.
- **Emissions-aware**: CO₂ is a first-class factor in every decision;
  measured CO₂ and estimated savings are reported per camera and exportable.
- **Priority for people**: emergency-vehicle preemption (one-click, with
  automatic flashing-light alerts), transit (bus) priority, pedestrian
  clearance protection, green-wave corridor coordination.
- **Safety analytics with evidence**: stopped vehicle, speeding, wrong-way,
  red-light running, reckless driving, loss-of-control/drift — each logged
  once with a photo snapshot and (for violators only) a validated license
  plate; auto-purged after the configured retention.
- **Operations**: multi-intersection console, multi-operator accounts with
  roles + audit trail, unattended 24/7 recording, live ingestion of
  RTSP/USB/files and YouTube-live feeds, per-camera small-object mode (SAHI)
  for aerial views.

## Measured results

| Metric | Result |
|---|---|
| Delay vs fixed-time (simulation, imbalanced demand) | **−80% delay, −69% idle CO₂, +529 vehicles served/h** |
| Delay vs fixed-time (heavy demand) | **−18% delay** (within the published 10–30% band for adaptive systems) |
| Green-wave corridor vs uncoordinated | **58% fewer stops** (2.1 vs 5.0 per vehicle) |
| Decision latency | ~35 µs — real-time |
| Pipeline integrity (live streams) | 0 duplicate boxes / 908 frames; glitch-induced false violations eliminated (26→3 sustained readings in 60 s test) |
| Plate capture policy | conservative by design: **no plate rather than a wrong plate** (format validation + multi-frame consensus) |

## Deployment

One Docker container (weights included, works offline); durable state on a
mounted volume; RBAC + TLS-ready; 30-day evidence retention by default.
Verified end-to-end on a live public video stream inside the container.
Bare-metal (macOS/Linux) setup script included.

## Honest boundaries

- Delay/CO₂ reductions above are **simulation** results; a pilot measures its
  own before/after via the built-in history export.
- Speed, drift and CO₂ accuracy depend on per-camera **calibration**
  (validation protocol provided; field speed validation is the pilot's first
  milestone).
- Violation outputs are **operator alerts/analytics**, not court evidence;
  plate capture requires ANPR-grade camera placement to perform well.
- Controlling physical signal hardware requires NTCIP-conformant controller
  integration and a certified conflict monitor — pilot scope is
  monitoring + decision support unless that integration is contracted.
