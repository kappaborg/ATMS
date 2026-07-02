# ADR-0021 — AI Decision Chamber (6-layer phase orchestrator)

**Status:** Accepted — Phase 1 MVP shipped 2026-06-14.
**Context:** Earlier sessions built ATMS up to "observe + display": vehicle detection, brand identification, per-direction emission aggregation, operator console. The system was **not** actually deciding anything — `commanded_phase` was a static string. The product is positioned as an **AI decision engine** for traffic priority, so we need a real, production-grade decision component.

## Decision

We introduce a **6-layer Decision Chamber** at `simulation/decision_chamber/`. Every tick takes per-direction sensor state and emits an explainable, auditable, safety-aware phase request:

```
L0 Sensor Fusion → L1 Preemption → L2 Policy Gates →
                   L3 Optimization → L4 Hysteresis → L5 Commit + Audit
```

### Why a layered architecture (not a single weighted sum)

A single weighted score cannot express the operational hierarchy real traffic engineers need:

| Concern | Where it lives | Why this layer |
|---|---|---|
| Emergency vehicle preemption | **L1**, before optimization | Hard override — ambulance never loses to a queue length comparison |
| Pedestrian phase already running | **L2**, before optimization | Hard safety constraint — chamber cannot interrupt a walk phase |
| Min/max phase | **L2** | Stability + equity guarantees |
| Multi-objective trade-offs | **L3** | The actual optimization (queue + emission + fairness) |
| Anti-flip-flop | **L4** | Hysteresis to stabilise on noisy signals |
| Audit trail | **L5** | Every decision logged with full provenance |

### Optimization objective (L3)

Three signals contribute to each direction's score:

1. **Queue pressure** — `vehicle_count`, normalised across directions
2. **Emission cost** — `Σ over queue [ idling_g_per_min × (seconds_already_waiting / 60) ]`. Prioritising the direction with the highest accumulated emission cost minimises **total system CO₂ per unit time**. This is the climate-aware objective and the project's core differentiator.
3. **Fairness pressure** — `seconds_since_green / max_starvation_seconds`

Default weights: `w_queue=0.30  w_emission=0.40  w_fairness=0.30`. Emission gets the slight lead per the project's environmental positioning. Tunable per deployment via `ChamberConfig`.

### Safety boundary — SIL separation

The chamber is **NOT** a SIL-rated component and **must not** drive signal lights directly. It outputs ADVISORY phase requests. In production these flow to an NTCIP-1202 signal controller (the SIL-rated device); the controller enforces hard safety (no conflicting greens, min clearance, watchdog) and falls back to fixed-time if the chamber crashes or sends invalid requests. This separation is non-negotiable for real-world deployment.

For Phase 1 the controller bridge writes the phase request to the state JSON; Phase 2 wires real NTCIP-1202.

### Emergency preemption — multi-source by design

`EmergencyDetector` protocol — each implementation polls a real source and emits `EmergencySignal` objects. Phase 1 ships:

- `OperatorOverrideDetector` — file-based (operator console writes JSON, chamber reads). Production swap: REST endpoint. Same signal shape.
- `VisualLightbarDetector` — colour heuristic on the top 25% of vehicle crops; counts strong-red + strong-blue pixels; both above threshold = lightbar.

Phase 2 stubs (interface ready, no implementation yet):
- `AudioSirenDetector` — short-time FFT + classifier on mic input
- `V2XSrmDetector` — SAE J2735 Signal Request Message subscriber

The chamber treats sources as logical OR — any one positive triggers preemption — but the audit log records WHICH source(s) fired so we can analyse reliability over time.

### State, replayability

Every chamber tick writes one JSON-line to the audit log containing the full `ChamberInput` AND `ChamberOutput`. A replay tool can re-run any logged tick → deterministic output (the chamber has no internal randomness; the only stateful elements are `seconds_since_green` per direction and `seconds_in_current_phase`, both reconstructible from the input stream). This is essential for:

- Regulatory audit (after-the-fact justification of a decision)
- Incident investigation (replay a 5-second window around an event)
- A/B testing (run a new weight set against the same logged input stream offline)

PII guarantees: the log contains only aggregated metrics (vehicle counts, emission rates, scores). No plate numbers, no per-vehicle fingerprints, no track IDs survive past the local 5-minute tracker window.

## Consequences

### Positive

- **Real decisions, real data.** No mocks at the boundaries: every signal in the chamber comes from a real sensor (camera-driven detections, real emission table lookups, real timer state). Phase 2's protocol bindings (NTCIP, V2X, GTFS) plug in without architectural changes.
- **Explainable.** Operator sees per-layer trace + per-direction scores + dominant factor + full reasoning. This is the difference between "AI black box" and "decision system a city engineer can defend in court".
- **Replayable.** Every decision can be re-run. Standard for safety-relevant ML/AI systems; rare in research prototypes.
- **Production architecture.** The L0-L5 split + protocol-based detectors + audit log + SIL boundary are the right shapes for actual deployment, not just demo polish.

### Negative / accepted limitations

- **Phase 1 doesn't implement audio siren or V2X.** Stub interfaces are in place; real implementations land in Phase 2 (audio model training + RSU hardware integration).
- **No multi-intersection coordination yet.** Pattern A (green wave), B (mesh), C (central optimizer) are Phase 3. Phase 1 ships single-intersection.
- **No transit signal priority.** Requires real GTFS-realtime feed from the target city's transit agency — deferred to Phase 2 when the pilot city is selected.
- **L0 sensor fusion is minimal in Phase 1.** Just counts-based health check. Production needs per-sensor freshness, calibration drift detection, cross-source agreement scoring.

### Open questions for Phase 2+

1. Pedestrian demand: today the chamber reads `has_pedestrian_demand` per direction but no source sets it. Need to wire (a) NTCIP detector signal from the push button, (b) camera-based pedestrian-at-crosswalk detection.
2. Mode switching state machine: `ChamberMode` is defined (adaptive / preempt / fixed_time / manual / flash_caution) but only `adaptive` and `preempt` transitions are implemented. The rest need explicit triggers + state machine.
3. Audit log archival: today writes JSON-lines to local disk. Production needs rotation + forwarding to city archive (TimescaleDB / S3) + retention policy enforcement.

## References

- Companion ADRs: [`0019-v2x-bsm-stub.md`](0019-v2x-bsm-stub.md) (V2X foundation), [`0020-vehicle-brand-perception.md`](0020-vehicle-brand-perception.md) (brand model that feeds the emission cost)
- Implementation: `simulation/decision_chamber/`
- Operator UI: `services/operator-console/src/app.py` (chamber panel)
- Dossier: `docs/demos/brand-perception-dossier.md` (will receive a chamber section in Phase 1 close-out)
