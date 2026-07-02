# ADR-0007: Emergency-vehicle preempt, pedestrian-call, and ADA event model

**Status:** Accepted
**Date:** 2026-05-30
**Closes:** PRODUCTION_GAPS.md gap #3 (Phase A7)

## Context

The Phase A1 failsafe controller (ADR-0005) handles AI decisions and falls back to a RiLSA-conformant fixed-time plan, but has no concept of:

- **Emergency-vehicle preempt** — a fire / police / ambulance / public-transit vehicle needs the intersection cleared on its approach now, regardless of what the AI was about to do.
- **Pedestrian call** — a pedestrian pressed the button (or an NTCIP `ped-call` MIB write arrived) requesting a walk phase. The call must be honored in the current or next cycle and must respect minimum-walk and clearance times.
- **ADA / accessibility signals** — the controller must emit a structured signal whenever a pedestrian phase begins so downstream hardware (accessible pedestrian-signal beacons, audible/tactile devices) can announce it.

ADR-0004 already locked in that we follow EU/RiLSA semantics — green-man / flashing-green-man / red-man for pedestrians, and **dedicated input channels** for EV preempt (KAR in NL, ÖPNV-Vorrang in DE, R09.16 in UK), **not** vision-based siren/strobe heuristics.

This ADR specifies the controller-side model. Real hardware integration (NTCIP MIB writes, transponder reception, audio drivers) is downstream (Phase C1/C2 NTCIP work and per-deployment vendor integration).

## Decision

### Priority order (highest first)

```
1. ALL_RED_FLASH         (operator E-stop / hardware fault / flap escalation)
2. EV preempt active     (takes the intersection from AI / fixed-time)
3. Pedestrian clearance  (in-flight: green-man or flashing-green-man cannot be cut)
4. AI decision           (AI_ADAPTIVE mode)
5. Fixed-time plan       (FIXED_TIME mode)
```

This is *strict*. A higher-priority condition always overrides a lower one. Pedestrian-call queueing (waiting to be served) sits below AI/fixed-time — calls are honored in the next cycle, not immediately.

### Wire schema additions (`shared/atms_common/preempt.py`)

```python
@dataclass(frozen=True)
class PreemptRequest:
    intersection_id: int
    approach: Approach          # NORTH_SOUTH or EAST_WEST
    priority: PreemptPriority   # FIRE_RESCUE | POLICE | AMBULANCE | TRANSIT
    valid_until_ns: int          # producer-set TTL (max duration of preempt)
    transponder_id: str          # opaque id from the dedicated channel
    producer_timestamp_ns: int

@dataclass(frozen=True)
class PedCallRequest:
    intersection_id: int
    approach: Approach          # which crosswalk
    accessibility: bool         # True = ADA call, triggers extended walk
    producer_timestamp_ns: int
    valid_until_ns: int         # short TTL; usually a button press
```

### New `CommandedPhase` values (`shared/atms_common/decision.py`)

| Value | Meaning |
|-------|---------|
| `EV_PREEMPT_NS` | All EW conflicts red; NS approach green; ped reds | 
| `EV_PREEMPT_EW` | Mirror of the above |
| `PED_NS_FLASHING_GREEN` | NS pedestrian clearance interval |
| `PED_EW_FLASHING_GREEN` | EW pedestrian clearance interval |

The existing `PED_NS_WALK` / `PED_EW_WALK` denote the *walk* (steady green-man) phase. The new flashing variants denote the *clearance* (countdown / flashing green-man) phase that follows. Transitioning out of walk before the clearance completes is **prohibited by the safety filter**, including for AI decisions and preempt — only `ALL_RED_FLASH` can override clearance.

### Failsafe controller — new behavior

`FailsafeController` gets two new submit methods:

- `submit_preempt(req) -> PreemptOutcome` — validates and arms preempt.
- `submit_ped_call(req) -> PedCallOutcome` — validates and queues a pedestrian call.

Preempt rules:
- Validation: intersection match, not expired, transponder_id non-empty (Phase B can add cryptographic verification of the transponder identity).
- On accept: set internal `_preempt_active = req`, `_preempt_until_ns = req.valid_until_ns`. The next `tick()` commands `EV_PREEMPT_NS` or `EV_PREEMPT_EW` after honouring any in-flight pedestrian clearance.
- Clear: `submit_preempt_clear(approach)` from the operator, OR `valid_until_ns` elapses, OR a different higher-priority preempt arrives (most jurisdictions: FIRE_RESCUE > AMBULANCE > POLICE > TRANSIT).
- After clear: insert intergreen (YELLOW + ALL_RED) before returning control to the previous mode.

Pedestrian-call rules:
- Validation: intersection match, not expired.
- On accept: append to `_ped_call_queue` (deduplicated by approach).
- Service: when the failsafe is about to transition to vehicular green on `approach`, instead transition through the ped phase: `PED_*_WALK` (held for `ped_min_walk_s`), then `PED_*_FLASHING_GREEN` (held for `ped_clearance_s`), then the vehicular green.
- ADA accessibility: if `req.accessibility=True`, the walk phase is held for `max(ped_min_walk_s, ada_min_walk_s)` (default ADA min: 7s).

ADA event emission:
- Whenever the commanded phase enters `PED_*_WALK` or `PED_*_FLASHING_GREEN`, the failsafe emits an `accessible_signal_state` event with fields `intersection_id`, `approach`, `state`, `accessibility_active`. The audit logger (B3) consumes this; hardware drivers downstream subscribe to it.
- This event is **always** emitted, regardless of whether the originating ped-call had `accessibility=True`. Downstream hardware decides whether to play audio.

### Hard safety invariants (extended)

Invariants from ADR-0005 still hold and are extended:

1. No two conflicting greens — including EV preempt (which can only command its own direction's green).
2. Min-green honored — preempt cannot cut a vehicular green shorter than `min_green_s`. (Operationally: dispatch comms warn EVs to use audible siren if the controller is mid-green; the preempt becomes effective on the next swap.)
3. Intergreen inserted — between any two vehicular greens (including preempt-NS → preempt-EW transitions on a multi-EV scenario), the appropriate yellow + all-red sequence runs.
4. Pedestrian clearance never shortened — even by preempt. The clearance interval must complete before the preempt-green is commanded.
5. ALL_RED_FLASH overrides everything — including in-flight preempt and in-flight ped clearance.

### Out of scope for this ADR

- Cryptographic verification of preempt transponder identity (Phase B5 mesh + identity).
- Real NTCIP MIB integration for ped-call and preempt (Phase C1).
- Audio/tactile hardware driver — the controller only emits the event; vendor integration is per-deployment.
- Multi-approach intersections (>4-way, dedicated turn lanes). The current 2-phase model assumes a 4-way intersection with one NS phase and one EW phase. Extension to phase rings is future work.

## Consequences

- Failsafe controller gains substantial state and additional transitions; tests must cover the priority order matrix and the property "preempt + ped-call combine without violating safety invariants."
- The wire-schema additions land in `shared/atms_common/preempt.py` (new module) and `shared/atms_common/decision.py` (CommandedPhase enum extension). All existing callers continue to work; the new enum values are additive.
- HTTP endpoints `/control/preempt`, `/control/preempt/clear`, `/control/ped-call` land on traffic-controller, gated by `engineer+` (preempt) and `operator+` (ped-call — operators / NTCIP adapters in the field).
- Runbook adds preempt-revoke and ped-call audit instructions.
- A future ADR will document the multi-approach phase-ring model when a pilot intersection requires it.
