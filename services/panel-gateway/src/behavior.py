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
