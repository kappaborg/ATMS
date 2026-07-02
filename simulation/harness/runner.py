"""
SUMO TraCI bridge — Phase C3.

The runner spins up SUMO (`sumo` binary), connects via TraCI, and at each
tick:
- Reads e1 detector counts per approach.
- Builds the same `TrafficData` dict the production decision-engine accepts.
- Calls `AIDecisionEngine.make_decision()` (in-process — no Kafka).
- Maps the recommended phase to a SUMO traffic-light program index.
- Records an `Observation` into the `KPIAccumulator`.

Designed to be importable without SUMO installed: `traci` and `sumolib` are
lazy-imported inside `SimulationRunner.run()`. The harness raises a clean
error message if you try to run without them, but the unit tests on
`kpis.py` and `report.py` do not require SUMO.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simulation.harness.kpis import KPIAccumulator, Observation, SimulationKPIs

log = logging.getLogger(__name__)


class SimulationError(Exception):
    """Raised by the harness on misconfiguration or upstream failure."""


# ---------------------------------------------------------------------------
# Decision callable contract
# ---------------------------------------------------------------------------

# A decision callable takes a per-approach metrics dict and returns one of:
# "ns_green" | "ew_green" | "all_red" | "ns_yellow" | "ew_yellow"
DecisionFn = Callable[[dict[str, Any], dict[str, Any]], str]


def default_decision_fn() -> DecisionFn:
    """
    Default decision callable: thin wrapper around the production
    `ai_decision_system.AIDecisionEngine`. Same logic that runs in prod.
    """
    # Lazy import — keeps `from simulation.harness.runner import default_decision_fn`
    # working even if the legacy ai_decision_system module isn't importable
    # in the current env.
    from ai_decision_system import AIDecisionEngine  # noqa: PLC0415

    # Wire-mapping helpers live in shared.atms_common.decision (no FastAPI /
    # JWT / OTel deps), so this runner can drive the AI engine in a minimal
    # Python environment (e.g. the demo on a fresh laptop).
    from shared.atms_common.decision import (  # noqa: PLC0415
        _priority_direction,
        _wire_commanded_phase,
    )

    engine = AIDecisionEngine()

    def _decide(ns_data: dict[str, Any], ew_data: dict[str, Any]) -> str:
        decision = engine.make_decision(ns_data, ew_data)
        priority_dir = _priority_direction(ns_data, ew_data)
        return _wire_commanded_phase(decision.recommended_phase.value, priority_dir)

    return _decide


# ---------------------------------------------------------------------------
# Phase mapping — wire CommandedPhase ↔ SUMO traffic-light program phase index
# ---------------------------------------------------------------------------

# Index into the `<tlLogic>` programs in the scenario's network.net.xml.
# Keep the program author in sync with this map — the rush-hour scenario
# below has a 4-phase program matching these indices.
_PHASE_TO_TLPROGRAM: dict[str, int] = {
    "ns_green": 0,
    "ns_yellow": 1,
    "ew_green": 2,
    "ew_yellow": 3,
    "all_red": 1,  # graceful fallback: hold the intergreen
}


def wire_to_tl_phase(wire: str) -> int:
    return _PHASE_TO_TLPROGRAM.get(wire, 1)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimulationConfig:
    scenario_name: str
    config_path: Path
    max_steps: int = 3600  # 1h sim at default 1s step
    step_length_s: float = 1.0
    seed: int = 42
    decision_period_s: float = 1.0  # invoke decision callable every N seconds
    traffic_light_id: str = "intersection"
    # Detectors named in detectors.add.xml: one per approach.
    detector_by_approach: dict[str, str] = None  # type: ignore[assignment]


class SimulationRunner:
    """SUMO + TraCI bridge runner."""

    def __init__(self, *, decision_fn: DecisionFn | None = None) -> None:
        self._decision_fn = decision_fn

    def run(self, config: SimulationConfig) -> SimulationKPIs:
        try:
            import sumolib  # noqa: PLC0415, F401
            import traci  # noqa: PLC0415
        except ImportError as e:
            raise SimulationError(
                "SUMO Python bindings not installed. "
                "Run: pip install -r simulation/requirements.txt "
                "(also requires the SUMO binary; macOS: `brew install sumo`)"
            ) from e

        sumo_binary = os.getenv("SUMO_BINARY", "sumo")
        sumo_cmd = [
            sumo_binary,
            "-c",
            str(config.config_path),
            "--step-length",
            str(config.step_length_s),
            "--seed",
            str(config.seed),
            "--no-step-log",
            "true",
            "--quit-on-end",
            "true",
        ]
        log.info("Starting SUMO: %s", " ".join(sumo_cmd))
        try:
            traci.start(sumo_cmd)
        except Exception as e:
            raise SimulationError(f"failed to start SUMO: {e}") from e

        decision_fn = self._decision_fn or default_decision_fn()
        acc = KPIAccumulator(scenario=config.scenario_name, tick_dt_s=config.step_length_s)
        detectors = config.detector_by_approach or {
            "north_south": "det_ns",
            "east_west": "det_ew",
        }
        steps_per_decision = max(1, int(config.decision_period_s / config.step_length_s))
        step = 0
        try:
            while step < config.max_steps:
                traci.simulationStep()
                step += 1
                sim_time = traci.simulation.getTime()

                queues = self._read_queues(traci, detectors)
                waits = self._read_waits(traci, detectors)
                departures = traci.simulation.getArrivedNumber()

                # Run the decision policy on the configured cadence.
                if step % steps_per_decision == 0:
                    ns_data = self._build_direction_data(queues, waits, "north_south")
                    ew_data = self._build_direction_data(queues, waits, "east_west")
                    wire = decision_fn(ns_data, ew_data)
                    traci.trafficlight.setPhase(config.traffic_light_id, wire_to_tl_phase(wire))

                # Read current green approaches from the TL state for KPI tracking.
                green_set = self._green_approaches(traci, config.traffic_light_id)

                acc.observe(
                    Observation(
                        sim_time_s=sim_time,
                        queue_by_approach=queues,
                        waiting_time_by_approach=waits,
                        departures_total=departures,
                        current_mode="sim_direct",
                        green_approach_set=green_set,
                    )
                )

                if traci.simulation.getMinExpectedNumber() <= 0:
                    log.info("SUMO finished at step %d", step)
                    break
        finally:
            try:
                traci.close()
            except Exception:
                pass

        return acc.finalize()

    # ------------------------------------------------------------------
    # Read helpers — keep them small and individually testable.
    # ------------------------------------------------------------------

    @staticmethod
    def _read_queues(traci_mod: Any, detectors: dict[str, str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for approach, det_id in detectors.items():
            try:
                out[approach] = int(traci_mod.inductionloop.getLastStepVehicleNumber(det_id))
            except Exception:
                out[approach] = 0
        return out

    @staticmethod
    def _read_waits(traci_mod: Any, detectors: dict[str, str]) -> dict[str, float]:
        out: dict[str, float] = {}
        for approach, det_id in detectors.items():
            try:
                # Sum of mean speeds is a rough proxy; SUMO exposes per-vehicle
                # waiting time on edges. The scenario XML wires edges aliased
                # to approach names; a future PR can switch to per-edge calls.
                out[approach] = float(traci_mod.inductionloop.getLastStepMeanSpeed(det_id))
            except Exception:
                out[approach] = 0.0
        return out

    @staticmethod
    def _build_direction_data(
        queues: dict[str, int],
        waits: dict[str, float],
        approach: str,
    ) -> dict[str, Any]:
        return {
            "vehicle_count": queues.get(approach, 0),
            "average_emission": 100.0,  # SUMO-derived emissions are follow-up
            "average_waiting_time": waits.get(approach, 0.0),
            "average_velocity": 10.0,
            "total_emission": 100.0,
            "environmental_impact_score": 30.0,
        }

    @staticmethod
    def _green_approaches(traci_mod: Any, tl_id: str) -> tuple[str, ...]:
        """
        Map the TL state string to a tuple of approach names currently green.
        The scenario's TLProgram defines a 4-link state e.g. "GGrr" / "rrGG"
        for the 4-link single intersection.
        """
        try:
            state = traci_mod.trafficlight.getRedYellowGreenState(tl_id)
        except Exception:
            return ()
        # Convention in the rush-hour scenario:
        # link 0,1 = north-south, link 2,3 = east-west.
        green: list[str] = []
        if len(state) >= 2 and "G" in state[0:2]:
            green.append("north_south")
        if len(state) >= 4 and "G" in state[2:4]:
            green.append("east_west")
        return tuple(green)
