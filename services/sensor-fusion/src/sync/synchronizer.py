"""
Sensor Fusion Service - Data Synchronizer
Week 1: Multi-Camera Synchronization with Time Alignment
"""
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import deque
import sys
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent.parent))
from shared.utils.logger import get_logger
from shared.models.base import CameraFrame

logger = get_logger(__name__)


class FrameSynchronizer:
    """
    Multi-camera frame synchronizer
    
    Features:
    - Time-based frame alignment
    - Buffer management
    - Drift compensation
    - Performance optimization
    """
    
    def __init__(
        self,
        camera_ids: List[str],
        sync_threshold_ms: int = 100,
        buffer_size: int = 30,
        timeout_seconds: int = 5
    ):
        """
        Initialize synchronizer
        
        Args:
            camera_ids: List of camera IDs to synchronize
            sync_threshold_ms: Max time difference for sync (milliseconds)
            buffer_size: Size of frame buffer per camera
            timeout_seconds: Timeout for waiting frames
        """
        self.camera_ids = camera_ids
        self.sync_threshold = timedelta(milliseconds=sync_threshold_ms)
        self.buffer_size = buffer_size
        self.timeout = timedelta(seconds=timeout_seconds)
        
        # Frame buffers for each camera
        self.buffers: Dict[str, deque] = {
            camera_id: deque(maxlen=buffer_size)
            for camera_id in camera_ids
        }
        
        # Statistics
        self.sync_count = 0
        self.timeout_count = 0
        self.drift_corrections = 0
        
        self.logger = logger.bind(
            camera_count=len(camera_ids),
            sync_threshold_ms=sync_threshold_ms
        )
    
    def add_frame(self, camera_id: str, frame: CameraFrame):
        """
        Add frame to synchronization buffer
        
        Args:
            camera_id: Camera identifier
            frame: Camera frame
        """
        if camera_id not in self.buffers:
            self.logger.warning(
                f"Unknown camera_id: {camera_id}",
                camera_id=camera_id
            )
            return
        
        self.buffers[camera_id].append(frame)
        
        self.logger.debug(
            "Frame added to buffer",
            camera_id=camera_id,
            frame_id=frame.frame_id,
            buffer_size=len(self.buffers[camera_id])
        )
    
    def get_synchronized_frames(self) -> Optional[Dict[str, CameraFrame]]:
        """
        Get synchronized frames from all cameras
        
        Returns:
            Dict[camera_id, frame] or None if sync not possible
        """
        # Check if all cameras have frames
        if not all(len(buffer) > 0 for buffer in self.buffers.values()):
            return None
        
        # Find earliest timestamp across all cameras
        earliest_frames = {
            camera_id: buffer[0]
            for camera_id, buffer in self.buffers.items()
        }
        
        # Find reference timestamp (median)
        timestamps = [frame.timestamp for frame in earliest_frames.values()]
        timestamps.sort()
        ref_timestamp = timestamps[len(timestamps) // 2]
        
        # Find best matching frames within sync threshold
        synced_frames = {}
        
        for camera_id, buffer in self.buffers.items():
            best_frame = None
            best_diff = self.timeout
            
            for frame in buffer:
                time_diff = abs(frame.timestamp - ref_timestamp)
                
                if time_diff <= self.sync_threshold and time_diff < best_diff:
                    best_frame = frame
                    best_diff = time_diff
            
            if best_frame:
                synced_frames[camera_id] = best_frame
            else:
                # No frame within threshold
                self.logger.warning(
                    "No synchronized frame found",
                    camera_id=camera_id,
                    ref_timestamp=ref_timestamp.isoformat()
                )
                return None
        
        # Remove synchronized frames from buffers
        for camera_id, frame in synced_frames.items():
            try:
                self.buffers[camera_id].remove(frame)
            except ValueError:
                pass
        
        self.sync_count += 1
        
        self.logger.debug(
            "Frames synchronized",
            sync_count=self.sync_count,
            ref_timestamp=ref_timestamp.isoformat(),
            camera_count=len(synced_frames)
        )
        
        return synced_frames
    
    def cleanup_old_frames(self):
        """Remove frames older than timeout"""
        current_time = datetime.utcnow()
        cleaned = 0
        
        for camera_id, buffer in self.buffers.items():
            initial_size = len(buffer)
            
            # Remove old frames
            while buffer and (current_time - buffer[0].timestamp) > self.timeout:
                buffer.popleft()
                cleaned += 1
            
            if len(buffer) < initial_size:
                self.logger.debug(
                    "Cleaned old frames",
                    camera_id=camera_id,
                    removed=initial_size - len(buffer)
                )
        
        if cleaned > 0:
            self.timeout_count += cleaned
    
    def detect_drift(self) -> Dict[str, timedelta]:
        """
        Detect time drift between cameras
        
        Returns:
            Dict[camera_id, drift_from_median]
        """
        if not all(len(buffer) > 0 for buffer in self.buffers.values()):
            return {}
        
        # Get latest frame timestamp from each camera
        latest_timestamps = {
            camera_id: buffer[-1].timestamp
            for camera_id, buffer in self.buffers.items()
        }
        
        # Calculate median timestamp
        timestamps = list(latest_timestamps.values())
        timestamps.sort()
        median_timestamp = timestamps[len(timestamps) // 2]
        
        # Calculate drift from median
        drifts = {
            camera_id: timestamp - median_timestamp
            for camera_id, timestamp in latest_timestamps.items()
        }
        
        # Log significant drifts
        for camera_id, drift in drifts.items():
            if abs(drift) > self.sync_threshold:
                self.logger.warning(
                    "Significant camera drift detected",
                    camera_id=camera_id,
                    drift_ms=drift.total_seconds() * 1000
                )
                self.drift_corrections += 1
        
        return drifts
    
    def get_buffer_status(self) -> Dict[str, int]:
        """Get current buffer sizes"""
        return {
            camera_id: len(buffer)
            for camera_id, buffer in self.buffers.items()
        }
    
    def get_stats(self) -> dict:
        """Get synchronizer statistics"""
        return {
            "sync_count": self.sync_count,
            "timeout_count": self.timeout_count,
            "drift_corrections": self.drift_corrections,
            "buffer_status": self.get_buffer_status(),
            "camera_count": len(self.camera_ids)
        }
    
    def reset(self):
        """Reset all buffers and statistics"""
        for buffer in self.buffers.values():
            buffer.clear()
        
        self.sync_count = 0
        self.timeout_count = 0
        self.drift_corrections = 0
        
        self.logger.info("Synchronizer reset")

