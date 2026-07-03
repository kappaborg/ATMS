"""
Per-vehicle incident detection for the panel.

The highest-value safety signal is a vehicle that has *stopped where it
shouldn't* — a breakdown, a crash, a stall in a live lane. This detector
flags any tracked vehicle that stays put longer than `stop_seconds`.

Naive by design: it does not yet know where the signal stop-line is, so at a
real intersection you would exclude the stop-zone (via approach zones) to
avoid flagging vehicles waiting at red. For a moving-traffic scene it cleanly
surfaces genuine stalls. Pedestrians are ignored.
"""
from __future__ import annotations

import math


class IncidentDetector:
    def __init__(self, stop_seconds: float = 6.0, move_threshold_px: float = 18.0) -> None:
        self.stop_seconds = stop_seconds
        self.move_threshold_px = move_threshold_px
        # track_id -> {"pos": (x,y), "since": t}
        self._tracks: dict[int, dict] = {}

    def update(self, vehicles: list, t: float) -> tuple[list[dict], set[int]]:
        """`vehicles` is a list of objects with .track_id and .center.
        Returns (incidents, stopped_track_ids)."""
        incidents: list[dict] = []
        stopped_ids: set[int] = set()
        live: set[int] = set()

        for v in vehicles:
            tid = int(v.track_id)
            cx, cy = v.center
            live.add(tid)
            st = self._tracks.get(tid)
            if st is None:
                self._tracks[tid] = {"pos": (cx, cy), "since": t}
                continue
            moved = math.hypot(cx - st["pos"][0], cy - st["pos"][1])
            if moved > self.move_threshold_px:
                st["pos"] = (cx, cy)
                st["since"] = t  # reset the stationary clock
            stationary_for = t - st["since"]
            if stationary_for >= self.stop_seconds:
                stopped_ids.add(tid)
                incidents.append(
                    {
                        "type": "stopped_vehicle",
                        "track_id": tid,
                        "seconds": round(stationary_for, 1),
                        "label": getattr(v, "label", "vehicle"),
                    }
                )

        # Drop tracks the tracker no longer reports.
        for tid in list(self._tracks):
            if tid not in live:
                del self._tracks[tid]
        return incidents, stopped_ids

    def remove(self, track_id: int) -> None:
        self._tracks.pop(track_id, None)
