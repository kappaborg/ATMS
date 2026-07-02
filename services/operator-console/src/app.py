"""ATMS Operator Console (Streamlit).

Single-page real-time view that combines:
  - Current failsafe mode (huge color-coded tile)
  - Per-direction queue + emission + vehicle count
  - The AI's current commanded phase
  - Recent demo / fault / recovery events
  - A scrolling "audit log" feed

Polls `/tmp/atms-demo-state.json` (or `$DEMO_STATE_PATH`) at 2 Hz. That file
is written by `python -m simulation.demo` on every tick (see
`simulation/demo/state_emitter.py`). The two processes are decoupled — start
the demo and the console in either order; the console shows "waiting for
demo" until a state file appears.

Run:
    python -m pip install streamlit
    streamlit run services/operator-console/src/app.py
    # then in a second terminal:
    python -m simulation.demo --gui   (or --max-steps 3000 for a long run)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STATE_PATH = Path(os.getenv("DEMO_STATE_PATH", "/tmp/atms-demo-state.json"))
POLL_HZ = 2.0  # times per second
STALE_THRESHOLD_S = 5.0  # if the state file hasn't updated in this long, mark stale

MODE_COLORS = {
    "AI_ADAPTIVE": ("#0f9d58", "AI ADAPTIVE"),  # green
    "FIXED_TIME": ("#f4b400", "FIXED TIME (FAILSAFE)"),  # amber
    "ALL_RED_FLASH": ("#db4437", "ALL RED FLASH — STOPPED"),  # red
}
PHASE_DISPLAY = {
    "ns_green": "NS → GREEN",
    "ns_yellow": "NS → YELLOW",
    "ew_green": "EW → GREEN",
    "ew_yellow": "EW → YELLOW",
    "all_red": "ALL RED",
}
IMPACT_COLOR = {
    "zero": "#0f9d58",
    "low": "#0f9d58",
    "medium": "#f4b400",
    "high": "#ff6d00",
    "very_high": "#db4437",
}


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="ATMS Operator Console",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom CSS for the projection-ready big-font look.
st.markdown(
    """
    <style>
        .mode-tile {
            padding: 1.5rem;
            border-radius: 12px;
            text-align: center;
            color: white;
            font-size: 2.5rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            margin-bottom: 1rem;
        }
        .phase-tile {
            padding: 0.8rem;
            border-radius: 8px;
            background: #202124;
            color: white;
            text-align: center;
            font-size: 1.4rem;
            font-weight: 600;
        }
        .direction-card {
            padding: 1rem;
            border-radius: 8px;
            background: #f6f8fa;
            border: 1px solid #d0d7de;
        }
        .direction-card.green {
            border-left: 6px solid #0f9d58;
        }
        .direction-card.red {
            border-left: 6px solid #db4437;
        }
        .metric-big {
            font-size: 2rem;
            font-weight: 700;
            color: #202124;
        }
        .metric-label {
            font-size: 0.85rem;
            color: #5f6368;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .event-line {
            font-family: ui-monospace, "SFMono-Regular", Consolas, monospace;
            font-size: 0.9rem;
            padding: 0.3rem 0.5rem;
            border-bottom: 1px solid #e1e4e8;
        }
        .event-line.fault { color: #db4437; font-weight: 600; }
        .event-line.recover { color: #0f9d58; font-weight: 600; }
        .event-line.v2x { color: #1a73e8; }
        .event-line.ped { color: #8430ce; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# State polling
# ---------------------------------------------------------------------------


def _read_state() -> tuple[dict[str, Any] | None, float | None]:
    """Return (state_dict, age_seconds). (None, None) if the file is missing."""
    if not STATE_PATH.exists():
        return None, None
    try:
        text = STATE_PATH.read_text()
        state = json.loads(text)
        mtime = STATE_PATH.stat().st_mtime
        age = time.time() - mtime
        return state, age
    except (OSError, json.JSONDecodeError):
        return None, None


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

from locales import t as _t  # noqa: E402

# Read current locale from the last-known state file (chamber writes it
# every tick). Fallback: English on first render before any state arrives.
def _current_locale() -> str:
    try:
        import json as _json
        return _json.load(open(STATE_PATH)).get("operator_locale", "en")
    except Exception:
        return "en"


_locale = _current_locale()

st.title("🚦 " + _t(_locale, "console_title"))
st.caption(_t(_locale, "console_subtitle"))

# Classifier-in-use banner — read from the state file's
# `brand_classifier_model` field. Shown so the operator knows which model
# produced the brand labels in the per-direction cards below.
classifier_banner = st.empty()

# Top status bar
status_col1, status_col2, status_col3 = st.columns([3, 1, 1])
state_placeholder = status_col1.empty()
sim_time_placeholder = status_col2.empty()
phase_placeholder = status_col3.empty()

st.divider()

# Per-direction cards
dir_col1, dir_col2 = st.columns(2)
ns_card = dir_col1.empty()
ew_card = dir_col2.empty()

st.divider()

# AI Decision Chamber panel — the 6-layer reasoning trace, priority bars,
# and current commanded phase. See simulation/decision_chamber/ and the
# brand-perception dossier for the design rationale.
chamber_panel = st.empty()

# Phase 5 production-readiness surfacing — closed-loop NTCIP status,
# active TSP routes, multi-source detector coverage badges.
closed_loop_panel = st.empty()
tsp_panel = st.empty()
detector_health_panel = st.empty()

# Pedestrian + emergency controls. These write JSON files that the
# chamber's detectors poll. In production these would be REST endpoints
# to a real intersection controller; for the demo, file-based signalling
# is enough — the chamber sees the demand the same way.
st.subheader(_t(_locale, "operator_controls"))
op_col1, op_col2, op_col3 = st.columns(3)

with op_col1:
    st.markdown(f"**{_t(_locale, 'ped_request_label')}**")
    ped_dir = st.selectbox(
        _t(_locale, "ped_direction_label"),
        ["north_south", "east_west"],
        key="ped_dir",
    )
    if st.button(_t(_locale, "ped_request_button"), type="primary", use_container_width=True):
        import json as _json
        from datetime import datetime as _dt
        from datetime import timezone as _tz
        from datetime import timedelta as _td

        expires_iso = (
            _dt.now(_tz.utc) + _td(seconds=60)
        ).isoformat().replace("+00:00", "Z")
        Path("/tmp/atms-ped-button.json").write_text(
            _json.dumps(
                {
                    "direction": ped_dir,
                    "expires_at": expires_iso,
                    "notes": "operator-console button press",
                }
            )
        )
        st.success(_t(_locale, "ped_request_success", direction=ped_dir))

with op_col2:
    st.markdown(f"**{_t(_locale, 'emg_preempt_label')}**")
    emg_dir = st.selectbox(
        _t(_locale, "emg_direction_label"),
        ["north_south", "east_west"],
        key="emg_dir",
    )
    if st.button(_t(_locale, "emg_preempt_button"), type="primary", use_container_width=True):
        import json as _json
        from datetime import datetime as _dt
        from datetime import timezone as _tz
        from datetime import timedelta as _td

        expires_iso = (
            _dt.now(_tz.utc) + _td(seconds=45)
        ).isoformat().replace("+00:00", "Z")
        Path("/tmp/atms-operator-override.json").write_text(
            _json.dumps(
                {
                    "direction": emg_dir,
                    "expires_at": expires_iso,
                    "notes": "operator-console emergency preempt",
                }
            )
        )
        st.warning(_t(_locale, "emg_preempt_warning", direction=emg_dir))

with op_col3:
    st.markdown(f"**{_t(_locale, 'clear_overrides_label')}**")
    st.caption(_t(_locale, "clear_overrides_caption"))
    if st.button(_t(_locale, "clear_overrides_button"), use_container_width=True):
        for p in ("/tmp/atms-ped-button.json", "/tmp/atms-operator-override.json"):
            Path(p).unlink(missing_ok=True)
        st.info(_t(_locale, "clear_overrides_info"))

st.divider()

# Aggregate emissions tile + recent events feed
agg_col, evt_col = st.columns([1, 2])
co2_tile = agg_col.empty()
events_panel = evt_col.empty()


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _mode_tile_html(mode: str) -> str:
    color, label = MODE_COLORS.get(mode, ("#5f6368", mode))
    return f'<div class="mode-tile" style="background:{color}">{label}</div>'


def _confidence_color(conf: float) -> str:
    """Confidence colour: green high, amber mid, gray low."""
    if conf >= 0.9:
        return "#0f9d58"  # green — high confidence
    if conf >= 0.7:
        return "#f4b400"  # amber — medium
    return "#9aa0a6"  # gray — low / unreliable


def _closed_loop_panel_html(decision: dict[str, Any]) -> str:
    """Closed-loop NTCIP status: chamber commanded phase vs controller
    actual phase. Production-critical — if these diverge for >3 ticks,
    operator needs to know NOW.
    """
    if not decision:
        return ""
    cl = decision.get("closed_loop", {})
    actual = cl.get("actual_active_directions") or []
    in_sync = cl.get("in_sync")
    divergence = cl.get("divergence_ticks", 0)
    commanded = decision.get("commanded_phase", "—").replace("_green", "")

    if in_sync is None:
        status_label = "no read-back"
        status_color = "#9aa0a6"
    elif in_sync:
        status_label = "in sync ✓"
        status_color = "#0f9d58"
    else:
        status_label = f"DIVERGE ({divergence} ticks)"
        status_color = "#db4437"

    return (
        f'<div style="background:#f6f8fa;border-left:4px solid {status_color};'
        f'padding:0.6rem 0.8rem;font-size:0.85rem;margin-bottom:0.5rem">'
        f'<div style="color:#5f6368;text-transform:uppercase;letter-spacing:0.06em;'
        f'font-size:0.7rem">Closed-loop NTCIP</div>'
        f'<div style="display:flex;gap:1.2rem;align-items:baseline;margin-top:0.2rem">'
        f'<div><strong>Commanded:</strong> <code>{commanded}</code></div>'
        f'<div><strong>Actual:</strong> <code>{",".join(actual) or "—"}</code></div>'
        f'<div style="color:{status_color};font-weight:600">{status_label}</div>'
        f"</div></div>"
    )


def _tsp_panel_html(decision: dict[str, Any]) -> str:
    """Transit Signal Priority — which routes are requesting priority
    right now and on which approach.
    """
    if not decision:
        return ""
    tsp = decision.get("transit_priority", {})
    routes_by_dir = tsp.get("active_routes_by_direction", {})
    if not routes_by_dir:
        return (
            '<div style="background:#f6f8fa;padding:0.6rem 0.8rem;'
            'font-size:0.85rem;color:#5f6368;margin-bottom:0.5rem">'
            'TSP: <em>no late buses active</em></div>'
        )
    rows = [
        '<div style="background:#f6f8fa;border-left:4px solid #4285f4;'
        'padding:0.6rem 0.8rem;font-size:0.85rem;margin-bottom:0.5rem">'
        '<div style="color:#5f6368;text-transform:uppercase;letter-spacing:0.06em;'
        'font-size:0.7rem">Transit Signal Priority — active</div>',
    ]
    for direction, routes in sorted(routes_by_dir.items()):
        route_chips = " ".join(
            f'<span style="background:#e8f0fe;color:#1967d2;padding:0.1rem 0.4rem;'
            f'border-radius:4px;font-family:monospace;font-size:0.75rem">{r}</span>'
            for r in routes
        )
        rows.append(
            f'<div style="margin-top:0.3rem">'
            f'<strong>{direction}</strong>: {route_chips}</div>'
        )
    rows.append("</div>")
    return "".join(rows)


def _detector_health_html(decision: dict[str, Any]) -> str:
    """Coverage badge row — shows which sensor/protocol sources are
    active. Lets the operator verify multi-source coverage at a glance
    instead of trusting that the architecture is doing what it claims.
    """
    if not decision:
        return ""
    health = decision.get("detector_health", {})
    if not health:
        return ""
    emerg = health.get("emergency_sources_active", [])
    peds = health.get("pedestrian_sources_active", [])
    tsp_on = health.get("tsp_enabled", False)
    mesh_on = health.get("mesh_connected", False)
    audit_type = health.get("audit_type", "?")
    bridge_type = health.get("bridge_type", "?")

    def chip(label, on=True):
        color = "#0f9d58" if on else "#9aa0a6"
        bg = "#e6f4ea" if on else "#f1f3f4"
        return (
            f'<span style="background:{bg};color:{color};border:1px solid {color};'
            f'padding:0.15rem 0.5rem;border-radius:12px;font-size:0.72rem;'
            f'font-family:monospace;margin-right:0.3rem">{label}</span>'
        )

    chips = (
        [chip(f"L1: {d}") for d in emerg]
        + [chip(f"L2/L3: {d}") for d in peds]
        + [chip("L3: gtfs-rt", on=tsp_on)]
        + [chip("L4: mqtt-mesh", on=mesh_on)]
        + [chip(f"L5: {bridge_type}")]
        + [chip(f"audit: {audit_type}")]
    )
    return (
        '<div style="background:#f6f8fa;padding:0.6rem 0.8rem;margin-bottom:0.5rem">'
        '<div style="color:#5f6368;text-transform:uppercase;letter-spacing:0.06em;'
        'font-size:0.7rem;margin-bottom:0.3rem">Detector + protocol coverage</div>'
        + "".join(chips)
        + "</div>"
    )


def _chamber_panel_html(decision: dict[str, Any]) -> str:
    """Render the AI Decision Chamber panel. Shows current phase, mode,
    per-layer reasoning trace, priority bars, and the dominant factor —
    every piece of information the operator needs to understand why the
    chamber decided what it decided.
    """
    if not decision:
        return (
            "<div style='padding:0.8rem;color:#5f6368;font-style:italic'>"
            "Decision chamber not active yet — waiting for first tick."
            "</div>"
        )

    mode = decision.get("mode", "adaptive")
    mode_color = {
        "adaptive": "#0f9d58",
        "preempt": "#db4437",
        "fixed_time": "#f4b400",
        "manual": "#4285f4",
        "flash_caution": "#db4437",
    }.get(mode, "#5f6368")
    commanded = decision.get("commanded_phase", "—")
    next_review = decision.get("seconds_until_next_review", 0)
    reasoning = decision.get("reasoning", "")
    dominant = decision.get("dominant_factor", "—")

    # Header
    rows = [
        f'<div style="background:#202124;color:white;padding:1rem;border-radius:8px">',
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.6rem">',
        '<div style="font-size:0.8rem;color:#9aa0a6;text-transform:uppercase;letter-spacing:0.06em">'
        "AI Decision Chamber</div>",
        f'<div style="background:{mode_color};color:white;padding:0.2rem 0.6rem;'
        f'border-radius:12px;font-size:0.7rem;text-transform:uppercase">{mode}</div>',
        "</div>",
        f'<div style="font-size:1.4rem;font-weight:700">🟢 {commanded}</div>',
        f'<div style="color:#9aa0a6;font-size:0.85rem;margin-top:0.2rem">'
        f"Next review in {next_review:.0f}s &middot; Dominant: <strong>{dominant}</strong></div>",
    ]

    # Reasoning
    if reasoning:
        rows.append(
            f'<div style="margin-top:0.6rem;padding:0.5rem;background:#3c4043;'
            f'border-radius:4px;font-size:0.85rem;color:#e8eaed">'
            f"<em>{reasoning}</em></div>"
        )

    # Priority bars
    scores = decision.get("priority_scores", {})
    if scores:
        rows.append('<div style="margin-top:0.8rem">')
        rows.append(
            '<div style="font-size:0.75rem;color:#9aa0a6;text-transform:uppercase;'
            'letter-spacing:0.06em;margin-bottom:0.4rem">Priority scores</div>'
        )
        max_score = max(scores.values()) if scores else 1.0
        for direction, score in sorted(scores.items(), key=lambda kv: -kv[1]):
            width_pct = int(score / max_score * 100) if max_score > 0 else 0
            winner = direction == commanded.replace("_green", "")
            bar_color = "#0f9d58" if winner else "#5f6368"
            label = f"{direction} {score:.2f}" + ("  ← winner" if winner else "")
            rows.append(
                f'<div style="margin-bottom:0.3rem">'
                f'<div style="background:#3c4043;border-radius:4px;height:18px;'
                f'position:relative;overflow:hidden">'
                f'<div style="background:{bar_color};width:{width_pct}%;height:100%"></div>'
                f'<div style="position:absolute;top:0;left:8px;line-height:18px;'
                f'font-size:0.75rem;color:white">{label}</div>'
                f"</div></div>"
            )
        rows.append("</div>")

    # Rule chain — collapsible-ish (always shown in MVP)
    rule_chain = decision.get("rule_chain", [])
    if rule_chain:
        rows.append('<div style="margin-top:0.8rem">')
        rows.append(
            '<div style="font-size:0.75rem;color:#9aa0a6;text-transform:uppercase;'
            'letter-spacing:0.06em;margin-bottom:0.4rem">Reasoning trace</div>'
        )
        for step in rule_chain:
            result = step.get("result", "")
            icon = {
                "passed": "✓",
                "preempted": "⚠",
                "blocked": "⛔",
                "held": "⏸",
                "switched": "→",
                "skipped": "·",
            }.get(result, "·")
            color = {
                "passed": "#0f9d58",
                "preempted": "#db4437",
                "blocked": "#f4b400",
                "held": "#9aa0a6",
                "switched": "#4285f4",
                "skipped": "#5f6368",
            }.get(result, "#9aa0a6")
            layer = step.get("layer", "")
            notes = step.get("notes", "")
            rows.append(
                f'<div style="font-size:0.78rem;margin-bottom:0.15rem;color:#e8eaed">'
                f'<span style="color:{color};margin-right:0.4rem">{icon}</span>'
                f'<strong style="color:#9aa0a6">{layer}</strong>  {notes}</div>'
            )
        rows.append("</div>")

    rows.append("</div>")
    return "".join(rows)


def _brand_mix_html(info: dict[str, Any]) -> str:
    """Per-brand table: count + average confidence + colour-coded bar."""
    breakdown = info.get("brand_breakdown", {})
    confidences = info.get("brand_confidence_by_brand", {})
    identified = info.get("brand_identified_count", 0)
    total = info.get("vehicle_count", 0)
    if not breakdown:
        return (
            "<div style='color:#5f6368;font-style:italic;font-size:0.85rem;"
            f"padding-top:0.5rem'>No brands identified ({identified}/{total})</div>"
        )
    rows = [
        f"<div style='font-size:0.85rem;color:#5f6368;padding-top:0.6rem;"
        f"text-transform:uppercase;letter-spacing:0.05em'>"
        f"Brand mix ({identified}/{total} identified)</div>"
        "<table style='width:100%;border-collapse:collapse;font-size:0.9rem'>"
    ]
    # Sort by count desc, then confidence desc
    sorted_brands = sorted(
        breakdown.items(),
        key=lambda kv: (-kv[1], -confidences.get(kv[0], 0)),
    )
    for brand, count in sorted_brands:
        conf = confidences.get(brand, 0.0)
        color = _confidence_color(conf)
        rows.append(
            "<tr style='border-bottom:1px solid #e1e4e8'>"
            f"<td style='padding:0.3rem 0.4rem;font-weight:600'>{brand}</td>"
            f"<td style='padding:0.3rem 0.4rem;text-align:right'>{count}</td>"
            f"<td style='padding:0.3rem 0.4rem;text-align:right'>"
            f"<span style='background:{color};color:white;padding:0.1rem 0.5rem;"
            f"border-radius:3px;font-size:0.75rem'>{conf:.2f}</span>"
            "</td></tr>"
        )
    rows.append("</table>")
    return "".join(rows)


def _direction_card_html(direction: str, info: dict[str, Any], is_green: bool) -> str:
    css_class = "direction-card " + ("green" if is_green else "red")
    emissions = info.get("emissions", {})
    emissions_baseline = info.get("emissions_baseline", emissions)
    avg_co2 = emissions.get("average_emission_g_per_km", 0)
    avg_co2_baseline = emissions_baseline.get("average_emission_g_per_km", avg_co2)
    co2_per_min = emissions.get("instantaneous_co2_g_per_min", 0)
    co2_per_min_baseline = emissions_baseline.get("instantaneous_co2_g_per_min", co2_per_min)
    vcount = info.get("vehicle_count", 0)
    avg_v = info.get("average_velocity", 0)
    impact = "low"
    if avg_co2 >= 200:
        impact = "very_high"
    elif avg_co2 >= 150:
        impact = "high"
    elif avg_co2 >= 100:
        impact = "medium"
    impact_color = IMPACT_COLOR.get(impact, "#5f6368")
    # Delta vs baseline tells the operator how much the brand multiplier is
    # affecting the headline number — quantifies the brand model's influence.
    delta_g_per_km = avg_co2 - avg_co2_baseline
    delta_label = ""
    if abs(delta_g_per_km) >= 1:
        sign = "+" if delta_g_per_km > 0 else "-"
        delta_label = (
            f"<span style='font-size:0.85rem;color:#5f6368'> "
            f"({sign}{abs(delta_g_per_km):.0f} vs baseline)</span>"
        )
    return (
        f'<div class="{css_class}">'
        f'<h3 style="margin-top:0;">{direction.replace("_", " ").title()} '
        f"{'🟢 GREEN' if is_green else '🔴 RED'}</h3>"
        f'<table style="width:100%;border-collapse:collapse">'
        f'<tr><td><span class="metric-label">Vehicles</span>'
        f'<div class="metric-big">{vcount}</div></td>'
        f'<td><span class="metric-label">Avg speed (km/h)</span>'
        f'<div class="metric-big">{avg_v:.0f}</div></td></tr>'
        f'<tr><td colspan="2" style="padding-top:0.6rem">'
        f'<span class="metric-label">Avg emission (g CO₂ / km){delta_label}</span>'
        f'<div class="metric-big" style="color:{impact_color}">{avg_co2:.0f} '
        f'<span style="font-size:1rem;color:#5f6368">(baseline {avg_co2_baseline:.0f})</span>'
        f"</div></td></tr>"
        f'<tr><td colspan="2">'
        f'<span class="metric-label">Instantaneous CO₂ rate (g/min)</span>'
        f'<div class="metric-big" style="color:{impact_color}">{co2_per_min:.0f} '
        f'<span style="font-size:1rem;color:#5f6368">(baseline {co2_per_min_baseline:.0f})</span>'
        f"</div></td></tr>"
        f"</table>"
        f"{_brand_mix_html(info)}"
        f"</div>"
    )


def _event_line_html(evt: dict[str, Any]) -> str:
    kind = evt.get("kind", "cue")
    css = {"force_mode": "fault", "recover": "recover", "v2x_inject": "v2x", "ped_call": "ped"}.get(
        kind, ""
    )
    ts = evt.get("sim_time_s", 0)
    msg = evt.get("message", "")
    return f'<div class="event-line {css}">[ t={ts:>6.1f}s ] {msg}</div>'


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------

while True:
    state, age = _read_state()

    if state is None:
        state_placeholder.markdown(_mode_tile_html("WAITING"), unsafe_allow_html=True)
        sim_time_placeholder.metric("Sim time", "—")
        phase_placeholder.metric("Phase", "—")
        classifier_banner.empty()
        ns_card.info(
            "Waiting for demo state. Start it with:\n\n```\npython -m simulation.demo\n```"
        )
        ew_card.empty()
        co2_tile.empty()
        events_panel.empty()
    else:
        mode = state.get("mode", "UNKNOWN")
        sim_time = state.get("sim_time_s", 0)
        phase = state.get("commanded_phase", "?")
        per_dir = state.get("per_direction", {})

        # State tile + stale indicator
        if age is not None and age > STALE_THRESHOLD_S:
            stale_warning = (
                f'<div style="color:#5f6368;font-style:italic">'
                f"Last update: {age:.1f}s ago (demo may have ended)"
                f"</div>"
            )
            state_placeholder.markdown(
                _mode_tile_html(mode) + stale_warning, unsafe_allow_html=True
            )
        else:
            state_placeholder.markdown(_mode_tile_html(mode), unsafe_allow_html=True)

        sim_time_placeholder.metric("Sim time", f"{sim_time:.0f}s")
        phase_placeholder.markdown(
            f'<div class="phase-tile">{PHASE_DISPLAY.get(phase, phase)}</div>',
            unsafe_allow_html=True,
        )

        # Classifier banner — which brand model is producing labels?
        clf = state.get("brand_classifier_model")
        if clf:
            clf_enabled = state.get("brand_classifier_enabled", True)
            badge_color = "#0f9d58" if clf_enabled else "#5f6368"
            clf_label = clf if clf_enabled else f"{clf} (unavailable)"
            classifier_banner.markdown(
                f'<div style="background:#f6f8fa;border-left:4px solid {badge_color};'
                f'padding:0.4rem 0.8rem;font-size:0.9rem;margin-bottom:0.6rem">'
                f'<span style="color:#5f6368;text-transform:uppercase;'
                f'letter-spacing:0.05em;font-size:0.75rem">Brand classifier</span> '
                f"<strong>{clf_label}</strong>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            classifier_banner.empty()

        # Per-direction.
        # The decision chamber now emits "north_south_green" / "east_west_green"
        # phase strings; legacy SUMO orchestrator used "ns_green" / "ew_green".
        # We support both so the operator console still works for either source.
        ns_info = per_dir.get("north_south", {})
        ew_info = per_dir.get("east_west", {})
        ns_green = phase in ("ns_green", "ns_yellow", "north_south_green")
        ew_green = phase in ("ew_green", "ew_yellow", "east_west_green")
        ns_card.markdown(
            _direction_card_html("north_south", ns_info, is_green=ns_green),
            unsafe_allow_html=True,
        )
        ew_card.markdown(
            _direction_card_html("east_west", ew_info, is_green=ew_green),
            unsafe_allow_html=True,
        )

        # AI Decision Chamber panel — shows the chamber's reasoning + priority
        # scores + rule chain so the operator can see WHY the current phase
        # is what it is. Empty if the source isn't running the chamber (e.g.,
        # an older SUMO orchestrator state file).
        decision = state.get("decision")
        chamber_panel.markdown(
            _chamber_panel_html(decision or {}), unsafe_allow_html=True
        )
        closed_loop_panel.markdown(
            _closed_loop_panel_html(decision or {}), unsafe_allow_html=True
        )
        tsp_panel.markdown(_tsp_panel_html(decision or {}), unsafe_allow_html=True)
        detector_health_panel.markdown(
            _detector_health_html(decision or {}), unsafe_allow_html=True
        )

        # Aggregate CO2
        total_co2_per_min = sum(
            d.get("emissions", {}).get("instantaneous_co2_g_per_min", 0) for d in per_dir.values()
        )
        co2_tile.markdown(
            f'<div style="padding:1rem;background:#202124;color:white;border-radius:8px;text-align:center">'
            f'<div class="metric-label" style="color:#9aa0a6">Total intersection CO₂ rate</div>'
            f'<div style="font-size:3rem;font-weight:700;color:white">{total_co2_per_min:.0f}</div>'
            f'<div style="color:#9aa0a6">g / min</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

        # Events
        events = state.get("recent_events", [])
        if events:
            events_panel.markdown(
                "<h4 style='margin-top:0'>Recent events</h4>"
                + "".join(_event_line_html(e) for e in reversed(events[-10:])),
                unsafe_allow_html=True,
            )
        else:
            events_panel.info(
                "No events yet. The demo timeline starts firing cues from sim-time 15s."
            )

    time.sleep(1.0 / POLL_HZ)
    # Streamlit needs an explicit rerun trigger when in a long-running loop.
    # Using st.experimental_rerun is the documented pattern; in newer Streamlit
    # versions the loop above just keeps updating placeholders, which is fine.
    # If you see "stuck" behaviour on older Streamlit, uncomment:
    # st.experimental_rerun()
