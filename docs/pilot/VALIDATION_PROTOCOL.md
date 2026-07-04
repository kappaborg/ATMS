# ATMS Field Validation Protocol

Purpose: convert the ATMS panel from *verified software* into a *validated
measuring instrument* for a pilot. Every measured output (speed, emissions,
savings, violations) inherits its accuracy from the steps below. Run them
once per installed camera; re-run after any camera move.

---

## 1. Camera installation & scene setup

| Requirement | Target |
|---|---|
| Mounting | fixed/rigid (no pole sway); the stability check below must pass |
| View | the monitored road surface approximately planar in view (the calibration assumes a flat ground plane) |
| Resolution | ≥ 720p for detection; for plate capture the plate must be ≥ ~60 px wide at the capture point (ANPR-grade placement) |
| Stability check | background motion < 1.5 px/frame (the panel's ingest tolerates more, but measurements degrade) |

Then, in the app (⚙ Calibrate):
1. **Ground-plane calibration** — Rectangle mode: click the 4 corners of a
   road rectangle whose true size you measured on site (tape/odometer — do
   NOT guess). Reprojection error shown must be < 0.3 m.
2. **Approach zones** — draw the roadway lanes per approach (this also
   separates parked vehicles from the roadway and enables wrong-way).
3. **Stop-lines** — draw per approach if red-light detection is in scope.

Record in the sheet (§5): camera ID, mount height/angle, rectangle
dimensions + how they were measured, reprojection error.

## 2. Speed validation (the core test)

**Reference**: a probe vehicle with GNSS speed logging (phone GPS app logging
at ≥ 1 Hz is acceptable for a pilot; a GNSS speedbox is better), or a
handheld radar/lidar gun.

**Procedure**
1. Drive the probe vehicle through the calibrated view ≥ **20 runs**,
   covering low/typical/high speeds (e.g., ~20, ~40, ~60 km/h) and both
   directions.
2. For each run, record: reference speed at mid-view vs the panel's reported
   speed for that vehicle (from the live overlay or the data stream).
3. Compute per-run error, then: mean absolute error (MAE), mean signed error
   (bias), and worst case.

**Pass criteria (pilot acceptance)**
- MAE ≤ **10%** of reference (stretch target 5%),
- |bias| ≤ **5%** (a systematic bias means the calibration rectangle
  dimensions are off — re-measure and re-calibrate),
- no run > 20% error without an identifiable cause (occlusion, track break).

A failed run set is diagnostic, not fatal: bias → fix calibration; large
random spread → camera too far/low FPS/unstable mount.

## 3. Detection & counting validation

1. Record (or observe) three 15-minute windows: off-peak, peak, and night if
   in scope.
2. Manually count vehicles crossing a reference line per window; compare to
   the panel's per-interval history counts.
3. **Pass**: panel count within **10%** of manual count per window. Note
   systematic misses (small motorcycles, night) explicitly — do not average
   them away.

## 4. Violation precision review

After ≥ 48 h of unattended recording (`PANEL_ALWAYS_RECORD=1`):
1. Export the violation log (Violations → Export CSV) and review **every**
   snapshot for the pilot period (or a 100-event sample if larger).
2. Classify each: confirmed / false / unclear.
3. **Pass**: precision (confirmed ÷ (confirmed + false)) ≥ **90%** per
   violation type in scope. Plate correctness: every plate string reported
   must match the snapshot — the design goal is **zero wrong plates**
   (missing plates are acceptable; wrong ones are not).

Tuning levers if a type under-performs: `PANEL_SPEED_LIMIT_KMH`,
`PANEL_SPEEDING_FRAMES`, `PANEL_ERRATIC_REVERSALS`, `PANEL_DRIFT_LAT_G`,
stop-line placement, zone geometry.

## 5. Record sheet (per camera)

```
Camera ID: ____   Location: ____________   Date: ______
Mount: height ___ m, fixed? __   Stability px/frame: ___
Calibration: rectangle ___ m x ___ m, measured by ______, reprojection ___ m
Speed: runs __, MAE __%, bias __%, worst __%   PASS/FAIL
Counting: window1 __/__ , window2 __/__ , window3 __/__   PASS/FAIL
Violations: reviewed __, confirmed __, false __, precision __%   PASS/FAIL
Plates: reported __, wrong __ (must be 0)   PASS/FAIL
Signed (operator): ______________   Signed (reviewer): ______________
```

## 6. Scope notes (honest boundaries)

- Speeds, emissions and drift are only as accurate as §1–2; uncalibrated
  cameras intentionally report no speed.
- All violation outputs are **operator alerts/analytics**, not legal
  enforcement evidence — citations require certified equipment and
  jurisdiction-specific evidentiary procedures.
- The control-benchmark numbers (delay/CO₂ reductions) are simulation
  results; a field pilot measures its own before/after using the panel's
  history export.
