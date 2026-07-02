"""
Performance Profiling Tools
Week 11: Performance Optimization

Provides profiling utilities for identifying bottlenecks
"""

import time
import cProfile
import pstats
import io
import logging
from typing import Dict, List, Optional, Callable
from contextlib import contextmanager
from functools import wraps
import threading

logger = logging.getLogger(__name__)

# py-spy is a command-line tool, not importable as a Python module
# It's optional for profiling - users can run it separately if needed
PYSPY_AVAILABLE = False

try:
    from memory_profiler import profile
    MEMORY_PROFILER_AVAILABLE = True
except ImportError:
    MEMORY_PROFILER_AVAILABLE = False
    profile = None


class PerformanceProfiler:
    """
    Performance profiler for identifying bottlenecks
    """
    
    def __init__(self):
        """Initialize profiler"""
        self.profiler = cProfile.Profile()
        self.timings: Dict[str, List[float]] = {}
        self.call_counts: Dict[str, int] = {}
        self.lock = threading.Lock()
    
    @contextmanager
    def profile_function(self, function_name: str):
        """
        Context manager for profiling a function
        
        Usage:
            with profiler.profile_function("detect_objects"):
                # code to profile
        """
        start_time = time.perf_counter()
        self.profiler.enable()
        
        try:
            yield
        finally:
            self.profiler.disable()
            elapsed = time.perf_counter() - start_time
            
            with self.lock:
                if function_name not in self.timings:
                    self.timings[function_name] = []
                    self.call_counts[function_name] = 0
                
                self.timings[function_name].append(elapsed)
                self.call_counts[function_name] += 1
    
    def profile_decorator(self, function_name: Optional[str] = None):
        """
        Decorator for profiling functions
        
        Usage:
            @profiler.profile_decorator("my_function")
            def my_function():
                pass
        """
        def decorator(func: Callable):
            name = function_name or func.__name__
            
            @wraps(func)
            def wrapper(*args, **kwargs):
                with self.profile_function(name):
                    return func(*args, **kwargs)
            
            return wrapper
        return decorator
    
    def get_stats(self) -> Dict[str, Dict]:
        """
        Get profiling statistics
        
        Returns:
            Dictionary with timing statistics for each function
        """
        stats = {}
        
        with self.lock:
            for func_name, timings in self.timings.items():
                if timings:
                    stats[func_name] = {
                        'call_count': self.call_counts[func_name],
                        'total_time': sum(timings),
                        'avg_time': sum(timings) / len(timings),
                        'min_time': min(timings),
                        'max_time': max(timings),
                        'fps': 1.0 / (sum(timings) / len(timings)) if timings else 0
                    }
        
        return stats
    
    def get_profile_report(self, sort_by: str = 'cumulative', limit: int = 20) -> str:
        """
        Get cProfile report
        
        Args:
            sort_by: Sort key ('cumulative', 'time', 'calls')
            limit: Number of lines to return
            
        Returns:
            Formatted profile report
        """
        s = io.StringIO()
        ps = pstats.Stats(self.profiler, stream=s)
        ps.sort_stats(sort_by)
        ps.print_stats(limit)
        return s.getvalue()
    
    def reset(self):
        """Reset profiler"""
        with self.lock:
            self.profiler = cProfile.Profile()
            self.timings.clear()
            self.call_counts.clear()
    
    def print_summary(self):
        """Print profiling summary"""
        stats = self.get_stats()
        
        if not stats:
            logger.info("No profiling data available")
            return
        
        logger.info("=" * 60)
        logger.info("Performance Profiling Summary")
        logger.info("=" * 60)
        
        # Sort by total time
        sorted_stats = sorted(stats.items(), key=lambda x: x[1]['total_time'], reverse=True)
        
        for func_name, func_stats in sorted_stats[:10]:
            logger.info(
                f"{func_name}: "
                f"calls={func_stats['call_count']}, "
                f"avg={func_stats['avg_time']*1000:.2f}ms, "
                f"fps={func_stats['fps']:.1f}"
            )
        
        logger.info("=" * 60)


class FrameRateMonitor:
    """
    Monitor frame processing rate (FPS)
    """
    
    def __init__(self, window_size: int = 60):
        """
        Initialize FPS monitor
        
        Args:
            window_size: Number of frames to track for moving average
        """
        self.window_size = window_size
        self.frame_times: List[float] = []
        self.frame_count = 0
        self.start_time = time.time()
        self.lock = threading.Lock()
    
    def record_frame(self, processing_time: Optional[float] = None):
        """
        Record a processed frame
        
        Args:
            processing_time: Time taken to process frame (if None, uses current time)
        """
        current_time = time.time()
        
        with self.lock:
            if processing_time is None:
                # Calculate time since last frame
                if self.frame_times:
                    processing_time = current_time - self.frame_times[-1]
                else:
                    processing_time = current_time - self.start_time
            
            self.frame_times.append(current_time)
            self.frame_count += 1
            
            # Keep only recent frames
            if len(self.frame_times) > self.window_size:
                self.frame_times.pop(0)
    
    def get_fps(self) -> float:
        """
        Get current FPS (moving average)
        
        Returns:
            Frames per second
        """
        with self.lock:
            if len(self.frame_times) < 2:
                return 0.0
            
            # Calculate FPS from time window
            time_window = self.frame_times[-1] - self.frame_times[0]
            if time_window > 0:
                return (len(self.frame_times) - 1) / time_window
            return 0.0
    
    def get_stats(self) -> dict:
        """Get FPS statistics"""
        fps = self.get_fps()
        
        with self.lock:
            if self.frame_times:
                avg_frame_time = (self.frame_times[-1] - self.frame_times[0]) / len(self.frame_times)
            else:
                avg_frame_time = 0.0
        
        return {
            'fps': fps,
            'frame_count': self.frame_count,
            'avg_frame_time_ms': avg_frame_time * 1000,
            'window_size': self.window_size
        }
    
    def reset(self):
        """Reset monitor"""
        with self.lock:
            self.frame_times.clear()
            self.frame_count = 0
            self.start_time = time.time()

