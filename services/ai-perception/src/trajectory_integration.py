"""
Integrated Trajectory Prediction System for ATMS
Based on research from City-scale Vehicle Trajectory Data study
https://pmc.ncbi.nlm.nih.gov/articles/PMC10582153/

This module integrates object tracking, trajectory prediction, and ATMS optimization
for real-time traffic management systems.
"""

import asyncio
import time
import logging
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from collections import defaultdict, deque
import numpy as np

from tracking import OptimizedObjectTracker, ObjectType, TrackedObject
from tracking.bytetrack_tracker import ByteTrackWrapper
from trajectory import HybridTrajectoryPredictor, TrajectoryPrediction
from optimization import ATMSTrafficOptimizer, SignalOptimization, PedestrianSafety, EmergencyPriority
from collections import deque

logger = logging.getLogger(__name__)

@dataclass
class ATMSProcessingResult:
    """Complete ATMS processing result"""
    frame_id: str
    timestamp: float
    tracked_objects: List[TrackedObject]
    trajectory_predictions: List[TrajectoryPrediction]
    signal_optimization: Optional[SignalOptimization]
    pedestrian_safety: Optional[PedestrianSafety]
    emergency_priority: Optional[EmergencyPriority]
    processing_time_ms: float
    performance_metrics: Dict[str, Any]

class IntegratedATMSSystem:
    """
    Integrated ATMS system combining tracking, prediction, and optimization
    Optimized for real-time performance and production deployment
    """
    
    def __init__(self, intersection_id: int = 1, 
                 prediction_horizon: float = 5.0,
                 optimization_enabled: bool = True):
        """
        Initialize integrated ATMS system
        
        Args:
            intersection_id: Unique intersection identifier
            prediction_horizon: Time horizon for trajectory prediction
            optimization_enabled: Enable ATMS optimization features
        """
        self.intersection_id = intersection_id
        self.prediction_horizon = prediction_horizon
        self.optimization_enabled = optimization_enabled
        
        # Initialize components - Use ByteTrack (SOTA tracking, better than DeepSORT)
        try:
            # Try ByteTrack first (better performance)
            self.byte_tracker = ByteTrackWrapper(
                track_thresh=0.5,
                track_buffer=30,
                match_thresh=0.8,
                frame_rate=30
            )
            self.use_bytetrack = self.byte_tracker.is_available
            self.object_tracker = None  # Not using OptimizedObjectTracker
            if self.use_bytetrack:
                logger.info("✅ Using ByteTrack for object tracking (SOTA, better than DeepSORT)")
            else:
                logger.warning("ByteTrack not available, falling back to OptimizedObjectTracker")
                self.object_tracker = OptimizedObjectTracker(
                    max_disappeared=30,
                    max_distance=50.0,
                    min_hits=3,
                    max_age=20
                )
        except Exception as e:
            logger.warning(f"ByteTrack initialization failed: {e}, using OptimizedObjectTracker")
            self.use_bytetrack = False
            self.byte_tracker = None
            self.object_tracker = OptimizedObjectTracker(
                max_disappeared=30,
                max_distance=50.0,
                min_hits=3,
                max_age=20
            )
        
        self.trajectory_predictor = HybridTrajectoryPredictor(
            prediction_horizon=prediction_horizon,
            confidence_threshold=0.7
        )
        
        if optimization_enabled:
            self.atms_optimizer = ATMSTrafficOptimizer(
                intersection_id=intersection_id,
                signal_phases=["north_south", "east_west", "left_turn"],
                min_phase_duration=5.0,
                max_phase_duration=60.0
            )
        else:
            self.atms_optimizer = None
        
        # Performance tracking
        self.processing_times = deque(maxlen=100)
        self.frame_count = 0
        self.total_objects_tracked = 0
        self.total_predictions = 0
        
        # Context tracking
        self.traffic_context = {
            'traffic_light_state': 'green',
            'nearby_vehicles': 0,
            'pedestrian_crossing': False,
            'emergency_vehicle_present': False
        }
        
        logger.info(f"Integrated ATMS System initialized for intersection {intersection_id}")
    
    async def process_frame(self, detections: List[Dict], 
                          frame_id: str = None,
                          context: Optional[Dict] = None) -> ATMSProcessingResult:
        """
        Process a frame with complete ATMS pipeline
        
        Args:
            detections: List of detection dictionaries
            frame_id: Unique frame identifier
            context: Additional context information
        
        Returns:
            Complete ATMS processing result
        """
        start_time = time.time()
        current_time = time.time()
        
        if frame_id is None:
            frame_id = f"frame_{int(current_time * 1000)}"
        
        # Update context
        if context:
            self.traffic_context.update(context)
        
        # Step 1: Object Tracking (using ByteTrack or OptimizedObjectTracker)
        if self.use_bytetrack and self.byte_tracker:
            # Convert detections to ByteTrack format
            byte_detections = []
            for det in detections:
                bbox = det.get('bbox', (0, 0, 0, 0))
                if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                    x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
                else:
                    x1, y1, x2, y2 = 0, 0, 0, 0
                
                byte_detections.append({
                    'bbox': {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2},
                    'confidence': det.get('confidence', 0.5),
                    'class_id': det.get('class_id', 0),
                    'object_type': det.get('object_type', ObjectType.VEHICLE)
                })
            
            # Update ByteTrack
            tracked_dicts = self.byte_tracker.update(byte_detections)
            
            # Convert ByteTrack output to TrackedObject format
            tracked_objects = self._convert_bytetrack_to_tracked_objects(tracked_dicts, detections)
        else:
            # Use OptimizedObjectTracker (fallback)
            tracked_objects = self.object_tracker.update(detections)
        
        self.total_objects_tracked += len(tracked_objects)
        
        # Step 2: Trajectory Prediction
        trajectory_predictions = await self._predict_trajectories(tracked_objects)
        self.total_predictions += len(trajectory_predictions)
        
        # Step 3: ATMS Optimization (if enabled)
        signal_optimization = None
        pedestrian_safety = None
        emergency_priority = None
        
        if self.optimization_enabled and self.atms_optimizer:
            # Signal optimization
            signal_optimization = self.atms_optimizer.optimize_signal_timing(
                trajectory_predictions, current_time
            )
            
            # Pedestrian safety analysis
            pedestrian_safety = self.atms_optimizer.analyze_pedestrian_safety(
                trajectory_predictions, current_time
            )
            
            # Emergency vehicle priority (if detected)
            emergency_vehicles = [
                pred for pred in trajectory_predictions 
                if pred.object_type == 'emergency'
            ]
            if emergency_vehicles:
                emergency_priority = self.atms_optimizer.handle_emergency_priority(
                    trajectory_predictions, emergency_vehicles[0].track_id, current_time
                )
        
        # Calculate processing time
        processing_time = time.time() - start_time
        self.processing_times.append(processing_time)
        self.frame_count += 1
        
        # Performance metrics
        performance_metrics = self._calculate_performance_metrics()
        
        # Create result
        result = ATMSProcessingResult(
            frame_id=frame_id,
            timestamp=current_time,
            tracked_objects=tracked_objects,
            trajectory_predictions=trajectory_predictions,
            signal_optimization=signal_optimization,
            pedestrian_safety=pedestrian_safety,
            emergency_priority=emergency_priority,
            processing_time_ms=processing_time * 1000,
            performance_metrics=performance_metrics
        )
        
        # Update system state
        self._update_system_state(result)
        
        logger.debug(f"ATMS processing completed: {len(tracked_objects)} objects, "
                    f"{len(trajectory_predictions)} predictions, "
                    f"{processing_time*1000:.2f}ms")
        
        return result
    
    def _convert_bytetrack_to_tracked_objects(
        self, 
        tracked_dicts: List[Dict], 
        original_detections: List[Dict]
    ) -> List[TrackedObject]:
        """Convert ByteTrack output to TrackedObject format for compatibility"""
        tracked_objects = []
        
        # Create a mapping from detection index to track_id
        track_id_map = {}
        for i, tracked_dict in enumerate(tracked_dicts):
            track_id = tracked_dict.get('track_id', i + 1)
            track_id_map[i] = track_id
        
        # Convert to TrackedObject format
        for i, (tracked_dict, orig_det) in enumerate(zip(tracked_dicts, original_detections)):
            track_id = tracked_dict.get('track_id', i + 1)
            bbox = tracked_dict.get('bbox', {})
            
            if isinstance(bbox, dict):
                x1, y1 = bbox.get('x1', 0), bbox.get('y1', 0)
                x2, y2 = bbox.get('x2', 0), bbox.get('y2', 0)
            else:
                x1, y1, x2, y2 = bbox[:4] if len(bbox) >= 4 else (0, 0, 0, 0)
            
            # Calculate centroid
            centroid = ((x1 + x2) / 2, (y1 + y2) / 2)
            
            # Get object type
            obj_type = orig_det.get('object_type', ObjectType.VEHICLE)
            if isinstance(obj_type, str):
                obj_type = ObjectType.VEHICLE  # Default fallback
            
            # Create TrackedObject
            tracked_obj = TrackedObject(
                track_id=track_id,
                object_type=obj_type,
                bbox=(x1, y1, x2, y2),
                confidence=tracked_dict.get('confidence', orig_det.get('confidence', 0.5)),
                velocity=(0.0, 0.0),  # Will be updated by trajectory predictor
                trajectory=deque([centroid], maxlen=30),
                last_seen=time.time(),
                age=1,
                hits=1,
                time_since_update=0
            )
            
            tracked_objects.append(tracked_obj)
        
        return tracked_objects
    
    async def _predict_trajectories(self, tracked_objects: List[TrackedObject]) -> List[TrajectoryPrediction]:
        """Predict trajectories for tracked objects"""
        predictions = []
        
        for tracked_obj in tracked_objects:
            try:
                # Get trajectory history
                trajectory = list(tracked_obj.trajectory)
                if len(trajectory) < 2:
                    continue
                
                # Predict trajectory
                prediction = self.trajectory_predictor.predict(
                    track_id=tracked_obj.track_id,
                    trajectory=trajectory,
                    velocity=tracked_obj.velocity,
                    object_type=tracked_obj.object_type.value if hasattr(tracked_obj.object_type, 'value') else str(tracked_obj.object_type),
                    context=self.traffic_context
                )
                
                if prediction:
                    predictions.append(prediction)
                    
            except Exception as e:
                logger.error(f"Trajectory prediction failed for track {tracked_obj.track_id}: {e}")
                continue
        
        return predictions
    
    def _calculate_performance_metrics(self) -> Dict[str, Any]:
        """Calculate performance metrics"""
        avg_processing_time = np.mean(self.processing_times) if self.processing_times else 0
        max_processing_time = max(self.processing_times) if self.processing_times else 0
        
        return {
            'frame_count': self.frame_count,
            'total_objects_tracked': self.total_objects_tracked,
            'total_predictions': self.total_predictions,
            'avg_processing_time_ms': avg_processing_time * 1000,
            'max_processing_time_ms': max_processing_time * 1000,
            'active_tracks': len(self.object_tracker.tracked_objects) if self.object_tracker else 0,
            'fps': 1.0 / avg_processing_time if avg_processing_time > 0 else 0,
            'tracker_metrics': self.object_tracker.get_performance_metrics() if self.object_tracker else {},
            'predictor_metrics': self.trajectory_predictor.get_performance_metrics(),
            'using_bytetrack': self.use_bytetrack
        }
    
    def _update_system_state(self, result: ATMSProcessingResult):
        """Update system state based on processing results"""
        # Update traffic context
        self.traffic_context['nearby_vehicles'] = len(result.tracked_objects)
        
        # Check for emergency vehicles
        emergency_vehicles = [
            obj for obj in result.tracked_objects 
            if obj.object_type == ObjectType.EMERGENCY
        ]
        self.traffic_context['emergency_vehicle_present'] = len(emergency_vehicles) > 0
        
        # Check for pedestrians
        pedestrians = [
            obj for obj in result.tracked_objects 
            if obj.object_type == ObjectType.PEDESTRIAN
        ]
        self.traffic_context['pedestrian_crossing'] = len(pedestrians) > 0
        
        # Update optimizer performance metrics
        if result.signal_optimization and self.atms_optimizer:
            self.atms_optimizer.update_performance_metrics(result.signal_optimization)
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get current system status"""
        return {
            'intersection_id': self.intersection_id,
            'optimization_enabled': self.optimization_enabled,
            'prediction_horizon': self.prediction_horizon,
            'traffic_context': self.traffic_context,
            'performance_metrics': self._calculate_performance_metrics(),
            'tracker_status': {
                'active_tracks': len(self.object_tracker.tracked_objects) if self.object_tracker else 0,
                'total_tracks': self.object_tracker.total_tracks if self.object_tracker else 0,
                'using_bytetrack': self.use_bytetrack
            },
            'optimizer_status': self.atms_optimizer.get_performance_metrics() if self.atms_optimizer else None
        }
    
    def reset_system(self):
        """Reset the ATMS system"""
        if self.use_bytetrack and self.byte_tracker:
            self.byte_tracker.reset()
        elif self.object_tracker:
            self.object_tracker.reset()
        self.frame_count = 0
        self.total_objects_tracked = 0
        self.total_predictions = 0
        self.processing_times.clear()
        
        # Reset context
        self.traffic_context = {
            'traffic_light_state': 'green',
            'nearby_vehicles': 0,
            'pedestrian_crossing': False,
            'emergency_vehicle_present': False
        }
        
        logger.info("ATMS system reset")
    
    def cleanup_old_data(self):
        """Cleanup old data to prevent memory leaks"""
        # Cleanup old tracks
        if self.object_tracker:
            active_track_ids = [obj.track_id for obj in self.object_tracker.tracked_objects.values()]
            self.trajectory_predictor.cleanup_old_tracks(active_track_ids)
        
        # Cleanup old performance data
        if len(self.processing_times) > 1000:
            self.processing_times = deque(list(self.processing_times)[-500:], maxlen=1000)
        
        logger.debug("ATMS system cleanup completed")

class ATMSDataCollector:
    """
    Data collector for ATMS system performance and analytics
    Based on research methodology from City-scale Vehicle Trajectory Data study
    """
    
    def __init__(self, max_records: int = 10000):
        """
        Initialize data collector
        
        Args:
            max_records: Maximum number of records to keep in memory
        """
        self.max_records = max_records
        self.processing_records = deque(maxlen=max_records)
        self.optimization_records = deque(maxlen=max_records)
        self.prediction_records = deque(maxlen=max_records)
        
        logger.info("ATMS Data Collector initialized")
    
    def collect_processing_data(self, result: ATMSProcessingResult):
        """Collect processing data for analysis"""
        record = {
            'timestamp': result.timestamp,
            'frame_id': result.frame_id,
            'processing_time_ms': result.processing_time_ms,
            'tracked_objects_count': len(result.tracked_objects),
            'predictions_count': len(result.trajectory_predictions),
            'has_signal_optimization': result.signal_optimization is not None,
            'has_pedestrian_safety': result.pedestrian_safety is not None,
            'has_emergency_priority': result.emergency_priority is not None
        }
        
        self.processing_records.append(record)
    
    def collect_optimization_data(self, optimization: SignalOptimization):
        """Collect optimization data for analysis"""
        record = {
            'timestamp': time.time(),
            'intersection_id': optimization.intersection_id,
            'current_phase': optimization.current_phase,
            'recommended_phase': optimization.recommended_phase,
            'phase_duration': optimization.phase_duration,
            'confidence': optimization.confidence,
            'expected_benefit': optimization.expected_benefit,
            'affected_vehicles': optimization.affected_vehicles,
            'wait_time_reduction': optimization.wait_time_reduction
        }
        
        self.optimization_records.append(record)
    
    def collect_prediction_data(self, prediction: TrajectoryPrediction):
        """Collect prediction data for analysis"""
        record = {
            'timestamp': time.time(),
            'track_id': prediction.track_id,
            'object_type': prediction.object_type,
            'prediction_horizon': prediction.prediction_horizon,
            'confidence': prediction.confidence,
            'intention': prediction.intention,
            'method_used': prediction.method_used.value,
            'predicted_points_count': len(prediction.predicted_points)
        }
        
        self.prediction_records.append(record)
    
    def get_analytics_summary(self) -> Dict[str, Any]:
        """Get analytics summary from collected data"""
        if not self.processing_records:
            return {}
        
        # Processing analytics
        processing_times = [r['processing_time_ms'] for r in self.processing_records]
        avg_processing_time = np.mean(processing_times)
        max_processing_time = max(processing_times)
        
        # Optimization analytics
        optimization_count = len(self.optimization_records)
        avg_benefit = np.mean([r['expected_benefit'] for r in self.optimization_records]) if optimization_count > 0 else 0
        
        # Prediction analytics
        prediction_count = len(self.prediction_records)
        avg_confidence = np.mean([r['confidence'] for r in self.prediction_records]) if prediction_count > 0 else 0
        
        return {
            'total_records': len(self.processing_records),
            'avg_processing_time_ms': avg_processing_time,
            'max_processing_time_ms': max_processing_time,
            'optimization_count': optimization_count,
            'avg_optimization_benefit': avg_benefit,
            'prediction_count': prediction_count,
            'avg_prediction_confidence': avg_confidence,
            'data_collection_period': {
                'start': min(r['timestamp'] for r in self.processing_records),
                'end': max(r['timestamp'] for r in self.processing_records)
            }
        }
    
    def export_data(self, filepath: str):
        """Export collected data to file"""
        import json
        
        data = {
            'processing_records': list(self.processing_records),
            'optimization_records': list(self.optimization_records),
            'prediction_records': list(self.prediction_records),
            'analytics_summary': self.get_analytics_summary()
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"ATMS data exported to {filepath}")
    
    def clear_data(self):
        """Clear all collected data"""
        self.processing_records.clear()
        self.optimization_records.clear()
        self.prediction_records.clear()
        logger.info("ATMS data collector cleared")
