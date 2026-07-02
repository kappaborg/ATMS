"""
ATMS-Specific Optimization Module
Based on research from City-scale Vehicle Trajectory Data study
https://pmc.ncbi.nlm.nih.gov/articles/PMC10582153/

This module implements traffic signal optimization, pedestrian safety,
and emergency vehicle priority using trajectory predictions.
"""

import numpy as np
from typing import List, Dict, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
import time
import logging
from collections import defaultdict, deque
import math

logger = logging.getLogger(__name__)

class SignalState(Enum):
    """Traffic signal states"""
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    TURNING_ARROW = "turning_arrow"

class PriorityLevel(Enum):
    """Priority levels for traffic management"""
    EMERGENCY = 1
    PEDESTRIAN = 2
    VEHICLE = 3
    CYCLIST = 4

@dataclass
class SignalOptimization:
    """Traffic signal optimization result"""
    intersection_id: int
    current_phase: str
    recommended_phase: str
    phase_duration: float
    confidence: float
    expected_benefit: float
    affected_vehicles: int
    wait_time_reduction: float

@dataclass
class PedestrianSafety:
    """Pedestrian safety analysis result"""
    intersection_id: int
    crossing_pedestrians: int
    jaywalking_risk: float
    safety_score: float
    recommended_action: str
    crossing_time_estimate: float

@dataclass
class EmergencyPriority:
    """Emergency vehicle priority result"""
    intersection_id: int
    emergency_vehicle_id: int
    estimated_arrival: float
    clearance_time: float
    affected_vehicles: int
    recommended_phases: List[str]

class ATMSTrafficOptimizer:
    """
    ATMS-specific traffic optimization using trajectory predictions
    Implements signal optimization, pedestrian safety, and emergency priority
    """
    
    def __init__(self, intersection_id: int, 
                 signal_phases: List[str] = None,
                 min_phase_duration: float = 5.0,
                 max_phase_duration: float = 60.0):
        """
        Initialize ATMS traffic optimizer
        
        Args:
            intersection_id: Unique intersection identifier
            signal_phases: Available signal phases
            min_phase_duration: Minimum phase duration in seconds
            max_phase_duration: Maximum phase duration in seconds
        """
        self.intersection_id = intersection_id
        self.signal_phases = signal_phases or ["north_south", "east_west", "left_turn"]
        self.min_phase_duration = min_phase_duration
        self.max_phase_duration = max_phase_duration
        
        # Current state
        self.current_phase = "north_south"
        self.phase_start_time = time.time()
        self.phase_duration = 30.0  # Default 30 seconds
        
        # Optimization parameters
        self.optimization_weights = {
            'wait_time': 0.4,
            'throughput': 0.3,
            'safety': 0.2,
            'efficiency': 0.1
        }
        
        # Historical data
        self.phase_performance = defaultdict(list)
        self.vehicle_wait_times = defaultdict(list)
        self.pedestrian_crossings = deque(maxlen=1000)
        
        logger.info(f"ATMS Traffic Optimizer initialized for intersection {intersection_id}")
    
    def optimize_signal_timing(self, trajectory_predictions: List[Dict], 
                             current_time: float) -> SignalOptimization:
        """
        Optimize traffic signal timing based on trajectory predictions
        
        Args:
            trajectory_predictions: List of trajectory prediction results
            current_time: Current timestamp
        
        Returns:
            Signal optimization recommendation
        """
        # Analyze current traffic state
        traffic_analysis = self._analyze_traffic_state(trajectory_predictions)
        
        # Calculate optimization for each phase
        phase_scores = {}
        for phase in self.signal_phases:
            score = self._calculate_phase_score(phase, traffic_analysis, current_time)
            phase_scores[phase] = score
        
        # Select best phase
        best_phase = max(phase_scores, key=phase_scores.get)
        best_score = phase_scores[best_phase]
        
        # Calculate recommended duration
        recommended_duration = self._calculate_optimal_duration(
            best_phase, traffic_analysis, current_time
        )
        
        # Calculate expected benefits
        expected_benefit = self._calculate_expected_benefit(
            best_phase, traffic_analysis, recommended_duration
        )
        
        # Count affected vehicles
        affected_vehicles = self._count_affected_vehicles(
            best_phase, trajectory_predictions
        )
        
        # Estimate wait time reduction
        wait_time_reduction = self._estimate_wait_time_reduction(
            best_phase, traffic_analysis
        )
        
        return SignalOptimization(
            intersection_id=self.intersection_id,
            current_phase=self.current_phase,
            recommended_phase=best_phase,
            phase_duration=recommended_duration,
            confidence=min(best_score, 1.0),
            expected_benefit=expected_benefit,
            affected_vehicles=affected_vehicles,
            wait_time_reduction=wait_time_reduction
        )
    
    def analyze_pedestrian_safety(self, trajectory_predictions: List[Dict], 
                                current_time: float) -> PedestrianSafety:
        """
        Analyze pedestrian safety based on trajectory predictions
        
        Args:
            trajectory_predictions: List of trajectory prediction results
            current_time: Current timestamp
        
        Returns:
            Pedestrian safety analysis result
        """
        # Filter pedestrian predictions
        pedestrian_predictions = [
            pred for pred in trajectory_predictions 
            if pred.get('object_type') == 'pedestrian'
        ]
        
        # Count crossing pedestrians
        crossing_pedestrians = self._count_crossing_pedestrians(pedestrian_predictions)
        
        # Calculate jaywalking risk
        jaywalking_risk = self._calculate_jaywalking_risk(pedestrian_predictions)
        
        # Calculate safety score
        safety_score = self._calculate_safety_score(
            crossing_pedestrians, jaywalking_risk
        )
        
        # Recommend action
        recommended_action = self._recommend_pedestrian_action(
            crossing_pedestrians, jaywalking_risk, safety_score
        )
        
        # Estimate crossing time
        crossing_time = self._estimate_crossing_time(pedestrian_predictions)
        
        return PedestrianSafety(
            intersection_id=self.intersection_id,
            crossing_pedestrians=crossing_pedestrians,
            jaywalking_risk=jaywalking_risk,
            safety_score=safety_score,
            recommended_action=recommended_action,
            crossing_time_estimate=crossing_time
        )
    
    def handle_emergency_priority(self, trajectory_predictions: List[Dict], 
                                emergency_vehicle_id: int,
                                current_time: float) -> EmergencyPriority:
        """
        Handle emergency vehicle priority
        
        Args:
            trajectory_predictions: List of trajectory prediction results
            emergency_vehicle_id: ID of emergency vehicle
            current_time: Current timestamp
        
        Returns:
            Emergency priority handling result
        """
        # Find emergency vehicle prediction
        emergency_pred = None
        for pred in trajectory_predictions:
            if pred.get('track_id') == emergency_vehicle_id:
                emergency_pred = pred
                break
        
        if not emergency_pred:
            return None
        
        # Estimate arrival time
        estimated_arrival = self._estimate_emergency_arrival(
            emergency_pred, current_time
        )
        
        # Calculate clearance time
        clearance_time = self._calculate_clearance_time(
            emergency_pred, trajectory_predictions
        )
        
        # Count affected vehicles
        affected_vehicles = self._count_affected_vehicles_for_emergency(
            emergency_pred, trajectory_predictions
        )
        
        # Recommend signal phases
        recommended_phases = self._recommend_emergency_phases(
            emergency_pred, trajectory_predictions
        )
        
        return EmergencyPriority(
            intersection_id=self.intersection_id,
            emergency_vehicle_id=emergency_vehicle_id,
            estimated_arrival=estimated_arrival,
            clearance_time=clearance_time,
            affected_vehicles=affected_vehicles,
            recommended_phases=recommended_phases
        )
    
    def _analyze_traffic_state(self, trajectory_predictions: List[Dict]) -> Dict:
        """Analyze current traffic state from trajectory predictions"""
        analysis = {
            'vehicle_count': 0,
            'pedestrian_count': 0,
            'average_speed': 0.0,
            'queue_lengths': {},
            'approaching_vehicles': 0,
            'turning_vehicles': 0
        }
        
        speeds = []
        queue_lengths = defaultdict(int)
        
        for pred in trajectory_predictions:
            obj_type = pred.get('object_type', 'vehicle')
            
            if obj_type == 'vehicle':
                analysis['vehicle_count'] += 1
                
                # Calculate speed
                velocity = pred.get('current_velocity', (0, 0))
                speed = math.sqrt(velocity[0]**2 + velocity[1]**2)
                speeds.append(speed)
                
                # Determine approach direction and queue
                approach_dir = self._determine_approach_direction(pred)
                queue_lengths[approach_dir] += 1
                
                # Check if approaching intersection
                if self._is_approaching_intersection(pred):
                    analysis['approaching_vehicles'] += 1
                
                # Check for turning intention
                if self._has_turning_intention(pred):
                    analysis['turning_vehicles'] += 1
            
            elif obj_type == 'pedestrian':
                analysis['pedestrian_count'] += 1
        
        analysis['average_speed'] = np.mean(speeds) if speeds else 0.0
        analysis['queue_lengths'] = dict(queue_lengths)
        
        return analysis
    
    def _calculate_phase_score(self, phase: str, traffic_analysis: Dict, 
                             current_time: float) -> float:
        """Calculate optimization score for a signal phase"""
        score = 0.0
        
        # Weight by current traffic in that direction
        if phase in traffic_analysis['queue_lengths']:
            queue_length = traffic_analysis['queue_lengths'][phase]
            score += queue_length * 0.3
        
        # Weight by approaching vehicles
        if phase in ['north_south', 'east_west']:
            score += traffic_analysis['approaching_vehicles'] * 0.2
        
        # Weight by turning vehicles
        if phase == 'left_turn':
            score += traffic_analysis['turning_vehicles'] * 0.4
        
        # Consider current phase duration
        current_duration = current_time - self.phase_start_time
        if current_duration > self.max_phase_duration:
            score += 0.5  # Force phase change
        elif current_duration < self.min_phase_duration:
            score -= 0.3  # Discourage premature change
        
        return max(score, 0.0)
    
    def _calculate_optimal_duration(self, phase: str, traffic_analysis: Dict, 
                                   current_time: float) -> float:
        """Calculate optimal duration for a signal phase"""
        base_duration = 30.0  # Default 30 seconds
        
        # Adjust based on traffic volume
        if phase in traffic_analysis['queue_lengths']:
            queue_length = traffic_analysis['queue_lengths'][phase]
            base_duration += queue_length * 2.0  # 2 seconds per vehicle
        
        # Adjust for approaching vehicles
        base_duration += traffic_analysis['approaching_vehicles'] * 1.0
        
        # Ensure within bounds
        return max(self.min_phase_duration, 
                  min(base_duration, self.max_phase_duration))
    
    def _calculate_expected_benefit(self, phase: str, traffic_analysis: Dict, 
                                  duration: float) -> float:
        """Calculate expected benefit of a signal phase"""
        benefit = 0.0
        
        # Reduce wait time for queued vehicles
        if phase in traffic_analysis['queue_lengths']:
            queue_length = traffic_analysis['queue_lengths'][phase]
            benefit += queue_length * 10.0  # 10 points per vehicle
        
        # Improve throughput
        benefit += traffic_analysis['approaching_vehicles'] * 5.0
        
        # Safety bonus
        benefit += traffic_analysis['pedestrian_count'] * 2.0
        
        return benefit
    
    def _count_affected_vehicles(self, phase: str, 
                                trajectory_predictions: List[Dict]) -> int:
        """Count vehicles affected by a signal phase"""
        count = 0
        for pred in trajectory_predictions:
            if pred.get('object_type') == 'vehicle':
                # Check if vehicle is in the phase direction
                if self._is_vehicle_in_phase_direction(pred, phase):
                    count += 1
        return count
    
    def _estimate_wait_time_reduction(self, phase: str, 
                                    traffic_analysis: Dict) -> float:
        """Estimate wait time reduction from signal optimization"""
        if phase in traffic_analysis['queue_lengths']:
            queue_length = traffic_analysis['queue_lengths'][phase]
            # Estimate 5 seconds reduction per queued vehicle
            return queue_length * 5.0
        return 0.0
    
    def _count_crossing_pedestrians(self, pedestrian_predictions: List[Dict]) -> int:
        """Count pedestrians currently crossing"""
        count = 0
        for pred in pedestrian_predictions:
            if self._is_pedestrian_crossing(pred):
                count += 1
        return count
    
    def _calculate_jaywalking_risk(self, pedestrian_predictions: List[Dict]) -> float:
        """Calculate jaywalking risk score"""
        risk_score = 0.0
        for pred in pedestrian_predictions:
            if self._is_pedestrian_jaywalking(pred):
                risk_score += 1.0
        return min(risk_score / 10.0, 1.0)  # Normalize to 0-1
    
    def _calculate_safety_score(self, crossing_pedestrians: int, 
                              jaywalking_risk: float) -> float:
        """Calculate overall pedestrian safety score"""
        # Base score from crossing pedestrians
        base_score = 1.0 - (crossing_pedestrians * 0.1)
        
        # Penalty for jaywalking risk
        jaywalking_penalty = jaywalking_risk * 0.3
        
        return max(0.0, base_score - jaywalking_penalty)
    
    def _recommend_pedestrian_action(self, crossing_pedestrians: int, 
                                   jaywalking_risk: float, 
                                   safety_score: float) -> str:
        """Recommend action for pedestrian safety"""
        if safety_score < 0.3:
            return "extend_pedestrian_phase"
        elif jaywalking_risk > 0.7:
            return "activate_pedestrian_warning"
        elif crossing_pedestrians > 5:
            return "extend_pedestrian_phase"
        else:
            return "normal_operation"
    
    def _estimate_crossing_time(self, pedestrian_predictions: List[Dict]) -> float:
        """Estimate time for pedestrians to cross intersection"""
        if not pedestrian_predictions:
            return 0.0
        
        # Calculate average crossing time based on predictions
        crossing_times = []
        for pred in pedestrian_predictions:
            if self._is_pedestrian_crossing(pred):
                # Estimate crossing time based on trajectory
                crossing_time = self._calculate_pedestrian_crossing_time(pred)
                crossing_times.append(crossing_time)
        
        return np.mean(crossing_times) if crossing_times else 15.0  # Default 15 seconds
    
    def _estimate_emergency_arrival(self, emergency_pred: Dict, 
                                  current_time: float) -> float:
        """Estimate emergency vehicle arrival time"""
        if not emergency_pred:
            return float('inf')
        
        # Calculate distance to intersection
        current_pos = emergency_pred.get('current_position', (0, 0))
        distance = self._calculate_distance_to_intersection(current_pos)
        
        # Calculate speed
        velocity = emergency_pred.get('current_velocity', (0, 0))
        speed = math.sqrt(velocity[0]**2 + velocity[1]**2)
        
        if speed > 0:
            arrival_time = distance / speed
            return current_time + arrival_time
        
        return float('inf')
    
    def _calculate_clearance_time(self, emergency_pred: Dict, 
                                 trajectory_predictions: List[Dict]) -> float:
        """Calculate time needed to clear intersection for emergency vehicle"""
        # Estimate based on current traffic
        affected_vehicles = self._count_affected_vehicles_for_emergency(
            emergency_pred, trajectory_predictions
        )
        
        # Estimate 3 seconds per affected vehicle
        return affected_vehicles * 3.0
    
    def _count_affected_vehicles_for_emergency(self, emergency_pred: Dict, 
                                              trajectory_predictions: List[Dict]) -> int:
        """Count vehicles that need to be cleared for emergency vehicle"""
        count = 0
        emergency_path = self._predict_emergency_path(emergency_pred)
        
        for pred in trajectory_predictions:
            if pred.get('object_type') == 'vehicle':
                vehicle_path = self._predict_vehicle_path(pred)
                if self._paths_intersect(emergency_path, vehicle_path):
                    count += 1
        
        return count
    
    def _recommend_emergency_phases(self, emergency_pred: Dict, 
                                   trajectory_predictions: List[Dict]) -> List[str]:
        """Recommend signal phases for emergency vehicle clearance"""
        emergency_direction = self._determine_emergency_direction(emergency_pred)
        
        if emergency_direction in ['north', 'south']:
            return ['north_south', 'left_turn']
        elif emergency_direction in ['east', 'west']:
            return ['east_west', 'left_turn']
        else:
            return ['north_south', 'east_west']
    
    # Helper methods for analysis
    def _determine_approach_direction(self, pred: Dict) -> str:
        """Determine approach direction of vehicle"""
        # Simplified direction detection
        velocity = pred.get('current_velocity', (0, 0))
        if abs(velocity[0]) > abs(velocity[1]):
            return 'east_west' if velocity[0] > 0 else 'west_east'
        else:
            return 'north_south' if velocity[1] > 0 else 'south_north'
    
    def _is_approaching_intersection(self, pred: Dict) -> bool:
        """Check if vehicle is approaching intersection"""
        # Simplified approach detection
        current_pos = pred.get('current_position', (0, 0))
        distance = self._calculate_distance_to_intersection(current_pos)
        return distance < 100  # Within 100 pixels
    
    def _has_turning_intention(self, pred: Dict) -> bool:
        """Check if vehicle has turning intention"""
        # Simplified turning detection
        intention = pred.get('intention', '')
        return intention in ['left', 'right']
    
    def _is_vehicle_in_phase_direction(self, pred: Dict, phase: str) -> bool:
        """Check if vehicle is in the signal phase direction"""
        approach_dir = self._determine_approach_direction(pred)
        return approach_dir.startswith(phase.split('_')[0])
    
    def _is_pedestrian_crossing(self, pred: Dict) -> bool:
        """Check if pedestrian is crossing intersection"""
        # Simplified crossing detection
        current_pos = pred.get('current_position', (0, 0))
        return self._is_position_in_crossing_area(current_pos)
    
    def _is_pedestrian_jaywalking(self, pred: Dict) -> bool:
        """Check if pedestrian is jaywalking"""
        # Simplified jaywalking detection
        intention = pred.get('intention', '')
        return intention == 'jaywalking'
    
    def _calculate_pedestrian_crossing_time(self, pred: Dict) -> float:
        """Calculate pedestrian crossing time"""
        # Simplified crossing time calculation
        return 15.0  # Default 15 seconds
    
    def _calculate_distance_to_intersection(self, position: Tuple[float, float]) -> float:
        """Calculate distance from position to intersection center"""
        # Simplified distance calculation
        intersection_center = (500, 500)  # Assume intersection center
        return math.sqrt((position[0] - intersection_center[0])**2 + 
                        (position[1] - intersection_center[1])**2)
    
    def _is_position_in_crossing_area(self, position: Tuple[float, float]) -> bool:
        """Check if position is in pedestrian crossing area"""
        # Simplified crossing area detection
        return (400 < position[0] < 600 and 400 < position[1] < 600)
    
    def _predict_emergency_path(self, emergency_pred: Dict) -> List[Tuple[float, float]]:
        """Predict emergency vehicle path"""
        # Simplified path prediction
        current_pos = emergency_pred.get('current_position', (0, 0))
        velocity = emergency_pred.get('current_velocity', (0, 0))
        
        path = [current_pos]
        for i in range(10):
            next_x = current_pos[0] + velocity[0] * (i + 1)
            next_y = current_pos[1] + velocity[1] * (i + 1)
            path.append((next_x, next_y))
        
        return path
    
    def _predict_vehicle_path(self, pred: Dict) -> List[Tuple[float, float]]:
        """Predict vehicle path"""
        # Simplified path prediction
        current_pos = pred.get('current_position', (0, 0))
        velocity = pred.get('current_velocity', (0, 0))
        
        path = [current_pos]
        for i in range(5):
            next_x = current_pos[0] + velocity[0] * (i + 1)
            next_y = current_pos[1] + velocity[1] * (i + 1)
            path.append((next_x, next_y))
        
        return path
    
    def _paths_intersect(self, path1: List[Tuple[float, float]], 
                        path2: List[Tuple[float, float]]) -> bool:
        """Check if two paths intersect"""
        # Simplified intersection detection
        for p1 in path1:
            for p2 in path2:
                distance = math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)
                if distance < 50:  # Within 50 pixels
                    return True
        return False
    
    def _determine_emergency_direction(self, emergency_pred: Dict) -> str:
        """Determine emergency vehicle direction"""
        velocity = emergency_pred.get('current_velocity', (0, 0))
        if abs(velocity[0]) > abs(velocity[1]):
            return 'east' if velocity[0] > 0 else 'west'
        else:
            return 'north' if velocity[1] > 0 else 'south'
    
    def update_performance_metrics(self, optimization_result: SignalOptimization):
        """Update performance metrics based on optimization results"""
        self.phase_performance[self.current_phase].append({
            'duration': optimization_result.phase_duration,
            'benefit': optimization_result.expected_benefit,
            'timestamp': time.time()
        })
    
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics for the optimizer"""
        return {
            'intersection_id': self.intersection_id,
            'current_phase': self.current_phase,
            'phase_duration': time.time() - self.phase_start_time,
            'total_optimizations': sum(len(phases) for phases in self.phase_performance.values()),
            'average_benefit': np.mean([
                perf['benefit'] for phases in self.phase_performance.values() 
                for perf in phases
            ]) if any(self.phase_performance.values()) else 0.0
        }
