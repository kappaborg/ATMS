# Runbook: SUMO simulation harness (Phase C3)

**Audience:** ML / traffic engineers running policy regressions.
**Design:** [ADR-0016](../adr/0016-sumo-simulation-harness.md).
**Code:** [`simulation/`](../../simulation/).

---

## 1. Install (one-time)

```bash
# 1. SUMO binary.
brew install sumo                       # macOS
# apt install sumo sumo-tools sumo-doc   # Debian/Ubuntu

# 2. Python bindings.
pip install -r simulation/requirements.txt
```

Verify:

```bash
which sumo
python -c "import traci, sumolib; print('ok')"
```

## 2. Run a scenario

```bash
make simulate SCENARIO=rush-hour
```

Equivalent without Make:

```bash
python -m simulation rush-hour
```

Output lands under `simulation/out/<scenario>/`:

- `kpis.json` — machine-readable KPIs.
- `report.html` — self-contained HTML report (open in any browser).

Exit code:
- `0` — simulation ran, no safety violations.
- `1` — simulation ran, at least one conflicting-green tick observed (safety violation — investigate before merging).
- `2` — simulation could not start (SUMO missing, scenario not found, etc.).

## 3. Reading the report

The HTML report sections, in order:

1. **Safety banner** — green = zero conflicts, red = violation count.
2. **Key indicators** — Avg delay, max queue, throughput, conflicts, preempts, ped phases.
3. **Run metadata** — scenario, duration, steps.
4. **Time in each mode** — failsafe state dwell breakdown.
5. **Baseline diff** (only if `simulation/baselines/<scenario>.json` exists) — per-KPI delta with colour coding (green = improvement; red = regression).

## 4. Comparing against a baseline

The first time a scenario is considered stable, an engineer commits its `kpis.json` as the baseline:

```bash
cp simulation/out/rush-hour/kpis.json simulation/baselines/rush-hour.json
git add simulation/baselines/rush-hour.json
git commit -m "sim: baseline for rush-hour scenario"
```

Every subsequent run renders a "Baseline diff" section in the report. A PR that changes the AI decision logic must include a fresh simulation run output (or trust the nightly regression workflow, follow-up).

## 5. Authoring a new scenario

1. Create `simulation/scenarios/<name>/`.
2. Add `network.net.xml`, `routes.rou.xml`, `detectors.add.xml`, `config.sumocfg`. The rush-hour scenario is a small reference.
3. Run `make simulate SCENARIO=<name>` locally and review the report.
4. Once stable, commit a baseline as in §4.

Per ADR-0016 the planned scenarios are: `rush-hour` (shipped), `ev-preempt`, `ped-storm`, `accident`, `camera-failure`. Each lands in its own PR.

## 6. The TraCI bridge

`simulation/harness/runner.py` is the bridge between SUMO and the decision-engine logic. At each tick:

1. Reads inductive-loop detector counts per approach via `traci.inductionloop`.
2. Builds the same `TrafficData` dict the production decision-engine accepts.
3. Calls `AIDecisionEngine.make_decision(...)` in-process — **no Kafka**, **no HTTP**.
4. Maps the recommended phase to a SUMO traffic-light program index via `traci.trafficlight.setPhase`.
5. Records the tick into the KPI accumulator.

Because the harness uses the **production AI logic** as a library, any decision-engine change is exercised by the sim. Conversely, replacing the simulation does not affect production behavior.

## 7. CI integration (follow-up)

Planned: `.github/workflows/sim-regression.yml` runs every scenario on push and posts deltas to the PR. The CI gate fails if any KPI regresses beyond a configurable threshold (default ±5%). Requires a SUMO-equipped runner — typically a self-hosted runner with `apt install sumo` baked in, since the default GitHub-hosted runners do not include SUMO.

Until that workflow ships, manual runs + commits to `simulation/baselines/` are the gate.

## 8. Troubleshooting

| Symptom | Probable cause | Fix |
|---------|----------------|-----|
| `SimulationError: SUMO Python bindings not installed` | `pip install` for `traci/sumolib/eclipse-sumo` not run | `pip install -r simulation/requirements.txt` |
| `RuntimeError: Could not connect to SUMO` (during a run) | `sumo` binary missing or not on PATH | `brew install sumo` |
| Reports show `0` throughput | Route flows didn't load; check `config.sumocfg` paths | Verify the `<route-files>` line in your sumocfg |
| Persistent conflicts > 0 | Either the AI is wrong **or** the TL program in `network.net.xml` is misaligned with `runner._PHASE_TO_TLPROGRAM` | Compare the TL phase string with the wire phase the AI emits |
| Test failure on CI but local pass | Non-determinism — likely a sim-time-based test bug | Re-run with `--seed N` to verify reproducibility |
