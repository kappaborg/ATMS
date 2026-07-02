# ADR-0022 — Decision Chamber production protocol bindings (Phases 2–5)

**Status:** Accepted — shipped 2026-06-14.
**Companion:** [ADR-0021](0021-decision-chamber.md) (Phase 1 layered architecture).
**Context:** Phase 1 shipped a 6-layer chamber with the layered architecture, scoring, hysteresis, and audit. Phases 2–5 add the real protocol bindings that turn the chamber from a "demo decision engine" into something deployable at a pilot intersection. This ADR captures the architecture decisions made across those phases.

## Decisions

### Phase 2 — Real protocol bindings at the L1 input and L5 output edges

#### NTCIP-1202 over SNMPv1 (controller bridge)

- **Reject** pulling in pysnmp's async stack as a heavy dependency. The chamber tick is synchronous and we want a small dependency surface for edge deployment.
- **Accept** a hand-rolled ASN.1 BER encoder + UDP socket. ~120 LoC, no deps, wire-compatible with any NTCIP-1202 controller. The same code talks to the dev emulator (`scripts/ntcip_emulator.py`) and to a real Econolite/Siemens/McCain controller — only the target IP differs.
- **Force-off semantic**: to make `north_south_green` happen, send force-off to phase 4 (east_west), NOT phase 2 (north_south). Confirmed against NEMA TS 4 §7.3.

#### V2X J2735 Signal Request Message (preemption input)

- **Reject** shipping the full 3500-line J2735-202309 ASN.1 spec for Phase 2. The minimal subset (`SimplifiedSrm`: msgId, vehicleId, requestedPhase, requestType, timestamp) covers preempt-vs-priority discrimination and stays small for testing.
- **Accept** `asn1tools` library — real UPER codec, schema is a small inlined string. Phase 6+ can drop in the full spec file with zero interface changes.
- **Single positive triggers preemption** — V2X SRM with `requestType=preempt` and confidence 0.95 emits an `EmergencySignal` that L1 turns into a phase command.

#### Pedestrian phase as L2 hard constraint

- **Accept** treating non-current direction with pedestrian demand as a **forced change** at L2, bypassing L4 hysteresis. Rationale: peds are a safety constraint, not a soft optimization signal; a small +0.40 score bias was getting held back by the current-phase bonus.
- **Accept** MUTCD §4E.06 walk + clearance minimum for the ped phase commit (default 12 m crossing / 1.0 m/s walking speed = 19 s vehicle red). Per-intersection override via site config.

### Phase 3 — Multi-intersection coordination + observability

#### MQTT mesh (Pattern A: green wave)

- **Reject** central optimizer (Pattern C) for Phase 3 — would require a city-layer service and pull cloud dependencies into the edge chamber. Defer to Phase 6+.
- **Reject** custom protocol on raw UDP — MQTT brokers are well-understood ops, have TLS/auth/HA tooling, and are deployed in every city for IoT.
- **Accept** `paho-mqtt` with QoS 1 + LWT. Topic schema `atms/intersection/<id>/{state,decision,wave_pulse,lwt}`.
- **Accept** NullMeshNode fallback when broker unreachable. The chamber's local decisions don't depend on the mesh — coordination is additive bias.

#### Prometheus text format

- **Reject** OpenTelemetry — heavier dep, more setup, no clear win at edge.
- **Accept** stdlib `http.server` HTTP exporter on `/metrics` in Prometheus text format. Any scraper (Prometheus, VictoriaMetrics, Mimir, Cortex) just works. Drop-in Grafana dashboard JSON shipped at `services/observability/grafana-chamber-dashboard.json`.
- **Metric naming**: `atms_chamber_<name>` convention with `intersection` label auto-attached for multi-intersection aggregation.

### Phase 4 — Closed-loop + vision pedestrian + TSP

#### NTCIP closed-loop GET status polling

- **Accept** background poller thread on `NtcipControllerBridge`, configurable interval (default 2 s).
- **Divergence detection**: chamber's commanded direction is compared with the controller's reported active directions; 3+ consecutive ticks of mismatch surfaces a warning log + `atms_chamber_controller_divergence_total` increment. Why 3 ticks: filters out the transient mismatch right after a SET (controller takes ~100-300 ms to update its phase state).

#### Vision pedestrian detection — pipeline integration

- **Accept** modifying `_detect()` to keep YOLOv8 class 0 (person) bboxes in a separate list rather than running a second inference pass. Zero extra inference cost.
- **Accept** crosswalk zones as rectangles in pixel coordinates, configured per-camera in site YAML. Default heuristic zones (NS = bottom 25%, EW = left 25%) work for typical 4-way arterial cameras pending real homography.

#### GTFS-realtime TSP subscriber

- **Accept** L3 SOFT bonus (default 0.10 per late bus), not hard preempt. Buses are priority, emergency vehicles are preempt — the semantics differ.
- **Phase 4 simplification**: filter by `route_id` only, no geo-fence around intersection lat/lon. Production deployment adds the geo-fence once intersection coordinates are known.

### Phase 5 — Production deployment pattern

#### SQLite audit storage with rotation

- **Reject** an external DB (Postgres) for edge audit. SQLite + WAL handles 10k writes/s, is durable, has no separate server.
- **Schema**: one row per decision with indexed `tick_time`, `mode`, `dominant`, `commanded_phase` + JSON blobs for full input/output.
- **Rotation**: size-based (default 200 MB) → rename current to `<path>.<timestamp>.db`, fresh DB opens for new writes. Archived DBs forward to city-layer storage in Phase 6.
- **Retention**: row-level delete + VACUUM, runs once per 24 h on write path. Default 90 days.

#### Audio siren detection — physics-based, no model

- **Reject** YAMNet/PANNs trained model for Phase 5. Heavy TFLite dep, model artefact to ship + update per deployment.
- **Accept** real-time STFT with three physics-based criteria: siren-band energy ratio, peak tonal clarity, frequency-modulation detection. Validated on synthetic FM wail (15/20 windows positive, 0 false positives on broadband noise).
- **Phase 6 upgrade path**: same `EmergencyDetector` interface; trained model swaps in without changes elsewhere.

#### Single YAML per intersection + factory

- **Reject** environment variables for per-intersection config — too many knobs (~25), too easy to miss one.
- **Accept** `SiteConfig` dataclass + `build_chamber_from_site_config(yaml_path)` factory. Field validation at load-time; missing required fields fail loudly with the path in the error message. Production runbook: copy template, fill values from site survey, hand to ops.

## Consequences

### Positive

- **Every protocol on the boundary is real** — the chamber doesn't know whether it's talking to a production controller or a Mac running the dev emulator. Code is the same.
- **One-call deployment** — operations team needs to fill a YAML and run one command. No code edits per site.
- **Closed-loop visibility** — operator console + audit + Prometheus all show whether the controller actually honoured the chamber's advisory request.
- **Observability is standard** — `atms_chamber_*` metrics drop into any Prometheus instance, dashboard JSON imports into Grafana.
- **Audit is replayable** — SQLite rows contain full ChamberInput + ChamberOutput; a replay tool can re-run any decision with deterministic output.

### Negative / accepted limitations

- **SNMPv1, not v3** — Phase 6 adds auth + encryption. Acceptable for pilot intersection on a trusted operations network; not acceptable for internet-exposed deployments.
- **Audio siren detector is physics-based, not learned** — slightly higher false-positive rate in noisy environments than a trained CNN would have. Phase 6 swap path documented.
- **Vision pedestrian uses default heuristic zones in the demo** — production needs per-camera homography + zone polygons during site survey.
- **TSP is route_id filter only** — no geo-fence. False-positive priority for late buses on routes that don't actually approach this intersection. Phase 6 with real lat/lon.
- **MQTT broker is plaintext** — Phase 6 adds TLS + cert auth for production.

### Open questions for Phase 6+

1. SNMPv3 secret distribution (per-intersection unique keys vs corridor-shared) — pilot operations decision.
2. Audit DB archival forwarding: TimescaleDB on-prem vs S3 with parquet conversion vs both. Depends on city's existing data infrastructure.
3. A/B test platform: shadow chamber instance running with different weights against the same input stream, side-by-side metrics. Needed for proving emission-cost weight changes before rolling them out.

## References

- ADR-0021 — Phase 1 layered architecture
- Implementation tree:
  - `simulation/decision_chamber/` (15 modules, 3897 LoC)
  - `scripts/ntcip_emulator.py`, `scripts/v2x_srm_sender.py`, `scripts/gtfs_synthetic_feed.py`
  - `services/observability/` — Grafana dashboard + Prometheus scrape + site config template
- Brand model integration: see ADR-0020.
