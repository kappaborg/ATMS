"""The Decision Chamber — main orchestrator.

Runs the 6-layer pipeline per tick:
    L0  Sensor Fusion   — aggregate + health-check inputs
    L1  Preemption      — emergency / safety hard overrides
    L2  Policy Gates    — min/max phase, pedestrian active, clearance
    L3  Optimization    — multi-objective scoring
    L4  Hysteresis      — anti-oscillation + future coordination hooks
    L5  Commit + Audit  — phase request output + decision log

Stateful: tracks `seconds_since_green` per direction and
`seconds_in_current_phase`. The state is updated on each `tick()` call
using the elapsed time between ticks (so the chamber is robust to
irregular tick rates).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from simulation.decision_chamber.audit import AuditLogger
from simulation.decision_chamber.controller_bridge import (
    ControllerBridge,
    StubControllerBridge,
)
from simulation.decision_chamber.coordination import GreenWaveCoordinator
from simulation.decision_chamber.mesh import MeshNode, NullMeshNode
from simulation.decision_chamber.metrics import PrometheusMetrics
from simulation.decision_chamber.optimization import (
    identify_dominant_factor,
    score_directions,
)
from simulation.decision_chamber.pedestrian import (
    PedestrianDetector,
    aggregate_demand,
    compute_ped_min_phase_seconds,
)
from simulation.decision_chamber.preemption import (
    EmergencyDetector,
    aggregate_signals,
    stale_signal_filter,
)
from simulation.decision_chamber.transit import TransitPriorityDetector
from simulation.decision_chamber.state import (
    ChamberConfig,
    ChamberInput,
    ChamberMode,
    ChamberOutput,
    DirectionState,
    EmergencySignal,
    LayerTrace,
)

log = logging.getLogger("atms.chamber")


class DecisionChamber:
    """Per-intersection AI decision engine.

    Lifecycle: instantiate once at pipeline startup, call `tick()` every
    review interval (default 2 s) with the current per-direction state +
    emergency detector context. Get a ChamberOutput back; pass its
    `commanded_phase` to whatever consumes the chamber output (NTCIP
    bridge in production; state JSON for the operator console in dev).
    """

    def __init__(
        self,
        config: ChamberConfig | None = None,
        detectors: list[EmergencyDetector] | None = None,
        pedestrian_detectors: list[PedestrianDetector] | None = None,
        controller_bridge: ControllerBridge | None = None,
        mesh: MeshNode | None = None,
        coordinator: GreenWaveCoordinator | None = None,
        metrics: PrometheusMetrics | None = None,
        intersection_id: str = "demo",
        transit_priority: TransitPriorityDetector | None = None,
    ):
        self._config = config or ChamberConfig()
        self._detectors = detectors or []
        self._ped_detectors = pedestrian_detectors or []
        self._bridge = controller_bridge or StubControllerBridge()
        self._mesh = mesh or NullMeshNode(intersection_id)
        self._coordinator = coordinator or GreenWaveCoordinator()
        self._metrics = metrics  # optional — None = no Prometheus exposure
        self._intersection_id = intersection_id
        self._tsp = transit_priority  # None = no GTFS-RT subscription
        self._audit = AuditLogger(
            Path(self._config.audit_log_path) if self._config.audit_log_path else None
        )

        # Stateful tracking
        self._mode: ChamberMode = ChamberMode.ADAPTIVE
        self._current_phase: str = "north_south_green"  # default starting phase
        self._phase_started_at: datetime | None = None
        self._last_tick_time: datetime | None = None
        self._seconds_since_green: dict[str, float] = {}
        self._decision_counter: int = 0
        self._last_output: ChamberOutput | None = None
        # Pedestrian-phase tracking. When a direction's ped demand triggers
        # a forced phase, we record when that ped phase began so L2 can
        # enforce its full MUTCD minimum (walk + clearance) regardless of
        # the regular min/max phase window.
        self._ped_phase_started_at: datetime | None = None
        self._ped_phase_direction: str | None = None
        # Closed-loop disagreement tracking — if commanded phase doesn't
        # match what the controller reports for >N consecutive ticks,
        # surface the alert. None = closed-loop disabled (no read-back).
        self._divergence_ticks: int = 0
        self._last_actual_phase: dict | None = None

    # --- public API --------------------------------------------------------

    def tick(
        self,
        tick_time: datetime,
        directions: list[DirectionState],
        detector_context: dict[str, Any] | None = None,
        pedestrian_phase_active: bool | None = None,
        pedestrian_clearance_remaining_s: float | None = None,
    ) -> ChamberOutput:
        """Run one decision cycle. The chamber's internal phase + timer
        state advances automatically based on the time delta between this
        tick and the previous one.

        Returns: the ChamberOutput, also stashed as `self.last_output`.
        """
        # Initialise timers on first tick
        if self._phase_started_at is None:
            self._phase_started_at = tick_time
        if self._last_tick_time is None:
            self._last_tick_time = tick_time

        # Time bookkeeping
        delta_s = max(0.0, (tick_time - self._last_tick_time).total_seconds())
        seconds_in_current_phase = (
            tick_time - self._phase_started_at
        ).total_seconds()

        # Update per-direction starvation timers
        green_direction = self._green_direction_from_phase(self._current_phase)
        for d in directions:
            if d.name == green_direction:
                self._seconds_since_green[d.name] = 0.0
            else:
                self._seconds_since_green[d.name] = (
                    self._seconds_since_green.get(d.name, 0.0) + delta_s
                )

        # Poll pedestrian detectors → which directions have demand right now
        ped_demand = aggregate_demand(
            self._ped_detectors, tick_time, detector_context or {}
        )

        # Inject the chamber's view of starvation + ped demand back into
        # the input objects (immutable, so we rebuild them).
        directions_with_state = [
            DirectionState(
                name=d.name,
                vehicle_count=d.vehicle_count,
                avg_speed_kmh=d.avg_speed_kmh,
                instantaneous_co2_g_per_min=d.instantaneous_co2_g_per_min,
                idling_vehicle_count=d.idling_vehicle_count,
                seconds_since_green=self._seconds_since_green.get(d.name, 0.0),
                has_pedestrian_demand=(d.name in ped_demand) or d.has_pedestrian_demand,
            )
            for d in directions
        ]

        # Aggregate emergency signals (L0 + L1 input)
        emergency_signals = stale_signal_filter(
            aggregate_signals(self._detectors, tick_time, detector_context or {}),
            tick_time,
        )

        # Compute pedestrian-phase active flag + clearance. A ped phase is
        # "active" if (a) the chamber is currently in a ped phase commit
        # (recorded via _ped_phase_started_at) AND (b) the MUTCD min walk
        # + clearance window hasn't expired.
        ped_min_phase = compute_ped_min_phase_seconds(
            crossing_distance_m=self._config.crossing_distance_m,
            walking_speed_mps=self._config.ped_clearance_speed_mps,
            min_walk_seconds=self._config.min_walk_seconds,
        )
        if pedestrian_phase_active is not None:
            ped_active = pedestrian_phase_active
            ped_remaining = (
                pedestrian_clearance_remaining_s
                if pedestrian_clearance_remaining_s is not None
                else 0.0
            )
        elif self._ped_phase_started_at is not None:
            elapsed_ped = (tick_time - self._ped_phase_started_at).total_seconds()
            ped_remaining = max(0.0, ped_min_phase - elapsed_ped)
            ped_active = ped_remaining > 0.0
            if not ped_active:
                # Ped clearance complete — release the lock so chamber can
                # resume normal optimization next tick.
                self._ped_phase_started_at = None
                self._ped_phase_direction = None
        else:
            ped_active = False
            ped_remaining = 0.0

        decision_input = ChamberInput(
            tick_time=tick_time,
            current_phase=self._current_phase,
            seconds_in_current_phase=seconds_in_current_phase,
            directions=directions_with_state,
            emergency_signals=emergency_signals,
            pedestrian_phase_active=ped_active,
            pedestrian_clearance_remaining_s=ped_remaining,
        )

        output = self._run_pipeline(decision_input)

        # Apply phase transition if the chamber changed it
        if output.commanded_phase != self._current_phase:
            old_phase = self._current_phase
            self._current_phase = output.commanded_phase
            self._phase_started_at = tick_time
            log.info(
                "phase transition -> %s  (mode=%s, dominant=%s)",
                output.commanded_phase,
                output.mode.value,
                output.dominant_factor,
            )
            # Multi-intersection coordination — publish a wave_pulse so
            # downstream neighbors know a packet of vehicles is en route.
            # This is what Pattern A (green wave) coordination consumes.
            if old_phase.endswith("_green"):
                old_direction = self._green_direction_from_phase(old_phase)
                self._mesh.publish_wave_pulse(
                    {
                        "wave_pulse_at": tick_time.isoformat(),
                        "from_direction": old_direction,
                        "intersection_id": self._intersection_id,
                    }
                )
            # Metrics: count this transition
            if self._metrics is not None:
                self._metrics.increment(
                    "atms_chamber_phase_transitions_total",
                    from_=old_phase,
                    to=output.commanded_phase,
                )
            # If the new green direction has pedestrian demand, commit
            # to serving the MUTCD min walk + clearance. The chamber
            # remembers this so L2 can block premature changes until
            # the walk is complete.
            green_dir = self._green_direction_from_phase(output.commanded_phase)
            if any(
                d.name == green_dir and d.has_pedestrian_demand
                for d in decision_input.directions
            ):
                self._ped_phase_started_at = tick_time
                self._ped_phase_direction = green_dir
                log.info("pedestrian phase committed for %s", green_dir)

        self._mode = output.mode
        self._last_tick_time = tick_time
        self._last_output = output
        self._audit.write(decision_input, output)
        # Layer 5b — push the advisory phase request to the bridge. If
        # the bridge raises, we log + count but don't fail the tick;
        # operator console + audit still reflect the chamber's decision.
        try:
            self._bridge.send_phase_request(output)
        except Exception as e:
            log.warning("controller bridge %s raised: %s", self._bridge.name, e)

        # Closed-loop check — read what the controller is ACTUALLY doing
        # (NTCIP GET polled in the bridge's background thread) and
        # compare with our commanded phase. Diverging for >N ticks is a
        # production-critical alert: it means our advisory was ignored or
        # the controller has fallen back to its safety mode without
        # telling us.
        try:
            actual = self._bridge.get_actual_phase()
            if actual is not None:
                commanded_dir = self._green_direction_from_phase(output.commanded_phase)
                active_dirs = actual.get("active_directions") or []
                if commanded_dir and commanded_dir not in active_dirs:
                    self._divergence_ticks += 1
                    if self._divergence_ticks >= 3:  # 3 consecutive ticks
                        log.warning(
                            "controller divergence: commanded=%s actual=%s",
                            commanded_dir, active_dirs,
                        )
                        if self._metrics is not None:
                            self._metrics.increment(
                                "atms_chamber_controller_divergence_total",
                                commanded=commanded_dir,
                            )
                else:
                    self._divergence_ticks = 0
                self._last_actual_phase = actual
        except Exception as e:
            log.debug("closed-loop check skipped: %s", e)

        # Multi-intersection mesh: publish state and decision so neighbors
        # + city dashboard see this chamber's view of the world.
        try:
            self._mesh.publish_state(
                {
                    "tick_time": tick_time.isoformat(),
                    "phase": self._current_phase,
                    "mode": output.mode.value,
                    "actual_phase": self._last_actual_phase,
                    "vehicle_counts": {
                        d.name: d.vehicle_count for d in decision_input.directions
                    },
                    "co2_g_per_min": {
                        d.name: d.instantaneous_co2_g_per_min
                        for d in decision_input.directions
                    },
                }
            )
            self._mesh.publish_decision(self.to_dict(output))
        except Exception as e:
            log.warning("mesh publish raised: %s", e)

        # Prometheus metrics — counter + gauge updates per tick.
        if self._metrics is not None:
            self._metrics.increment(
                "atms_chamber_decisions_total",
                mode=output.mode.value,
                dominant=output.dominant_factor,
            )
            if output.mode == ChamberMode.PREEMPT and decision_input.emergency_signals:
                self._metrics.increment(
                    "atms_chamber_preemptions_total",
                    source=decision_input.emergency_signals[0].source.value,
                )
            for d in decision_input.directions:
                self._metrics.set_gauge(
                    "atms_chamber_vehicle_count",
                    d.vehicle_count,
                    direction=d.name,
                )
                self._metrics.set_gauge(
                    "atms_chamber_emission_g_per_min",
                    d.instantaneous_co2_g_per_min,
                    direction=d.name,
                )
                if d.name in output.priority_scores:
                    self._metrics.set_gauge(
                        "atms_chamber_priority_score",
                        output.priority_scores[d.name],
                        direction=d.name,
                    )
            self._metrics.set_gauge(
                "atms_chamber_seconds_in_phase",
                seconds_in_current_phase,
                phase=self._current_phase,
            )
        return output

    @property
    def last_output(self) -> ChamberOutput | None:
        return self._last_output

    # --- pipeline ---------------------------------------------------------

    def _run_pipeline(self, ci: ChamberInput) -> ChamberOutput:
        trace: list[LayerTrace] = []

        # L0 — sensor fusion (minimal in Phase 1: just availability check)
        l0 = self._layer0_sensor_fusion(ci)
        trace.append(l0)

        # L1 — preemption
        l1_output, l1_trace = self._layer1_preemption(ci)
        trace.append(l1_trace)
        if l1_output is not None:
            return self._finalise(ci, l1_output, trace, "preempt", "emergency", {})

        # L2 — policy gates
        gate_result, l2_trace = self._layer2_policy_gates(ci)
        trace.append(l2_trace)
        if gate_result == "hold":
            # When gated, the "dominant factor" is the gate that blocked
            # the change — that's the most informative thing to surface
            # to the operator (not a free-text note).
            held_reason = (
                "pedestrian_phase"
                if ci.pedestrian_phase_active
                else "min_phase_lock"
            )
            return self._finalise(
                ci,
                ci.current_phase,
                trace,
                "adaptive",
                held_reason,
                {},
            )

        # L3 — optimization
        scores, per_signal, l3_trace = self._layer3_optimization(ci)
        trace.append(l3_trace)

        # L4 — hysteresis + green-wave coordination. If L2 forced a
        # change (max phase exceeded or ped demand), we must NOT apply
        # the current-phase bonus or the chamber would silently overrun
        # max_phase or skip ped service.
        force_change = bool(l2_trace.detail.get("forced_change"))

        # Multi-intersection coordination: ask the green-wave coordinator
        # whether a packet of vehicles is currently passing through. If
        # so, it returns a small bonus to add to the current direction's
        # score so we lean toward holding the green.
        coord_bonus = 0.0
        coord_reason = ""
        if not force_change and self._coordinator.neighbors:
            since = ci.tick_time - timedelta(seconds=30)
            pulses = self._mesh.get_recent_neighbor_wave_pulses(since)
            current_dir = self._green_direction_from_phase(self._current_phase)
            coord_bonus, coord_reason = self._coordinator.evaluate(
                ci.tick_time, current_dir, pulses
            )
            if coord_bonus > 0.0 and current_dir in scores:
                scores = {**scores, current_dir: scores[current_dir] + coord_bonus}
            trace.append(
                LayerTrace(
                    layer="L4_coordination",
                    result="passed" if coord_bonus > 0 else "skipped",
                    notes=coord_reason,
                    detail={"bonus": coord_bonus},
                )
            )

        winner, l4_trace = self._layer4_hysteresis(scores, ci, force_change=force_change)
        trace.append(l4_trace)

        dominant = identify_dominant_factor(per_signal, winner, self._config)

        # L5 happens in _finalise (audit log + reasoning)
        return self._finalise(ci, winner, trace, "adaptive", dominant, scores)

    # --- per-layer --------------------------------------------------------

    def _layer0_sensor_fusion(self, ci: ChamberInput) -> LayerTrace:
        """In Phase 1 this is just a counts-based health check. Real
        implementation will check per-sensor freshness, calibration drift,
        cross-source agreement.
        """
        n_dir = len(ci.directions)
        n_emerg = len(ci.emergency_signals)
        return LayerTrace(
            layer="L0_sensor_fusion",
            result="passed",
            notes=f"{n_dir} direction(s) reporting, {n_emerg} emergency signal(s)",
            detail={"directions": [d.name for d in ci.directions]},
        )

    def _layer1_preemption(
        self, ci: ChamberInput
    ) -> tuple[str | None, LayerTrace]:
        """Returns (commanded_phase, trace). If commanded_phase is not
        None, skip the rest of the pipeline — preemption is active.
        """
        if not ci.emergency_signals:
            return None, LayerTrace(
                layer="L1_preemption",
                result="passed",
                notes="no emergency signals",
            )
        # Highest-confidence signal wins. Ties → operator override first,
        # then visual, then audio, then V2X (most → least trustworthy
        # ordering for Phase 1 — flips when V2X is real).
        best = max(ci.emergency_signals, key=lambda s: s.confidence)
        commanded = f"{best.direction}_green"
        return commanded, LayerTrace(
            layer="L1_preemption",
            result="preempted",
            notes=f"{best.source.value} → {best.direction} conf={best.confidence:.2f}",
            detail={"signal_count": len(ci.emergency_signals)},
        )

    def _layer2_policy_gates(self, ci: ChamberInput) -> tuple[str, LayerTrace]:
        """Returns ('proceed' | 'hold', trace). 'hold' means optimization
        is skipped and the current phase stays.
        """
        # Pedestrian phase active → cannot interrupt (MUTCD requirement)
        if ci.pedestrian_phase_active:
            return "hold", LayerTrace(
                layer="L2_policy_gates",
                result="blocked",
                notes=f"pedestrian phase active ({ci.pedestrian_clearance_remaining_s:.1f}s left)",
                detail={"ped_locked": True},
            )

        # Min phase duration must be met before any change
        if ci.seconds_in_current_phase < self._config.min_phase_seconds:
            remaining = self._config.min_phase_seconds - ci.seconds_in_current_phase
            return "hold", LayerTrace(
                layer="L2_policy_gates",
                result="blocked",
                notes=f"min phase not yet met ({remaining:.1f}s remaining)",
            )

        # Pedestrian demand on a non-current direction → forced change.
        # Peds are a hard constraint; once min_phase is met they get the
        # next green. This bypasses L4 hysteresis so a small ped score
        # doesn't get held back by the current-phase bonus.
        current_dir = self._green_direction_from_phase(ci.current_phase)
        ped_demand_dirs = [
            d.name
            for d in ci.directions
            if d.has_pedestrian_demand and d.name != current_dir
        ]
        if ped_demand_dirs:
            return "proceed", LayerTrace(
                layer="L2_policy_gates",
                result="passed",
                notes=(
                    f"pedestrian demand on {','.join(ped_demand_dirs)} — "
                    "forcing change"
                ),
                detail={"forced_change": True, "ped_demand": ped_demand_dirs},
            )

        # Max phase duration crossed → force a switch (chamber can pick
        # ANY non-current direction; optimization will tell it which).
        if ci.seconds_in_current_phase >= self._config.max_phase_seconds:
            return "proceed", LayerTrace(
                layer="L2_policy_gates",
                result="passed",
                notes=(
                    f"max phase reached ({ci.seconds_in_current_phase:.1f}s) — "
                    "forcing change"
                ),
                detail={"forced_change": True},
            )

        return "proceed", LayerTrace(
            layer="L2_policy_gates",
            result="passed",
            notes=f"phase {ci.seconds_in_current_phase:.1f}s into [min, max] window",
        )

    def _layer3_optimization(
        self, ci: ChamberInput
    ) -> tuple[dict[str, float], dict[str, dict[str, float]], LayerTrace]:
        tsp_bonus: dict[str, float] = {}
        if self._tsp is not None:
            try:
                tsp_bonus = self._tsp.get_tsp_bonus_per_direction()
            except Exception as e:
                log.debug("TSP poll failed in L3: %s", e)
        return score_directions(ci.directions, self._config, tsp_bonus=tsp_bonus)

    def _layer4_hysteresis(
        self, scores: dict[str, float], ci: ChamberInput, force_change: bool = False
    ) -> tuple[str, LayerTrace]:
        """Apply current-phase bonus + challenger margin. Returns winning
        direction name.

        When `force_change=True` (signalled by L2's max-phase override):
        - No current-phase bonus
        - No challenger margin
        - The current direction is REMOVED from contention so the chamber
          is forced to switch even if all the metrics still favour it.
        This is the correct behaviour when max_phase has been exceeded —
        equity of service requires moving on.
        """
        if not scores:
            return self._green_direction_from_phase(ci.current_phase), LayerTrace(
                layer="L4_hysteresis",
                result="skipped",
                notes="no scores — staying on current phase",
            )

        current_dir = self._green_direction_from_phase(ci.current_phase)

        if force_change:
            # Pull current direction out of contention; pick best of the rest.
            challenger_scores = {k: v for k, v in scores.items() if k != current_dir}
            if not challenger_scores:
                # Only one direction available — no choice but to keep it
                return current_dir, LayerTrace(
                    layer="L4_hysteresis",
                    result="held",
                    notes="forced change requested but no alternative direction",
                )
            winner = max(challenger_scores.items(), key=lambda kv: kv[1])[0]
            return winner, LayerTrace(
                layer="L4_hysteresis",
                result="switched",
                notes=(
                    f"forced change from {current_dir} -> {winner} "
                    f"(scored {challenger_scores[winner]:.3f})"
                ),
                detail={"forced": True, "scores": scores},
            )

        adjusted = dict(scores)
        if current_dir in adjusted:
            adjusted[current_dir] += self._config.current_phase_bonus

        winner = max(adjusted.items(), key=lambda kv: kv[1])[0]
        # If the current phase still wins after bonus, keep it.
        if winner == current_dir:
            return current_dir, LayerTrace(
                layer="L4_hysteresis",
                result="held",
                notes=f"current direction {current_dir} keeps lead",
                detail={"adjusted": adjusted, "bonus": self._config.current_phase_bonus},
            )

        # Otherwise check the challenger margin
        margin = adjusted[winner] - adjusted[current_dir]
        if margin < self._config.challenger_margin:
            return current_dir, LayerTrace(
                layer="L4_hysteresis",
                result="held",
                notes=(
                    f"{winner} leads by {margin:.3f}, below margin "
                    f"{self._config.challenger_margin}"
                ),
                detail={"adjusted": adjusted},
            )

        return winner, LayerTrace(
            layer="L4_hysteresis",
            result="switched",
            notes=f"{winner} beats {current_dir} by {margin:.3f}",
            detail={"adjusted": adjusted, "margin": margin},
        )

    def _finalise(
        self,
        ci: ChamberInput,
        commanded_direction_or_phase: str,
        trace: list[LayerTrace],
        mode_name: str,
        dominant: str,
        scores: dict[str, float],
    ) -> ChamberOutput:
        """Build the ChamberOutput. Argument naming is permissive: most
        callers pass a direction name like 'east_west'; we translate to
        a phase string like 'east_west_green'. Preemption passes a fully
        formed phase already.
        """
        commanded_phase = (
            commanded_direction_or_phase
            if commanded_direction_or_phase.endswith("_green")
            or commanded_direction_or_phase == "all_red"
            else f"{commanded_direction_or_phase}_green"
        )
        mode = {
            "preempt": ChamberMode.PREEMPT,
            "adaptive": ChamberMode.ADAPTIVE,
            "fixed_time": ChamberMode.FIXED_TIME,
            "manual": ChamberMode.MANUAL,
            "flash_caution": ChamberMode.FLASH_CAUTION,
        }.get(mode_name, ChamberMode.ADAPTIVE)

        # Reasoning string — human-readable summary
        reasoning_parts: list[str] = []
        if mode == ChamberMode.PREEMPT:
            sig = ci.emergency_signals[0]
            reasoning_parts.append(
                f"EMERGENCY preemption via {sig.source.value} "
                f"(conf={sig.confidence:.2f})"
            )
        elif scores:
            winner_dir = self._green_direction_from_phase(commanded_phase)
            if winner_dir in scores:
                reasoning_parts.append(
                    f"{winner_dir} scored {scores[winner_dir]:.2f} (dominant: {dominant})"
                )
        if any(t.result == "blocked" for t in trace):
            blocking = next(t for t in trace if t.result == "blocked")
            reasoning_parts.append(f"held: {blocking.notes}")

        self._decision_counter += 1
        decision_id = f"{ci.tick_time.strftime('%Y%m%dT%H%M%S')}-{self._decision_counter:04d}"

        return ChamberOutput(
            decision_id=decision_id,
            timestamp=ci.tick_time,
            mode=mode,
            commanded_phase=commanded_phase,
            seconds_until_next_review=self._config.review_interval_seconds,
            priority_scores=scores,
            dominant_factor=dominant,
            rule_chain=trace,
            reasoning=" | ".join(reasoning_parts) or "no change",
            min_phase_seconds=self._config.min_phase_seconds,
            max_phase_seconds=self._config.max_phase_seconds,
        )

    @staticmethod
    def _green_direction_from_phase(phase: str) -> str:
        """Strip the '_green' suffix to get the direction name. Returns
        the phase as-is if there's no suffix (e.g., 'all_red').
        """
        return phase[: -len("_green")] if phase.endswith("_green") else phase

    # --- output helpers ---------------------------------------------------

    def to_dict(self, output: ChamberOutput) -> dict:
        """Serialise the output for embedding in the operator-console
        state JSON. Returns a plain dict — JSON-safe.
        """
        # Live closed-loop status from the bridge (None until first poll).
        actual = None
        try:
            actual = self._bridge.get_actual_phase()
        except Exception:
            actual = None
        commanded_dir = self._green_direction_from_phase(output.commanded_phase)
        active = (actual.get("active_directions") if actual else []) or []
        controller_in_sync = (commanded_dir in active) if active else None

        # Active TSP routes per direction
        tsp_routes: dict[str, list[str]] = {}
        if self._tsp is not None:
            try:
                tsp_routes = self._tsp.get_demand_detail()
            except Exception:
                tsp_routes = {}

        # Detector health snapshot — which sources are alive AND have
        # been polled this tick. Useful for the operator to verify
        # multi-source coverage at a glance.
        detector_health = {
            "emergency_sources_active": [d.name for d in self._detectors],
            "pedestrian_sources_active": [d.name for d in self._ped_detectors],
            "tsp_enabled": self._tsp is not None,
            "mesh_connected": getattr(self._mesh, "connected", False),
            "audit_type": type(self._audit).__name__,
            "bridge_type": self._bridge.name,
        }

        return {
            "decision_id": output.decision_id,
            "timestamp": output.timestamp.isoformat(),
            "mode": output.mode.value,
            "commanded_phase": output.commanded_phase,
            "seconds_until_next_review": output.seconds_until_next_review,
            "priority_scores": output.priority_scores,
            "dominant_factor": output.dominant_factor,
            "rule_chain": [
                {
                    "layer": t.layer,
                    "result": t.result,
                    "notes": t.notes,
                    "detail": t.detail,
                }
                for t in output.rule_chain
            ],
            "reasoning": output.reasoning,
            "min_phase_seconds": output.min_phase_seconds,
            "max_phase_seconds": output.max_phase_seconds,
            # Phase 10.1 — chamber's full internal timer state for
            # PERFECT deterministic replay. Without this, the replayer
            # warm-starts from ChamberInput alone and has score drift
            # because pedestrian-phase commits and divergence counters
            # aren't reconstructed exactly.
            "internal_state": {
                "ped_phase_started_at": (
                    self._ped_phase_started_at.isoformat()
                    if self._ped_phase_started_at is not None else None
                ),
                "ped_phase_direction": self._ped_phase_direction,
                "divergence_ticks": self._divergence_ticks,
                "decision_counter": self._decision_counter,
                "seconds_since_green": dict(self._seconds_since_green),
            },
            # NEW in Phase 5 consolidation — surfaced to operator console
            "closed_loop": {
                "actual_active_directions": active,
                "in_sync": controller_in_sync,
                "divergence_ticks": self._divergence_ticks,
                "read_at": actual.get("read_at") if actual else None,
            },
            "transit_priority": {
                "active_routes_by_direction": tsp_routes,
            },
            "detector_health": detector_health,
        }
