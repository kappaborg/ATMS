# ADR-0023 — Phase 6 production hardening for pilot deployment

**Status:** Accepted — shipped 2026-06-14.
**Companion:** [ADR-0021](0021-decision-chamber.md), [ADR-0022](0022-decision-chamber-production-bindings.md).
**Context:** Phases 1-5 shipped a feature-complete decision chamber with real protocols at every boundary. Phase 6 closes the remaining gaps that pilot operations teams (specifically KJP "Park" Sarajevo) flagged as deployment blockers.

## Decisions

### 6.1 — SNMPv3 USM for NTCIP write access

- **Reject** SNMPv1 community-string authentication for production. KJP ops policy mirrors most municipal IT in 2025: read-only SNMPv1 may pass for monitoring, but write access requires authenticated SNMPv3.
- **Accept** SNMPv3 USM with HMAC-SHA1 auth + AES-CFB-128 privacy (`authPriv` security level). MD5 + DES are deprecated and rejected per RFC 7860.
- **Accept** `puresnmp` 2.x as the SNMPv3 library — pure Python, async API, real cryptography. (pysnmp 6.x's transitive pyasn1 conflict on Python 3.14 blocked that choice.)
- **Accept** env-var expansion in site YAML (`${ATMS_NTCIP_AUTH_KEY}`) so passphrases never live in checked-in config. Production deployment injects from a secrets manager via systemd `EnvironmentFile`.

### 6.2 — A/B test harness via shadow chambers

- **Problem:** weight tuning (e.g., raising `w_emission` from 0.40 to 0.50) is risky to deploy without before/after data. Cities can't accept "trust me, this'll reduce CO₂" without metrics.
- **Accept** in-process shadow chambers that compute decisions on the same input stream but never send to the controller. Their divergence vs primary gets emitted to Prometheus with `shadow_label` so the operator can compare hypothetical decisions to actual.
- **Reject** running a separate shadow process — for tuning experiments the input must be IDENTICAL, which means same tick context. Process boundary adds risk of input drift.
- **Accept** zero-cost when no shadows are added (`ABTestHarness` is opt-in; chamber tick works unchanged).
- **Promotion pattern:** if shadow consistently outperforms primary on the objective metric for N days, promote = swap the shadow config to primary in site YAML and restart.

### 6.3 — Per-camera homography calibration

- **Reject** single-value `pixels_per_meter` as the production answer. The Phase 1 default works for camera-centre but is wrong by 30-50% at the frame edges where perspective distortion is highest. Field speed estimates at frame edges become unreliable.
- **Accept** a homography matrix calibrated via a site-survey tool that prompts an operator to click 4 reference points in the camera image, given the real-world (X, Y) coords. Tool validates the fit and rejects calibrations with > 0.5 m residual error.
- **Accept** the homography as a per-camera JSON artefact (`config/intersection-<id>-homography.json`) the chamber loads at startup. Speed and emission calculations transform pixel motion to metres via the homography rather than a single ratio.
- **Phase 7 future:** auto-recalibration trigger when scene shift detected (e.g., construction, camera mount shift).

### 6.4 — TimescaleDB audit archive forwarder

- **Reject** keeping audit data on edge disk forever. Even with 200 MB rotation × 180-day retention, the edge accumulates ~150 GB / year per intersection. Field maintenance can't replace edge disks at that rate.
- **Reject** S3 / object-storage archive as the only forwarding target. Operators need queryable history for incident replay; Glacier-style cold storage is too slow.
- **Accept** TimescaleDB hypertable as the city-layer archive. Postgres-compatible (city IT already has Postgres expertise), auto-partitions by time, continuous aggregates make Grafana queries fast.
- **Accept** ON CONFLICT idempotency — partial-failure retries don't double-insert. Forwarder can re-run safely if a previous batch crashed mid-transfer.
- **Accept** running as a separate process (systemd timer / cron) so chamber crash and forwarder crash are independent. Edge chamber failure must not affect city-layer archival; archival failure must not affect intersection signal control.

## Consequences

### Positive

- **Pilot-deployable security**: KJP ops can sign off on SNMPv3 authPriv where they'd reject SNMPv1.
- **Tunable in production**: A/B harness lets pilot operators try `w_emission=0.50` against real traffic without committing the change.
- **Real speed at frame edges**: homography eliminates the 30-50% edge error of the single-ratio approximation, making the speed and idling estimates trustworthy across the whole intersection ROI.
- **Long-term audit queryability**: 1-year+ history accessible in TimescaleDB with Postgres tooling.
- **Bosnia pilot unblocked**: every gap KJP raised has a code answer.

### Negative / accepted limitations

- **SNMPv3 engine discovery adds ~50ms to the first send** after the chamber starts. Subsequent sends are normal speed. Acceptable for adaptive control (2 s review interval).
- **A/B harness divergence metrics need a Grafana dashboard** to be useful at scale — Phase 7 adds the dedicated A/B panel.
- **Homography calibration requires a one-time site survey** per camera. Phase 7 may add auto-recalibration triggered by scene-change detection.
- **TimescaleDB forwarder is a separate ops surface** — chambers run on edge, forwarder runs in city ops. Two systems to monitor.

### Open questions for Phase 7+

1. Multi-intersection corridor A/B: shadow corridor configs (e.g., green wave offset 18s vs 22s) need their own harness pattern — shadowing requires synchronised mesh state.
2. SNMPv3 key rotation cadence — KJP policy TBD. Pilot launches with manual rotation; automated rotation via KJP HSM in Phase 2.
3. Audit forwarder back-pressure — what if Timescale is unreachable for a week? Edge SQLite fills up. Phase 7 adds bounded local retention with optional S3 cold-tier overflow.

## References

- ADR-0021 — Phase 1 layered architecture
- ADR-0022 — Phase 2-5 production bindings
- Implementation:
  - `simulation/decision_chamber/ntcip_v3_bridge.py` (243 LoC)
  - `simulation/decision_chamber/ab_test.py` (180 LoC)
  - `simulation/decision_chamber/audit_forwarder.py` (200 LoC)
  - `scripts/calibrate_camera_homography.py` (245 LoC)
- Site config additions: `NtcipConfig.snmp_version`, `v3_username`, `v3_auth_passphrase`, `v3_priv_passphrase`, `v3_security_level`
- Bosnia pilot template: `services/observability/sarajevo-pilot.yaml`
- Bosnia pilot deployment guide: `docs/demos/bosnia-pilot-deployment.md`
