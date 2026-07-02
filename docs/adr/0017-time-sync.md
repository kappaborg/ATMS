# ADR-0017: NTP cluster-wide, PTP on the edge, monotonic clock in the decision path

**Status:** Accepted
**Date:** 2026-05-30
**Closes:** PRODUCTION_GAPS.md gap #20 (Phase C5)

## Context

Audit gap #20: frame timestamps and decision timestamps in ATMS use `datetime.now()` / `time.time()` — both are wall-clock sources that can step backwards, forwards, or jump tens of milliseconds when NTP corrects. The failsafe controller (A1) and the wire-schema's `producer_timestamp_ns` field rely on monotonicity. Without an explicit sync model the system is one clock-skew away from rejecting valid decisions as "future-dated" or accepting expired ones.

Cross-camera coordination (multi-intersection green wave, C2 edge work) compounds the problem: a 50 ms skew between cameras means a synchronised platoon detection is off by half a vehicle length.

## Decision

### Three-tier sync topology

**Tier 1 — cluster-wide NTP via chrony.** Every Kubernetes node runs `chronyd` pointed at the operator's stratum-2 NTP servers (or a public pool fallback). This is the baseline; pods inherit the node clock. Expected accuracy: ±5 ms cluster-wide.

**Tier 2 — PTP (IEEE 1588) on the edge subnet.** The C2 edge agent, cameras, and the local NTCIP-connected controller share a switched edge subnet. A PTP boundary clock on the edge agent disciplines the camera timestamps and the controller's local clock. Expected accuracy: ±100 µs between cameras on the same subnet (assumes hardware that supports PTP — flagged in the C2 hardware-selection ADR).

**Tier 3 — monotonic clock in the decision path.** Within a single process, every timestamp that matters for safety uses `time.monotonic_ns()`. Wall-clock (`time.time()`) is **forbidden** in the failsafe + decision-engine hot paths and is detected by lint (see §rule below). Wall-clock is still recorded alongside the monotonic value when an event needs human-readable display, but the safety logic only ever compares monotonic deltas.

### `SyncedTimestamp` — the canonical timestamp shape

```python
@dataclass(frozen=True)
class SyncedTimestamp:
    monotonic_ns: int       # time.monotonic_ns()
    wall_clock_ns: int      # time.time_ns()
    source: TimeSyncSource  # SYSTEM_CLOCK | NTP | PTP
    skew_estimate_ms: float # observed skew vs ground-truth reference
```

Use `SyncedTimestamp.now(source_probe)` at every system-edge ingestion point (camera frame, Kafka message receipt, NTCIP response). Inside the process: use the `monotonic_ns` field exclusively.

### Code rule: ban `time.time()` in safety code

Implemented as [`tools/lint_safety_clock.py`](../../tools/lint_safety_clock.py), wired into CI's `lint` job. The script fails the PR if `time.time()`, `time.time_ns()`, `datetime.now(...)`, or `datetime.utcnow()` appears anywhere under:

- `shared/atms_common/`
- `services/traffic-controller/src/`
- `services/decision-engine/src/`
- `services/v2x-interface/src/`
- `services/sensor-fusion/src/`
- `services/ai-perception/src/`

Allowed exceptions:

1. **Test files** (paths containing `tests/` or filenames starting with `test_`) — skipped wholesale.
2. **Per-line exemption** `# noqa: ATMS-CLOCK` — for display-only callsites (audit-log fields, HTTP response timestamps, JWT iat/exp where the JWT spec requires Unix epoch, etc.). Always include a brief reason after the tag.
3. **File-level grandfathering** via [`tools/.safety_clock_legacy.txt`](../../tools/.safety_clock_legacy.txt) — legacy files awaiting Phase A2 refactor (currently `services/sensor-fusion/src/*` and `services/ai-perception/src/*`). Entries come off the list as each file is refactored.

The canonical wall-clock anchor is `SyncedTimestamp.now()` in `shared/atms_common/timekeeping.py:75` (the single `# noqa: ATMS-CLOCK`-tagged `time.time_ns()` call). All other safety code reads time via `Clock.now_ns()` (monotonic) or that anchor.

Code that needs human-readable timestamps for **logs** still uses `datetime.now()` via the structlog timestamper — that's outside the safety path.

**Known minor limitation:** the lint resolves dotted calls (`time.time()`, `datetime.now()`, `datetime.datetime.now()`). Aliased imports like `import time as _time; _time.time()` aren't flagged — rename the alias or add `# noqa: ATMS-CLOCK` explicitly. Tests in `tools/tests/test_lint_safety_clock.py` cover the common forms.

### Health-check integration

The HealthRouter (B1) gains two new bundled checks per service:

- `ntp_sync_check(skew_threshold_ms=50)` — reads `chronyc tracking` output; fails if skew > threshold or clock isn't synced.
- `ptp_sync_check(skew_threshold_us=1000)` — reads `pmc -u -b 0` (linuxptp); only enabled on edge nodes.

A pod that loses NTP sync becomes `/ready` 503 within 5 polls, K8s drains it.

### Cross-camera skew metric

Each camera frame carries a `SyncedTimestamp` from the camera. The `sensor-fusion` service computes pairwise skew between cameras at the same intersection and emits:

- `atms_camera_skew_ms{intersection_id,camera_a,camera_b}` (gauge)

Alert: skew > 10 ms for > 1 minute. (Above the prompt's 10 ms acceptance threshold per scenario.)

## Out of scope for C5

- **Actually deploying chrony.** The Helm chart for cluster bootstrap configures it; this ADR is the code-side contract.
- **GPS-disciplined PTP grandmasters.** Required when geographic accuracy matters (>1 km between intersections in coordinated waves). Operator-side decision; out of scope.
- **Auditing every existing `time.time()` callsite.** The lint rule fails new code; existing callsites under safety modules are tracked and removed incrementally.

## Consequences

- Two new shared protocols (`TimeSyncSource`, `SyncedTimestamp`) + helper module `shared/atms_common/timekeeping.py`.
- Lint gate added to CI (custom script under `.github/workflows/ci.yml` `lint` job).
- HealthRouter dep-check additions; existing services pick them up via the same B1 bootstrap.
- Existing `datetime.utcnow()` calls in the controller's `TrafficSignal.set_state` get migrated to the monotonic-aware path in a follow-up PR (logged time stays wall-clock; comparison time becomes monotonic).
- `services/decision-engine/src/main.py` already uses `time.monotonic_ns()` for `producer_timestamp_ns` (A1+A3 work). C5 generalises that pattern.
