"""
SUMO simulation KPIs — Phase C3.

Pure-Python accumulator. The runner feeds per-tick `Observation`s, and the
accumulator computes the final KPI bundle.

Designed to be testable without SUMO: tests synthesise observations and assert
the computed KPIs match.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Observation:
    """One tick of simulation state, fed to the accumulator."""

    sim_time_s: float
    # Per-approach queued vehicles.
    queue_by_approach: dict[str, int] = field(default_factory=dict)
    # Per-approach waiting time accumulated this tick (sum across vehicles).
    waiting_time_by_approach: dict[str, float] = field(default_factory=dict)
    # Cumulative departures (vehicles that have left the simulation since start).
    departures_total: int = 0
    # Mode the failsafe is currently in (e.g., "ai_adaptive", "fixed_time").
    current_mode: str = ""
    # Number of approaches currently green simultaneously. Anything > 1 of the
    # conflicting set is a violation; the accumulator counts those.
    green_approach_set: tuple[str, ...] = ()
    # Counters for events the harness saw this tick.
    preempts_armed: int = 0
    ped_calls_served: int = 0


@dataclass(frozen=True)
class SimulationKPIs:
    """Final KPI bundle. JSON-serialisable."""

    scenario: str
    sim_duration_s: float
    sim_steps: int
    avg_delay_s: float
    max_queue_length: int
    throughput_vph: float
    conflicts: int
    mode_dwell_s: dict[str, float]
    preempt_events: int
    ped_calls_served: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "sim_duration_s": self.sim_duration_s,
            "sim_steps": self.sim_steps,
            "avg_delay_s": self.avg_delay_s,
            "max_queue_length": self.max_queue_length,
            "throughput_vph": self.throughput_vph,
            "conflicts": self.conflicts,
            "mode_dwell_s": dict(self.mode_dwell_s),
            "preempt_events": self.preempt_events,
            "ped_calls_served": self.ped_calls_served,
        }


# ---------------------------------------------------------------------------
# Conflict set — approaches that must never be GREEN simultaneously.
# Mirrors shared.atms_common.safety._CONFLICTING_GREEN_PAIRS, but at the
# SUMO approach-name granularity (the strings used in the route+detector XML).
# ---------------------------------------------------------------------------

_CONFLICTING_APPROACH_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"north_south", "east_west"}),
    }
)


def _is_conflict(green_set: tuple[str, ...]) -> bool:
    g = set(green_set)
    return any(pair.issubset(g) for pair in _CONFLICTING_APPROACH_PAIRS)


# ---------------------------------------------------------------------------
# Accumulator
# ---------------------------------------------------------------------------


class KPIAccumulator:
    """Stateful accumulator. One per simulation run."""

    def __init__(self, scenario: str, *, tick_dt_s: float = 1.0) -> None:
        self._scenario = scenario
        self._tick_dt_s = tick_dt_s
        self._steps = 0
        self._sim_time_s = 0.0
        self._total_waiting_time = 0.0
        self._max_queue = 0
        self._final_departures = 0
        self._conflicts = 0
        self._mode_dwell: dict[str, float] = defaultdict(float)
        self._preempt_events = 0
        self._ped_calls_served = 0

    def observe(self, obs: Observation) -> None:
        self._steps += 1
        self._sim_time_s = obs.sim_time_s
        self._total_waiting_time += sum(obs.waiting_time_by_approach.values())
        if obs.queue_by_approach:
            tick_max = max(obs.queue_by_approach.values())
            self._max_queue = max(self._max_queue, tick_max)
        self._final_departures = obs.departures_total
        if _is_conflict(obs.green_approach_set):
            self._conflicts += 1
        if obs.current_mode:
            self._mode_dwell[obs.current_mode] += self._tick_dt_s
        self._preempt_events += obs.preempts_armed
        self._ped_calls_served += obs.ped_calls_served

    def finalize(self) -> SimulationKPIs:
        avg_delay = (
            self._total_waiting_time / self._final_departures if self._final_departures > 0 else 0.0
        )
        throughput_vph = (
            self._final_departures * 3600.0 / self._sim_time_s if self._sim_time_s > 0 else 0.0
        )
        return SimulationKPIs(
            scenario=self._scenario,
            sim_duration_s=self._sim_time_s,
            sim_steps=self._steps,
            avg_delay_s=round(avg_delay, 3),
            max_queue_length=self._max_queue,
            throughput_vph=round(throughput_vph, 1),
            conflicts=self._conflicts,
            mode_dwell_s={k: round(v, 1) for k, v in self._mode_dwell.items()},
            preempt_events=self._preempt_events,
            ped_calls_served=self._ped_calls_served,
        )


# ---------------------------------------------------------------------------
# Baseline diff
# ---------------------------------------------------------------------------


def diff_against_baseline(
    current: SimulationKPIs, baseline: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """
    Return per-KPI deltas. Each entry has `current`, `baseline`, `delta`,
    `delta_pct` (when baseline > 0). Used by the HTML report and the
    sim-regression CI gate.
    """
    out: dict[str, dict[str, Any]] = {}
    scalar_kpis = (
        "avg_delay_s",
        "max_queue_length",
        "throughput_vph",
        "conflicts",
        "preempt_events",
        "ped_calls_served",
    )
    current_dict = current.to_dict()
    for k in scalar_kpis:
        cur = current_dict.get(k)
        base = baseline.get(k)
        if cur is None or base is None:
            continue
        delta = cur - base
        pct: float | None = (delta / base * 100.0) if base != 0 else None
        out[k] = {
            "current": cur,
            "baseline": base,
            "delta": round(delta, 3),
            "delta_pct": round(pct, 1) if pct is not None else None,
        }
    return out
