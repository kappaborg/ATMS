# ATMS Benchmarks

Quantifies whether the ATMS adaptive controller actually beats what most
intersections run today. We **cannot** run SCATS/SCOOT/commercial controllers
here, so we benchmark honestly against **fixed-time** (the real-world baseline)
and a **naive greedy** controller, on identical simulated demand with identical
clearance intervals.

```bash
python benchmarks/benchmark_control.py
```

## What it measures

A lightweight microsimulation of a 2-phase intersection (Poisson arrivals,
saturation-flow discharge on green). Per controller: average delay per vehicle,
throughput, max queue, idle CO₂ (same model as the panel), and decision latency.

## Representative result (1-hour sim per scenario)

| Scenario | Adaptive vs fixed-time (delay) | CO₂ | Note |
|----------|-------------------------------|-----|------|
| Balanced light | **−7%** | −7% | fixed-time already near-optimal; adaptive isn't meant to help here |
| Imbalanced | **+77%** | +65% | fixed-time wastes green on the empty approach and oversaturates |
| Heavy / rush | **+18%** | +13% | in the published 10–30% band |

Decision latency ~35 µs/tick → comfortably real-time. Naive greedy is unstable
(thrashes, far worse than fixed-time) — which is *why* our engine uses
hysteresis + min/max-green.

## Honest reading

- Adaptive control helps most under **imbalanced or saturated** demand; there we
  meet or exceed published adaptive-signal deployments (~10–30% delay cut).
- Under **light, balanced** demand it's ~even (here slightly worse by ~6%,
  which is <1s on a 12s delay). A **minimum-benefit gate** (don't pay clearance
  to switch green for 1–2 cars while the current approach still flows;
  standard in SCATS/SCOOT-class control) improved throughput under imbalance
  and is the principled fix. The residual balanced-light tie is *fundamental*,
  not a bug — under uniform light demand no signal policy meaningfully beats a
  sensible fixed cycle, and forcing it by tuning to this synthetic scenario
  would be over-fitting.
- This is simulation, not a field trial. Real-world numbers depend on validated
  detection/speed and true demand — see the panel calibration/validation step.

`test_control_benchmark.py` locks in the key property: adaptive must beat
fixed-time under imbalance and stay real-time.
