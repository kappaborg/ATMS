"""
Optimized Object Tracking Module for ATMS
Based on research from City-scale Vehicle Trajectory Data study
https://pmc.ncbi.nlm.nih.gov/articles/PMC10582153/

This module implements efficient multi-object tracking with trajectory prediction
for real-time traffic management systems.
"""

import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import time
import logging
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

class ObjectType(Enum):
    """Object types for tracking"""
    VEHICLE = "vehicle"
    PEDESTRIAN = "pedestrian"
    CYCLIST = "cyclist"
    EMERGENCY = "emergency"

@dataclass
class TrackedObject:
    """Represents a tracked object with trajectory history"""
    track_id: int
    object_type: ObjectType
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2
    confidence: float
    velocity: Tuple[float, float]  # vx, vy in pixels/frame
    trajectory: deque  # Recent positions
    last_seen: float
    age: int
    hits: int
    time_since_update: int
    
    def __post_init__(self):
        if not hasattr(self, 'trajectory'):
            self.trajectory = deque(maxlen=30)  # Keep last 30 positions
        if not hasattr(self, 'last_seen'):
            self.last_seen = time.time()
        if not hasattr(self, 'age'):
            self.age = 0
        if not hasattr(self, 'hits'):
            self.hits = 0
        if not hasattr(self, 'time_since_update'):
            self.time_since_update = 0

class OptimizedObjectTracker:
    """
    Optimized multi-object tracker for ATMS
    Implements efficient tracking with trajectory prediction capabilities
    """
    
    def __init__(self, 
                 max_disappeared: int = 30,
                 max_distance: float = 50.0,
                 min_hits: int = 3,
                 max_age: int = 20):
        """
        Initialize the optimized object tracker
        
        Args:
            max_disappeared: Maximum frames an object can be missing
            max_distance: Maximum distance for object association
            min_hits: Minimum hits before confirming a track
            max_age: Maximum age before deleting a track
        """
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance
        self.min_hits = min_hits
        self.max_age = max_age
        
        # Tracking state
        self.next_id = 1
        self.tracked_objects: Dict[int, TrackedObject] = {}
        self.disappeared: Dict[int, int] = {}
        
        # Performance metrics
        self.total_tracks = 0
        self.active_tracks = 0
        self.processing_times = deque(maxlen=100)
        
        logger.info("Optimized Object Tracker initialized")
    
    def update(self, detections: List[Dict]) -> List[TrackedObject]:
        """
        Update tracker with new detections
        
        Args:
            detections: List of detection dictionaries with keys:
                - bbox: (x1, y1, x2, y2)
                - confidence: float
                - class_id: int
                - object_type: ObjectType
        
        Returns:
            List of tracked objects
        """
        start_time = time.time()
        
        # If no detections, update disappeared counts
        if len(detections) == 0:
            self._update_disappeared()
            self._cleanup_old_tracks()
            return list(self.tracked_objects.values())
        
        # Extract detection data
        detection_centroids = []
        detection_bboxes = []
        detection_confidences = []
        detection_types = []
        
        for det in detections:
            bbox = det['bbox']
            centroid = self._calculate_centroid(bbox)
            detection_centroids.append(centroid)
            detection_bboxes.append(bbox)
            detection_confidences.append(det['confidence'])
            detection_types.append(det.get('object_type', ObjectType.VEHICLE))
        
        # If no existing tracks, create new ones
        if len(self.tracked_objects) == 0:
            for i, (centroid, bbox, conf, obj_type) in enumerate(
                zip(detection_centroids, detection_bboxes, detection_confidences, detection_types)
            ):
                self._create_new_track(centroid, bbox, conf, obj_type)
        else:
            # Associate detections with existing tracks
            self._associate_detections(
                detection_centroids, detection_bboxes, 
                detection_confidences, detection_types
            )
        
        # Update disappeared counts and cleanup
        self._update_disappeared()
        self._cleanup_old_tracks()
        
        # Calculate processing time
        processing_time = time.time() - start_time
        self.processing_times.append(processing_time)
        
        # Update metrics
        self.active_tracks = len(self.tracked_objects)
        
        logger.debug(f"Tracking update completed: {self.active_tracks} active tracks, "
                    f"{processing_time*1000:.2f}ms processing time")
        
        return list(self.tracked_objects.values())
    
    def _calculate_centroid(self, bbox: Tuple[float, float, float, float]) -> Tuple[float, float]:
        """Calculate centroid from bounding box"""
        x1, y1, x2, y2 = bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    
    def _create_new_track(self, centroid: Tuple[float, float], bbox: Tuple[float, float, float, float], 
                         confidence: float, object_type: ObjectType):
        """Create a new track for a detection"""
        track_id = self.next_id
        self.next_id += 1
        
        # Calculate velocity (will be 0 for new tracks)
        velocity = (0.0, 0.0)
        
        # Create tracked object
        tracked_obj = TrackedObject(
            track_id=track_id,
            object_type=object_type,
            bbox=bbox,
            confidence=confidence,
            velocity=velocity,
            trajectory=deque([centroid], maxlen=30),
            last_seen=time.time(),
            age=1,
            hits=1,
            time_since_update=0
        )
        
        self.tracked_objects[track_id] = tracked_obj
        self.disappeared[track_id] = 0
        self.total_tracks += 1
        
        logger.debug(f"Created new track {track_id} for {object_type.value}")
    
    def _associate_detections(self, centroids: List[Tuple[float, float]], 
                             bboxes: List[Tuple[float, float, float, float]],
                             confidences: List[float], 
                             object_types: List[ObjectType]):
        """Associate detections with existing tracks using Hungarian algorithm"""
        
        # Get existing track centroids
        existing_centroids = []
        existing_track_ids = []
        
        for track_id, tracked_obj in self.tracked_objects.items():
            if len(tracked_obj.trajectory) > 0:
                existing_centroids.append(tracked_obj.trajectory[-1])
                existing_track_ids.append(track_id)
        
        if len(existing_centroids) == 0:
            # No existing tracks, create new ones
            for i, (centroid, bbox, conf, obj_type) in enumerate(
                zip(centroids, bboxes, confidences, object_types)
            ):
                self._create_new_track(centroid, bbox, conf, obj_type)
            return
        
        # Calculate distance matrix
        distance_matrix = self._calculate_distance_matrix(existing_centroids, centroids)
        
        # Use Hungarian algorithm for optimal assignment
        matched_indices, unmatched_detections = self._hungarian_assignment(distance_matrix)
        
        # Update matched tracks
        for track_idx, det_idx in matched_indices:
            track_id = existing_track_ids[track_idx]
            tracked_obj = self.tracked_objects[track_id]
            
            # Calculate velocity
            old_centroid = tracked_obj.trajectory[-1]
            new_centroid = centroids[det_idx]
            velocity = (
                new_centroid[0] - old_centroid[0],
                new_centroid[1] - old_centroid[1]
            )
            
            # Update tracked object
            tracked_obj.bbox = bboxes[det_idx]
            tracked_obj.confidence = confidences[det_idx]
            tracked_obj.velocity = velocity
            tracked_obj.trajectory.append(new_centroid)
            tracked_obj.last_seen = time.time()
            tracked_obj.age += 1
            tracked_obj.hits += 1
            tracked_obj.time_since_update = 0
            
            # Reset disappeared count
            self.disappeared[track_id] = 0
        
        # Create new tracks for unmatched detections
        for det_idx in unmatched_detections:
            self._create_new_track(
                centroids[det_idx], bboxes[det_idx], 
                confidences[det_idx], object_types[det_idx]
            )
    
    def _calculate_distance_matrix(self, centroids1: List[Tuple[float, float]], 
                                 centroids2: List[Tuple[float, float]]) -> np.ndarray:
        """Calculate distance matrix between two sets of centroids"""
        if len(centroids1) == 0 or len(centroids2) == 0:
            return np.array([])
        
        centroids1 = np.array(centroids1)
        centroids2 = np.array(centroids2)
        
        # Calculate Euclidean distances
        distances = np.sqrt(
            np.sum((centroids1[:, np.newaxis] - centroids2[np.newaxis, :]) ** 2, axis=2)
        )
        
        return distances
    
    def _hungarian_assignment(self, distance_matrix: np.ndarray) -> Tuple[List[Tuple[int, int]], List[int]]:
        """Perform Hungarian algorithm assignment"""
        if distance_matrix.size == 0:
            return [], []
        
        # Apply distance threshold
        distance_matrix[distance_matrix > self.max_distance] = float('inf')
        
        # Use scipy's linear_sum_assignment
        try:
            from scipy.optimize import linear_sum_assignment
            row_indices, col_indices = linear_sum_assignment(distance_matrix)
            
            # Filter out infinite distances
            valid_matches = []
            for i, j in zip(row_indices, col_indices):
                if distance_matrix[i, j] != float('inf'):
                    valid_matches.append((i, j))
            
            # Find unmatched detections
            matched_detections = set(j for _, j in valid_matches)
            unmatched_detections = [j for j in range(distance_matrix.shape[1]) 
                                  if j not in matched_detections]
            
            return valid_matches, unmatched_detections
            
        except ImportError:
            logger.warning("scipy not available, using simple greedy assignment")
            return self._greedy_assignment(distance_matrix)
    
    def _greedy_assignment(self, distance_matrix: np.ndarray) -> Tuple[List[Tuple[int, int]], List[int]]:
        """Simple greedy assignment as fallback"""
        matches = []
        used_tracks = set()
        used_detections = set()
        
        # Sort by distance
        indices = np.unravel_index(np.argsort(distance_matrix.ravel()), distance_matrix.shape)
        
        for i, j in zip(indices[0], indices[1]):
            if (i not in used_tracks and j not in used_detections and 
                distance_matrix[i, j] <= self.max_distance):
                matches.append((i, j))
                used_tracks.add(i)
                used_detections.add(j)
        
        unmatched_detections = [j for j in range(distance_matrix.shape[1]) 
                              if j not in used_detections]
        
        return matches, unmatched_detections
    
    def _update_disappeared(self):
        """Update disappeared counts for all tracks"""
        for track_id in list(self.tracked_objects.keys()):
            if track_id not in self.disappeared:
                self.disappeared[track_id] = 0
            else:
                self.disappeared[track_id] += 1
    
    def _cleanup_old_tracks(self):
        """Remove old and disappeared tracks"""
        tracks_to_remove = []
        
        for track_id, tracked_obj in self.tracked_objects.items():
            # Remove if disappeared too long
            if self.disappeared[track_id] > self.max_disappeared:
                tracks_to_remove.append(track_id)
            # Remove if too old
            elif tracked_obj.age > self.max_age:
                tracks_to_remove.append(track_id)
            # Remove if not enough hits
            elif tracked_obj.hits < self.min_hits:
                tracks_to_remove.append(track_id)
        
        for track_id in tracks_to_remove:
            del self.tracked_objects[track_id]
            if track_id in self.disappeared:
                del self.disappeared[track_id]
    
    def get_trajectory_data(self, track_id: int) -> Optional[List[Tuple[float, float]]]:
        """Get trajectory data for a specific track"""
        if track_id in self.tracked_objects:
            return list(self.tracked_objects[track_id].trajectory)
        return None
    
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics for the tracker"""
        avg_processing_time = np.mean(self.processing_times) if self.processing_times else 0
        
        return {
            'active_tracks': self.active_tracks,
            'total_tracks': self.total_tracks,
            'avg_processing_time_ms': avg_processing_time * 1000,
            'max_processing_time_ms': max(self.processing_times) * 1000 if self.processing_times else 0
        }
    
    def reset(self):
        """Reset the tracker state"""
        self.tracked_objects.clear()
        self.disappeared.clear()
        self.next_id = 1
        self.total_tracks = 0
        self.active_tracks = 0
        self.processing_times.clear()
        logger.info("Object tracker reset")
