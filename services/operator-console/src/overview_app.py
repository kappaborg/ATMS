"""Multi-intersection corridor overview — Streamlit page.

Production deployment scenario: Sarajevo arterial corridor (Marijin
Dvor → Hiseta → Pofalići → Skenderija). Each intersection runs its
own chamber + console. KS operations centre needs ONE screen showing
all four intersections side-by-side so the on-duty operator can spot
corridor-wide issues at a glance.

This Streamlit page subscribes to MQTT state topics from configured
intersections and renders a grid of mini-cards, each showing:
- Current commanded phase + mode
- Largest queue direction
- Closed-loop divergence indicator
- Recent ped + emergency events count
- Click-to-drilldown to that intersection's single-intersection console

Source of truth: MQTT broker publishing per-intersection state. The
chamber's mesh.publish_state() in Phase 3 emits `atms/intersection/
<id>/state` exactly what this page consumes. Falls back to reading
local state JSON files when MQTT isn't reachable (dev pattern).

Run:
    streamlit run services/operator-console/src/overview_app.py
    # Configure broker via env:
    #   ATMS_OVERVIEW_BROKER=mqtt.atms.city
    #   ATMS_OVERVIEW_INTERSECTIONS=sarajevo-001,sarajevo-002,sarajevo-003,sarajevo-004
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

log = logging.getLogger("atms.console.overview")

# Config via env (dev override below in the UI)
BROKER_HOST = os.getenv("ATMS_OVERVIEW_BROKER", "")
INTERSECTIONS = [
    s.strip()
    for s in os.getenv("ATMS_OVERVIEW_INTERSECTIONS",
                        "sarajevo-marijindvor-001").split(",")
    if s.strip()
]


# -----------------------------------------------------------------
# State sources — MQTT (production) and file (dev)
# -----------------------------------------------------------------


class MultiIntersectionState:
    """Thread-safe per-intersection state cache.

    Two backends:
    - `MqttBackend`: subscribes to `atms/intersection/+/state`, updates
      on every published message
    - `FileBackend`: polls /tmp/atms-demo-state*.json per intersection
      (dev fallback when no broker)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._states: dict[str, dict] = {}
        self._last_seen: dict[str, float] = {}

    def update(self, intersection_id: str, payload: dict) -> None:
        with self._lock:
            self._states[intersection_id] = payload
            self._last_seen[intersection_id] = time.monotonic()

    def get(self, intersection_id: str) -> tuple[dict | None, float]:
        with self._lock:
            state = self._states.get(intersection_id)
            seen = self._last_seen.get(intersection_id)
            age = (time.monotonic() - seen) if seen is not None else 999.0
            return (state, age)


@st.cache_resource(show_spinner=False)
def get_multi_state() -> MultiIntersectionState:
    return MultiIntersectionState()


@st.cache_resource(show_spinner=False)
def mqtt_subscriber(broker_host: str, intersections: tuple[str, ...]) -> bool:
    """One-time MQTT setup. Returns True if connected, False if not
    available. Streamlit's cache means we don't double-subscribe.
    """
    if not broker_host:
        return False
    try:
        import paho.mqtt.client as mqtt  # noqa: PLC0415
    except ImportError:
        log.warning("paho-mqtt missing; falling back to file polling")
        return False

    state = get_multi_state()

    def on_message(_client, _userdata, msg):
        parts = msg.topic.split("/")
        # Topic shape: atms/intersection/<id>/state
        if len(parts) >= 4 and parts[0] == "atms" and parts[1] == "intersection":
            iid = parts[2]
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
                state.update(iid, payload)
            except Exception as e:
                log.warning("bad MQTT payload for %s: %s", iid, e)

    client = mqtt.Client(client_id=f"overview-console-{os.getpid()}")
    client.on_message = on_message
    try:
        client.connect(broker_host, 1883, keepalive=30)
        for iid in intersections:
            client.subscribe(f"atms/intersection/{iid}/state", qos=0)
        client.loop_start()
        log.info("overview console connected to %s subscribing %d intersections",
                 broker_host, len(intersections))
        return True
    except Exception as e:
        log.warning("MQTT connect failed: %s — falling back to file polling", e)
        return False


def poll_local_files(intersections: list[str]) -> None:
    """Dev fallback when no MQTT broker: read per-intersection JSON files.
    Convention: `/tmp/atms-demo-state-<id>.json` (multi-process demos
    write their state here).
    """
    state_cache = get_multi_state()
    for iid in intersections:
        path = Path(f"/tmp/atms-demo-state-{iid}.json")
        if not path.exists():
            # Fallback to the single-intersection default file
            path = Path("/tmp/atms-demo-state.json")
        if path.exists():
            try:
                payload = json.loads(path.read_text())
                state_cache.update(iid, payload)
            except Exception:
                pass


# -----------------------------------------------------------------
# UI
# -----------------------------------------------------------------


def render_intersection_card(intersection_id: str, state: dict | None, age_s: float):
    decision = (state or {}).get("decision") or {}
    per_dir = (state or {}).get("per_direction") or {}

    mode = decision.get("mode", "unknown")
    phase = decision.get("commanded_phase", "—").replace("_green", "")
    dominant = decision.get("dominant_factor", "—")

    closed_loop = decision.get("closed_loop") or {}
    in_sync = closed_loop.get("in_sync")
    divergence = closed_loop.get("divergence_ticks", 0)

    health = decision.get("detector_health") or {}
    mesh_on = health.get("mesh_connected", False)

    queue_max = 0
    queue_dir = "—"
    for d, info in per_dir.items():
        if info.get("vehicle_count", 0) > queue_max:
            queue_max = info["vehicle_count"]
            queue_dir = d

    # Status colours
    mode_colors = {
        "adaptive": "#0f9d58",
        "preempt": "#db4437",
        "fixed_time": "#f4b400",
        "manual": "#4285f4",
        "flash_caution": "#db4437",
    }
    border = mode_colors.get(mode, "#9aa0a6")

    # Stale check (>5 s = greyed out)
    stale = age_s > 5.0
    if stale:
        border = "#9aa0a6"

    cl_badge = ""
    if in_sync is True:
        cl_badge = "<span style='color:#0f9d58'>✓ sync</span>"
    elif in_sync is False:
        cl_badge = f"<span style='color:#db4437'>⚠ DIVERGE ({divergence})</span>"
    else:
        cl_badge = "<span style='color:#9aa0a6'>no read-back</span>"

    return f"""
    <div style="border-left:6px solid {border};background:#fafbfc;padding:0.8rem 1rem;
                border-radius:6px;margin-bottom:0.6rem">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <strong style="font-size:1.05rem">{intersection_id}</strong>
        <span style="color:#5f6368;font-size:0.78rem">{'stale ' if stale else ''}{age_s:.0f}s ago</span>
      </div>
      <div style="display:flex;justify-content:space-between;margin-top:0.3rem;font-size:0.92rem">
        <div><strong>{phase}</strong> <span style="color:#5f6368">({mode})</span></div>
        <div>{cl_badge}</div>
      </div>
      <div style="color:#5f6368;font-size:0.82rem;margin-top:0.2rem">
        dominant: {dominant} &middot; queue: {queue_dir} ({queue_max}) &middot;
        mesh: {'connected' if mesh_on else 'standalone'}
      </div>
    </div>
    """


st.set_page_config(
    page_title="ATMS Corridor Overview",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.title("🛣️ ATMS — Corridor Overview")
st.caption(
    "Multi-intersection coordination view. Reads state from MQTT broker "
    "(production) or local JSON files (dev fallback)."
)

# Config widget
with st.sidebar:
    st.header("Configuration")
    broker_input = st.text_input("MQTT broker host", value=BROKER_HOST)
    intersections_input = st.text_area(
        "Intersections (one per line)",
        value="\n".join(INTERSECTIONS),
    )
    intersections = [i.strip() for i in intersections_input.split("\n") if i.strip()]

# Wire MQTT subscription (cached so it runs once)
connected = mqtt_subscriber(broker_input, tuple(intersections)) if broker_input else False
if not connected:
    poll_local_files(intersections)
    st.info("Reading state from local JSON files (no MQTT broker)")
else:
    st.success(f"MQTT connected to {broker_input}")

# Grid of intersection cards — 2 per row
state_cache = get_multi_state()
cols = st.columns(2)
for idx, iid in enumerate(intersections):
    payload, age = state_cache.get(iid)
    with cols[idx % 2]:
        st.markdown(render_intersection_card(iid, payload, age), unsafe_allow_html=True)

# Aggregate metrics across all intersections
st.divider()
total_branded = 0
total_vehicles = 0
total_co2 = 0
for iid in intersections:
    payload, _ = state_cache.get(iid)
    if not payload:
        continue
    for d, info in (payload.get("per_direction") or {}).items():
        total_vehicles += info.get("vehicle_count", 0)
        total_branded += info.get("brand_identified_count", 0)
        total_co2 += info.get("emissions", {}).get("instantaneous_co2_g_per_min", 0)

agg_col1, agg_col2, agg_col3 = st.columns(3)
agg_col1.metric(
    "Corridor vehicle count",
    f"{total_vehicles}",
    help="Sum across all live intersections",
)
agg_col2.metric(
    "Brand-identified",
    f"{total_branded}",
    help="Sum across all live intersections",
)
agg_col3.metric(
    "Total CO₂ rate (g/min)",
    f"{total_co2:.0f}",
    help="Instantaneous sum across all live intersections",
)

# Auto-refresh
st.caption("Updates every 2 s. Refresh manually to apply config changes.")
time.sleep(2.0)
st.rerun()
