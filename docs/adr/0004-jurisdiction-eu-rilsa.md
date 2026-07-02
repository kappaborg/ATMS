# ADR-0004: Jurisdiction baseline — EU / RiLSA-family signal timing

**Status:** Accepted
**Date:** 2026-05-29

## Context

ATMS must comply with the local traffic-signal timing and pedestrian-protection standards of the jurisdiction it operates in. The pilot is in the **European Union** (`docs/assumptions.md` #2). The dominant German technical guideline RiLSA (Richtlinien für Lichtsignalanlagen) is the closest pan-EU reference for adaptive signal timing; most national variants (NL CROW, UK TSRGD, FR IISR) are compatible at the parameter level. The US MUTCD is **not** the controlling standard here.

Key differences from MUTCD that matter to our code:
- No "WALK / DON'T WALK / FLASHING DON'T WALK" tri-state. EU uses **green-man / flashing-green-man (or static red-man clearance) / red-man** — a different state count and slightly different semantics.
- Driver yellow time is **speed-dependent** (3 s ≤50 km/h, 4 s ≤60 km/h, 5 s ≤70 km/h) per StVO §37, rather than a single national value.
- All-red intergreen is **computed from geometry** (clearance distance vs entering distance), not a fixed value.
- Emergency-vehicle preempt is typically driven by **dedicated channels** (KAR, ÖPNV-Vorrang, R09.16 transponders) rather than siren/strobe detection.

## Decision

- All timing parameters live in `docs/assumptions.md` (defaults table) and are loaded into the failsafe controller and decision engine via configuration — **no hard-coded numbers** in `failsafe.py` or `ai_decision_system.py`.
- The signal-state model in code uses an enum that covers RiLSA states explicitly: `RED`, `RED_YELLOW`, `GREEN`, `YELLOW` for vehicles; `PED_RED`, `PED_GREEN`, `PED_FLASHING_GREEN` (or jurisdiction-equivalent clearance) for pedestrians. Mapping to MUTCD or other regimes is done in a future adapter, not in the core.
- Property-based tests (A3) encode RiLSA invariants as defaults: min-green, intergreen ≥ computed clearance, pedestrian green ≥ 5 s, conflicting greens never simultaneous.
- A per-pilot YAML (`config/intersections/<id>.yaml`) overrides defaults with intersection-specific numbers (geometry, clearance times, speed limits).
- EV preempt initial implementation uses a **dedicated input channel** (NTCIP MIB or external GPIO via the edge agent), not a vision-based heuristic. Vision can be a secondary signal later, never a primary one.

## Consequences

- Any future expansion to a non-EU jurisdiction (US/MUTCD, Asia/local) requires a new ADR and an adapter layer; the core stays parameter-driven.
- The failsafe `FIXED_TIME` plan format uses RiLSA terminology and timing semantics by default.
- A3 tests are written against RiLSA invariants; an MUTCD pilot would add a parallel test pack.
- Documentation (runbooks, PROJECT_REPORT) is updated to remove MUTCD-only language.
