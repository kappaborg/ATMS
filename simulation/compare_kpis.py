#!/usr/bin/env python3
"""
Compare a simulation KPI run against a stored baseline (Phase C3 follow-up).

Used by the CI sim-regression workflow: a PR's SUMO run produces
`simulation/out/<scenario>/kpis.json`; this script diffs it against
`simulation/baselines/<scenario>.json` and exits non-zero on regression.

A regression is defined per-metric:

    avg_delay_s         > baseline * (1 + delay_pct_tolerance)
    max_queue_length    > baseline * (1 + queue_pct_tolerance)
    throughput_vph      < baseline * (1 - throughput_pct_tolerance)
    conflicts           > 0 (any conflict is a regression — hard gate)
    preempt_events      |delta| > preempt_abs_tolerance  (informational only)
    ped_calls_served    |delta| > ped_abs_tolerance      (informational only)

Tolerances are scenario-specific and live in
`simulation/baselines/<scenario>.json` under a `tolerances` block. Defaults
are conservative — they fail on a 10% delay increase, a 10% queue increase,
or a 5% throughput drop. Any non-zero `conflicts` is fatal regardless.

Usage:

    python -m simulation.compare_kpis \\
        --scenario rush-hour \\
        --kpis simulation/out/rush-hour/kpis.json \\
        [--baseline simulation/baselines/rush-hour.json] \\
        [--format text|markdown|github] \\
        [--out diff.md]

Exit codes:
    0 — within tolerances
    1 — regression detected
    2 — missing/malformed input
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass

_DEFAULT_TOLERANCES = {
    "delay_pct_tolerance": 0.10,
    "queue_pct_tolerance": 0.10,
    "throughput_pct_tolerance": 0.05,
    "preempt_abs_tolerance": 1,
    "ped_abs_tolerance": 1,
}


@dataclass(frozen=True)
class MetricResult:
    name: str
    baseline: float
    actual: float
    delta_abs: float
    delta_pct: float | None  # None when baseline is 0
    verdict: str  # "ok" | "regression" | "info"
    threshold: str  # human-readable threshold description


def _pct(actual: float, baseline: float) -> float | None:
    if baseline == 0:
        return None
    return (actual - baseline) / baseline


def _grade_higher_is_worse(
    name: str,
    actual: float,
    baseline: float,
    pct_tol: float,
) -> MetricResult:
    delta = actual - baseline
    pct = _pct(actual, baseline)
    threshold = f"{name} ≤ baseline x{1 + pct_tol:.2f}"
    if pct is None:
        verdict = "regression" if actual > 0 else "ok"
    else:
        verdict = "regression" if pct > pct_tol else "ok"
    return MetricResult(name, baseline, actual, delta, pct, verdict, threshold)


def _grade_lower_is_worse(
    name: str,
    actual: float,
    baseline: float,
    pct_tol: float,
) -> MetricResult:
    delta = actual - baseline
    pct = _pct(actual, baseline)
    threshold = f"{name} ≥ baseline x{1 - pct_tol:.2f}"
    if pct is None:
        verdict = "regression" if actual < 0 else "ok"
    else:
        verdict = "regression" if pct < -pct_tol else "ok"
    return MetricResult(name, baseline, actual, delta, pct, verdict, threshold)


def _grade_hard_zero(name: str, actual: float) -> MetricResult:
    return MetricResult(
        name=name,
        baseline=0.0,
        actual=actual,
        delta_abs=actual,
        delta_pct=None,
        verdict="regression" if actual > 0 else "ok",
        threshold=f"{name} == 0",
    )


def _grade_info(name: str, actual: float, baseline: float, abs_tol: float) -> MetricResult:
    delta = actual - baseline
    return MetricResult(
        name=name,
        baseline=baseline,
        actual=actual,
        delta_abs=delta,
        delta_pct=_pct(actual, baseline),
        verdict="info" if abs(delta) > abs_tol else "ok",
        threshold=f"|Δ {name}| ≤ {abs_tol}",
    )


def compare(actual: dict, baseline: dict) -> list[MetricResult]:
    tol = {**_DEFAULT_TOLERANCES, **baseline.get("tolerances", {})}
    base_kpis = baseline.get("kpis", baseline)  # accept either shape

    return [
        _grade_hard_zero("conflicts", float(actual["conflicts"])),
        _grade_higher_is_worse(
            "avg_delay_s",
            float(actual["avg_delay_s"]),
            float(base_kpis["avg_delay_s"]),
            tol["delay_pct_tolerance"],
        ),
        _grade_higher_is_worse(
            "max_queue_length",
            float(actual["max_queue_length"]),
            float(base_kpis["max_queue_length"]),
            tol["queue_pct_tolerance"],
        ),
        _grade_lower_is_worse(
            "throughput_vph",
            float(actual["throughput_vph"]),
            float(base_kpis["throughput_vph"]),
            tol["throughput_pct_tolerance"],
        ),
        _grade_info(
            "preempt_events",
            float(actual["preempt_events"]),
            float(base_kpis.get("preempt_events", 0)),
            tol["preempt_abs_tolerance"],
        ),
        _grade_info(
            "ped_calls_served",
            float(actual["ped_calls_served"]),
            float(base_kpis.get("ped_calls_served", 0)),
            tol["ped_abs_tolerance"],
        ),
    ]


def format_markdown(scenario: str, results: list[MetricResult]) -> str:
    verdicts = {r.verdict for r in results}
    overall = "FAIL" if "regression" in verdicts else "PASS"
    title = f"## SUMO sim-regression — `{scenario}` — **{overall}**\n\n"
    header = (
        "| Metric | Baseline | Actual | Δ | Δ% | Verdict |\n"
        "|--------|---------:|-------:|---:|---:|:-------:|\n"
    )
    rows = []
    for r in results:
        delta_pct = "" if r.delta_pct is None else f"{r.delta_pct * 100:+.1f}%"
        emoji = {"ok": "✓", "regression": "✗", "info": "ⓘ"}[r.verdict]
        rows.append(
            f"| `{r.name}` | {r.baseline:g} | {r.actual:g} | {r.delta_abs:+g} | {delta_pct} | {emoji} |"
        )
    legend = "\n\n_Legend: ✓ within tolerance · ✗ regression · ⓘ informational drift_"
    return title + header + "\n".join(rows) + legend


def format_text(scenario: str, results: list[MetricResult]) -> str:
    verdicts = {r.verdict for r in results}
    overall = "FAIL" if "regression" in verdicts else "PASS"
    lines = [f"SUMO sim-regression — {scenario} — {overall}", ""]
    for r in results:
        delta_pct = "n/a" if r.delta_pct is None else f"{r.delta_pct * 100:+.1f}%"
        lines.append(
            f"  [{r.verdict.upper():>10}] {r.name:<20} "
            f"baseline={r.baseline:g}  actual={r.actual:g}  "
            f"Δ={r.delta_abs:+g} ({delta_pct})  rule={r.threshold}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simulation.compare_kpis")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--kpis", required=True, help="path to the run's kpis.json")
    parser.add_argument(
        "--baseline",
        default=None,
        help="path to baseline JSON (defaults to simulation/baselines/<scenario>.json)",
    )
    parser.add_argument("--format", choices=("text", "markdown"), default="text")
    parser.add_argument("--out", default=None, help="write formatted output to this path too")
    args = parser.parse_args(argv)

    kpis_path = pathlib.Path(args.kpis)
    if not kpis_path.exists():
        print(f"✗ KPI file not found: {kpis_path}", file=sys.stderr)
        return 2
    try:
        actual = json.loads(kpis_path.read_text())
    except json.JSONDecodeError as e:
        print(f"✗ KPI file is not valid JSON ({kpis_path}): {e}", file=sys.stderr)
        return 2

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    baseline_path = pathlib.Path(
        args.baseline or repo_root / "simulation" / "baselines" / f"{args.scenario}.json"
    )
    if not baseline_path.exists():
        print(
            f"✗ baseline not found: {baseline_path}. "
            "Create one with: python -m simulation.compare_kpis_capture_baseline "
            "or copy the run's kpis.json into the baselines dir.",
            file=sys.stderr,
        )
        return 2
    try:
        baseline = json.loads(baseline_path.read_text())
    except json.JSONDecodeError as e:
        print(f"✗ baseline JSON malformed ({baseline_path}): {e}", file=sys.stderr)
        return 2

    results = compare(actual, baseline)
    formatted = (
        format_markdown(args.scenario, results)
        if args.format == "markdown"
        else format_text(args.scenario, results)
    )
    print(formatted)
    if args.out:
        pathlib.Path(args.out).write_text(formatted + "\n")

    return 1 if any(r.verdict == "regression" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
