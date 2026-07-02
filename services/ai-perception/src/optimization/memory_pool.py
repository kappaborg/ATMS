"""
Memory Pooling for Frame Processing
Week 11: Performance Optimization

Reduces memory allocations by reusing frame buffers
"""

import numpy as np
from typing import Optional, List, Tuple
import logging
from collections import deque

logger = logging.getLogger(__name__)


class FrameMemoryPool:
    """
    Memory pool for frame buffers to reduce allocations
    
    Benefits:
    - Reduces GC pressure
    - Faster frame processing
    - Lower memory fragmentation
    """
    
    def __init__(
        self,
        pool_size: int = 10,
        default_shape: Tuple[int, int, int] = (1080, 1920, 3),
        dtype: type = np.uint8
    ):
        """
        Initialize memory pool
        
        Args:
            pool_size: Number of buffers to keep in pool
            default_shape: Default frame shape (height, width, channels)
            dtype: Data type for frames
        """
        self.pool_size = pool_size
        self.default_shape = default_shape
        self.dtype = dtype
        
        # Pool of pre-allocated buffers
        self._pool: deque = deque(maxlen=pool_size)
        self._allocated_count = 0
        
        # Pre-allocate initial buffers
        for _ in range(pool_size):
            buffer = np.empty(default_shape, dtype=dtype)
            self._pool.append(buffer)
        
        logger.info(
            f"FrameMemoryPool initialized: pool_size={pool_size}, "
            f"shape={default_shape}, dtype={dtype}"
        )
    
    def get_buffer(self, shape: Optional[Tuple[int, int, int]] = None) -> np.ndarray:
        """
        Get a buffer from the pool
        
        Args:
            shape: Desired buffer shape (if None, uses default)
            
        Returns:
            numpy array buffer
        """
        if shape is None:
            shape = self.default_shape
        
        # Try to get from pool
        if self._pool:
            buffer = self._pool.popleft()
            
            # Resize if needed
            if buffer.shape != shape:
                buffer = np.empty(shape, dtype=self.dtype)
                self._allocated_count += 1
            else:
                # Reuse existing buffer
                buffer.fill(0)  # Clear buffer
            
            return buffer
        else:
            # Pool empty, allocate new buffer
            buffer = np.empty(shape, dtype=self.dtype)
            self._allocated_count += 1
            return buffer
    
    def return_buffer(self, buffer: np.ndarray):
        """
        Return a buffer to the pool
        
        Args:
            buffer: Buffer to return
        """
        if buffer is not None and len(self._pool) < self.pool_size:
            # Clear buffer before returning
            buffer.fill(0)
            self._pool.append(buffer)
    
    def get_stats(self) -> dict:
        """Get pool statistics"""
        return {
            'pool_size': self.pool_size,
            'available_buffers': len(self._pool),
            'allocated_count': self._allocated_count,
            'utilization': (self.pool_size - len(self._pool)) / self.pool_size if self.pool_size > 0 else 0
        }


class DetectionMemoryPool:
    """
    Memory pool for detection objects to reduce allocations
    """
    
    def __init__(self, pool_size: int = 100):
        """
        Initialize detection memory pool
        
        Args:
            pool_size: Number of detection objects to keep in pool
        """
        self.pool_size = pool_size
        self._pool: deque = deque(maxlen=pool_size)
        self._allocated_count = 0
    
    def get_detection(self):
        """Get a detection object from pool"""
        if self._pool:
            return self._pool.popleft()
        else:
            self._allocated_count += 1
            return None  # Caller creates new object
    
    def return_detection(self, detection):
        """Return detection object to pool"""
        if detection is not None and len(self._pool) < self.pool_size:
            # Clear detection data
            detection.detection_id = None
            detection.bbox = None
            detection.confidence = 0.0
            self._pool.append(detection)
    
    def get_stats(self) -> dict:
        """Get pool statistics"""
        return {
            'pool_size': self.pool_size,
            'available_objects': len(self._pool),
            'allocated_count': self._allocated_count
        }

