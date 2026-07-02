#!/usr/bin/env python3
"""
Frame Batch Processor
====================

Optimized batch processing for multiple frames to improve GPU utilization
and overall throughput.
"""

import asyncio
import time
import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
from collections import deque

@dataclass
class FrameBatch:
    """Represents a batch of frames to process"""
    frames: List[np.ndarray]
    frame_ids: List[int]
    timestamps: List[datetime]
    
class FrameBatchProcessor:
    """Optimized batch processor for frames"""
    
    def __init__(self, batch_size: int = 2, max_wait_time: float = 0.05):
        """
        Initialize batch processor
        
        Args:
            batch_size: Number of frames to process together
            max_wait_time: Maximum time to wait for batch (seconds)
        """
        self.batch_size = batch_size
        self.max_wait_time = max_wait_time
        self.frame_queue: deque = deque(maxlen=batch_size * 2)
        self.last_batch_time = time.time()
        self.batch_count = 0
        
    def add_frame(self, frame: np.ndarray, frame_id: int) -> bool:
        """
        Add frame to batch queue
        
        Returns:
            True if batch is ready, False otherwise
        """
        self.frame_queue.append({
            'frame': frame,
            'frame_id': frame_id,
            'timestamp': datetime.now()
        })
        
        # Check if batch is ready
        ready = len(self.frame_queue) >= self.batch_size
        timeout = (time.time() - self.last_batch_time) >= self.max_wait_time
        
        return ready or (timeout and len(self.frame_queue) > 0)
    
    def get_batch(self) -> Optional[FrameBatch]:
        """Get next batch of frames"""
        if len(self.frame_queue) < 1:
            return None
        
        # Take up to batch_size frames
        num_frames = min(self.batch_size, len(self.frame_queue))
        batch_frames = []
        batch_ids = []
        batch_timestamps = []
        
        for _ in range(num_frames):
            if self.frame_queue:
                item = self.frame_queue.popleft()
                batch_frames.append(item['frame'])
                batch_ids.append(item['frame_id'])
                batch_timestamps.append(item['timestamp'])
        
        self.last_batch_time = time.time()
        self.batch_count += 1
        
        return FrameBatch(
            frames=batch_frames,
            frame_ids=batch_ids,
            timestamps=batch_timestamps
        )
    
    def clear(self):
        """Clear the frame queue"""
        self.frame_queue.clear()


