#!/usr/bin/env python3
"""
AI Decision System for Traffic Management
=========================================
Intelligent traffic light control system based on vehicle count, emissions, and traffic flow.
Makes real-time decisions to optimize traffic flow and minimize environmental impact.
"""

from enum import Enum
from datetime import datetime, timezone
from typing import Callable, Dict, Optional
from dataclasses import dataclass
import time
import uuid
import logging

logger = logging.getLogger(__name__)


class TrafficPhase(Enum):
    """Traffic light phases"""
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    ALL_RED = "ALL_RED"  # Safety phase


class DecisionPriority(Enum):
    """Decision priority levels"""
    EMERGENCY = "EMERGENCY"  # Emergency vehicles, critical situations
    HIGH = "HIGH"  # High traffic, high emissions
    MEDIUM = "MEDIUM"  # Normal traffic conditions
    LOW = "LOW"  # Low traffic, minimal impact


@dataclass
class TrafficDecision:
    """Traffic decision data structure"""
    decision_id: str
    timestamp: datetime
    current_phase: TrafficPhase
    recommended_phase: TrafficPhase
    priority: DecisionPriority
    reason: str
    confidence: float  # 0.0 to 1.0
    expected_impact: Dict[str, float]  # Expected improvements
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'decision_id': self.decision_id,
            'timestamp': self.timestamp.isoformat(),
            'current_phase': self.current_phase.value,
            'recommended_phase': self.recommended_phase.value,
            'priority': self.priority.value,
            'reason': self.reason,
            'confidence': self.confidence,
            'expected_impact': self.expected_impact
        }


class AIDecisionEngine:
    """
    AI-powered traffic decision engine
    
    Makes intelligent decisions based on:
    - Vehicle count per direction
    - Average emissions
    - Waiting time
    - Traffic velocity
    - Environmental impact
    - Reinforcement Learning (optional)
    - Predictive Analytics (optional)
    - Anomaly Detection (optional)
    """
    
    def __init__(
        self,
        use_rl: bool = False,
        use_predictions: bool = False,
        use_anomaly_detection: bool = False,
        min_green_s: float = 10.0,
        max_green_s: float = 90.0,
        yellow_s: float = 3.0,
        all_red_s: float = 2.0,
        switch_threshold: float = 1.2,
        min_switch_vehicles: int = 3,
        transit_weight: float = 0.2,
        coordination_weight: float = 0.2,
        max_ped_extend_s: float = 6.0,
        prediction_weight: float = 0.15,
        prediction_horizon_min: int = 15,
        now_fn: Optional[Callable[[], float]] = None,
    ):
        """Initialize the decision engine.

        Timing parameters are wall-clock seconds enforced by the internal
        phase state machine (GREEN → YELLOW → ALL_RED → opposite GREEN).
        `now_fn` is injectable for deterministic tests/simulation.
        """
        self.current_phase = TrafficPhase.GREEN
        # Which approach currently holds green. The wire mapping in
        # shared.atms_common.decision combines phase + direction downstream.
        self.active_direction = "north_south"
        self.min_green_s = min_green_s
        self.max_green_s = max_green_s
        self.yellow_s = yellow_s
        self.all_red_s = all_red_s
        self.switch_threshold = switch_threshold
        # Minimum-benefit gate: don't pay clearance (yellow+all-red) to switch
        # green to an approach with only a trivial queue while the current
        # approach is still flowing. Prevents wasted clearance under light,
        # balanced demand (where fixed-time is otherwise near-optimal).
        self.min_switch_vehicles = min_switch_vehicles
        # Transit signal priority: bounded score bonus for an approach with a
        # detected transit vehicle (bus). Soft priority — it can extend/expedite
        # green for a bus but heavy cross-demand can still override it (unlike
        # emergency preemption, which is a hard override).
        self.transit_weight = transit_weight
        self._last_transit: Optional[Dict] = None
        # Pedestrian safety: hold the all-red clearance up to this many extra
        # seconds while a pedestrian is still in the roadway, so cross-traffic
        # is never released into someone mid-crossing. Bounded so the signal
        # can't be stalled indefinitely.
        self.max_ped_extend_s = max_ped_extend_s
        self._ped_present = False
        self._ped_hold_active = False
        # Green-wave coordination: a bounded bias toward the coordinated
        # approach while the corridor clock is in this intersection's green
        # band. Soft (heavy local demand can override) — an "adaptive" wave.
        self.coordination_weight = coordination_weight
        self._coord: Optional[Dict] = None  # {offset_s, cycle_s, green_s, direction}
        # Predictive congestion: how much a short-horizon forecast can nudge a
        # direction's score (bounded so it never overrides real demand).
        self.prediction_weight = prediction_weight
        self.prediction_horizon_min = prediction_horizon_min
        self._last_prediction: Optional[Dict] = None
        self._last_anomaly: Optional[str] = None
        # Emergency-vehicle preemption: forced-green approach + optional expiry.
        self._preempt_direction: Optional[str] = None
        self._preempt_until: Optional[float] = None
        self._now = now_fn or time.monotonic
        self._phase_started_at = self._now()
        self.phase_history = []
        self.decision_count = 0
        self.statistics = {
            'total_decisions': 0,
            'phase_changes': 0,
            'average_confidence': 0.0,
            'total_emission_reduction': 0.0
        }
        
        # Decision weights (multi-factor optimization)
        self.weights = {
            'vehicle_count': 0.30,      # 30% weight on vehicle count
            'emissions': 0.30,          # 30% weight on emissions
            'waiting_time': 0.20,       # 20% weight on waiting time
            'traffic_flow': 0.20         # 20% weight on traffic flow
        }
        
        # Phase 2: Advanced AI features (optional)
        self.use_rl = use_rl
        self.use_predictions = use_predictions
        self.use_anomaly_detection = use_anomaly_detection
        
        # Initialize AI components if requested
        self.rl_agent = None
        self.predictor = None
        self.anomaly_detector = None
        
        if use_rl:
            try:
                from ai import create_rl_agent
                self.rl_agent = create_rl_agent(use_rl=True)
                logger.info("✅ RL agent initialized")
            except Exception as e:
                logger.warning(f"Could not initialize RL agent: {e}")
                self.use_rl = False
        
        if use_predictions:
            try:
                from ai import create_predictor
                self.predictor = create_predictor()
                logger.info("✅ Traffic predictor initialized")
            except Exception as e:
                logger.warning(f"Could not initialize predictor: {e}")
                self.use_predictions = False
        
        if use_anomaly_detection:
            try:
                from ai import create_anomaly_detector
                self.anomaly_detector = create_anomaly_detector()
                logger.info("✅ Anomaly detector initialized")
            except Exception as e:
                logger.warning(f"Could not initialize anomaly detector: {e}")
                self.use_anomaly_detection = False
        
        logger.info("AI Decision Engine initialized")
    
    def make_decision(
        self,
        north_south: Dict,
        east_west: Dict,
        pedestrian_present: bool = False,
    ) -> TrafficDecision:
        """
        Make a traffic decision based on traffic data from two directions

        Args:
            north_south: Traffic data for north-south direction
            east_west: Traffic data for east-west direction
            pedestrian_present: True if a pedestrian is still in the roadway;
                holds the all-red clearance (bounded) so cross-traffic is not
                released into them.

        Returns:
            TrafficDecision object with recommended action
        """
        self.decision_count += 1
        self._ped_present = bool(pedestrian_present)

        # Transit signal priority: note which approaches have a bus (for
        # surfacing); the score bonus itself is applied in the score function.
        self._last_transit = {
            "north_south": bool(north_south.get("transit_present")),
            "east_west": bool(east_west.get("transit_present")),
        }

        # Calculate scores for each direction (current demand)
        ns_score = self._calculate_direction_score(north_south)
        ew_score = self._calculate_direction_score(east_west)

        # Fold in a short-horizon congestion forecast so the signal reacts
        # BEFORE a jam forms, not after. Bounded — it nudges the scores, never
        # overrides real demand. The failsafe controller still enforces all
        # timing/safety on the resulting recommendation.
        ns_score, ew_score, self._last_prediction = self._apply_prediction(
            north_south, east_west, ns_score, ew_score
        )

        # Green-wave coordination: bounded bias toward the corridor's coordinated
        # approach during its green band (soft — heavy demand can still override).
        coord_dir = self._coordination_direction()
        if coord_dir == "north_south":
            ns_score += self.coordination_weight
        elif coord_dir == "east_west":
            ew_score += self.coordination_weight

        # Determine priority direction
        if ns_score > ew_score:
            priority_direction = "north_south"
            priority_score = ns_score
            other_score = ew_score
            priority_data = north_south
            other_data = east_west
        else:
            priority_direction = "east_west"
            priority_score = ew_score
            other_score = ns_score
            priority_data = east_west
            other_data = north_south
        
        # Emergency-vehicle preemption overrides demand entirely: the preempted
        # approach is forced to priority. The phase state machine STILL enforces
        # clearance (yellow/all-red) so the transition is never unsafe.
        preempt = self._preemption_active()
        if preempt is not None:
            priority_direction = preempt
            priority_score, other_score = 999.0, 0.0
            if preempt == "north_south":
                priority_data, other_data = north_south, east_west
            else:
                priority_data, other_data = east_west, north_south

        previous_phase = self.current_phase

        # Decide whether demand justifies handing green to the other approach.
        # The phase state machine then enforces min-green / clearance timing.
        if preempt is not None:
            wants_switch = self.active_direction != preempt
        else:
            # priority_data is the demand winner; when it isn't the active
            # approach, it is the one waiting for green, and other_data is the
            # approach currently holding it.
            wants_switch = self._rule_based_wants_switch(
                priority_direction,
                priority_score,
                other_score,
                waiting_vehicles=int(priority_data.get("vehicle_count", 0)),
                current_vehicles=int(other_data.get("vehicle_count", 0)),
            )

        # Phase 2: Use RL agent if available — its action overrides the
        # rule-based switch request, but never the safety timing below.
        if self.use_rl and self.rl_agent:
            try:
                # Prepare state for RL
                state = {
                    'north_south': north_south,
                    'east_west': east_west,
                    'current_phase': 0 if self.current_phase == TrafficPhase.RED else
                                   1 if self.current_phase == TrafficPhase.YELLOW else 2,
                    'time_of_day': 0.5  # Normalized hour (can be improved)
                }

                # Get RL prediction
                phase_action, duration = self.rl_agent.predict_action(state)

                # Map RL action to a switch request against the active direction
                if phase_action == 1:  # NS should get green
                    wants_switch = self.active_direction != "north_south"
                elif phase_action == 2:  # EW should get green
                    wants_switch = self.active_direction != "east_west"
                else:  # Keep current
                    wants_switch = False

                logger.debug(f"RL agent recommended: action={phase_action}, duration={duration}s")

            except Exception as e:
                logger.warning(f"RL prediction failed, using rule-based: {e}")

        # Advance the phase state machine (mutates current_phase /
        # active_direction under min-green, yellow and all-red timing).
        recommended_phase = self._advance_phase(wants_switch, other_score)
        
        # Phase 2: Check for anomalies (single detect+classify pass)
        anomaly_type = None
        if self.use_anomaly_detection and self.anomaly_detector:
            try:
                is_anomaly, anomaly_score, anomaly_type = self.anomaly_detector.evaluate(
                    {"north_south": north_south, "east_west": east_west}
                )
                if is_anomaly:
                    logger.warning(f"⚠️  Anomaly detected: {anomaly_type} (score: {anomaly_score:.2f})")
            except Exception as e:  # noqa: BLE001 — advisory; never break the decision
                logger.warning(f"Anomaly detection failed: {e}")
        self._last_anomaly = anomaly_type
        
        # Escalate priority when the forecast (already folded into the scores
        # above) shows imminent congestion on either approach.
        prediction_adjustment = 0.0
        if self._last_prediction:
            peak = max(
                self._last_prediction.get("north_south", 0.0),
                self._last_prediction.get("east_west", 0.0),
            )
            if peak > 0.8:
                prediction_adjustment = 0.1
                logger.info("📊 Congestion predicted — escalating priority")

        # Calculate priority level (adjust for predictions)
        base_priority = self._determine_priority(priority_data, other_data)
        
        # Adjust priority based on predictions
        if prediction_adjustment > 0:
            if base_priority == DecisionPriority.MEDIUM:
                priority = DecisionPriority.HIGH
            elif base_priority == DecisionPriority.LOW:
                priority = DecisionPriority.MEDIUM
            else:
                priority = base_priority
        else:
            priority = base_priority
        
        # Emergency priority for anomalies
        if anomaly_type in ["CONGESTION", "HIGH_TRAFFIC"]:
            priority = DecisionPriority.EMERGENCY
        # Emergency-vehicle preemption is the highest priority of all.
        if preempt is not None:
            priority = DecisionPriority.EMERGENCY

        # Generate reason
        reason = self._generate_reason(
            priority_direction,
            priority_data,
            other_data,
            priority_score,
            other_score
        )
        # Surface a strong congestion forecast in the human-readable reason.
        if self._last_prediction:
            pdir = "N-S" if self._last_prediction["north_south"] >= self._last_prediction["east_west"] else "E-W"
            ppct = max(self._last_prediction["north_south"], self._last_prediction["east_west"])
            if ppct >= 0.5:
                reason = reason.rstrip(".") + f". Congestion forecast {pdir} {ppct:.0%} in {self._last_prediction['horizon_min']}min."

        # Calculate confidence
        confidence = self._calculate_confidence(priority_score, other_score, priority_data, other_data)

        # Calculate expected impact
        expected_impact = self._calculate_expected_impact(
            priority_data,
            other_data,
            recommended_phase
        )
        if self._last_prediction:
            expected_impact["predicted_congestion_ns"] = self._last_prediction["north_south"]
            expected_impact["predicted_congestion_ew"] = self._last_prediction["east_west"]
        if self._last_anomaly:
            expected_impact["anomaly"] = self._last_anomaly
            reason = reason.rstrip(".") + f". ⚠ Anomaly: {self._last_anomaly}."
        if self._last_transit and (self._last_transit["north_south"] or self._last_transit["east_west"]):
            tdir = "N-S" if self._last_transit["north_south"] else "E-W"
            reason = reason.rstrip(".") + f". 🚌 Transit priority {tdir}."
            expected_impact["transit_priority"] = tdir
        if coord_dir is not None:
            reason = reason.rstrip(".") + f". 🌊 Green-wave coordination ({'N-S' if coord_dir == 'north_south' else 'E-W'})."
            expected_impact["coordination"] = coord_dir
        if self._ped_hold_active:
            reason = reason.rstrip(".") + ". 🚶 Holding all-red for pedestrian clearance."
            expected_impact["pedestrian_clearance"] = True
        elif self._ped_present:
            expected_impact["pedestrian_present"] = True
        if preempt is not None:
            label = "N-S" if preempt == "north_south" else "E-W"
            reason = f"🚨 EMERGENCY VEHICLE PREEMPTION — clearing {label}. " + reason
            expected_impact["preemption"] = preempt

        # Create decision
        decision = TrafficDecision(
            decision_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            current_phase=previous_phase,
            recommended_phase=recommended_phase,
            priority=priority,
            reason=reason,
            confidence=confidence,
            expected_impact=expected_impact
        )
        
        # Update statistics
        self.statistics['total_decisions'] += 1
        self.statistics['average_confidence'] = (
            (self.statistics['average_confidence'] * (self.statistics['total_decisions'] - 1) + confidence) /
            self.statistics['total_decisions']
        )
        
        logger.info(f"Decision made: {recommended_phase.value} for {priority_direction} (confidence: {confidence:.2%})")
        
        return decision
    
    def set_coordination(self, offset_s: float, cycle_s: float, green_s: float, direction: str) -> None:
        """Join a green-wave corridor: bias `direction` to green while the
        corridor clock is within [offset_s, offset_s+green_s] each cycle."""
        if direction not in ("north_south", "east_west"):
            raise ValueError(f"invalid direction: {direction}")
        self._coord = {"offset_s": offset_s, "cycle_s": cycle_s, "green_s": green_s, "direction": direction}

    def clear_coordination(self) -> None:
        self._coord = None

    def _coordination_direction(self) -> Optional[str]:
        """The approach favoured by the green wave right now, or None. Uses the
        engine clock; in-process engines share an origin, so their bands align."""
        if not self._coord:
            return None
        phase = (self._now() - self._coord["offset_s"]) % self._coord["cycle_s"]
        return self._coord["direction"] if phase < self._coord["green_s"] else None

    def request_preemption(self, direction: str, hold_s: Optional[float] = None) -> None:
        """Trigger emergency-vehicle preemption for an approach.

        `direction` is 'north_south' or 'east_west'. `hold_s`, if given,
        auto-clears the preemption after that many seconds (else it holds until
        clear_preemption()). Typically driven by dispatch/V2X (Opticom-style)
        or an operator; visual auto-detection needs a trained EV detector.
        """
        if direction not in ("north_south", "east_west"):
            raise ValueError(f"invalid direction: {direction}")
        self._preempt_direction = direction
        self._preempt_until = (self._now() + hold_s) if hold_s else None
        logger.warning("🚨 Emergency preemption requested: %s", direction)

    def clear_preemption(self) -> None:
        if self._preempt_direction is not None:
            logger.warning("Emergency preemption cleared")
        self._preempt_direction = None
        self._preempt_until = None

    def _preemption_active(self) -> Optional[str]:
        if self._preempt_direction is None:
            return None
        if self._preempt_until is not None and self._now() >= self._preempt_until:
            self.clear_preemption()
            return None
        return self._preempt_direction

    def _apply_prediction(
        self, north_south: Dict, east_west: Dict, ns_score: float, ew_score: float
    ):
        """Fold a short-horizon congestion forecast into the direction scores.

        Returns (ns_score, ew_score, info) where `info` is the per-direction
        predicted congestion (0..1) or None when prediction is disabled/failed.
        The boost is bounded by `prediction_weight` so it can shade a decision
        proactively but never overrides current demand.
        """
        if not (self.use_predictions and self.predictor):
            return ns_score, ew_score, None
        try:
            self.predictor.update_history({"north_south": north_south, "east_west": east_west})
            congestion = self.predictor.predict_congestion(
                minutes_ahead=self.prediction_horizon_min
            )
            ns_c = float(congestion.get("north_south", 0.0))
            ew_c = float(congestion.get("east_west", 0.0))
            ns_score += ns_c * self.prediction_weight
            ew_score += ew_c * self.prediction_weight
            return ns_score, ew_score, {
                "north_south": round(ns_c, 2),
                "east_west": round(ew_c, 2),
                "horizon_min": self.prediction_horizon_min,
            }
        except Exception as e:  # noqa: BLE001 — advisory; never break the decision
            logger.warning(f"Prediction failed: {e}")
            return ns_score, ew_score, None

    def _rule_based_wants_switch(
        self,
        priority_direction: str,
        priority_score: float,
        other_score: float,
        waiting_vehicles: int = 999,
        current_vehicles: int = 0,
    ) -> bool:
        """Should green move to the other approach?

        True only when the demand winner is NOT the approach currently holding
        green AND its score clears the hysteresis threshold (prevents flapping)
        AND the switch is worth the clearance cost: the waiting approach has a
        non-trivial queue, or the current approach has gapped out (empty).
        `waiting_vehicles` defaults high so callers that don't pass counts keep
        the pure-ratio behaviour.
        """
        if priority_direction == self.active_direction:
            return False
        if priority_score <= other_score * self.switch_threshold:
            return False
        # Minimum-benefit gate: hold green rather than pay clearance to serve a
        # couple of cars while the current approach is still discharging.
        if waiting_vehicles < self.min_switch_vehicles and current_vehicles > 0:
            return False
        return True

    def _advance_phase(self, wants_switch: bool, other_demand: float) -> TrafficPhase:
        """Advance the signal state machine one decision tick.

        GREEN holds for at least `min_green_s`; a justified switch (or the
        `max_green_s` anti-starvation guard) starts a YELLOW → ALL_RED
        clearance, after which green flips to the opposite approach.
        NOTE: the downstream failsafe controller independently enforces its
        own hard invariants — this machine is the recommendation layer.
        """
        now = self._now()
        elapsed = now - self._phase_started_at

        if self.current_phase == TrafficPhase.GREEN:
            if elapsed < self.min_green_s:
                return TrafficPhase.GREEN
            starvation_guard = elapsed >= self.max_green_s and other_demand > 0.0
            if wants_switch or starvation_guard:
                self._begin_phase(TrafficPhase.YELLOW, now)
            return self.current_phase

        if self.current_phase == TrafficPhase.YELLOW:
            if elapsed >= self.yellow_s:
                self._begin_phase(TrafficPhase.ALL_RED, now)
            return self.current_phase

        if self.current_phase == TrafficPhase.ALL_RED:
            # Pedestrian protection: once the base clearance has elapsed, keep
            # holding all-red while a pedestrian is still in the roadway, up to
            # a bounded maximum so the intersection can never be stalled.
            self._ped_hold_active = (
                self._ped_present
                and elapsed >= self.all_red_s
                and elapsed < self.all_red_s + self.max_ped_extend_s
            )
            if elapsed >= self.all_red_s and not self._ped_hold_active:
                self.active_direction = (
                    "east_west" if self.active_direction == "north_south" else "north_south"
                )
                self._begin_phase(TrafficPhase.GREEN, now)
                logger.info(f"Green handed to {self.active_direction}")
            return self.current_phase

        # Legacy RED value (set only via external reset paths): treat as
        # completed clearance and restart green on the active approach.
        self._begin_phase(TrafficPhase.GREEN, now)
        return self.current_phase

    def _begin_phase(self, phase: TrafficPhase, now: float) -> None:
        """Transition to a new phase and stamp its start time."""
        if phase != self.current_phase:
            self.statistics['phase_changes'] += 1
            logger.info(f"Phase change: {self.current_phase.value} → {phase.value}")
        self.current_phase = phase
        self._phase_started_at = now
    
    def _calculate_direction_score(self, direction_data: Dict) -> float:
        """
        Calculate priority score for a direction
        
        Higher score = higher priority for green light
        """
        vehicle_count = direction_data.get('vehicle_count', 0)
        avg_emission = direction_data.get('average_emission', 0.0)
        waiting_time = direction_data.get('average_waiting_time', 0.0)
        velocity = direction_data.get('average_velocity', 0.0)
        env_score = direction_data.get('environmental_impact_score', 0.0)
        
        # Normalize values (0-1 scale)
        vehicle_score = min(1.0, vehicle_count / 20.0)  # Max 20 vehicles = score 1.0
        emission_score = min(1.0, avg_emission / 200.0)  # Max 200 g/km = score 1.0
        waiting_score = min(1.0, waiting_time / 60.0)  # Max 60 seconds = score 1.0
        flow_score = min(1.0, max(0.0, (velocity - 5.0) / 50.0))  # 5-55 km/h range
        
        # Weighted combination
        score = (
            vehicle_score * self.weights['vehicle_count'] +
            emission_score * self.weights['emissions'] +
            waiting_score * self.weights['waiting_time'] +
            flow_score * self.weights['traffic_flow']
        )
        
        # Transit signal priority: soft bounded bonus when a bus is present.
        if direction_data.get('transit_present'):
            score += self.transit_weight

        # Boost for high environmental impact
        if env_score > 70:
            score *= 1.2  # 20% boost for high emissions

        return score
    
    def _determine_priority(
        self,
        priority_data: Dict,
        other_data: Dict
    ) -> DecisionPriority:
        """Determine decision priority level"""
        priority_vehicles = priority_data.get('vehicle_count', 0)
        priority_emissions = priority_data.get('environmental_impact_score', 0.0)
        priority_waiting = priority_data.get('average_waiting_time', 0.0)
        
        # Emergency: Very high traffic, very high emissions, long waiting
        if (priority_vehicles > 15 and priority_emissions > 80 and priority_waiting > 45):
            return DecisionPriority.EMERGENCY
        
        # High: High traffic or high emissions
        if (priority_vehicles > 10 or priority_emissions > 70 or priority_waiting > 30):
            return DecisionPriority.HIGH
        
        # Medium: Moderate traffic
        if (priority_vehicles > 5 or priority_emissions > 50):
            return DecisionPriority.MEDIUM
        
        # Low: Low traffic
        return DecisionPriority.LOW
    
    def _generate_reason(
        self,
        priority_direction: str,
        priority_data: Dict,
        other_data: Dict,
        priority_score: float,
        other_score: float
    ) -> str:
        """Generate human-readable reason for decision"""
        priority_vehicles = priority_data.get('vehicle_count', 0)
        priority_emissions = priority_data.get('average_emission', 0.0)
        priority_waiting = priority_data.get('average_waiting_time', 0.0)
        
        reasons = []
        
        if priority_vehicles > other_data.get('vehicle_count', 0) * 1.5:
            reasons.append(f"{priority_direction.replace('_', '-').title()} has {priority_vehicles} vehicles")
        
        if priority_emissions > 150:
            reasons.append(f"High emissions ({priority_emissions:.1f} g/km)")
        
        if priority_waiting > 30:
            reasons.append(f"Long waiting time ({priority_waiting:.1f}s)")
        
        if priority_score > other_score * 1.3:
            reasons.append("Significant traffic imbalance")
        
        if not reasons:
            reasons.append("Balanced traffic flow")
        
        return ". ".join(reasons) + "."
    
    def _calculate_confidence(
        self,
        priority_score: float,
        other_score: float,
        priority_data: Dict,
        other_data: Dict
    ) -> float:
        """Calculate confidence in decision (0.0 to 1.0)"""
        # Base confidence from score difference
        score_diff = abs(priority_score - other_score)
        base_confidence = min(1.0, score_diff * 2.0)  # Max confidence at 0.5 difference
        
        # Boost confidence if data is consistent
        priority_vehicles = priority_data.get('vehicle_count', 0)
        other_vehicles = other_data.get('vehicle_count', 0)
        
        if priority_vehicles > 0 and other_vehicles > 0:
            # High confidence if clear difference
            vehicle_ratio = priority_vehicles / max(other_vehicles, 1)
            if vehicle_ratio > 2.0:
                base_confidence = min(1.0, base_confidence + 0.2)
            elif vehicle_ratio > 1.5:
                base_confidence = min(1.0, base_confidence + 0.1)
        
        # Reduce confidence if scores are very close
        if score_diff < 0.1:
            base_confidence *= 0.7
        
        return max(0.5, min(1.0, base_confidence))  # Clamp between 0.5 and 1.0
    
    def _calculate_expected_impact(
        self,
        priority_data: Dict,
        other_data: Dict,
        recommended_phase: TrafficPhase
    ) -> Dict[str, float]:
        """Calculate expected impact of decision"""
        priority_emissions = priority_data.get('average_emission', 0.0)
        priority_waiting = priority_data.get('average_waiting_time', 0.0)
        priority_vehicles = priority_data.get('vehicle_count', 0)
        
        # Estimate emission reduction (vehicles moving = less idle emissions)
        emission_reduction = priority_emissions * priority_vehicles * 0.1  # 10% reduction estimate
        
        # Estimate waiting time reduction
        waiting_reduction = priority_waiting * 0.3  # 30% reduction estimate
        
        # Estimate traffic flow improvement
        flow_improvement = min(100.0, priority_vehicles * 5.0)  # 5% per vehicle, max 100%
        
        return {
            'emission_reduction_kg': emission_reduction / 1000.0,  # Convert to kg
            'waiting_time_reduction_s': waiting_reduction,
            'traffic_flow_improvement_percent': flow_improvement,
            'vehicles_served': priority_vehicles
        }
    
    def execute_decision(self, decision: TrafficDecision):
        """
        Record an executed decision.

        The phase itself is advanced by the state machine inside
        `make_decision` (so callers that never call execute_decision — e.g.
        the simulation harness — still get correct phase progression); this
        method records history and impact statistics.

        Args:
            decision: TrafficDecision to execute
        """
        self.phase_history.append(decision)
        
        # Keep only last 100 decisions
        if len(self.phase_history) > 100:
            self.phase_history.pop(0)
        
        # Update emission reduction statistics
        if 'emission_reduction_kg' in decision.expected_impact:
            self.statistics['total_emission_reduction'] += decision.expected_impact['emission_reduction_kg']
    
    def get_statistics(self) -> Dict:
        """Get engine statistics"""
        return {
            **self.statistics,
            'current_phase': self.current_phase.value,
            'decision_count': self.decision_count,
            'recent_decisions': len(self.phase_history)
        }
    
    def reset(self):
        """Reset engine state"""
        self.current_phase = TrafficPhase.GREEN
        self.active_direction = "north_south"
        self._phase_started_at = self._now()
        self.phase_history = []
        self.decision_count = 0
        self.statistics = {
            'total_decisions': 0,
            'phase_changes': 0,
            'average_confidence': 0.0,
            'total_emission_reduction': 0.0
        }
        logger.info("Decision engine reset")


# For backward compatibility and direct usage
if __name__ == "__main__":
    # Example usage
    engine = AIDecisionEngine()
    
    # Example traffic data
    north_south = {
        'vehicle_count': 12,
        'average_emission': 180.0,
        'average_waiting_time': 35.0,
        'average_velocity': 8.0,
        'total_emission': 2160.0,
        'environmental_impact_score': 75.0
    }
    
    east_west = {
        'vehicle_count': 5,
        'average_emission': 150.0,
        'average_waiting_time': 15.0,
        'average_velocity': 12.0,
        'total_emission': 750.0,
        'environmental_impact_score': 50.0
    }
    
    # Make decision
    decision = engine.make_decision(north_south, east_west)
    
    print("\n" + "="*60)
    print("TRAFFIC DECISION")
    print("="*60)
    print(f"Decision ID: {decision.decision_id}")
    print(f"Timestamp: {decision.timestamp}")
    print(f"Current Phase: {decision.current_phase.value}")
    print(f"Recommended Phase: {decision.recommended_phase.value}")
    print(f"Priority: {decision.priority.value}")
    print(f"Reason: {decision.reason}")
    print(f"Confidence: {decision.confidence:.1%}")
    print(f"\nExpected Impact:")
    for key, value in decision.expected_impact.items():
        print(f"  {key}: {value:.2f}")
    print("="*60)
    
    # Execute decision
    engine.execute_decision(decision)
    
    # Get statistics
    stats = engine.get_statistics()
    print(f"\nStatistics: {stats}")

