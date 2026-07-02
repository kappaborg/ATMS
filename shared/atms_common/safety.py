"""
Hard safety invariants and the FixedTimePlan datatype.

Defaults follow EU/RiLSA (ADR-0004). Per-intersection overrides come from YAML.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .decision import CommandedPhase

# Pairs that must never be GREEN simultaneously.
#
# Phase A1 starts with the basic NS↔EW conflict. Phase A7 extends to
# preempt-vs-cross-traffic conflicts: an EV preempt commands its direction's
# green; the conflicting direction must not be simultaneously green or ped-walk.
_CONFLICTING_GREEN_PAIRS = frozenset(
    {
        frozenset({CommandedPhase.NS_GREEN, CommandedPhase.EW_GREEN}),
        frozenset({CommandedPhase.EV_PREEMPT_NS, CommandedPhase.EW_GREEN}),
        frozenset({CommandedPhase.EV_PREEMPT_EW, CommandedPhase.NS_GREEN}),
        frozenset({CommandedPhase.EV_PREEMPT_NS, CommandedPhase.EV_PREEMPT_EW}),
        # Pedestrian-walk against vehicular preempt on the same direction is a
        # conflict — the EV would run over the pedestrian. Failsafe forces ped
        # clearance to complete first.
        frozenset({CommandedPhase.EV_PREEMPT_NS, CommandedPhase.PED_NS_WALK}),
        frozenset({CommandedPhase.EV_PREEMPT_EW, CommandedPhase.PED_EW_WALK}),
    }
)


def is_conflicting(a: CommandedPhase, b: CommandedPhase) -> bool:
    """True if simultaneously commanding `a` and `b` would violate safety."""
    return frozenset({a, b}) in _CONFLICTING_GREEN_PAIRS


@dataclass(frozen=True)
class FixedTimePlan:
    """
    A simple two-phase RiLSA-style fixed-time plan.

    Times in seconds. Sum of (ns_green + ns_yellow + all_red_after_ns
    + ew_green + ew_yellow + all_red_after_ew) = cycle_s.
    """

    cycle_s: float
    ns_green_s: float
    ns_yellow_s: float
    all_red_after_ns_s: float
    ew_green_s: float
    ew_yellow_s: float
    all_red_after_ew_s: float

    # EU/RiLSA defaults; per-pilot YAML overrides.
    min_green_s: float = 10.0

    def __post_init__(self) -> None:
        parts = (
            self.ns_green_s,
            self.ns_yellow_s,
            self.all_red_after_ns_s,
            self.ew_green_s,
            self.ew_yellow_s,
            self.all_red_after_ew_s,
        )
        if any(p < 0 for p in parts):
            raise ValueError("FixedTimePlan parts must be non-negative")
        if abs(sum(parts) - self.cycle_s) > 1e-6:
            raise ValueError(
                f"FixedTimePlan parts must sum to cycle_s ({self.cycle_s}); got {sum(parts)}"
            )
        if self.ns_green_s < self.min_green_s or self.ew_green_s < self.min_green_s:
            raise ValueError(f"FixedTimePlan greens must be >= min_green_s ({self.min_green_s})")

    @classmethod
    def rilsa_default(cls) -> FixedTimePlan:
        """Reference RiLSA urban plan, 80s cycle."""
        return cls(
            cycle_s=80.0,
            ns_green_s=32.0,
            ns_yellow_s=3.0,
            all_red_after_ns_s=2.0,
            ew_green_s=38.0,
            ew_yellow_s=3.0,
            all_red_after_ew_s=2.0,
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, float]) -> FixedTimePlan:
        return cls(
            cycle_s=float(data["cycle_s"]),
            ns_green_s=float(data["ns_green_s"]),
            ns_yellow_s=float(data["ns_yellow_s"]),
            all_red_after_ns_s=float(data["all_red_after_ns_s"]),
            ew_green_s=float(data["ew_green_s"]),
            ew_yellow_s=float(data["ew_yellow_s"]),
            all_red_after_ew_s=float(data["all_red_after_ew_s"]),
            min_green_s=float(data.get("min_green_s", 10.0)),
        )

    def phase_at(self, elapsed_in_cycle_s: float) -> CommandedPhase:
        """Return the commanded phase for a given offset into the cycle."""
        t = elapsed_in_cycle_s % self.cycle_s
        boundaries = [
            (self.ns_green_s, CommandedPhase.NS_GREEN),
            (self.ns_yellow_s, CommandedPhase.NS_YELLOW),
            (self.all_red_after_ns_s, CommandedPhase.ALL_RED),
            (self.ew_green_s, CommandedPhase.EW_GREEN),
            (self.ew_yellow_s, CommandedPhase.EW_YELLOW),
            (self.all_red_after_ew_s, CommandedPhase.ALL_RED),
        ]
        acc = 0.0
        for dur, phase in boundaries:
            acc += dur
            if t < acc:
                return phase
        return CommandedPhase.ALL_RED  # numerical edge


@dataclass(frozen=True)
class SafetyConfig:
    """Per-intersection safety knobs. Defaults are EU/RiLSA-friendly."""

    min_green_s: float = 10.0
    driver_yellow_s: float = 3.0
    all_red_intergreen_s: float = 2.0
    ped_min_walk_s: float = 5.0
    ped_clearance_walking_speed_mps: float = 1.2  # RiLSA §3.4

    def yellow_for_speed(self, speed_kmh: float) -> float:
        """Speed-dependent driver yellow per StVO §37."""
        if speed_kmh <= 50:
            return 3.0
        if speed_kmh <= 60:
            return 4.0
        return 5.0
