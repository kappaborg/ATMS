# Runbook: Failsafe controller (Phase A1)

**Audience:** On-call operators and traffic engineers responsible for the ATMS pilot intersection(s).
**Owning component:** `services/traffic-controller` (failsafe core in `src/failsafe.py`).
**Design:** [ADR-0005](../adr/0005-failsafe-controller-state-machine.md).

This runbook tells you what to do when the failsafe controller transitions modes, when to page out, and how to recover from the emergency state. **Read this before responding to a controller mode-transition alert.**

---

## 1. The three modes — what they mean operationally

| Mode | What the signal looks like to a driver / pedestrian | Throughput | Safety |
|------|-----------------------------------------------------|------------|--------|
| `AI_ADAPTIVE` | Normal adaptive operation — phase durations vary with traffic. | Highest | Constrained by hard invariants |
| `FIXED_TIME` | The intersection runs the RiLSA-conformant fixed-time plan from `config/intersections/<id>.yaml`. Cycle and splits are fixed; the intersection still operates safely. | Medium | Inherent |
| `ALL_RED_FLASH` | All vehicular signals flash red; the intersection behaves as a 4-way stop. Pedestrian signals are dark or red as configured. | Lowest | Highest |

> Important: `ALL_RED_FLASH` does **not** recover automatically. An operator must reset it.

## 2. Transitions you will see

Every transition is logged as `event=controller_mode_transition` with fields:
`intersection_id`, `from_mode`, `to_mode`, `reason`, `detail`, `last_decision_id`, `last_decision_age_ms`, `flap_count_in_window`.

The same transition increments `atms_controller_mode_transitions_total{from,to,reason}` and updates `atms_controller_mode{mode}` (gauge, 1 for current).

### 2.1 `AI_ADAPTIVE → FIXED_TIME` (reason: `ai_decision_stale`)

**Trigger:** the controller did not receive a valid decision within `MAX_AI_STALENESS_MS` (default 2000 ms).

**Expected causes (most common first):**
1. `decision-engine` pod crashed / restarting.
2. `ai-perception` pod crashed / restarting.
3. Kafka partition leader election in progress.
4. Inter-AZ / WAN packet loss between the perception stack and the controller.

**Operator action:**
- Open Grafana dashboard "ATMS Overview" → `atms_controller_ai_decision_age_ms` panel. The age will be climbing.
- Check `kubectl get pods -n atms` for `decision-engine` and `ai-perception`. Look for CrashLoopBackOff or recent restarts.
- If decision-engine is up: check its `/health` endpoint and the `atms_decisions_published_total` rate.
- If the upstream comes back up, the controller will auto-recover to `AI_ADAPTIVE` after `FIXED_TIME_MIN_DWELL_S` (default 30 s) of dwell **and** 5 consecutive valid decisions. No operator action required.

**Do not page out** for a single occurrence within an otherwise healthy day. Page out if:
- The intersection is in `FIXED_TIME` for > 10 minutes during a peak period, OR
- More than 3 such transitions in 1 hour (flap risk; see §2.3).

### 2.2 `AI_ADAPTIVE → FIXED_TIME` (reason: `invalid_decision_burst`)

**Trigger:** 3 consecutive decision messages failed schema or semantic validation (intersection mismatch, non-monotonic id, future timestamp, expired, signature invalid).

**Expected causes:**
1. A bad rollout: decision-engine version emits a schema the controller doesn't accept.
2. Misconfiguration: producer's `ATMS_INTERSECTION_ID` doesn't match the controller's.
3. Clock skew between producer and consumer beyond the tolerance (default 500 ms).
4. (Phase B+) Signature key rotation incomplete.

**Operator action:**
- Look at the controller log: each rejected decision emits an `invalid_decisions_total{reason}` increment. The `reason` label tells you which gate failed.
- For `intersection_mismatch`: producer config wrong. Fix `ATMS_INTERSECTION_ID` on the decision-engine deployment.
- For `non_monotonic_id`: decision-engine restarted and reset its id counter. Either accept the temporary outage (controller will recover after dwell) or restart traffic-controller to clear `_last_accepted_decision_id`.
- For `future_timestamp`: NTP/PTP sync broken. See `docs/runbooks/time-sync.md` (Phase C5).
- For `expired`: decision-engine is too slow at producing; check its CPU saturation.
- For `schema_missing_field` / `schema_unknown_phase`: bad rollout. Roll back the decision-engine.

### 2.3 `* → ALL_RED_FLASH` (reason: `flap_threshold`)

**Trigger:** the controller has bounced between `AI_ADAPTIVE` and `FIXED_TIME` 3 times within 5 minutes (configurable via `ATMS_FAILSAFE_FLAP_WINDOW_S` / `ATMS_FAILSAFE_FLAP_THRESHOLD`).

**Why this exists:** persistent flapping suggests the AI is unhealthy enough that drivers cannot predict the intersection's behavior. A 4-way stop is safer than oscillating timing plans.

**This is a paging condition.** Page the on-call traffic engineer.

### 2.4 `* → ALL_RED_FLASH` (reason: `hardware_fault`)

**Trigger:** the NTCIP layer reported a controller / lamp / detector fault.

**This is a paging condition.** Page on-call. Dispatch a field tech.

### 2.5 `* → ALL_RED_FLASH` (reason: `operator_override`)

**Trigger:** operator explicitly called `/control/emergency`. This is the planned E-stop path.

**Audit:** every operator override is logged with the operator-supplied `reason` string. Confirm the audit trail in Loki / your log store.

### 2.6 `FIXED_TIME → AI_ADAPTIVE` (reason: `recovery_valid_stream`)

**Trigger:** dwell satisfied AND `CONSECUTIVE_VALID_TO_RECOVER` (default 5) decisions accepted in a row.

No operator action required. This is the happy path. Confirm in the dashboard that `atms_controller_ai_decision_age_ms` is now near zero.

---

## 3. Paging matrix (quick reference)

| Event | Page on-call? | Notes |
|-------|---------------|-------|
| Single `ai_decision_stale` transition | No (alert only) | Auto-recovers |
| `ai_decision_stale` for > 10 min during peak | **Yes** | Investigate upstream stack |
| `invalid_decision_burst` | **Yes** | Likely a bad rollout — consider rollback |
| `flap_threshold` (→ ALL_RED_FLASH) | **Yes — severity 2** | Persistent unhealthy AI |
| `hardware_fault` (→ ALL_RED_FLASH) | **Yes — severity 1** | Dispatch field tech |
| `operator_override` (→ ALL_RED_FLASH) | No (informational) | Planned action — audit only |

---

## 4. Recovering from `ALL_RED_FLASH`

**There is no automatic recovery.** The failsafe will hold the intersection in `ALL_RED_FLASH` until an operator explicitly forces a different mode. This is a deliberate safety property — the human is in the loop before vehicles move.

### 4.1 Pre-recovery safety walk-through

Before issuing the recover command, the operator must confirm:

1. The underlying fault (if any) is resolved. Check `atms_controller_mode_transitions_total` history for the trigger reason; consult the incident write-up.
2. Field tech confirms (where applicable) that all lamps, detectors, ped buttons, and cabinet hardware are operational.
3. NTP/PTP time sync is healthy on both producer and controller nodes.
4. Both `decision-engine` and `ai-perception` are healthy (`/ready` returns 200, `atms_decisions_published_total` rate > 0).
5. Recent `atms_controller_invalid_decisions_total` rate is zero for the past 5 minutes.

Document the walk-through in your incident tracker; reference its ID in the recover reason string.

### 4.2 Recover command

```bash
# Recover to fixed-time first; promote to AI_ADAPTIVE only after observation.
curl -X POST https://<controller-host>:8003/control/recover \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target":"fixed_time","reason":"INC-12345 hardware verified, ped button replaced"}'
```

Then observe for at least one full cycle (~80 s by default). If `atms_controller_mode_transitions_total{from="fixed_time",to="all_red_flash"}` does not increment, promote:

```bash
curl -X POST https://<controller-host>:8003/control/recover \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target":"ai_adaptive","reason":"INC-12345 observation clean"}'
```

#### Authentication (Phase A6)

`$OPERATOR_TOKEN` is a JWT issued by the operator IdP (Keycloak in production, a short-lived HS256 token in dev — see `CONTRIBUTING.md`). The token must carry the `engineer` role or higher; `viewer` and `operator` roles will receive a 403.

Every accepted call to `/control/emergency` and `/control/recover` emits a structured `operator_action` log line with the principal's `sub`, `jti`, and the supplied `reason`. The principal id is also appended to the failsafe `mode_transition` event so the audit trail is complete end-to-end. Search Loki for `event="operator_action" path="/control/recover" outcome="success"` to find every successful recovery.

Denials (401 / 403) are logged with `outcome="denied"` and the client IP so failed credential attempts are visible.

### 4.3 Recovering directly to `AI_ADAPTIVE` is allowed but discouraged

The API accepts it, but operationally the right move is to use `fixed_time` as a "warm pad" first.

---

## 5. Configuration reference

All values are env-vars on the `traffic-controller` deployment. Defaults shown.

| Env var | Default | Meaning |
|---------|---------|---------|
| `ATMS_INTERSECTION_ID` | `1` | This controller's intersection id; producer must match. |
| `ATMS_MAX_AI_STALENESS_MS` | `2000` | Watchdog timeout. |
| `ATMS_INVALID_DECISION_BURST` | `3` | Consecutive invalids → FIXED_TIME. |
| `ATMS_FIXED_TIME_MIN_DWELL_S` | `30` | Min dwell in FIXED_TIME before recovery permitted. |
| `ATMS_CONSECUTIVE_VALID_TO_RECOVER` | `5` | Valid decisions needed to recover into AI_ADAPTIVE. |
| `ATMS_FAILSAFE_FLAP_WINDOW_S` | `300` | Window for counting AI↔FT flaps. |
| `ATMS_FAILSAFE_FLAP_THRESHOLD` | `3` | Flaps in window → ALL_RED_FLASH. |

Tune carefully; defaults are conservative for an EU/RiLSA single-intersection pilot.

---

## 5b. EV preempt (Phase A7)

EV preempt arrives via `POST /control/preempt` from a trusted source (NTCIP MIB writer, dedicated transponder receiver, or operator). Per ADR-0004 it is **dedicated-channel-only** — siren/strobe vision is not an authoritative preempt source.

### Priority order (highest first)
1. `ALL_RED_FLASH` (operator E-stop / hardware fault / flap escalation)
2. EV preempt (overrides AI / fixed-time)
3. In-flight pedestrian clearance (`PED_*_FLASHING_GREEN`) — cannot be cut
4. AI decision (`AI_ADAPTIVE` mode)
5. Fixed-time plan (`FIXED_TIME` mode)
6. Queued ped-call (served at next safe boundary)

### Preempt request shape
```json
{
  "approach": "north_south" | "east_west",
  "priority": "fire_rescue" | "ambulance" | "police" | "transit",
  "valid_until_ns": <epoch-monotonic-ns TTL>,
  "transponder_id": "<opaque-id>"
}
```

Inter-preempt priority: `FIRE_RESCUE > AMBULANCE > POLICE > TRANSIT`. A higher-priority preempt replaces a lower-priority one in flight; equal-or-lower is rejected (400).

### Min-green still honoured

Cross-direction preempt does **not** cut min-green. If the intersection is mid-NS-green and a preempt arrives for EW, the controller completes min-green, runs the normal intergreen sequence (yellow + all-red), then commands `EV_PREEMPT_EW`. The operational guidance is that dispatch comms warn EVs to use audible siren during the worst-case dwell. Same-direction preempt is exempt (continuation of the same approach's green).

### Clearing a preempt

```bash
curl -X POST https://<controller>:8003/control/preempt/clear \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -d '{"approach":"east_west","reason":"INC-12345 vehicle passed"}'
```

The clear honours `preempt_min_dwell_s` (default 3 s) — clears within that window are ignored to filter transponder glitches. The `valid_until_ns` from the original arm acts as a hard TTL; once it elapses, the preempt auto-clears at the next tick.

### Audit
Each `submit_preempt` / `submit_preempt_clear` emits a structured `preempt_arm` / `preempt_clear` log event with `approach`, `priority`, `transponder_id`, and (for HTTP calls) the operator's `principal_sub` / `jti`. The Prometheus counters are `atms_controller_preempt_armed_total{approach,priority}`, `atms_controller_preempt_cleared_total{approach,reason}`, and `atms_controller_preempt_rejected_total{reason}`.

## 5c. Pedestrian call + ADA event (Phase A7)

Pedestrian calls arrive via `POST /control/ped-call` from a push-button driver or NTCIP MIB writer.

### Ped-call request shape
```json
{
  "approach": "north_south" | "east_west",
  "valid_until_ns": <TTL>,
  "accessibility": true | false
}
```

`accessibility=true` extends the walk interval from `ped_min_walk_s` (default 5 s) to `ada_min_walk_s` (default 7 s) per ADR-0007. A non-accessibility call arriving while an accessibility call is queued does **not** downgrade.

### Servicing
The controller dedupes by approach (one queued call per direction), and serves the highest-priority call (accessibility first, then producer timestamp) at the next safe boundary — i.e., when not currently mid-vehicular-green min-green hold and not in an active preempt. The ped phase is `PED_*_WALK` (held ≥ `min_walk`) → `PED_*_FLASHING_GREEN` (held ≥ `ped_clearance_min_s`, default 6 s) → resume normal scheduling.

### ADA hardware integration

Every entry into `PED_*_WALK` or `PED_*_FLASHING_GREEN` emits an `accessible_signal_state` structured log event:

```json
{
  "event": "accessible_signal_state",
  "intersection_id": 1,
  "approach": "north_south",
  "state": "walk" | "clearance",
  "accessibility_active": true | false
}
```

Downstream audio/tactile drivers (vendor-specific) subscribe to these events. The controller does not drive the hardware directly — it emits the canonical state signal and the driver decides whether to play audio / pulse tactile based on `accessibility_active`.

### Audit
Per-call metrics: `atms_controller_ped_call_queued_total{approach,accessibility}`. Per-service event: `ped_call_queued` (queued), `ped_call_serviced` (completed).

## 5d. Kafka circuit breaker (Phase B4)

The Kafka producer wraps every `send()` in:
1. `Bulkhead` (queueing under saturation)
2. `CircuitBreaker` (fails fast when broker is sick)
3. `Retry` (exponential backoff + jitter)
4. `with_timeout` (no unbounded await)

Composition order documented in [ADR-0009](../adr/0009-resilience-patterns.md).

### Breaker states
- **CLOSED** (normal): sends pass through.
- **OPEN** (broker is sick): sends fail immediately with `CircuitBreakerOpenError`. The decision-engine surfaces this as a 500; the controller's failsafe (already silent on AI input) falls back to FIXED_TIME within `MAX_AI_STALENESS_MS` if the producer is unreachable.
- **HALF_OPEN**: after `reset_timeout_s` (default 30 s), the breaker permits one probe call. Two consecutive successes → CLOSED. Any failure → back to OPEN.

### Operator actions on `state="open"` alert
1. Check broker health: `kubectl -n atms exec -it kafka-0 -- kafka-topics --bootstrap-server localhost:9092 --list`.
2. Look for leader-election events in the broker logs.
3. If broker is genuinely down: page Kafka on-call. The breaker will auto-probe every 30 s.
4. If broker is up but breaker stuck open (false positive): operator can `force_close` via the producer's admin API (planned — for now restart the producing pod).

### Metrics
- `atms_circuit_breaker_state{name,state}` — gauge, 1 for current state.
- `atms_circuit_breaker_transitions_total{name,from,to,reason}` — alert on rapid `closed → open` cycles.
- `atms_circuit_breaker_short_circuited_total{name}` — count of fast-failed calls. Spikes mean upstream is sick.
- `atms_retry_attempts_total{name,outcome}` — `outcome="exhausted"` is a leading indicator of impending breaker open.
- `atms_bulkhead_saturated_total{name}` — control loop should NEVER saturate; if it does, raise an SLO violation.
- `atms_operation_timeouts_total{name}` — tighten the timeout or fix the upstream.

## 5e. Distributed tracing (Phase B2)

Every HTTP request and every Kafka produce/consume is a span. `trace_id` is auto-injected into every JSON log line. To follow a single intersection-control flow end-to-end:

1. **Find the trace** — grep Loki for the operator action or alert of interest:
   ```
   {service="traffic-controller", event="controller_mode_transition"} | json
   ```
   Each line has a `trace_id` field (32 hex chars).

2. **Open the trace** — paste the `trace_id` into Tempo / Jaeger:
   ```
   https://tempo.atms.internal/explore?orgId=1&traceId=<trace_id>
   ```

3. **Span tree** for a typical decision:
   ```
   http.server (POST /decision/make)
   └─ decision_engine.make_decision
      └─ kafka.send.decisions
         └─ (consumer side)
            kafka.consume.decisions
            └─ failsafe.submit_decision
               └─ failsafe.tick
   ```

### Common queries
- **Slow decisions:** Tempo: `{ name="decision_engine.make_decision" } | duration > 100ms`
- **Failed validations:** filter on `atms.validation_status != "ok"`
- **Operator actions:** filter on `http.target =~ "/control/.*"`

### Tuning sample ratio
- `OTEL_TRACES_SAMPLER_ARG=0.01` → 1% sampling (prod default; tunes via env)
- `OTEL_TRACES_SAMPLER_ARG=1.0` → 100% (dev / debugging)
- Errors are always sampled regardless (`ParentBased(root=...)` honors parent decisions).

## 6. Observability cheat-sheet

| Signal | Type | Use |
|--------|------|-----|
| `atms_controller_mode{mode}` | gauge (0/1) | Current mode. |
| `atms_controller_mode_transitions_total{from,to,reason}` | counter | Transition history; alert on `reason="flap_threshold"`. |
| `atms_controller_invalid_decisions_total{reason}` | counter | Schema/validation rejects. |
| `atms_controller_ai_decision_age_ms` | gauge | Age of most recently accepted decision. Should sit near `tick_period`. |
| `atms_controller_commanded_phase_total{phase}` | counter | Per-tick commanded phase. |

Suggested Grafana panels:
- Time series of `atms_controller_mode` per intersection.
- Rate of `atms_controller_mode_transitions_total` faceted by `reason`.
- Heatmap of `atms_controller_ai_decision_age_ms`.

Suggested alerts (PromQL sketch):
- `max_over_time(atms_controller_ai_decision_age_ms[5m]) > 1500` → warn.
- `atms_controller_mode{mode="all_red_flash"} == 1` → page (sev 2).
- `increase(atms_controller_mode_transitions_total{reason="hardware_fault"}[1h]) > 0` → page (sev 1).

---

## 7. Test it before you trust it

The chaos integration test `tests/integration/test_tick_loop.py` verifies the
core safety property (silence → FIXED_TIME within 2 s). Run it before any
change to the controller is deployed:

```bash
cd services/traffic-controller
pytest tests/ -v
```

The full Kafka-driven chaos test (`tests/integration/test_failsafe_chaos.py`)
runs in CI nightly against a Testcontainers Kafka.
