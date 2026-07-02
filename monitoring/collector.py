"""
Performance Collector
=====================
Lightweight performance metrics collector that integrates with YouTube processor.
Non-blocking design to maintain FPS performance.
"""

import time
import psutil
import threading
from typing import Dict, Optional, Deque
from collections import deque
import logging

from .metrics import MetricsCollector, get_metrics_collector

logger = logging.getLogger(__name__)


class PerformanceCollector:
    """
    Performance metrics collector for real-time monitoring.
    Collects metrics in background thread to avoid blocking main processing.
    """
    
    def __init__(self, update_interval: float = 1.0, enable_prometheus: bool = True):
        """
        Initialize performance collector.
        
        Args:
            update_interval: How often to update metrics (seconds)
            enable_prometheus: Whether to send metrics to Prometheus
        """
        self.update_interval = update_interval
        self.enable_prometheus = enable_prometheus
        self.running = False
        self.collector_thread: Optional[threading.Thread] = None
        
        # Metrics storage
        self.fps_history: Deque[float] = deque(maxlen=100)
        self.processing_times: Deque[float] = deque(maxlen=100)
        self.detection_times: Deque[float] = deque(maxlen=100)
        self.tracking_times: Deque[float] = deque(maxlen=100)
        self.decision_times: Deque[float] = deque(maxlen=100)
        
        # Current metrics
        self.current_fps = 0.0
        self.average_fps = 0.0
        self.current_detections = 0
        self.current_vehicles = 0
        self.current_pedestrians = 0
        
        # Prometheus collector
        if enable_prometheus:
            self.metrics = get_metrics_collector(enable_http_server=True)
        else:
            self.metrics = None
    
    def start(self):
        """Start background metrics collection"""
        if self.running:
            return
        
        self.running = True
        self.collector_thread = threading.Thread(target=self._collect_loop, daemon=True)
        self.collector_thread.start()
        logger.info("✅ Performance collector started")
    
    def stop(self):
        """Stop background metrics collection"""
        self.running = False
        if self.collector_thread:
            self.collector_thread.join(timeout=2.0)
        logger.info("⏹️  Performance collector stopped")
    
    def _collect_loop(self):
        """Background loop for collecting system metrics"""
        process = psutil.Process()
        
        while self.running:
            try:
                # Collect system metrics
                memory_mb = process.memory_info().rss / 1024 / 1024
                cpu_percent = process.cpu_percent(interval=0.1)
                
                # Update Prometheus metrics (batched)
                if self.metrics and self.metrics.enabled:
                    self.metrics.update_memory_usage(memory_mb)
                    self.metrics.update_cpu_usage(cpu_percent)
                
                # Update FPS metrics
                if self.fps_history:
                    self.average_fps = sum(self.fps_history) / len(self.fps_history)
                    if self.metrics and self.metrics.enabled:
                        self.metrics.update_fps(self.current_fps, self.average_fps)
                
                time.sleep(self.update_interval)
            except Exception as e:
                logger.error(f"Error in performance collector: {e}")
                time.sleep(self.update_interval)
    
    def record_frame_processing(self, processing_time_ms: float):
        """Record frame processing time"""
        self.processing_times.append(processing_time_ms)
        if self.metrics and self.metrics.enabled:
            self.metrics.record_frame_processing_time(processing_time_ms)
    
    def record_detection(self, detection_time_ms: float, detection_count: int, 
                       vehicles: int, pedestrians: int):
        """Record detection metrics"""
        self.detection_times.append(detection_time_ms)
        self.current_detections = detection_count
        self.current_vehicles = vehicles
        self.current_pedestrians = pedestrians
        
        if self.metrics and self.metrics.enabled:
            self.metrics.record_detection_time(detection_time_ms)
            self.metrics.increment_detections(detection_count)
            self.metrics.update_vehicle_count(vehicles)
            self.metrics.update_pedestrian_count(pedestrians)
    
    def record_tracking(self, tracking_time_ms: float):
        """Record tracking processing time"""
        self.tracking_times.append(tracking_time_ms)
        if self.metrics and self.metrics.enabled:
            self.metrics.record_tracking_time(tracking_time_ms)
    
    def record_decision(self, decision_time_ms: float, confidence: float):
        """Record decision making metrics"""
        self.decision_times.append(decision_time_ms)
        if self.metrics and self.metrics.enabled:
            self.metrics.record_decision_time(decision_time_ms)
            self.metrics.increment_decisions()
            self.metrics.record_decision_confidence(confidence)
    
    def update_fps(self, fps: float):
        """Update current FPS"""
        self.current_fps = fps
        self.fps_history.append(fps)
    
    def get_stats(self) -> Dict:
        """Get current performance statistics"""
        avg_processing = sum(self.processing_times) / len(self.processing_times) if self.processing_times else 0
        avg_detection = sum(self.detection_times) / len(self.detection_times) if self.detection_times else 0
        avg_tracking = sum(self.tracking_times) / len(self.tracking_times) if self.tracking_times else 0
        avg_decision = sum(self.decision_times) / len(self.decision_times) if self.decision_times else 0
        
        return {
            'fps': {
                'current': self.current_fps,
                'average': self.average_fps
            },
            'processing_times_ms': {
                'average': avg_processing,
                'min': min(self.processing_times) if self.processing_times else 0,
                'max': max(self.processing_times) if self.processing_times else 0
            },
            'detection_times_ms': {
                'average': avg_detection,
                'min': min(self.detection_times) if self.detection_times else 0,
                'max': max(self.detection_times) if self.detection_times else 0
            },
            'tracking_times_ms': {
                'average': avg_tracking,
                'min': min(self.tracking_times) if self.tracking_times else 0,
                'max': max(self.tracking_times) if self.tracking_times else 0
            },
            'decision_times_ms': {
                'average': avg_decision,
                'min': min(self.decision_times) if self.decision_times else 0,
                'max': max(self.decision_times) if self.decision_times else 0
            },
            'detections': {
                'current': self.current_detections,
                'vehicles': self.current_vehicles,
                'pedestrians': self.current_pedestrians
            }
        }

