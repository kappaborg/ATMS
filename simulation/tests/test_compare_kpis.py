"""Unit tests for simulation/compare_kpis.py."""

from __future__ import annotations

import json
import pathlib

import pytest

from simulation.compare_kpis import (
    _DEFAULT_TOLERANCES,
    compare,
    format_markdown,
    format_text,
    main,
)


def _baseline(**overrides) -> dict:
    kpis = {
        "scenario": "rush-hour",
        "sim_duration_s": 3600.0,
        "sim_steps": 3600,
        "avg_delay_s": 22.0,
        "max_queue_length": 18,
        "throughput_vph": 1100.0,
        "conflicts": 0,
        "mode_dwell_s": {"ai_adaptive": 3600.0},
        "preempt_events": 0,
        "ped_calls_served": 0,
    }
    kpis.update(overrides)
    return {"kpis": kpis, "tolerances": dict(_DEFAULT_TOLERANCES)}


def _actual(**overrides) -> dict:
    a = {
        "scenario": "rush-hour",
        "sim_duration_s": 3600.0,
        "sim_steps": 3600,
        "avg_delay_s": 22.0,
        "max_queue_length": 18,
        "throughput_vph": 1100.0,
        "conflicts": 0,
        "mode_dwell_s": {"ai_adaptive": 3600.0},
        "preempt_events": 0,
        "ped_calls_served": 0,
    }
    a.update(overrides)
    return a


class TestCompare:
    def test_identical_run_is_ok(self):
        results = compare(_actual(), _baseline())
        assert all(r.verdict == "ok" for r in results)

    def test_delay_regression(self):
        # 11% delay increase — over 10% tolerance
        results = compare(_actual(avg_delay_s=24.5), _baseline())
        delay = next(r for r in results if r.name == "avg_delay_s")
        assert delay.verdict == "regression"

    def test_delay_within_tolerance(self):
        # 9% delay increase — under 10% tolerance
        results = compare(_actual(avg_delay_s=24.0), _baseline())
        delay = next(r for r in results if r.name == "avg_delay_s")
        assert delay.verdict == "ok"

    def test_queue_regression(self):
        results = compare(_actual(max_queue_length=22), _baseline())  # +22%
        q = next(r for r in results if r.name == "max_queue_length")
        assert q.verdict == "regression"

    def test_throughput_regression(self):
        # 6% throughput drop — over 5% tolerance
        results = compare(_actual(throughput_vph=1034.0), _baseline())
        t = next(r for r in results if r.name == "throughput_vph")
        assert t.verdict == "regression"

    def test_throughput_improvement_is_ok(self):
        results = compare(_actual(throughput_vph=1200.0), _baseline())
        t = next(r for r in results if r.name == "throughput_vph")
        assert t.verdict == "ok"

    def test_any_conflict_is_regression(self):
        results = compare(_actual(conflicts=1), _baseline())
        c = next(r for r in results if r.name == "conflicts")
        assert c.verdict == "regression"

    def test_preempt_drift_is_info_not_regression(self):
        # Preempt counts can legitimately vary; > abs_tolerance flagged as info
        results = compare(_actual(preempt_events=5), _baseline())
        p = next(r for r in results if r.name == "preempt_events")
        assert p.verdict == "info"
        # And the run overall does not fail on info-only differences
        assert not any(r.verdict == "regression" for r in results)

    def test_baseline_can_be_flat_kpis_or_wrapped(self):
        flat = _baseline()["kpis"]  # no wrapper
        results = compare(_actual(), flat)
        assert all(r.verdict == "ok" for r in results)

    def test_zero_baseline_throughput_does_not_crash(self):
        b = _baseline()
        b["kpis"]["throughput_vph"] = 0.0
        results = compare(_actual(throughput_vph=0.0), b)
        t = next(r for r in results if r.name == "throughput_vph")
        assert t.verdict == "ok"
        assert t.delta_pct is None

    def test_custom_tolerance_in_baseline_overrides_default(self):
        b = _baseline()
        b["tolerances"]["delay_pct_tolerance"] = 0.50  # very loose
        # 40% delay increase, under 50% custom tolerance
        results = compare(_actual(avg_delay_s=30.8), b)
        delay = next(r for r in results if r.name == "avg_delay_s")
        assert delay.verdict == "ok"


class TestFormat:
    def test_markdown_contains_pass(self):
        out = format_markdown("rush-hour", compare(_actual(), _baseline()))
        assert "PASS" in out
        assert "rush-hour" in out
        assert "| `conflicts` |" in out

    def test_markdown_contains_fail(self):
        out = format_markdown("rush-hour", compare(_actual(conflicts=1), _baseline()))
        assert "FAIL" in out

    def test_text_format_includes_threshold_descriptions(self):
        out = format_text("rush-hour", compare(_actual(), _baseline()))
        assert "rule=" in out
        assert "conflicts == 0" in out


class TestMain:
    def test_passes_on_baseline_match(self, tmp_path: pathlib.Path):
        baseline_path = tmp_path / "rush-hour.json"
        baseline_path.write_text(json.dumps(_baseline()))
        kpis_path = tmp_path / "kpis.json"
        kpis_path.write_text(json.dumps(_actual()))
        rc = main(
            [
                "--scenario",
                "rush-hour",
                "--kpis",
                str(kpis_path),
                "--baseline",
                str(baseline_path),
            ]
        )
        assert rc == 0

    def test_fails_on_regression(self, tmp_path: pathlib.Path):
        baseline_path = tmp_path / "rush-hour.json"
        baseline_path.write_text(json.dumps(_baseline()))
        kpis_path = tmp_path / "kpis.json"
        kpis_path.write_text(json.dumps(_actual(conflicts=1)))
        rc = main(
            [
                "--scenario",
                "rush-hour",
                "--kpis",
                str(kpis_path),
                "--baseline",
                str(baseline_path),
            ]
        )
        assert rc == 1

    def test_missing_kpis_file_exits_2(self, tmp_path: pathlib.Path):
        baseline_path = tmp_path / "rush-hour.json"
        baseline_path.write_text(json.dumps(_baseline()))
        rc = main(
            [
                "--scenario",
                "rush-hour",
                "--kpis",
                str(tmp_path / "nope.json"),
                "--baseline",
                str(baseline_path),
            ]
        )
        assert rc == 2

    def test_missing_baseline_file_exits_2(self, tmp_path: pathlib.Path):
        kpis_path = tmp_path / "kpis.json"
        kpis_path.write_text(json.dumps(_actual()))
        rc = main(
            [
                "--scenario",
                "rush-hour",
                "--kpis",
                str(kpis_path),
                "--baseline",
                str(tmp_path / "nope.json"),
            ]
        )
        assert rc == 2

    def test_writes_out_file(self, tmp_path: pathlib.Path):
        baseline_path = tmp_path / "rush-hour.json"
        baseline_path.write_text(json.dumps(_baseline()))
        kpis_path = tmp_path / "kpis.json"
        kpis_path.write_text(json.dumps(_actual()))
        out_path = tmp_path / "diff.md"
        rc = main(
            [
                "--scenario",
                "rush-hour",
                "--kpis",
                str(kpis_path),
                "--baseline",
                str(baseline_path),
                "--format",
                "markdown",
                "--out",
                str(out_path),
            ]
        )
        assert rc == 0
        text = out_path.read_text()
        assert "PASS" in text
        assert "rush-hour" in text


@pytest.fixture(autouse=True)
def _no_implicit_cwd(monkeypatch, tmp_path: pathlib.Path):
    """Each main() call passes --baseline explicitly so cwd does not matter."""
    return monkeypatch
