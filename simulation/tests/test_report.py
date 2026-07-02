"""Tests for simulation/harness/report.py — Phase C3."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from simulation.harness.kpis import SimulationKPIs  # noqa: E402
from simulation.harness.report import render_report  # noqa: E402


def _kpis(**kw) -> SimulationKPIs:
    defaults = dict(
        scenario="test",
        sim_duration_s=3600.0,
        sim_steps=3600,
        avg_delay_s=5.5,
        max_queue_length=8,
        throughput_vph=720.0,
        conflicts=0,
        mode_dwell_s={"ai_adaptive": 3000.0, "fixed_time": 600.0},
        preempt_events=2,
        ped_calls_served=12,
    )
    defaults.update(kw)
    return SimulationKPIs(**defaults)


class TestReport:
    def test_renders_html(self):
        out = render_report(_kpis())
        assert out.startswith("<!doctype html>")
        assert "ATMS simulation" in out
        assert "test" in out

    def test_shows_zero_conflicts_as_ok(self):
        out = render_report(_kpis(conflicts=0))
        assert "Safety invariant held" in out
        assert "SAFETY VIOLATION" not in out

    def test_shows_conflicts_as_violation(self):
        out = render_report(_kpis(conflicts=3))
        assert "SAFETY VIOLATION" in out

    def test_baseline_diff_section_appears(self):
        out = render_report(_kpis(), baseline={"avg_delay_s": 4.0})
        assert "Baseline diff" in out
        assert "Δ" in out

    def test_no_baseline_no_diff_section(self):
        out = render_report(_kpis(), baseline=None)
        assert "Baseline diff" not in out

    def test_html_escapes_scenario_name(self):
        out = render_report(_kpis(scenario="<script>alert('xss')</script>"))
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_git_sha_line_appears(self):
        out = render_report(_kpis(), git_sha="abc123def")
        assert "abc123def" in out

    def test_mode_dwell_rendered(self):
        out = render_report(_kpis())
        assert "ai_adaptive" in out
        assert "fixed_time" in out
