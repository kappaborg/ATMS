"""
ByteTrack Integration - SOTA Multi-Object Tracking
Better than DeepSORT for traffic scenarios
"""
import logging
from typing import List, Dict, Tuple
import numpy as np

# Use simple implementation (package has build issues)
# Simple implementation is just as good and has no dependencies
try:
    from .bytetrack_simple import SimpleByteTracker
except ImportError:
    # Fallback for when loaded via importlib (no parent package)
    import sys
    from pathlib import Path
    tracking_dir = Path(__file__).parent
    sys.path.insert(0, str(tracking_dir))
    try:
        from bytetrack_simple import SimpleByteTracker
    except ImportError:
        # Last resort: define a minimal tracker
        SimpleByteTracker = None

BYTETRACK_AVAILABLE = True  # Always available (simple implementation)
BYTETracker = None  # Not using official package

logger = logging.getLogger(__name__)


class ByteTrackWrapper:
    """
    ByteTrack wrapper for improved multi-object tracking
    Better handling of occlusions and high false positive rates
    """
    
    def __init__(
        self,
        track_thresh: float = 0.5,
        track_buffer: int = 30,
        match_thresh: float = 0.8,
        frame_rate: int = 30
    ):
        """
        Initialize ByteTrack tracker
        
        Args:
            track_thresh: Detection confidence threshold
            track_buffer: Number of frames to keep lost tracks
            match_thresh: IoU threshold for matching
            frame_rate: Video frame rate
        """
        if not BYTETRACK_AVAILABLE:
            logger.warning("ByteTrack not available. Install: pip install bytetrack")
            self.tracker = None
            self.is_available = False
            return
        
        try:
            if SimpleByteTracker is None:
                raise ImportError("SimpleByteTracker not available")
            
            # Always use simple implementation (no dependencies, same algorithm)
            self.tracker = SimpleByteTracker(
                track_thresh=track_thresh,
                high_thresh=0.6,
                match_thresh=match_thresh,
                track_buffer=track_buffer,
                frame_rate=frame_rate
            )
            self.is_available = True
            logger.info("✅ ByteTrack initialized (simple implementation - no dependencies)")
        except Exception as e:
            logger.error(f"Failed to initialize ByteTrack: {e}")
            self.tracker = None
            self.is_available = False
    
    def update(self, detections: List[Dict], frame: np.ndarray = None) -> List[Dict]:
        """
        Update tracker with new detections
        
        Args:
            detections: List of detection dicts with bbox, confidence, class
            frame: Optional frame for visual tracking
        
        Returns:
            List of tracked objects with track_id
        """
        if not self.is_available or not self.tracker:
            # Return detections without tracking if ByteTrack unavailable
            for i, det in enumerate(detections):
                if 'track_id' not in det:
                    det['track_id'] = i
            return detections
        
        try:
            # Use tracker's update method (works for both official and simple)
            if hasattr(self.tracker, 'update'):
                # SimpleByteTracker or official BYTETracker
                tracked = self.tracker.update(detections, frame)
                return tracked
            else:
                # Official ByteTrack expects numpy array format
                dets = []
                for det in detections:
                    bbox = det.get('bbox', {})
                    if isinstance(bbox, dict):
                        x1, y1 = bbox.get('x1', 0), bbox.get('y1', 0)
                        x2, y2 = bbox.get('x2', 0), bbox.get('y2', 0)
                    else:
                        x1, y1, x2, y2 = bbox[:4]
                    
                    score = det.get('confidence', 0)
                    class_id = det.get('class_id', 0)
                    dets.append([x1, y1, x2, y2, score, class_id])
                
                if len(dets) == 0:
                    return detections
                
                dets_array = np.array(dets, dtype=np.float32)
                tracks = self.tracker.update(dets_array, frame)
                
                # Map track IDs back to detections
                tracked_detections = []
                for track in tracks:
                    track_id = int(track[4])
                    # Find matching detection and assign track_id
                    for det in detections:
                        if 'track_id' not in det:
                            det['track_id'] = track_id
                            tracked_detections.append(det)
                            break
                
                return tracked_detections if tracked_detections else detections
            
        except Exception as e:
            logger.error(f"ByteTrack update error: {e}")
            # Return original detections on error
            return detections
    
    def reset(self):
        """Reset tracker state"""
        if self.tracker:
            self.tracker.reset()

