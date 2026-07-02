# ADR-0005: Failsafe controller state machine

**Status:** Accepted
**Date:** 2026-05-29
**Closes:** PRODUCTION_GAPS.md gap #1

## Context

Audit gap #1: if the AI decision pipeline fails (decision-engine crash, Kafka partition outage, AI model returns garbage, WAN to cloud drops), the current `services/traffic-controller` blocks on the Kafka consumer and leaves the signals on their last commanded phase indefinitely. For a signalized intersection, that is a safety-critical failure mode — a stuck green on one approach with stuck red on the other will cause rear-end collisions and run-the-light incidents within minutes.

We need a controller that is **safe by default**. AI input is an *enrichment* of fixed-time operation, not a *replacement* for it. When the enrichment is unavailable or untrustworthy, the controller must fall back to fixed-time within a hard upper bound (seconds), and to an emergency all-red flash if fixed-time itself is unrecoverable.

## Decision

Implement a three-mode state machine in `services/traffic-controller/src/failsafe.py`. The module is pure synchronous Python with dependency injection for `Clock`, `MetricsRecorder`, and `TransitionLogger`, so the entire state machine is unit-testable without Kafka, network, or wall-clock time.

### Modes

| Mode | Meaning | Throughput | Safety |
|------|---------|------------|--------|
| `AI_ADAPTIVE` | Normal. Honors valid decisions from `services/decision-engine`. | Highest | Constrained by hard invariants (below) |
| `FIXED_TIME` | Fallback. Runs a pre-loaded RiLSA-conformant cycle plan. | Medium | Inherent (no AI in the path) |
| `ALL_RED_FLASH` | Emergency. All approaches flash red; intersection becomes a 4-way stop. | Lowest | Highest |

### Transitions

```
                       valid decisions resume (cooldown elapsed)
                  ┌──────────────────────────────────────────┐
                  ▼                                          │
            ┌───────────┐    decision stale > T_max     ┌────────────┐
   start ─▶ │AI_ADAPTIVE│ ─────────────────────────────▶│ FIXED_TIME │
            └───────────┘                                └────────────┘
                  │                                          │
                  │     ≥ N flap-transitions in window       │
                  └───────┬──────────────────────────────────┘
                          ▼
                   ┌────────────────┐
                   │ ALL_RED_FLASH  │ ◀── manual override / NTCIP fault
                   └────────────────┘
                           ▲   │
                           │   └── (no automatic recovery; manual reset only)
                           │
                       all transitions emit `mode_transition` metric + log
```

Concrete rules:

- **`AI_ADAPTIVE → FIXED_TIME`**: triggered when watchdog observes `now - last_valid_decision_received_at > MAX_AI_STALENESS_MS` (default 2000 ms). Also triggered after `INVALID_DECISION_BURST` consecutive invalid decisions (default 3).
- **`FIXED_TIME → AI_ADAPTIVE`**: triggered after `FIXED_TIME_MIN_DWELL_S` (default 30 s) AND `K` consecutive valid decisions (default 5). The dwell prevents thrashing.
- **`* → ALL_RED_FLASH`**: triggered when `mode_transition_count(AI_ADAPTIVE↔FIXED_TIME) within FLAP_WINDOW_S` ≥ `FLAP_THRESHOLD` (defaults 300 s and 3). Also triggered by an NTCIP-reported hardware fault, or by a manual `/control/emergency` API call.
- **`ALL_RED_FLASH → *`**: **manual operator reset only**. There is no automatic recovery from an emergency mode; an engineer confirms the intersection is safe before any movement resumes.

### Decision-message validation gate

A `DecisionMessage` is *valid* iff all of:

1. Schema parses (Pydantic / dataclass + explicit fields).
2. `intersection_id` equals this controller's configured intersection.
3. `decision_id > last_accepted_decision_id` (monotonic; rejects replay / out-of-order).
4. `producer_timestamp_ns ≤ now_ns() + CLOCK_SKEW_TOLERANCE_NS` (rejects future-dated, default skew 500 ms).
5. `valid_until_ns > now_ns()` (rejects stale; producer must set a TTL).
6. (Phase B) signature verifies against the expected producer key. Until B, this field is parsed but not enforced — a `signature_required` config flag flips enforcement on.

Any failure increments an `invalid_decisions_total{reason="..."}` counter. Three consecutive failures trip the transition rule above.

### Hard safety invariants (enforced regardless of mode)

The `current_commanded_phase()` output passes through a final safety filter that enforces:

- **No conflicting greens.** N-S and E-W cannot both be `GREEN` simultaneously, ever, regardless of what AI says.
- **Minimum green honored.** A `GREEN` is held to `MIN_GREEN_S` (default 10 s for EU/RiLSA) before any transition out.
- **Intergreen inserted.** Between two conflicting greens, the appropriate `YELLOW` + `ALL_RED` sequence is inserted with durations from the per-intersection config (speed-dependent yellow per StVO §37; geometry-derived all-red).
- **Pedestrian clearance not shortened mid-cycle.** Once `PED_*_WALK` begins, the clearance interval (`PED_*_FLASHING_GREEN` + minimum-red-man) runs to completion before any other phase change.

These invariants are properties of the **failsafe**, not of the AI. AI cannot override them. The unit-test suite encodes them as `hypothesis` properties (Phase A3).

### Outputs

- `submit_decision(decision_dict) → ValidationResult` — called by the Kafka consumer.
- `tick(now_ns: int) → CommandedPhase` — called every `WATCHDOG_TICK_MS` by the controller loop; returns the phase to drive into NTCIP this tick.
- `current_mode() → Mode` — accessor for `/status` and `/ready` endpoints.
- `force_mode(mode: Mode, reason: str)` — operator override path; always emits an audit log.

### Dependencies (injected, all under `shared/atms_common/`)

- `Clock` protocol → production `MonotonicClock`, tests `FakeClock`.
- `MetricsRecorder` protocol → production Prometheus wrapper, tests in-memory.
- `TransitionLogger` protocol → production structlog wrapper, tests list-capturing.
- `FixedTimePlan` dataclass → loaded from YAML at startup (per ADR-0004).

### Metrics emitted

- `atms_controller_mode{mode="..."}` (gauge, 1 for current mode 0 for others).
- `atms_controller_mode_transitions_total{from="...",to="...",reason="..."}` (counter).
- `atms_controller_invalid_decisions_total{reason="..."}` (counter).
- `atms_controller_ai_decision_age_ms` (gauge, age of the most recently accepted decision).
- `atms_controller_commanded_phase_total{phase="..."}` (counter, per-tick increment).

### Structured log fields on transition

`event="controller_mode_transition"`, `intersection_id`, `from_mode`, `to_mode`, `reason`, `last_decision_id`, `last_decision_age_ms`, `flap_count_in_window`.

## Consequences

- The traffic-controller stops being a thin Kafka-to-NTCIP shim and becomes a stateful safety component. Subsequent changes to it require Phase A3 test coverage to stay green.
- Decision-engine must populate the new fields (`decision_id`, `producer_timestamp_ns`, `valid_until_ns`, `intersection_id`, `commanded_phase`). Backward-compat: if any required field is missing, the validator rejects the message with `reason="schema_missing_field"` — the consequence is that decision-engine PRs that don't update the schema cannot drive the controller. This is intentional.
- A small piece of `shared/atms_common/` is created in this phase (decision schema, clock, metric protocols). The full shared library is Phase B (B1); we accept this minor scope creep because A1 requires the schema and clock.
- `ALL_RED_FLASH` has **no automatic recovery**. Operators must reset it. This is a deliberate safety choice and must be documented in the runbook (`docs/runbooks/failsafe.md`).
- Per-intersection fixed-time plans live in `config/intersections/<id>.yaml` and are part of the deployment artifact, version-controlled.
