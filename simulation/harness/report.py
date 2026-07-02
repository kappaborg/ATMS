"""
Self-contained HTML report renderer — Phase C3.

Inline CSS, no external assets. Inputs: a `SimulationKPIs` and an optional
baseline dict. Output: an HTML string the caller writes to disk.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import Any

from simulation.harness.kpis import (
    SimulationKPIs,
    diff_against_baseline,
)

_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       max-width: 1100px; margin: 2em auto; padding: 0 1em; color: #1f2937; }
h1, h2 { color: #111827; }
.subtitle { color: #6b7280; margin-top: -0.5em; }
table { border-collapse: collapse; width: 100%; margin-top: 1em; }
th, td { text-align: left; padding: 0.5em 0.75em; border-bottom: 1px solid #e5e7eb; }
th { background: #f9fafb; font-weight: 600; color: #374151; }
td.num { font-variant-numeric: tabular-nums; }
.delta-pos { color: #16a34a; }
.delta-neg { color: #dc2626; }
.delta-neutral { color: #6b7280; }
.kpi-card { display: inline-block; min-width: 180px; margin: 0.5em; padding: 1em;
            border: 1px solid #e5e7eb; border-radius: 8px; background: #ffffff;
            vertical-align: top; }
.kpi-card .label { color: #6b7280; font-size: 0.85em; text-transform: uppercase;
                   letter-spacing: 0.05em; }
.kpi-card .value { font-size: 1.6em; font-weight: 600; color: #111827; }
.violation { background: #fee2e2; color: #991b1b; padding: 0.75em; border-radius: 6px;
             font-weight: 600; }
.ok { background: #d1fae5; color: #065f46; padding: 0.75em; border-radius: 6px;
      font-weight: 600; }
.footer { color: #9ca3af; font-size: 0.85em; margin-top: 3em; }
"""


# ---------------------------------------------------------------------------
# KPIs that are "lower is better" — used to colour deltas correctly.
# ---------------------------------------------------------------------------

_LOWER_IS_BETTER = frozenset({"avg_delay_s", "max_queue_length", "conflicts"})


def _delta_class(name: str, delta: float) -> str:
    if delta == 0:
        return "delta-neutral"
    lower_better = name in _LOWER_IS_BETTER
    improved = (delta < 0) if lower_better else (delta > 0)
    return "delta-pos" if improved else "delta-neg"


def _format_value(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return html.escape(str(v))


def render_report(
    kpis: SimulationKPIs,
    *,
    baseline: dict[str, Any] | None = None,
    git_sha: str = "",
) -> str:
    """Render the simulation report as a stand-alone HTML document."""

    now = datetime.now(tz=UTC).isoformat()

    conflict_block = (
        '<div class="violation">⚠️ SAFETY VIOLATION: '
        f"{kpis.conflicts} conflicting-green ticks observed. Investigate before merging.</div>"
        if kpis.conflicts > 0
        else '<div class="ok">✓ Zero conflicting-green ticks. Safety invariant held.</div>'
    )

    cards = [
        ("avg_delay_s", "Avg delay (s)", kpis.avg_delay_s),
        ("max_queue_length", "Max queue (veh)", kpis.max_queue_length),
        ("throughput_vph", "Throughput (vph)", kpis.throughput_vph),
        ("conflicts", "Conflicts", kpis.conflicts),
        ("preempt_events", "Preempts", kpis.preempt_events),
        ("ped_calls_served", "Ped phases", kpis.ped_calls_served),
    ]
    cards_html = "".join(
        f'<div class="kpi-card"><div class="label">{html.escape(label)}</div>'
        f'<div class="value">{_format_value(value)}</div></div>'
        for _, label, value in cards
    )

    mode_rows = (
        "".join(
            f"<tr><td>{html.escape(mode)}</td><td class='num'>{_format_value(secs)}</td></tr>"
            for mode, secs in sorted(kpis.mode_dwell_s.items())
        )
        or "<tr><td colspan='2'>no mode data</td></tr>"
    )

    diff_html = ""
    if baseline is not None:
        diff = diff_against_baseline(kpis, baseline)
        if diff:
            rows = []
            for name, d in diff.items():
                pct = d["delta_pct"]
                pct_str = f" ({pct:+.1f}%)" if pct is not None else ""
                cls = _delta_class(name, d["delta"])
                rows.append(
                    f"<tr><td>{html.escape(name)}</td>"
                    f"<td class='num'>{_format_value(d['current'])}</td>"
                    f"<td class='num'>{_format_value(d['baseline'])}</td>"
                    f"<td class='num {cls}'>{_format_value(d['delta'])}{pct_str}</td></tr>"
                )
            diff_html = f"""
            <h2>Baseline diff</h2>
            <table>
              <thead><tr><th>KPI</th><th>Current</th><th>Baseline</th><th>Δ</th></tr></thead>
              <tbody>{"".join(rows)}</tbody>
            </table>"""

    sha_line = (
        f'<p class="subtitle">Git SHA: <code>{html.escape(git_sha)}</code></p>' if git_sha else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ATMS sim · {html.escape(kpis.scenario)}</title>
<style>{_CSS}</style>
</head>
<body>
  <h1>ATMS simulation · {html.escape(kpis.scenario)}</h1>
  <p class="subtitle">Generated {html.escape(now)}</p>
  {sha_line}

  {conflict_block}

  <h2>Key indicators</h2>
  <div>{cards_html}</div>

  <h2>Run metadata</h2>
  <table>
    <tr><td>Scenario</td><td>{html.escape(kpis.scenario)}</td></tr>
    <tr><td>Duration (s)</td><td class='num'>{_format_value(kpis.sim_duration_s)}</td></tr>
    <tr><td>Steps</td><td class='num'>{_format_value(kpis.sim_steps)}</td></tr>
  </table>

  <h2>Time in each mode</h2>
  <table>
    <thead><tr><th>Mode</th><th>Seconds</th></tr></thead>
    <tbody>{mode_rows}</tbody>
  </table>

  {diff_html}

  <div class="footer">
    Generated by simulation/harness/report.py — see docs/adr/0016-sumo-simulation-harness.md
  </div>
</body>
</html>
"""
