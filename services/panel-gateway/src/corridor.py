"""
Green-wave corridor coordination.

A corridor is an ordered list of intersections along a route. To "ride the
green wave", each intersection's coordinated green must start offset from the
first by exactly the time a platoon at the design speed needs to reach it:

    offset[i] = (cumulative_distance[i] / design_speed) mod cycle

(cumulative from the first intersection — NOT the pairwise travel time, which
is a common mistake). A vehicle leaving intersection 0 at the start of its
green then arrives at every downstream intersection exactly as it turns green.

This module is pure geometry/timing: it produces the offset schedule, the
green bands for a time-space diagram, and the design-speed vehicle trajectory.
The decision engine consumes the offset as a bounded coordination bias.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Stop:
    intersection_id: str
    distance_m: float  # from the previous stop (0 for the first)


class Corridor:
    def __init__(
        self,
        corridor_id: str,
        stops: list[Stop],
        design_speed_kmh: float = 50.0,
        cycle_s: float = 60.0,
        green_s: float = 27.0,
        direction: str = "north_south",
    ):
        if len(stops) < 2:
            raise ValueError("a corridor needs at least 2 intersections")
        if design_speed_kmh <= 0 or cycle_s <= 0 or green_s <= 0:
            raise ValueError("speed, cycle and green must be positive")
        if direction not in ("north_south", "east_west"):
            raise ValueError(f"invalid direction: {direction}")
        self.corridor_id = corridor_id
        self.stops = stops
        self.direction = direction
        self.design_speed_kmh = design_speed_kmh
        self.speed_mps = design_speed_kmh / 3.6
        self.cycle_s = cycle_s
        self.green_s = min(green_s, cycle_s)

    def cumulative_distances(self) -> list[float]:
        out, acc = [], 0.0
        for s in self.stops:
            acc += s.distance_m
            out.append(acc)
        return out

    def offsets(self) -> dict[str, float]:
        """Coordinated green-start offset (s into the cycle) per intersection."""
        cum = self.cumulative_distances()
        return {
            s.intersection_id: round((d / self.speed_mps) % self.cycle_s, 2)
            for s, d in zip(self.stops, cum)
        }

    def bands(self, num_cycles: int = 2) -> list[dict]:
        """Green windows per intersection over `num_cycles`, for a time-space
        diagram (x=time, y=distance)."""
        offs = self.offsets()
        cum = self.cumulative_distances()
        out = []
        for s, d in zip(self.stops, cum):
            o = offs[s.intersection_id]
            windows = [
                [round(o + k * self.cycle_s, 2), round(o + k * self.cycle_s + self.green_s, 2)]
                for k in range(num_cycles)
            ]
            out.append({"intersection_id": s.intersection_id, "distance_m": round(d, 1), "windows": windows})
        return out

    def trajectory(self, num_cycles: int = 2) -> list[list[float]]:
        """The design-speed vehicle line [t, distance] — it should pass through
        the start of every green band (that's the wave)."""
        total_t = self.cycle_s * num_cycles
        total_d = self.cumulative_distances()[-1]
        # A straight line at design speed from (0,0); clip at the diagram edges.
        t_end = min(total_t, total_d / self.speed_mps)
        return [[0.0, 0.0], [round(t_end, 2), round(t_end * self.speed_mps, 1)]]

    def to_dict(self) -> dict:
        return {
            "corridor_id": self.corridor_id,
            "direction": self.direction,
            "design_speed_kmh": self.design_speed_kmh,
            "cycle_s": self.cycle_s,
            "green_s": self.green_s,
            "offsets": self.offsets(),
            "bands": self.bands(),
            "trajectory": self.trajectory(),
            "length_m": round(self.cumulative_distances()[-1], 1),
        }

    def coordination_for(self, intersection_id: str, direction: str) -> dict | None:
        """The bounded coordination hint an intersection's decision engine
        consumes: when the corridor clock is in this intersection's green band,
        bias toward `direction`."""
        offs = self.offsets()
        if intersection_id not in offs:
            return None
        return {
            "offset_s": offs[intersection_id],
            "cycle_s": self.cycle_s,
            "green_s": self.green_s,
            "direction": direction,
        }


def build_corridor(payload: dict) -> Corridor:
    """From {corridor_id, design_speed_kmh?, cycle_s?, green_s?,
    stops:[{intersection_id, distance_m}]}."""
    stops = [Stop(s["intersection_id"], float(s.get("distance_m", 0.0))) for s in payload["stops"]]
    return Corridor(
        corridor_id=payload["corridor_id"],
        stops=stops,
        design_speed_kmh=float(payload.get("design_speed_kmh", 50.0)),
        cycle_s=float(payload.get("cycle_s", 60.0)),
        green_s=float(payload.get("green_s", 27.0)),
        direction=payload.get("direction", "north_south"),
    )
