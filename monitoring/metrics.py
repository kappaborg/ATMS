"""
Prometheus Metrics Integration
===============================
Non-blocking, async metrics collection for traffic management system.
Designed to have <1% performance impact.
"""

import time
import threading
from typing import Dict, Optional
from collections import deque
import logging

try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest, start_http_server
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logging.warning("Prometheus client not available. Install with: pip install prometheus-client")

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Prometheus metrics collector for traffic management system.
    All metrics are collected asynchronously to avoid performance impact.
    """
    
    def __init__(self, port: int = 8004, enable_http_server: bool = True):
        """
        Initialize metrics collector.
        
        Args:
            port: Port for Prometheus HTTP server
            enable_http_server: Whether to start HTTP server for metrics scraping
        """
        if not PROMETHEUS_AVAILABLE:
            logger.error("❌ Prometheus client not available - metrics will be disabled")
            logger.error("   Install with: pip install prometheus-client")
            self.enabled = False
            self.port = port
            return
        
        self.enabled = True
        self.port = port
        self.start_time = time.time()
        
        # Performance Metrics
        self.fps_current = Gauge('traffic_fps_current', 'Current FPS')
        self.fps_average = Gauge('traffic_fps_average', 'Average FPS')
        self.frame_processing_time = Histogram(
            'traffic_frame_processing_time_ms',
            'Frame processing time in milliseconds',
            buckets=[10, 25, 50, 100, 200, 500, 1000]
        )
        self.detection_time = Histogram(
            'traffic_detection_time_ms',
            'Detection processing time in milliseconds',
            buckets=[5, 10, 20, 50, 100, 200, 500]
        )
        self.tracking_time = Histogram(
            'traffic_tracking_time_ms',
            'Tracking processing time in milliseconds',
            buckets=[1, 5, 10, 20, 50, 100]
        )
        self.decision_time = Histogram(
            'traffic_decision_time_ms',
            'Decision making time in milliseconds',
            buckets=[5, 10, 20, 50, 100, 200]
        )
        
        # Detection Metrics
        self.detections_total = Counter('traffic_detections_total', 'Total detections')
        self.detections_filtered = Counter('traffic_detections_filtered', 'Filtered detections')
        self.vehicles_detected = Gauge('traffic_vehicles_detected', 'Current vehicles detected')
        self.pedestrians_detected = Gauge('traffic_pedestrians_detected', 'Current pedestrians detected')
        
        # System Metrics
        self.memory_usage = Gauge('traffic_memory_usage_mb', 'Memory usage in MB')
        self.cpu_usage = Gauge('traffic_cpu_usage_percent', 'CPU usage percentage')
        
        # Kafka Metrics
        self.kafka_messages_sent = Counter('traffic_kafka_messages_sent_total', 'Total Kafka messages sent')
        self.kafka_errors = Counter('traffic_kafka_errors_total', 'Total Kafka errors')
        
        # Decision Metrics
        self.decisions_total = Counter('traffic_decisions_total', 'Total decisions made')
        self.phase_changes = Counter('traffic_phase_changes_total', 'Total phase changes')
        self.decision_confidence = Histogram(
            'traffic_decision_confidence',
            'Decision confidence score',
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        )
        
        # Traffic Metrics
        self.vehicle_count_ns = Gauge('traffic_vehicle_count_north_south', 'Vehicle count North-South')
        self.vehicle_count_ew = Gauge('traffic_vehicle_count_east_west', 'Vehicle count East-West')
        self.emission_ns = Gauge('traffic_emission_north_south_kg', 'Emission North-South in kg')
        self.emission_ew = Gauge('traffic_emission_east_west_kg', 'Emission East-West in kg')
        
        # Batch update mechanism (update every N calls, not every call)
        self.batch_size = 10
        self.batch_counter = 0
        self.pending_updates = {}
        
        # Start HTTP server in separate thread
        if enable_http_server:
            self._start_http_server()
    
    def _start_http_server(self):
        """Start Prometheus HTTP server in separate thread"""
        try:
            start_http_server(self.port)
            logger.info(f"✅ Prometheus metrics server started on port {self.port}")
            logger.info(f"   Metrics available at: http://localhost:{self.port}/metrics")
            logger.info(f"   Prometheus should scrape from: http://host.docker.internal:{self.port}/metrics")
        except OSError as e:
            if "Address already in use" in str(e):
                logger.warning(f"⚠️  Port {self.port} already in use - metrics server may already be running")
                logger.warning(f"   Check if another instance is running: lsof -i :{self.port}")
            else:
                logger.error(f"❌ Could not start Prometheus HTTP server on port {self.port}: {e}")
                logger.error(f"   Check if port is available and not blocked by firewall")
        except Exception as e:
            logger.error(f"❌ Could not start Prometheus HTTP server: {e}")
    
    def update_fps(self, current: float, average: float):
        """Update FPS metrics (batched)"""
        if not self.enabled:
            return
        self.fps_current.set(current)
        self.fps_average.set(average)
    
    def record_frame_processing_time(self, time_ms: float):
        """Record frame processing time"""
        if not self.enabled:
            return
        self.frame_processing_time.observe(time_ms)
    
    def record_detection_time(self, time_ms: float):
        """Record detection processing time"""
        if not self.enabled:
            return
        self.detection_time.observe(time_ms)
    
    def record_tracking_time(self, time_ms: float):
        """Record tracking processing time"""
        if not self.enabled:
            return
        self.tracking_time.observe(time_ms)
    
    def record_decision_time(self, time_ms: float):
        """Record decision making time"""
        if not self.enabled:
            return
        self.decision_time.observe(time_ms)
    
    def increment_detections(self, count: int = 1):
        """Increment detection counter"""
        if not self.enabled:
            return
        self.detections_total.inc(count)
    
    def increment_filtered_detections(self, count: int = 1):
        """Increment filtered detection counter"""
        if not self.enabled:
            return
        self.detections_filtered.inc(count)
    
    def update_vehicle_count(self, count: int):
        """Update current vehicle count"""
        if not self.enabled:
            return
        self.vehicles_detected.set(count)
    
    def update_pedestrian_count(self, count: int):
        """Update current pedestrian count"""
        if not self.enabled:
            return
        self.pedestrians_detected.set(count)
    
    def update_memory_usage(self, mb: float):
        """Update memory usage (batched)"""
        if not self.enabled:
            return
        self.batch_counter += 1
        if self.batch_counter >= self.batch_size:
            self.memory_usage.set(mb)
            self.batch_counter = 0
    
    def update_cpu_usage(self, percent: float):
        """Update CPU usage (batched)"""
        if not self.enabled:
            return
        # Only update every batch_size calls
        if self.batch_counter == 0:
            self.cpu_usage.set(percent)
    
    def increment_kafka_messages(self, count: int = 1):
        """Increment Kafka messages sent"""
        if not self.enabled:
            return
        self.kafka_messages_sent.inc(count)
    
    def increment_kafka_errors(self, count: int = 1):
        """Increment Kafka errors"""
        if not self.enabled:
            return
        self.kafka_errors.inc(count)
    
    def increment_decisions(self):
        """Increment decision counter"""
        if not self.enabled:
            return
        self.decisions_total.inc()
    
    def increment_phase_changes(self):
        """Increment phase change counter"""
        if not self.enabled:
            return
        self.phase_changes.inc()
    
    def record_decision_confidence(self, confidence: float):
        """Record decision confidence"""
        if not self.enabled:
            return
        self.decision_confidence.observe(confidence)
    
    def update_traffic_metrics(self, ns_vehicles: int, ew_vehicles: int, 
                               ns_emission: float, ew_emission: float):
        """Update traffic metrics"""
        if not self.enabled:
            return
        self.vehicle_count_ns.set(ns_vehicles)
        self.vehicle_count_ew.set(ew_vehicles)
        self.emission_ns.set(ns_emission)
        self.emission_ew.set(ew_emission)
    
    def get_metrics(self) -> str:
        """Get Prometheus metrics as string"""
        if not self.enabled:
            return "# Metrics disabled - Prometheus not available\n"
        return generate_latest().decode('utf-8')


# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector(port: int = 8004, enable_http_server: bool = True) -> MetricsCollector:
    """Get or create global metrics collector instance"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector(port=port, enable_http_server=enable_http_server)
    return _metrics_collector

