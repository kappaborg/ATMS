# ADR-0016: SUMO simulation harness

**Status:** Accepted
**Date:** 2026-05-30
**Closes:** PRODUCTION_GAPS.md gap #24 (Phase C3)

## Context

The senior-engineer prompt requires that any PR touching the decision logic show simulation deltas (avg delay, max queue, throughput, conflicts) against a baseline. We cannot test on real intersections; we need a fast deterministic sim.

SUMO (Eclipse SUMO) is the de-facto OSS traffic micro-simulator. It runs offline, is scriptable via TraCI (a TCP-based control interface), and can replay scenarios from XML. CARLA is the alternative (heavier, sim-focused on autonomous vehicles + sensors); for signal-control policy testing SUMO is sufficient and an order of magnitude lighter.

## Decision

### Tool

**SUMO** via the Python `traci` library. Local install:
- macOS: `brew install sumo`
- Linux: `apt install sumo sumo-tools sumo-doc`
- Python deps: `pip install eclipse-sumo traci sumolib`

### Architecture

```
simulation/
├── __main__.py                  # `python -m simulation <scenario>`
├── harness/
│   ├── kpis.py                  # Pure-Python KPI accumulator (testable without SUMO)
│   ├── runner.py                # SimulationRunner — TraCI bridge
│   └── report.py                # Self-contained HTML report renderer
├── scenarios/
│   ├── rush-hour/
│   │   ├── network.net.xml
│   │   ├── routes.rou.xml
│   │   ├── detectors.add.xml
│   │   └── config.sumocfg
│   ├── ev-preempt/             # (follow-up)
│   ├── ped-storm/              # (follow-up)
│   └── camera-failure/         # (follow-up)
└── out/
    └── <scenario>/
        ├── report.html
        └── kpis.json
```

The harness is invoked as `python -m simulation rush-hour` (or `make simulate SCENARIO=rush-hour`). It:
1. Launches SUMO with `traci.start([...])`.
2. Each step:
   - Reads e1 detector counts per approach.
   - Builds a `TrafficData` dict matching the decision-engine's existing input shape.
   - Calls `AIDecisionEngine.make_decision(ns, ew)` (in-process — no Kafka).
   - Maps the recommended phase to SUMO's traffic-light program (`traci.trafficlight.setPhase`).
   - Observes one step's KPIs into the accumulator.
3. At end, writes `kpis.json` and renders `report.html`.

### Decision-engine integration boundary

The harness uses `ai_decision_system.AIDecisionEngine` directly as a library — **no** Kafka, **no** HTTP. The same AI logic that runs in production runs in the sim; only the I/O is swapped. This is the right inversion: the sim is a test harness, not a runtime dependency of the service.

### KPI surface

The accumulator records per-tick observations and computes the following at the end of the simulation:

| KPI | Definition | Units |
|-----|-----------|-------|
| `avg_delay_s` | Sum of vehicle waiting time / vehicles departed | seconds |
| `max_queue_length` | Maximum simultaneous queued vehicles across all approaches | count |
| `throughput_vph` | Vehicles departed × 3600 / sim_duration_s | vehicles/hour |
| `conflicts` | Pairs of conflicting greens observed in tick state | count (must always be 0) |
| `mode_dwell_s` | Time spent in each FailsafeController mode | dict[mode, seconds] |
| `preempt_events` | Number of EV preempts armed | count |
| `ped_calls_served` | Number of ped phases completed | count |

KPI calculation is in `kpis.py` and is **pure Python** — fully testable without SUMO. Observations are simple dicts the runner feeds in.

### Baseline diff

If `simulation/baselines/<scenario>.json` exists, the report includes a baseline-diff section. Each KPI's delta from baseline is shown with a green/red highlight. A PR that worsens any KPI by more than a threshold (configurable per scenario; default ±5%) fails the simulation-gate CI job (follow-up — wires the gate after the first baseline is committed).

### Determinism

SUMO runs are deterministic when seeded. The harness sets `--seed 42` by default; per-scenario overrides allowed. Two runs of the same scenario produce identical KPIs.

### Out of scope for C3

- **Multi-intersection coordination scenarios.** Phase C3 ships single-intersection; multi-intersection is a follow-up driven by the intersection-coordinator service.
- **Realistic vehicle dynamics (acceleration profiles per vehicle type).** SUMO defaults are sufficient for policy testing; per-vehicle physics is future work.
- **Connected-vehicle traces (V2X).** Phase C8 stub feeds in here; harness ingestion is a follow-up after V2X service ships.
- **Headless cluster CI.** Adding `sumo-gui` requires a display server; CI runs `sumo` (no GUI) only. Headless verified locally before merge.

## Consequences

- New dev-only deps: `eclipse-sumo`, `traci`, `sumolib` (installed via `pip install -r simulation/requirements.txt`). Production runtime is unaffected.
- `make simulate SCENARIO=rush-hour` becomes a developer pre-merge check for any change to decision logic.
- Baseline files live in `simulation/baselines/`; updates require a justification in the PR description.
- A CI job (`.github/workflows/sim-regression.yml`, follow-up) re-runs every scenario nightly and posts to the PR if a baseline is exceeded.
- Phase C3 unlocks A7's "simulated EV scenario triggers preempt within one decision cycle" acceptance through a more realistic harness than the in-process unit test.
