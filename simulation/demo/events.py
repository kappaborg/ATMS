"""Scripted demo event timeline.

A demo event fires once at a specific sim-time. Each event carries a
**presenter cue** (printed to stdout so the speaker can stay in sync with the
visuals) and optionally a **side-effect** description — what the orchestrator
will do at that moment (HTTP POST, log marker, fault injection).

Side-effects are encoded as `kind` strings handled by the orchestrator in
`simulation/demo/__main__.py`. Keeping events as data — not callables — keeps
this module trivially testable.

Timeline at a glance:

    t=15s   |  Audience cue: "watch the queue lengths"
    t=60s   |  EV approaches from east — V2X BSM injected
    t=75s   |  Presenter pauses; queue should clear EW first
    t=120s  |  Pedestrian call on NS — show min-walk respected
    t=180s  |  Fault injection — controller flips to ALL_RED_FLASH
    t=210s  |  Recover from fault — back to AI_ADAPTIVE
    t=270s  |  Wrap-up cue: KPIs vs baseline
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DemoEvent:
    """A scripted event in the demo timeline."""

    at_sim_time_s: float
    cue: str
    kind: str = "cue"  # one of: "cue" | "v2x_inject" | "ped_call" | "force_mode" | "recover"
    payload: dict[str, Any] = field(default_factory=dict)


DEMO_TIMELINE: tuple[DemoEvent, ...] = (
    DemoEvent(
        at_sim_time_s=15.0,
        cue=(
            "[ 0:15 ] DEMO START — point at sumo-gui. Note: NS arterial has "
            "~50% more traffic than EW. The AI is balancing them."
        ),
        kind="cue",
    ),
    DemoEvent(
        at_sim_time_s=55.0,
        cue=(
            "[ 0:55 ] EV approaching from EAST in 5s. Talk through: 'When "
            "this EV's OBU transmits a J2735 BSM, our v2x-interface ingests "
            "it, validates the signature, and synthesises a PreemptRequest.'"
        ),
        kind="cue",
    ),
    DemoEvent(
        at_sim_time_s=60.0,
        cue=(
            "[ 1:00 ] V2X BSM injected. Controller arms preempt. Watch the "
            "EW signal head — it gets green within the next intergreen window. "
            "Open Grafana panel 'Failsafe Mode' — show the audit-log line."
        ),
        kind="v2x_inject",
        payload={
            "temporary_id": "DEMO-EV-001",
            "intersection_id": 1,
            "message_type": "regular",
            "vehicle_class": "emergency",
            "latitude_deg": 52.5200,
            "longitude_deg": 13.4050,
            "speed_mps": 18.0,
            "heading_deg": 270.0,
            "approach": "east_west",
            "distance_to_intersection_m": 80.0,
            "siren_active": True,
            "transponder_id": "DEMO-EV-001",
        },
    ),
    DemoEvent(
        at_sim_time_s=120.0,
        cue=(
            "[ 2:00 ] Pedestrian call on NS crosswalk. Watch the controller "
            "honour min-walk: even after the call, the EW phase finishes its "
            "min-green before NS gets green-with-walk. Safety > responsiveness."
        ),
        kind="ped_call",
        payload={
            "intersection_id": 1,
            "approach": "north_south",
            "ada_extended": False,
        },
    ),
    DemoEvent(
        at_sim_time_s=180.0,
        cue=(
            "[ 3:00 ] FAULT — controller will force ALL_RED_FLASH. This is "
            "the safety floor. In production this fires on AI watchdog "
            "timeout, NTP loss, or a hardware-fault read from NTCIP."
        ),
        kind="force_mode",
        payload={"mode": "all_red_flash", "reason": "demo: simulated hardware fault"},
    ),
    DemoEvent(
        at_sim_time_s=210.0,
        cue=(
            "[ 3:30 ] Operator recovers. ALL_RED_FLASH lifts ONLY if the "
            "underlying fault is acknowledged AND a human commits to recover. "
            "The state machine never self-recovers from this mode."
        ),
        kind="recover",
        payload={"intersection_id": 1, "acknowledged_by": "demo-operator"},
    ),
    DemoEvent(
        at_sim_time_s=270.0,
        cue=(
            "[ 4:30 ] Wrap up. Note: KPIs after the disruption returned to "
            "baseline within ~30s. Stress that the AI improved KPIs vs "
            "fixed-time (compare with simulation/baselines/rush-hour.json)."
        ),
        kind="cue",
    ),
)


def cues_only(timeline: tuple[DemoEvent, ...] = DEMO_TIMELINE) -> tuple[DemoEvent, ...]:
    """Return only the audience-cue events (no side-effects)."""
    return tuple(e for e in timeline if e.kind == "cue")


def side_effects(timeline: tuple[DemoEvent, ...] = DEMO_TIMELINE) -> tuple[DemoEvent, ...]:
    """Return only events that trigger a side-effect."""
    return tuple(e for e in timeline if e.kind != "cue")


def events_due(
    sim_time_s: float,
    last_fired_at_s: float,
    timeline: tuple[DemoEvent, ...] = DEMO_TIMELINE,
) -> list[DemoEvent]:
    """Return events whose `at_sim_time_s` is in (last_fired_at_s, sim_time_s].

    Used by the orchestrator's tick loop: each tick computes which events
    have now elapsed since the previous tick and fires them in order.
    """
    return [e for e in timeline if last_fired_at_s < e.at_sim_time_s <= sim_time_s]
