# ATMS — Open Decisions and Assumptions

Captured per the Senior Engineer Prompt. Each entry: what was decided, who decided, when, and what it drives.

| # | Question | Answer | Decided | Drives |
|---|----------|--------|---------|--------|
| 1 | Deployment target | **On-prem / self-hosted Kubernetes** | Product owner, 2026-05-29 | A5 secrets (SOPS + age), B5 mesh (Linkerd), C2 edge agent target hardware, no managed cloud KMS |
| 2 | Jurisdiction for pilot | **European Union** (RiLSA-family signal timing) | Product owner, 2026-05-29 | A3 invariants (RiLSA min-green, intergreen), A7 ped/EV (no MUTCD WALK/DON'T WALK semantics — uses green-man + flashing-green-man), C1 NTCIP overlay (still NTCIP-compatible but parameters differ) |
| 3 | Controller hardware for the pilot | **Open** | — | C1 NTCIP MIB choices, HW-in-the-loop fixture |
| 4 | Privacy regime | **GDPR** (implied by EU jurisdiction; confirm if non-EU pilot precedes) | Inferred 2026-05-29 | D4 (LPR anonymization on-by-default, DSAR endpoint, encryption at rest) |
| 5 | Safety-review authority | **Open** | — | Phase C sign-off, runbook approval, change-advisory process |

## EU/RiLSA timing defaults (locked in until per-pilot tuning)

Used as defaults for `services/traffic-controller/src/failsafe.py` fixed-time plan and for A3 invariant tests. These are conservative urban single-intersection values; per-pilot timing plans override.

| Parameter | Default | Source |
|-----------|---------|--------|
| Cycle time | 80 s | RiLSA Section 2.4 typical urban |
| Min green (vehicular) | 10 s | RiLSA Section 3 |
| Max green (vehicular) | 60 s | Operator policy |
| Driver yellow | 3 s for v≤50 km/h, 4 s for v≤60 km/h, 5 s for v≤70 km/h | StVO §37 |
| All-red / intergreen | Computed from intersection geometry (default 2 s minimum) | RiLSA Section 5 |
| Pedestrian green | min 5 s | RiLSA Section 3.4 |
| Pedestrian clearance walking speed | 1.2 m/s | RiLSA Section 3.4 |
| EV preempt | National variant — `KAR` (NL) / `ÖPNV-Vorrang` (DE) / `R09.16` (UK). Default: dedicated input channel, no siren-strobe heuristic | Per-deployment |

## Notes

- "Open" items must be resolved before the phase task that depends on them is merged. A1 (this session) is parameterized to defer #3 and #5.
- This file is the place to record any new product/policy decision before it enters code.
