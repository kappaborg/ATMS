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


class DriverBehavior:
    def __init__(
        self,
        speed_limit_kmh: float | None = None,
        wrong_way_frames: int = 5,
        min_move_px: float = 2.0,
        oppose_dot: float = -0.3,  # cos < -0.3  ->  > ~107° from the flow
    ):
        self.speed_limit_kmh = (
            speed_limit_kmh
            if speed_limit_kmh is not None
            else float(os.getenv("PANEL_SPEED_LIMIT_KMH", "60"))
        )
        self.wrong_way_frames = wrong_way_frames
        self.min_move_px = min_move_px
        self.oppose_dot = oppose_dot
        self._pos: dict[int, tuple[float, float]] = {}
        self._flow: dict[str, tuple[float, float]] = {}  # approach -> unit flow vector
        self._streak: dict[int, int] = {}  # consecutive against-flow frames

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

            # --- speeding ---
            if v.speed_kmh is not None and v.speed_kmh > self.speed_limit_kmh:
                speeding.add(tid)
                violations.append({
                    "type": "speeding", "track_id": tid,
                    "speed_kmh": round(v.speed_kmh, 1), "limit_kmh": self.speed_limit_kmh,
                })

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
        return violations, speeding, wrong

    def remove(self, track_id: int) -> None:
        self._pos.pop(track_id, None)
        self._streak.pop(track_id, None)


def _segments_cross(p1, p2, p3, p4) -> bool:
    """True if segment p1-p2 crosses segment p3-p4 (orientation test)."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])
    return ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4)


class RedLightDetector:
    """Flags a vehicle that crosses an approach's stop-line while that approach
    is RED. Works in image space (no ground-plane calibration needed) — it just
    needs the stop-line drawn and the current signal phase."""

    def __init__(self, cooldown_s: float = 3.0, min_move_px: float = 3.0):
        self.cooldown_s = cooldown_s
        self.min_move_px = min_move_px
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
            if math.hypot(cur[0] - prev[0], cur[1] - prev[1]) < self.min_move_px:
                continue
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
