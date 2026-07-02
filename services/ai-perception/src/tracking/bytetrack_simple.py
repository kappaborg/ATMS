"""
Simple ByteTrack Implementation
Alternative to bytetrack package (which has build issues)
Implements core ByteTrack algorithm for multi-object tracking
"""
import logging
from typing import List, Dict, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class SimpleByteTracker:
    """
    Simplified ByteTrack implementation
    Core algorithm without external dependencies
    """
    
    def __init__(
        self,
        track_thresh: float = 0.3,  # Lowered from 0.5 - catch more detections
        high_thresh: float = 0.5,   # Lowered from 0.6 - more high confidence detections
        match_thresh: float = 0.3,   # CRITICAL: Lowered from 0.8 to 0.3 - prevent ID switching!
        track_buffer: int = 90,      # Increased from 30 to 90 - keep tracks longer
        frame_rate: int = 30
    ):
        """
        Initialize Simple ByteTracker
        
        Args:
            track_thresh: Detection confidence threshold
            high_thresh: High confidence threshold
            match_thresh: IoU threshold for matching
            track_buffer: Frames to keep lost tracks
            frame_rate: Video frame rate
        """
        self.track_thresh = track_thresh
        self.high_thresh = high_thresh
        self.match_thresh = match_thresh
        self.track_buffer = track_buffer
        self.frame_rate = frame_rate
        
        self.tracked_stracks = []  # Active tracks
        self.lost_stracks = []    # Lost tracks
        self.removed_stracks = []  # Removed tracks
        
        self.frame_id = 0
        self.track_id_count = 0
        
        # Track position history for motion prediction (prevents ID switching)
        self.track_positions = {}  # track_id -> [(x, y), ...] (last 5 positions)
        
        logger.info(f"✅ Simple ByteTracker initialized (match_thresh={match_thresh}, track_buffer={track_buffer})")
    
    def update(self, detections: List[Dict], frame: np.ndarray = None) -> List[Dict]:
        """
        Update tracker with new detections
        
        Args:
            detections: List of detection dicts with bbox, confidence, class
            frame: Optional frame (not used in simple version)
        
        Returns:
            List of tracked detections with track_id
        """
        self.frame_id += 1
        
        # Convert detections to track format
        detections_track = []
        for det in detections:
            bbox = det.get('bbox', {})
            if isinstance(bbox, dict):
                x1, y1, x2, y2 = bbox.get('x1', 0), bbox.get('y1', 0), bbox.get('x2', 0), bbox.get('y2', 0)
            else:
                x1, y1, x2, y2 = bbox[:4] if len(bbox) >= 4 else (0, 0, 0, 0)
            
            conf = det.get('confidence', 0)
            cls = det.get('class_id', 0)
            
            detections_track.append({
                'bbox': [x1, y1, x2, y2],
                'confidence': conf,
                'class_id': cls,
                'detection': det
            })
        
        # Separate high and low confidence detections
        high_conf_dets = [d for d in detections_track if d['confidence'] >= self.high_thresh]
        low_conf_dets = [d for d in detections_track if self.track_thresh <= d['confidence'] < self.high_thresh]
        
        # Update tracked objects
        # Match high confidence detections with existing tracks
        matched, unmatched_dets, unmatched_tracks = self._associate_detections_to_trackers(
            high_conf_dets, self.tracked_stracks
        )
        
        # Update matched tracks
        for m in matched:
            track = self.tracked_stracks[m[1]]
            det = high_conf_dets[m[0]]
            track['bbox'] = det['bbox']
            track['confidence'] = det['confidence']
            track['detection'] = det['detection']
            track['time_since_update'] = 0
            
            # Update position history for motion prediction
            center = self._get_bbox_center(det['bbox'])
            track_id = track['track_id']
            if track_id not in self.track_positions:
                self.track_positions[track_id] = []
            self.track_positions[track_id].append(center)
            # Keep only last 5 positions
            if len(self.track_positions[track_id]) > 5:
                self.track_positions[track_id].pop(0)
        
        # Create new tracks for unmatched detections
        for i in unmatched_dets:
            det = high_conf_dets[i]
            new_track = {
                'track_id': self.track_id_count,
                'bbox': det['bbox'],
                'confidence': det['confidence'],
                'class_id': det['class_id'],
                'detection': det['detection'],
                'time_since_update': 0,
                'age': 1
            }
            self.tracked_stracks.append(new_track)
            
            # Initialize position history for new track
            center = self._get_bbox_center(det['bbox'])
            self.track_positions[self.track_id_count] = [center]
            
            self.track_id_count += 1
        
        # Handle unmatched tracks (mark as lost)
        for i in unmatched_tracks:
            track = self.tracked_stracks[i]
            track['time_since_update'] += 1
            if track['time_since_update'] > self.track_buffer:
                self.removed_stracks.append(track)
                # Clean up position history for removed tracks
                if track['track_id'] in self.track_positions:
                    del self.track_positions[track['track_id']]
        
        # Move lost tracks
        self.lost_stracks = [t for t in self.tracked_stracks if t['time_since_update'] > 0]
        self.tracked_stracks = [t for t in self.tracked_stracks if t['time_since_update'] == 0]
        
        # Match low confidence detections with lost tracks
        if len(low_conf_dets) > 0 and len(self.lost_stracks) > 0:
            matched2, _, _ = self._associate_detections_to_trackers(
                low_conf_dets, self.lost_stracks
            )
            
            for m in matched2:
                # Bounds checking to prevent IndexError
                if len(m) < 2 or m[1] >= len(self.lost_stracks) or m[0] >= len(low_conf_dets):
                    continue
                track = self.lost_stracks[m[1]]
                det = low_conf_dets[m[0]]
                track['bbox'] = det['bbox']
                track['confidence'] = det['confidence']
                track['detection'] = det['detection']
                track['time_since_update'] = 0
                self.tracked_stracks.append(track)
                self.lost_stracks.remove(track)
                
                # Update position history for recovered track
                center = self._get_bbox_center(det['bbox'])
                track_id = track['track_id']
                if track_id not in self.track_positions:
                    self.track_positions[track_id] = []
                self.track_positions[track_id].append(center)
                # Keep only last 5 positions
                if len(self.track_positions[track_id]) > 5:
                    self.track_positions[track_id].pop(0)
        
        # Build output detections with track IDs
        output = []
        for track in self.tracked_stracks:
            det = track['detection'].copy()
            det['track_id'] = track['track_id']
            output.append(det)
        
        return output
    
    def _associate_detections_to_trackers(self, detections, trackers):
        """Associate detections to trackers using IoU with motion prediction"""
        if len(trackers) == 0:
            return [], list(range(len(detections))), []
        
        if len(detections) == 0:
            return [], [], list(range(len(trackers)))
        
        # Calculate IoU matrix with motion prediction
        iou_matrix = np.zeros((len(detections), len(trackers)), dtype=np.float32)
        
        for d, det in enumerate(detections):
            det_center = self._get_bbox_center(det['bbox'])
            for t, trk in enumerate(trackers):
                # Use predicted position if available (motion prediction)
                trk_bbox = trk['bbox']
                if trk['track_id'] in self.track_positions:
                    # Predict next position based on velocity
                    positions = self.track_positions[trk['track_id']]
                    if len(positions) >= 2:
                        # Calculate velocity
                        dx = positions[-1][0] - positions[-2][0]
                        dy = positions[-1][1] - positions[-2][1]
                        # Predict next position
                        pred_center = (positions[-1][0] + dx, positions[-1][1] + dy)
                        # Adjust bbox center for prediction
                        trk_center = self._get_bbox_center(trk_bbox)
                        offset_x = pred_center[0] - trk_center[0]
                        offset_y = pred_center[1] - trk_center[1]
                        # Create predicted bbox
                        pred_bbox = [trk_bbox[0] + offset_x, trk_bbox[1] + offset_y,
                                    trk_bbox[2] + offset_x, trk_bbox[3] + offset_y]
                        iou_matrix[d, t] = self._iou(det['bbox'], pred_bbox)
                    else:
                        iou_matrix[d, t] = self._iou(det['bbox'], trk_bbox)
                else:
                    iou_matrix[d, t] = self._iou(det['bbox'], trk_bbox)
        
        # Improved matching: Sort by IoU and match best pairs first
        matched_indices = []
        unmatched_dets = []
        unmatched_trks = []
        
        # Create list of all possible matches with IoU scores
        matches = []
        for d in range(len(detections)):
            for t in range(len(trackers)):
                if iou_matrix[d, t] > self.match_thresh:
                    matches.append((iou_matrix[d, t], d, t))
        
        # Sort by IoU (highest first)
        matches.sort(reverse=True, key=lambda x: x[0])
        
        # Greedy matching (best IoU first)
        used_dets = set()
        used_trks = set()
        for iou_score, d, t in matches:
            if d not in used_dets and t not in used_trks:
                matched_indices.append([d, t])
                used_dets.add(d)
                used_trks.add(t)
        
        # Find unmatched
        unmatched_dets = [d for d in range(len(detections)) if d not in used_dets]
        unmatched_trks = [t for t in range(len(trackers)) if t not in used_trks]
        
        return matched_indices, unmatched_dets, unmatched_trks
    
    def _get_bbox_center(self, bbox):
        """Get center point of bounding box"""
        if isinstance(bbox, dict):
            x1, y1, x2, y2 = bbox.get('x1', 0), bbox.get('y1', 0), bbox.get('x2', 0), bbox.get('y2', 0)
        else:
            x1, y1, x2, y2 = bbox[:4] if len(bbox) >= 4 else (0, 0, 0, 0)
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    
    def _iou(self, box1: List[float], box2: List[float]) -> float:
        """Calculate IoU between two boxes"""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        
        if x2 <= x1 or y2 <= y1:
            return 0.0
        
        intersection = (x2 - x1) * (y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - intersection
        
        return intersection / union if union > 0 else 0.0
    
    def reset(self):
        """Reset tracker state"""
        self.tracked_stracks = []
        self.lost_stracks = []
        self.removed_stracks = []
        self.frame_id = 0
        self.track_id_count = 0
        self.track_positions = {}  # Clear position history

