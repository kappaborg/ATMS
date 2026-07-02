"""Tests for simulation/harness/kpis.py — Phase C3."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from simulation.harness.kpis import (  # noqa: E402
    KPIAccumulator,
    Observation,
    SimulationKPIs,
    _is_conflict,
    diff_against_baseline,
)


def _obs(**kw) -> Observation:
    defaults = dict(
        sim_time_s=0.0,
        queue_by_approach={},
        waiting_time_by_approach={},
        departures_total=0,
        current_mode="ai_adaptive",
        green_approach_set=(),
        preempts_armed=0,
        ped_calls_served=0,
    )
    defaults.update(kw)
    return Observation(**defaults)


class TestConflictDetection:
    def test_no_conflict_when_one_direction(self):
        assert not _is_conflict(("north_south",))
        assert not _is_conflict(("east_west",))
        assert not _is_conflict(())

    def test_conflict_when_both_directions(self):
        assert _is_conflict(("north_south", "east_west"))
        assert _is_conflict(("east_west", "north_south"))


class TestAccumulator:
    def test_zero_observations(self):
        acc = KPIAccumulator("empty")
        kpis = acc.finalize()
        assert kpis.scenario == "empty"
        assert kpis.sim_steps == 0
        assert kpis.avg_delay_s == 0.0
        assert kpis.throughput_vph == 0.0
        assert kpis.conflicts == 0

    def test_basic_delay_and_throughput(self):
        acc = KPIAccumulator("basic")
        # 100 vehicles depart over a 1000s sim with 500s aggregate wait.
        # Final tick is the one that matters for cumulative counters.
        for t in range(1, 1001):
            acc.observe(
                _obs(
                    sim_time_s=float(t),
                    waiting_time_by_approach={"north_south": 0.5},  # 0.5s per tick
                    departures_total=t // 10,  # 100 by end
                )
            )
        kpis = acc.finalize()
        assert kpis.sim_steps == 1000
        # 1000 ticks x 0.5s = 500s total wait / 100 vehicles = 5s avg.
        assert kpis.avg_delay_s == pytest.approx(5.0)
        # 100 vehicles x 3600 / 1000s = 360 vph.
        assert kpis.throughput_vph == pytest.approx(360.0)

    def test_max_queue_picks_peak(self):
        acc = KPIAccumulator("queue")
        for q in [3, 7, 5, 12, 2]:
            acc.observe(_obs(sim_time_s=float(q), queue_by_approach={"north_south": q}))
        assert acc.finalize().max_queue_length == 12

    def test_conflict_counter(self):
        acc = KPIAccumulator("conflict")
        # 5 ticks with NS green only, 2 with both (illegal), 3 with EW only.
        for _ in range(5):
            acc.observe(_obs(sim_time_s=1.0, green_approach_set=("north_south",)))
        for _ in range(2):
            acc.observe(
                _obs(
                    sim_time_s=1.0,
                    green_approach_set=("north_south", "east_west"),
                )
            )
        for _ in range(3):
            acc.observe(_obs(sim_time_s=1.0, green_approach_set=("east_west",)))
        assert acc.finalize().conflicts == 2

    def test_mode_dwell(self):
        acc = KPIAccumulator("modes", tick_dt_s=1.0)
        for _ in range(10):
            acc.observe(_obs(current_mode="ai_adaptive"))
        for _ in range(5):
            acc.observe(_obs(current_mode="fixed_time"))
        for _ in range(2):
            acc.observe(_obs(current_mode="all_red_flash"))
        kpis = acc.finalize()
        assert kpis.mode_dwell_s["ai_adaptive"] == 10.0
        assert kpis.mode_dwell_s["fixed_time"] == 5.0
        assert kpis.mode_dwell_s["all_red_flash"] == 2.0

    def test_preempt_and_ped_counters(self):
        acc = KPIAccumulator("events")
        acc.observe(_obs(preempts_armed=1, ped_calls_served=2))
        acc.observe(_obs(preempts_armed=2, ped_calls_served=1))
        kpis = acc.finalize()
        assert kpis.preempt_events == 3
        assert kpis.ped_calls_served == 3


class TestBaselineDiff:
    def test_no_baseline_returns_empty_when_keys_missing(self):
        cur = SimulationKPIs(
            scenario="x",
            sim_duration_s=10,
            sim_steps=10,
            avg_delay_s=5.0,
            max_queue_length=3,
            throughput_vph=300,
            conflicts=0,
            mode_dwell_s={},
            preempt_events=0,
            ped_calls_served=0,
        )
        diff = diff_against_baseline(cur, {})
        assert diff == {}

    def test_diff_pct_calculation(self):
        cur = SimulationKPIs(
            scenario="x",
            sim_duration_s=10,
            sim_steps=10,
            avg_delay_s=6.0,
            max_queue_length=3,
            throughput_vph=300,
            conflicts=0,
            mode_dwell_s={},
            preempt_events=0,
            ped_calls_served=0,
        )
        baseline = {"avg_delay_s": 5.0}
        diff = diff_against_baseline(cur, baseline)
        assert diff["avg_delay_s"]["delta"] == 1.0
        assert diff["avg_delay_s"]["delta_pct"] == 20.0

    def test_diff_pct_none_when_baseline_zero(self):
        cur = SimulationKPIs(
            scenario="x",
            sim_duration_s=10,
            sim_steps=10,
            avg_delay_s=6.0,
            max_queue_length=3,
            throughput_vph=300,
            conflicts=1,
            mode_dwell_s={},
            preempt_events=0,
            ped_calls_served=0,
        )
        diff = diff_against_baseline(cur, {"conflicts": 0})
        assert diff["conflicts"]["delta"] == 1
        assert diff["conflicts"]["delta_pct"] is None
