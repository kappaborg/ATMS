"""
Driver-behaviour anomaly detection: speeding and wrong-way.

Both reuse data the pipeline already produces (per-vehicle tracking + speed +
approach), so they stay consistent with the stopped-vehicle incident detector.

* speeding  — measured speed over a configurable limit (needs calibration for
  a real km/h; otherwise never fires — honest).
* wrong-way — the detector LEARNS the normal flow direction per approach from
  forward-moving vehicles (EMA), then flags a vehicle whose sustained motion
  opposes it. Self-calibrating: works even before ground-plane calibration
  because it's about direction, not speed. Wrong-way vehicles don't corrupt
  the learned flow (only forward movers update it).

These are operator ALERTS / analytics, not legal enforcement (that needs
certified equipment + evidentiary standards).
"""
from __future__ import annotations

import math
import os
from collections import deque


class DriverBehavior:
    def __init__(
        self,
        speed_limit_kmh: float | None = None,
        wrong_way_frames: int = 5,
        min_move_px: float = 2.0,
        oppose_dot: float = -0.3,  # cos < -0.3  ->  > ~107° from the flow
        speeding_frames: int | None = None,
    ):
        self.speed_limit_kmh = (
            speed_limit_kmh
            if speed_limit_kmh is not None
            else float(os.getenv("PANEL_SPEED_LIMIT_KMH", "60"))
        )
        self.wrong_way_frames = wrong_way_frames
        self.min_move_px = min_move_px
        self.oppose_dot = oppose_dot
        # SUSTAINED speeding only: a real speeder is over the limit for many
        # consecutive measurements; a single-frame spike (jitter/association
        # noise) is not a violation.
        self.speeding_frames = (
            speeding_frames if speeding_frames is not None
            else int(os.getenv("PANEL_SPEEDING_FRAMES", "3"))
        )
        self._pos: dict[int, tuple[float, float]] = {}
        self._flow: dict[str, tuple[float, float]] = {}  # approach -> unit flow vector
        self._streak: dict[int, int] = {}  # consecutive against-flow frames
        self._speed_streak: dict[int, int] = {}  # consecutive over-limit frames

    def update(
        self, vehicles: list, t: float, wrong_way: bool = True
    ) -> tuple[list[dict], set[int], set[int]]:
        """`vehicles` have .track_id, .center, .speed_kmh, .approach.
        Returns (violations, speeding_ids, wrong_way_ids).

        `wrong_way` should be False when approaches are only the crude
        left/right frame split (uncalibrated) — that isn't real per-approach
        flow, so direction-based wrong-way detection would false-positive.
        Speeding is unaffected (it uses measured speed, which needs calibration
        anyway)."""
        violations: list[dict] = []
        speeding: set[int] = set()
        wrong: set[int] = set()
        live: set[int] = set()

        for v in vehicles:
            tid = int(v.track_id)
            live.add(tid)
            cx, cy = v.center

            # --- speeding (sustained over consecutive measurements) ---
            if v.speed_kmh is not None and v.speed_kmh > self.speed_limit_kmh:
                self._speed_streak[tid] = self._speed_streak.get(tid, 0) + 1
                if self._speed_streak[tid] >= self.speeding_frames:
                    speeding.add(tid)
                    violations.append({
                        "type": "speeding", "track_id": tid,
                        "speed_kmh": round(v.speed_kmh, 1), "limit_kmh": self.speed_limit_kmh,
                    })
            elif v.speed_kmh is not None:
                self._speed_streak[tid] = 0

            # --- wrong-way (direction vs learned per-approach flow) ---
            if not wrong_way:
                continue
            prev = self._pos.get(tid)
            self._pos[tid] = (cx, cy)
            if prev is None:
                self._streak[tid] = 0
                continue
            mvx, mvy = cx - prev[0], cy - prev[1]
            mag = math.hypot(mvx, mvy)
            if mag < self.min_move_px:
                continue  # too little motion to judge a direction
            ux, uy = mvx / mag, mvy / mag
            key = v.approach or "global"
            flow = self._flow.get(key)
            if flow is None:
                self._flow[key] = (ux, uy)  # bootstrap flow
                self._streak[tid] = 0
                continue
            dot = ux * flow[0] + uy * flow[1]
            if dot < self.oppose_dot:
                self._streak[tid] = self._streak.get(tid, 0) + 1
                if self._streak[tid] >= self.wrong_way_frames:
                    wrong.add(tid)
                    violations.append({"type": "wrong_way", "track_id": tid})
            else:
                self._streak[tid] = 0
                # only forward movers refine the learned flow (EMA)
                a = 0.05
                fx, fy = (1 - a) * flow[0] + a * ux, (1 - a) * flow[1] + a * uy
                nmag = math.hypot(fx, fy) or 1.0
                self._flow[key] = (fx / nmag, fy / nmag)

        for tid in list(self._pos):
            if tid not in live:
                self._pos.pop(tid, None)
                self._streak.pop(tid, None)
                self._speed_streak.pop(tid, None)
        return violations, speeding, wrong

    def remove(self, track_id: int) -> None:
        self._pos.pop(track_id, None)
        self._streak.pop(track_id, None)
        self._speed_streak.pop(track_id, None)


class ErraticDriving:
    """Flags reckless/erratic driving = repeated left-right HEADING reversals
    (weaving), which a normal path — even a turn — doesn't produce. Purely
    trajectory-based (no lane geometry, no calibration). Conservative by design
    (needs several significant reversals) since it's an ADVISORY signal with a
    higher false-positive rate than the clean violations. Tune with
    PANEL_ERRATIC_REVERSALS.
    """

    def __init__(
        self,
        step_px: float = 26.0,   # record a heading only after this much travel
        window: int = 8,          # over this many recorded headings
        min_reversals: int | None = None,
        turn_deg: float = 38.0,   # only large, genuine direction swings count
        cooldown_s: float = 3.0,
    ):
        self.step_px = step_px
        self.window = window
        self.min_reversals = (
            min_reversals if min_reversals is not None
            else int(os.getenv("PANEL_ERRATIC_REVERSALS", "4"))
        )
        self.turn_cos = math.cos(math.radians(turn_deg))
        self.cooldown_s = cooldown_s
        self._last_pos: dict[int, tuple[float, float]] = {}
        self._vecs: dict[int, deque] = {}
        self._step_pos: dict[int, deque] = {}  # position at each recorded step
        self._flagged_until: dict[int, float] = {}

    def update(self, vehicles: list, t: float) -> tuple[list[dict], set[int]]:
        violations: list[dict] = []
        ids: set[int] = set()
        live: set[int] = set()
        for v in vehicles:
            tid = int(v.track_id)
            live.add(tid)
            cur = v.center
            if self._flagged_until.get(tid, 0.0) > t:
                ids.add(tid)
            lp = self._last_pos.get(tid)
            if lp is None:
                self._last_pos[tid] = cur
                continue
            dx, dy = cur[0] - lp[0], cur[1] - lp[1]
            mag = math.hypot(dx, dy)
            # Only record a new heading after a real displacement step — this
            # averages out per-frame tracking jitter (the false-positive source).
            if mag < self.step_px:
                continue
            self._last_pos[tid] = cur
            dq = self._vecs.setdefault(tid, deque(maxlen=self.window))
            dq.append((dx / mag, dy / mag))
            pq = self._step_pos.setdefault(tid, deque(maxlen=self.window + 1))
            pq.append(cur)
            if len(dq) < self.window:
                continue
            # PROGRESSION gate: a weaving driver still advances; a parked car
            # whose box oscillates (occlusion flicker) has ~zero NET travel.
            net = math.hypot(pq[-1][0] - pq[0][0], pq[-1][1] - pq[0][1])
            if net < 0.3 * self.step_px * self.window:
                continue
            # Count sign changes of the turn direction, over SIGNIFICANT turns
            # only. Weaving -> many reversals; a straight path or a single turn
            # -> ~0.
            reversals, last_sign = 0, 0
            seq = list(dq)
            for a, b in zip(seq, seq[1:]):
                if a[0] * b[0] + a[1] * b[1] >= self.turn_cos:
                    continue  # heading barely changed — not a turn
                sign = 1 if (a[0] * b[1] - a[1] * b[0]) > 0 else -1
                if last_sign and sign != last_sign:
                    reversals += 1
                last_sign = sign
            if reversals >= self.min_reversals:
                ids.add(tid)
                self._flagged_until[tid] = t + self.cooldown_s
                violations.append({"type": "reckless", "track_id": tid, "reversals": reversals})
        for tid in list(self._last_pos):
            if tid not in live:
                self._last_pos.pop(tid, None)
                self._vecs.pop(tid, None)
                self._step_pos.pop(tid, None)
                self._flagged_until.pop(tid, None)
        return violations, ids

    def remove(self, track_id: int) -> None:
        self._last_pos.pop(track_id, None)
        self._vecs.pop(track_id, None)
        self._step_pos.pop(track_id, None)
        self._flagged_until.pop(track_id, None)


class DriftDetector:
    """Flags drifting / loss-of-control from PHYSICS: lateral acceleration =
    v^2 * path-curvature. A tyre grips to ~0.9g; normal cornering stays well
    under (drivers slow for bends), so exceeding ~0.6g means the car is
    sliding/drifting/spinning. Needs calibration (real speed + world-metre
    curvature). Note: this is a physical loss-of-control signal — true
    slip-angle drift would additionally need vehicle orientation (an oriented-
    bbox/pose model), which the axis-aligned detector doesn't provide.
    """

    def __init__(
        self,
        lat_g_thresh: float | None = None,
        min_speed_kmh: float = 15.0,
        step_m: float = 0.8,
        cooldown_s: float = 3.0,
    ):
        self.lat_accel_thresh = (
            (lat_g_thresh if lat_g_thresh is not None
             else float(os.getenv("PANEL_DRIFT_LAT_G", "0.6"))) * 9.81
        )
        self.min_speed_kmh = min_speed_kmh
        self.step_m = step_m
        self.cooldown_s = cooldown_s
        self._pts: dict[int, deque] = {}   # tid -> deque[(X, Y, t)] spaced by step_m
        self._flagged_until: dict[int, float] = {}

    def update(self, world_positions: list, t: float) -> tuple[list[dict], set[int]]:
        """`world_positions` = [(track_id, X_m, Y_m)] in ground-plane metres."""
        violations: list[dict] = []
        ids: set[int] = set()
        live: set[int] = set()
        for tid, X, Y in world_positions:
            tid = int(tid)
            live.add(tid)
            if self._flagged_until.get(tid, 0.0) > t:
                ids.add(tid)
            dq = self._pts.setdefault(tid, deque(maxlen=3))
            if dq:
                lx, ly, lt = dq[-1]
                step = math.hypot(X - lx, Y - ly)
                if step < self.step_m:
                    continue  # not moved a full step — skip (de-jitter)
                # Teleport: an impossible ground-plane jump (ID switch) —
                # reset the trajectory rather than compute a monster lateral-G.
                if step / max(t - lt, 1e-3) > 70.0:  # > 250 km/h between samples
                    dq.clear()
            dq.append((X, Y, t))
            if len(dq) < 3:
                continue
            (ax, ay, at), (bx, by, _bt), (cx, cy, ct) = dq
            span_t = ct - at
            if span_t <= 0:
                continue
            v = math.hypot(cx - ax, cy - ay) / span_t  # m/s over the 2-step span
            if v * 3.6 < self.min_speed_kmh:
                continue  # drift needs speed; slow tight turns aren't drifts
            # Menger curvature of A,B,C: kappa = 2*Area / (|AB||BC||CA|)
            area2 = abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))  # 2*Area
            denom = (math.hypot(bx - ax, by - ay) * math.hypot(cx - bx, cy - by)
                     * math.hypot(ax - cx, ay - cy))
            if denom < 1e-6:
                continue
            lat_accel = v * v * (2.0 * area2 / denom)
            if lat_accel > self.lat_accel_thresh:
                ids.add(tid)
                self._flagged_until[tid] = t + self.cooldown_s
                violations.append({
                    "type": "drift", "track_id": tid,
                    "lateral_g": round(lat_accel / 9.81, 2), "speed_kmh": round(v * 3.6, 1),
                })
        for tid in list(self._pts):
            if tid not in live:
                self._pts.pop(tid, None)
                self._flagged_until.pop(tid, None)
        return violations, ids

    def remove(self, track_id: int) -> None:
        self._pts.pop(track_id, None)
        self._flagged_until.pop(track_id, None)


def _segments_cross(p1, p2, p3, p4) -> bool:
    """True if segment p1-p2 crosses segment p3-p4 (orientation test)."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])
    return ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4)


class RedLightDetector:
    """Flags a vehicle that crosses an approach's stop-line while that approach
    is RED. Works in image space (no ground-plane calibration needed) — it just
    needs the stop-line drawn and the current signal phase."""

    def __init__(self, cooldown_s: float = 3.0, min_move_px: float = 3.0, max_move_px: float = 240.0):
        self.cooldown_s = cooldown_s
        self.min_move_px = min_move_px
        # A motion segment longer than this is a track teleport (ID switch /
        # occlusion jump), not a vehicle crossing the line — ignore it.
        self.max_move_px = max_move_px
        self._pos: dict[int, tuple[float, float]] = {}
        self._flagged_until: dict[int, float] = {}

    def update(self, vehicles: list, t: float, stop_lines: list, is_red) -> tuple[list[dict], set[int]]:
        """`stop_lines` = [{"approach","points":[[x1,y1],[x2,y2]]}]; `is_red(approach)`
        returns True when that approach's signal is red."""
        violations: list[dict] = []
        ids: set[int] = set()
        live: set[int] = set()
        for v in vehicles:
            tid = int(v.track_id)
            live.add(tid)
            cur = v.center
            prev = self._pos.get(tid)
            self._pos[tid] = cur
            if self._flagged_until.get(tid, 0.0) > t:
                ids.add(tid)  # keep marked briefly so the operator sees it
            if prev is None:
                continue
            step = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
            if step < self.min_move_px or step > self.max_move_px:
                continue  # too small to judge / too large to be real motion
            for sl in stop_lines:
                p3, p4 = sl["points"]
                if _segments_cross(prev, cur, p3, p4) and is_red(sl["approach"]):
                    ids.add(tid)
                    self._flagged_until[tid] = t + self.cooldown_s
                    violations.append({"type": "red_light", "track_id": tid, "approach": sl["approach"]})
                    break
        for tid in list(self._pos):
            if tid not in live:
                self._pos.pop(tid, None)
                self._flagged_until.pop(tid, None)
        return violations, ids

    def remove(self, track_id: int) -> None:
        self._pos.pop(track_id, None)
        self._flagged_until.pop(track_id, None)
