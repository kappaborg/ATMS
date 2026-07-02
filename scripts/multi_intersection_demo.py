#!/usr/bin/env python3
"""Multi-intersection arterial corridor live demo.

Runs TWO chambers in one process, coordinating via an in-memory mesh
shim that emulates an MQTT broker (so the demo works without
Mosquitto installed). Demonstrates Pattern A green wave coordination:
when upstream intersection (`alley-A`) ends its through-movement green,
it publishes a wave_pulse; downstream (`alley-B`) receives it and L4
biases toward holding its through green to let the packet pass.

This is the most visually compelling demo of multi-intersection
coordination — paydaş'a "AI bir tek kavşağı değil, koridoru
optimize ediyor" hikayesini görsel olarak veriyor.

Run:
    python3 scripts/multi_intersection_demo.py --ticks 30
    # Open two operator console tabs (one per intersection state file)
    # to see the wave propagate
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("multi_demo")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulation.decision_chamber import (  # noqa: E402
    ChamberConfig,
    DecisionChamber,
    DirectionState,
)
from simulation.decision_chamber.coordination import (  # noqa: E402
    CoordinationConfig,
    GreenWaveCoordinator,
    WaveNeighbor,
)
from simulation.decision_chamber.mesh import MeshNode  # noqa: E402


class InMemoryMeshShim:
    """Two-chamber in-process mesh — emulates MQTT pub/sub without a
    broker. Per-intersection MeshNode instance forwards publishes into a
    shared bus; subscribers read from their per-topic queues.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # {(topic, recipient_intersection_id) -> list[payload]}
        self._pending: dict[str, list[tuple[datetime, str, dict]]] = {}

    def publish_wave(self, from_id: str, payload: dict) -> None:
        with self._lock:
            for key in list(self._pending.keys()):
                if key.endswith(f":sub:{from_id}"):
                    self._pending[key].append((datetime.now(timezone.utc), from_id, payload))

    def subscribe(self, listener_id: str, upstream_id: str) -> str:
        key = f"wave_pulse:{listener_id}:sub:{upstream_id}"
        with self._lock:
            self._pending.setdefault(key, [])
        return key

    def drain_for_listener(self, listener_id: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)
        with self._lock:
            for key, items in list(self._pending.items()):
                parts = key.split(":")
                if len(parts) < 4 or parts[1] != listener_id:
                    continue
                upstream = parts[3]
                # Fresh entries only
                fresh = [(t, fid, p) for (t, fid, p) in items if t >= cutoff]
                self._pending[key] = fresh
                if fresh:
                    out[upstream] = fresh[-1][2]
        return out


class ShimMeshNode:
    """MeshNode adapter for InMemoryMeshShim — same interface as
    NullMeshNode / MqttMeshNode but routes through the in-memory shim.
    """

    def __init__(self, intersection_id: str, shim: InMemoryMeshShim, upstream: list[str]):
        self.intersection_id = intersection_id
        self.connected = True
        self._shim = shim
        for u in upstream:
            shim.subscribe(intersection_id, u)

    def publish_state(self, payload: dict) -> None: pass
    def publish_decision(self, payload: dict) -> None: pass

    def publish_wave_pulse(self, payload: dict) -> None:
        self._shim.publish_wave(self.intersection_id, payload)

    def get_recent_neighbor_wave_pulses(self, since: datetime) -> dict[str, dict]:
        return self._shim.drain_for_listener(self.intersection_id)

    def close(self) -> None: pass


def main() -> int:
    p = argparse.ArgumentParser(prog="multi_intersection_demo.py")
    p.add_argument("--ticks", type=int, default=30, help="number of ticks to simulate")
    p.add_argument("--tick-interval-s", type=float, default=2.0)
    p.add_argument("--wave-offset-s", type=float, default=18.0)
    args = p.parse_args()

    shim = InMemoryMeshShim()

    # Upstream: alley-A (no neighbors of its own)
    chamber_a = DecisionChamber(
        config=ChamberConfig(audit_log_path=None, min_phase_seconds=8.0),
        mesh=ShimMeshNode("alley-A", shim, upstream=[]),
        intersection_id="alley-A",
    )

    # Downstream: alley-B subscribes to alley-A's wave pulses + applies
    # green-wave coordination with 18 s offset.
    chamber_b = DecisionChamber(
        config=ChamberConfig(audit_log_path=None, min_phase_seconds=8.0),
        mesh=ShimMeshNode("alley-B", shim, upstream=["alley-A"]),
        coordinator=GreenWaveCoordinator(
            CoordinationConfig(
                upstream_neighbors=(
                    WaveNeighbor(
                        intersection_id="alley-A",
                        offset_seconds=args.wave_offset_s,
                        through_direction="north_south",
                    ),
                ),
                wave_window_seconds=6.0,
                wave_hold_bonus=0.30,
            )
        ),
        intersection_id="alley-B",
    )

    start = datetime.now(timezone.utc)
    log.info("──────────────────────────────────────────────")
    log.info("  arterial corridor: alley-A → alley-B")
    log.info("  wave offset: %.1fs (vehicle packet travel time)", args.wave_offset_s)
    log.info("──────────────────────────────────────────────")
    print(
        f"  {'tick':>5}  {'time':>4}  "
        f"{'alley-A':<26}  {'alley-B':<26}  notes"
    )
    print("  " + "─" * 90)

    # Simulate growing east_west queue at alley-A causing a switch at
    # ~tick 8, then wave pulse propagation triggers alley-B to hold.
    for tick in range(args.ticks):
        t = start + timedelta(seconds=tick * args.tick_interval_s)

        # alley-A — east_west queue grows over time, triggering switch
        ew_queue_a = 2 + tick // 2
        out_a = chamber_a.tick(
            tick_time=t,
            directions=[
                DirectionState("north_south", vehicle_count=3, avg_speed_kmh=25,
                               instantaneous_co2_g_per_min=400, idling_vehicle_count=1,
                               seconds_since_green=0.0),
                DirectionState("east_west", vehicle_count=ew_queue_a, avg_speed_kmh=5,
                               instantaneous_co2_g_per_min=ew_queue_a * 250,
                               idling_vehicle_count=ew_queue_a, seconds_since_green=0.0),
            ],
        )

        # alley-B — north_south steady flow, sometimes serving east_west
        ns_queue_b = 5
        ew_queue_b = 2 + tick // 4
        out_b = chamber_b.tick(
            tick_time=t,
            directions=[
                DirectionState("north_south", vehicle_count=ns_queue_b, avg_speed_kmh=30,
                               instantaneous_co2_g_per_min=ns_queue_b * 180,
                               idling_vehicle_count=1, seconds_since_green=0.0),
                DirectionState("east_west", vehicle_count=ew_queue_b, avg_speed_kmh=8,
                               instantaneous_co2_g_per_min=ew_queue_b * 220,
                               idling_vehicle_count=ew_queue_b, seconds_since_green=0.0),
            ],
        )

        # Surface green-wave bonus if it fired
        wave_note = ""
        for trace in out_b.rule_chain:
            if trace.layer == "L4_coordination" and trace.detail.get("bonus", 0) > 0:
                wave_note = f"← wave bonus {trace.detail['bonus']:.2f}"

        a_label = f"{out_a.commanded_phase} ({out_a.dominant_factor[:14]})"
        b_label = f"{out_b.commanded_phase} ({out_b.dominant_factor[:14]})"
        print(
            f"  {tick:>5}  {tick*args.tick_interval_s:>3.0f}s  "
            f"{a_label:<26}  {b_label:<26}  {wave_note}"
        )

    print("\n  ──────────────────────────────────────────────")
    log.info("multi-intersection demo complete")
    log.info("audit logs at /tmp/atms-chamber-audit*.jsonl (per-chamber)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
