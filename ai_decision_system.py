#!/usr/bin/env python3
"""
AI Decision System for Traffic Management
=========================================
Intelligent traffic light control system based on vehicle count, emissions, and traffic flow.
Makes real-time decisions to optimize traffic flow and minimize environmental impact.
"""

from enum import Enum
from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass
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
    
    def __init__(self, use_rl: bool = False, use_predictions: bool = False, use_anomaly_detection: bool = False):
        """Initialize the decision engine"""
        self.current_phase = TrafficPhase.GREEN
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
        east_west: Dict
    ) -> TrafficDecision:
        """
        Make a traffic decision based on traffic data from two directions
        
        Args:
            north_south: Traffic data for north-south direction
            east_west: Traffic data for east-west direction
        
        Returns:
            TrafficDecision object with recommended action
        """
        self.decision_count += 1
        
        # Calculate scores for each direction
        ns_score = self._calculate_direction_score(north_south)
        ew_score = self._calculate_direction_score(east_west)
        
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
        
        # Phase 2: Use RL agent if available
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
                
                # Map RL action to phase
                if phase_action == 1:  # Change to NS
                    recommended_phase = TrafficPhase.GREEN  # NS gets green
                elif phase_action == 2:  # Change to EW
                    recommended_phase = TrafficPhase.GREEN  # EW gets green (can be extended)
                else:  # Keep current
                    recommended_phase = self.current_phase
                
                logger.debug(f"RL agent recommended: action={phase_action}, duration={duration}s")
                
            except Exception as e:
                logger.warning(f"RL prediction failed, using rule-based: {e}")
                # Fall through to rule-based logic
                recommended_phase = self._rule_based_phase(priority_direction, priority_score, other_score)
        else:
            # Rule-based decision (original logic)
            recommended_phase = self._rule_based_phase(priority_direction, priority_score, other_score)
        
        # Phase 2: Check for anomalies
        anomaly_type = None
        if self.use_anomaly_detection and self.anomaly_detector:
            try:
                metrics_dict = {
                    'north_south': north_south,
                    'east_west': east_west
                }
                is_anomaly, anomaly_score = self.anomaly_detector.detect_anomaly(metrics_dict)
                if is_anomaly:
                    anomaly_type = self.anomaly_detector.classify_anomaly(metrics_dict)
                    logger.warning(f"⚠️  Anomaly detected: {anomaly_type} (score: {anomaly_score:.2f})")
            except Exception as e:
                logger.warning(f"Anomaly detection failed: {e}")
        
        # Phase 2: Use predictions if available
        prediction_adjustment = 0.0
        if self.use_predictions and self.predictor:
            try:
                # Update predictor history
                metrics_dict = {
                    'north_south': north_south,
                    'east_west': east_west
                }
                self.predictor.update_history(metrics_dict)
                
                # Predict congestion
                congestion = self.predictor.predict_congestion(minutes_ahead=15)
                if congestion['north_south'] > 0.8 or congestion['east_west'] > 0.8:
                    prediction_adjustment = 0.1  # Boost priority if congestion predicted
                    logger.info(f"📊 Congestion predicted - adjusting decision")
            except Exception as e:
                logger.warning(f"Prediction failed: {e}")
        
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
        
        # Generate reason
        reason = self._generate_reason(
            priority_direction,
            priority_data,
            other_data,
            priority_score,
            other_score
        )
        
        # Calculate confidence
        confidence = self._calculate_confidence(priority_score, other_score, priority_data, other_data)
        
        # Calculate expected impact
        expected_impact = self._calculate_expected_impact(
            priority_data,
            other_data,
            recommended_phase
        )
        
        # Create decision
        decision = TrafficDecision(
            decision_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            current_phase=self.current_phase,
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
    
    def _rule_based_phase(self, priority_direction: str, priority_score: float, other_score: float) -> TrafficPhase:
        """Rule-based phase determination (original logic)"""
        if priority_score > other_score * 1.2:  # 20% threshold
            # Clear priority - recommend green for priority direction
            return TrafficPhase.GREEN
        elif priority_score > other_score * 1.1:  # 10% threshold
            # Moderate priority - extend current phase if already green
            return self.current_phase if self.current_phase == TrafficPhase.GREEN else TrafficPhase.GREEN
        else:
            # Balanced traffic - maintain current or switch
            return TrafficPhase.GREEN
    
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
        Execute a traffic decision (update current phase)
        
        Args:
            decision: TrafficDecision to execute
        """
        if decision.recommended_phase != self.current_phase:
            self.statistics['phase_changes'] += 1
            logger.info(f"Phase change: {self.current_phase.value} → {decision.recommended_phase.value}")
        
        self.current_phase = decision.recommended_phase
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

