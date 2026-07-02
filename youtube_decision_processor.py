#!/usr/bin/env python3
"""
YouTube Live Stream Processor with Decision Engine Integration
=============================================================
Processes YouTube live streams in real-time with all AI models and traffic decision making
"""

import cv2
import numpy as np
import sys
import time
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
import contextlib
import logging
import subprocess
import json
import asyncio

# Add project paths
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "services" / "ai-perception" / "src"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import AI models
from config import model_config, perception_config
from detection.yolo_detector import YOLODetector
from license_plate_processor import LicensePlateProcessor
from brand.brand_classifier import BrandClassifier
from multiview.multiview_detector import MultiViewDetector
from tramway.tramway_detector import TramwayDetector
from emission.emission_calculator import EmissionCalculator
from calculations.enhanced_emission_calculator import EnhancedEmissionCalculator
from calculations.speed_calculator import SpeedCalculator
from trajectory_integration import IntegratedATMSSystem
from tracking.bytetrack_simple import SimpleByteTracker
from atms_config import get_atms_runtime_config
from atms_core.model_factory import (
    create_emission_calculators,
    create_integrated_atms_system,
    create_speed_calculator,
    create_tracker,
    first_existing_path,
    resolve_auto_device,
    try_create_brand_classifier,
    try_create_license_plate_processor,
    try_create_multiview_detector,
    try_create_tramway_detector,
)
from atms_core.pipeline import ATMSPipeline

# Kafka and Decision Engine
try:
    from aiokafka import AIOKafkaProducer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logger.warning("Kafka not available - decisions won't be sent to Kafka")

# Decision Engine - will be imported in initialize_models
DECISION_ENGINE_AVAILABLE = True  # We created ai_decision_system.py in project root


# Monitoring - Phase 1 implementation
try:
    # Try importing dependencies first
    try:
        from prometheus_client import start_http_server
        import psutil
        DEPS_AVAILABLE = True
    except ImportError as e:
        DEPS_AVAILABLE = False
        logger.warning(f"⚠️  Monitoring dependencies not available: {e}")
        logger.warning("   Install with: pip install prometheus-client psutil")
        logger.warning("   Note: Make sure you're using the correct Python environment")
    
    if DEPS_AVAILABLE:
        from monitoring import PerformanceCollector
        # Dashboard is optional (requires tkinter which may not be available)
        try:
            from monitoring.dashboard import create_dashboard
            DASHBOARD_AVAILABLE = True
        except ImportError:
            # Silently ignore - dashboard is optional
            DASHBOARD_AVAILABLE = False
            create_dashboard = None
        MONITORING_AVAILABLE = True
    else:
        MONITORING_AVAILABLE = False
        create_dashboard = None
        DASHBOARD_AVAILABLE = False
except ImportError as e:
    MONITORING_AVAILABLE = False
    logger.warning(f"⚠️  Monitoring module import failed: {e}")
    logger.warning("   Install with: pip install prometheus-client psutil")
    create_dashboard = None
    DASHBOARD_AVAILABLE = False


class YouTubeDecisionProcessor:
    """
    YouTube Live Stream Processor with Decision Engine
    Processes YouTube streams in real-time with all AI models and makes traffic decisions
    """
    
    def __init__(self, youtube_url: str, output_path: Optional[Path] = None):
        self.youtube_url = youtube_url
        self.stream_url = None
        
        # Generate output path from YouTube URL
        video_id = youtube_url.split('watch?v=')[-1].split('&')[0] if 'watch?v=' in youtube_url else youtube_url.split('/')[-1]
        output_name = f"youtube_{video_id}_processed.mp4"
        self.output_path = output_path or (project_root / "Processed_Videos" / output_name)
        self.output_path.parent.mkdir(exist_ok=True, parents=True)
        
        # Initialize all AI models
        self.detector = None
        self.plate_processor = None
        self.brand_classifier = None
        self.multiview_detector = None
        self.tramway_detector = None
        self.emission_calculator = None
        self.enhanced_emission_calculator = None
        self.speed_calculator = None
        self.atms_system = None
        self.tracker = None
        self.pipeline: Optional[ATMSPipeline] = None
        
        # Decision Engine
        self.decision_engine = None
        self.kafka_producer = None  # For decisions (AIOKafkaProducer)
        self.kafka_detection_producer = None  # For detections (KafkaDetectionProducer)
        self.current_decision = None
        self.decision_history = []
        self.decision_update_interval = 30  # Update decision every 30 frames (~1 second at 30 FPS)
        
        # Dashboard (optional)
        self.dashboard = None
        
        # CSV Export
        self.all_detections = []  # Store all detection data for CSV export
        self.video_fps = 25.0  # Will be updated with actual video FPS
        
        # Traffic metrics for decision making
        self.traffic_metrics = {
            'north_south': {
                'vehicle_count': 0,
                'average_emission': 0.0,
                'average_waiting_time': 0.0,
                'average_velocity': 0.0,
                'total_emission': 0.0,
                'environmental_impact_score': 0.0
            },
            'east_west': {
                'vehicle_count': 0,
                'average_emission': 0.0,
                'average_waiting_time': 0.0,
                'average_velocity': 0.0,
                'total_emission': 0.0,
                'environmental_impact_score': 0.0
            }
        }
        
        # Tracking and trajectory
        self.track_buffer: Dict[int, Dict] = {}
        self.trajectory_history: Dict[int, List[Tuple[float, float]]] = {}
        self.trajectory_max_length = 60
        self.actual_fps = 25.0
        
        # Statistics
        self.frame_count = 0
        self.total_detections = 0
        self.start_time = None
        
        # Data storage for CSV export
        self.all_detections: List[Dict] = []
        self.video_start_time = datetime.now()
        
        # Monitoring (Phase 1) - Non-blocking performance monitoring
        self.performance_collector = None
        self.dashboard = None
        if MONITORING_AVAILABLE:
            try:
                self.performance_collector = PerformanceCollector(
                    update_interval=1.0,
                    enable_prometheus=True
                )
                logger.info("✅ Performance monitoring enabled")
                # Verify metrics server will start
                if self.performance_collector.metrics and self.performance_collector.metrics.enabled:
                    logger.info(f"   📊 Metrics server will start on port {self.performance_collector.metrics.port}")
                    logger.info(f"   Prometheus should scrape from: http://host.docker.internal:{self.performance_collector.metrics.port}/metrics")
                else:
                    logger.warning("⚠️  Metrics server not enabled - Prometheus won't be able to scrape")
                    logger.warning("   Install dependencies: pip install prometheus-client psutil")
            except Exception as e:
                logger.error(f"❌ Performance monitoring initialization failed: {e}")
                logger.error("   Install dependencies: pip install prometheus-client psutil")
                self.performance_collector = None
    
    def _get_youtube_stream_url(self, youtube_url: str) -> Optional[str]:
        """Extract stream URL from YouTube using yt-dlp"""
        try:
            logger.info(f"🔗 Extracting YouTube stream URL from: {youtube_url}")
            # Use yt-dlp to get best video stream URL (720p for faster processing)
            cmd = [
                'yt-dlp',
                '-f', 'best[height<=720]',  # Get best quality up to 720p
                '--get-url',
                youtube_url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                stream_url = result.stdout.strip()
                logger.info(f"✅ YouTube stream URL extracted successfully")
                logger.info(f"   Stream URL: {stream_url[:80]}...")
                return stream_url
            else:
                logger.error(f"❌ Failed to extract stream URL: {result.stderr}")
                return None
        except subprocess.TimeoutExpired:
            logger.error("❌ Timeout extracting YouTube stream URL")
            return None
        except FileNotFoundError:
            logger.error("❌ yt-dlp not found. Install with: pip install yt-dlp")
            logger.error("   Or: brew install yt-dlp (on macOS)")
            return None
        except Exception as e:
            logger.error(f"❌ Error extracting YouTube stream: {e}")
            return None
    
    def initialize_models(self) -> bool:
        """Initialize all AI models and decision engine"""
        try:
            logger.info("🔧 Initializing AI models and Decision Engine...")
            
            # Import existing initialization from realtime_video_processor
            # For now, we'll duplicate the initialization logic
            # (In production, this should be refactored to share code)
            
            # 1. YOLO Detector
            logger.info("   Loading YOLO detector...")
            auto_device = resolve_auto_device(model_config.DEVICE)
            if auto_device != model_config.DEVICE:
                logger.info(
                    f"   🍎 macOS detected - using {auto_device} (enables CoreML optimization)"
                )
            
            trained_model_paths = [
                project_root / "models" / "vehicle_classification_training" / "weights" / "best.mlpackage",
                project_root / "models" / "vehicle_classification_training" / "weights" / "best.pt",
                project_root / "models" / "yolov8n.mlpackage",
                project_root / "models" / "yolov8n.pt",
            ]
            
            model_path = model_config.MODEL_PATH
            for path in trained_model_paths:
                if path.exists():
                    model_path = str(path)
                    logger.info(f"   ✅ Found trained model: {path.name}")
                    break
            
            # IMPROVEMENT: Lower confidence threshold for better distant object detection
            # Use 0.25 instead of 0.3 to catch more distant objects (will be filtered later)
            self.detector = YOLODetector(
                model_path=model_path,
                confidence_threshold=0.25,  # Lowered from 0.3 for better range detection
                device=auto_device
            )
            if not self.detector.load_model():
                logger.error("   ❌ Failed to load YOLO detector")
                return False
            logger.info(f"   ✅ YOLO Detector initialized (device: {auto_device}, CoreML: {self.detector.use_coreml})")
            
            # 2. License Plate Processor
            logger.info("   Loading License Plate Processor...")
            plate_candidates = [
                project_root
                / "models"
                / "license_plate_training"
                / "outputs"
                / "license_plate_model_mps"
                / "weights"
                / "best.mlpackage",
                project_root
                / "models"
                / "license_plate_training"
                / "outputs"
                / "license_plate_model_mps"
                / "weights"
                / "best.pt",
            ]
            plate_model_path = first_existing_path(plate_candidates)
            self.plate_processor = try_create_license_plate_processor(
                yolo_model_path=str(plate_model_path) if plate_model_path else None,
                ocr_primary_method="professional",
                confidence_threshold=0.15,
            )
            if self.plate_processor:
                logger.info("   ✅ License Plate Processor initialized")
            else:
                logger.warning("   ⚠️ License plate model not found, skipping")
            
            # 3. Brand Classifier
            logger.info("   Loading Brand Classifier...")
            brand_candidates = [
                project_root
                / "models"
                / "car_brand_classification"
                / "outputs"
                / "car_brand_classification_robust"
                / "weights"
                / "best.mlpackage",
                project_root
                / "models"
                / "car_brand_classification"
                / "outputs"
                / "car_brand_classification_robust"
                / "weights"
                / "best.pt",
            ]
            brand_model_path = first_existing_path(brand_candidates)
            self.brand_classifier = try_create_brand_classifier(
                model_path=str(brand_model_path) if brand_model_path else None,
                confidence_threshold=0.3,
                device=auto_device,
            )
            if self.brand_classifier:
                logger.info("   ✅ Brand Classifier initialized")
            else:
                logger.warning("   ⚠️ Brand model not found or failed to load, skipping")
            
            # 4. Multi-View Detector (DISABLED by default)
            ENABLE_MULTIVIEW = False
            if ENABLE_MULTIVIEW:
                logger.info("   Loading Multi-View Detector...")
                try:
                    self.multiview_detector = try_create_multiview_detector(
                        top_model_path=str(
                            project_root
                            / "multiview_models"
                            / "top_view_model"
                            / "weights"
                            / "best.mlpackage"
                        ),
                        side_model_path=str(
                            project_root
                            / "multiview_models"
                            / "side_profile_model"
                            / "weights"
                            / "best.mlpackage"
                        ),
                        front_model_path=str(
                            project_root
                            / "multiview_models"
                            / "front_bumper_model"
                            / "weights"
                            / "best.mlpackage"
                        ),
                        confidence_threshold=0.50,
                        iou_threshold=0.45,
                        device=auto_device,
                        enable_fusion=True,
                    )
                    if self.multiview_detector:
                        logger.info("   ✅ Multi-View Detector initialized")
                    else:
                        self.multiview_detector = None
                except Exception as e:
                    logger.warning(f"   ⚠️ Multi-View Detector error: {e}")
                    self.multiview_detector = None
            else:
                self.multiview_detector = None
            
            # 5. Tramway Detector (DISABLED by default)
            ENABLE_TRAMWAY = False
            if ENABLE_TRAMWAY:
                logger.info("   Loading Tramway Detector...")
                tramway_candidates = [
                    project_root
                    / "models"
                    / "tramway_training"
                    / "tramway_runs"
                    / "train_20251028_210058"
                    / "weights"
                    / "best.mlpackage",
                    project_root
                    / "models"
                    / "tramway_training"
                    / "tramway_runs"
                    / "train_20251028_210058"
                    / "weights"
                    / "best.pt",
                ]
                tramway_model_path = first_existing_path(tramway_candidates)
                self.tramway_detector = try_create_tramway_detector(
                    model_path=str(tramway_model_path) if tramway_model_path else None,
                    confidence_threshold=0.60,
                    device=auto_device,
                )
                if self.tramway_detector:
                    logger.info("   ✅ Tramway Detector initialized")
                else:
                    self.tramway_detector = None
            else:
                self.tramway_detector = None
            
            # 6. Emission Calculator
            logger.info("   Loading Emission Calculator...")
            self.emission_calculator, self.enhanced_emission_calculator = create_emission_calculators()
            logger.info("   ✅ Emission Calculator initialized")
            
            # 7. Enhanced Emission Calculator (created above)
            logger.info("   ✅ Enhanced Emission Calculator initialized")
            
            # 8. Speed Calculator - IMPROVEMENT: Auto-calibrate pixel-to-meter ratio
            logger.info("   Loading Speed Calculator...")
            # IMPROVEMENT: Auto-estimate pixel-to-meter ratio based on typical YouTube video resolution
            # YouTube videos are typically 1920x1080 or 1280x720
            # For city street intersection: ~0.05-0.08 m/pixel is typical
            # We'll use a conservative estimate and allow manual override via env var
            import os
            pixel_to_meter_ratio = float(os.getenv("PIXEL_TO_METER_RATIO", "0.06"))  # Improved default for YouTube videos
            self.speed_calculator = create_speed_calculator(
                pixel_to_meter_ratio=pixel_to_meter_ratio,
                fps=25.0,  # Will be updated with actual video FPS
                min_track_length=3,  # Reduced from 5 to 3 for faster speed calculation
                max_track_history=30,
                use_kalman=True,
                use_cvm=True,
                use_wls=True,
            )
            logger.info(f"   ✅ Speed Calculator initialized (pixel-to-meter: {pixel_to_meter_ratio:.4f} m/pixel)")
            logger.info("   💡 Set PIXEL_TO_METER_RATIO env var to calibrate for your camera angle")
            
            # 9. ATMS System
            logger.info("   Loading ATMS System...")
            self.atms_system = create_integrated_atms_system(
                intersection_id=1,
                prediction_horizon=5.0,
                optimization_enabled=True,
            )
            logger.info("   ✅ ATMS System initialized")
            
            # 10. ByteTracker
            logger.info("   Loading ByteTracker...")
            self.tracker = create_tracker()
            logger.info("   ✅ ByteTracker initialized")

            # 11. Shared pipeline for detection->tracking->speed->emissions.
            # YouTube currently uses distance-aware filtering + emissions for decision making.
            # To keep the script behavior close to the existing version, we disable ATMS
            # prediction inside this pipeline and keep plate/brand/multiview disabled per-frame.
            self.pipeline = ATMSPipeline(
                detector=self.detector,
                tracker=self.tracker,
                speed_calculator=self.speed_calculator,
                enhanced_emission_calculator=self.enhanced_emission_calculator,
                atms_system=None,  # Disable ATMS trajectory/anomaly prediction
                trajectory_history=self.trajectory_history,
                trajectory_max_length=self.trajectory_max_length,
                plate_processor=self.plate_processor,
                brand_classifier=self.brand_classifier,
                multiview_detector=self.multiview_detector,
                max_yolo_detections=300,
                max_tracked_objects=30,
                speed_confidence_threshold=0.3,
            )
            
            # 11. Decision Engine
            logger.info("   Loading Decision Engine...")
            try:
                # Import from project root (where we created ai_decision_system.py)
                from ai_decision_system import AIDecisionEngine, TrafficPhase, DecisionPriority
                self.decision_engine = AIDecisionEngine()
                logger.info("   ✅ Decision Engine initialized")
            except ImportError as e:
                logger.warning(f"   ⚠️ Decision Engine not available: {e}")
                logger.warning("   💡 Make sure ai_decision_system.py is in project root")
                self.decision_engine = None
            except Exception as e:
                logger.warning(f"   ⚠️ Decision Engine initialization error: {e}")
                self.decision_engine = None
            
            # 12. Kafka Producer for Decisions (optional)
            if KAFKA_AVAILABLE:
                try:
                    import os
                    kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
                    logger.info(f"   Initializing Kafka producer for decisions...")
                    # Will be initialized asynchronously
                except Exception as e:
                    logger.warning(f"   ⚠️ Kafka not available: {e}")
            
            logger.info("✅ All AI models and Decision Engine initialized successfully!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error initializing models: {e}", exc_info=True)
            return False
    
    async def initialize_kafka(self):
        """Initialize Kafka producer for decisions"""
        if not KAFKA_AVAILABLE:
            return False
        
        try:
            import os
            kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")

            # Assign to self only AFTER start() succeeds — if the caller's
            # wait_for() cancels a slow start, a half-initialized producer
            # must not be left behind for the frame loop / shutdown to trip on.
            producer = AIOKafkaProducer(
                bootstrap_servers=kafka_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            try:
                await producer.start()
            except BaseException:
                # Covers CancelledError from the caller's timeout as well.
                with contextlib.suppress(Exception):
                    await producer.stop()
                raise
            self.kafka_producer = producer
            logger.info("✅ Kafka producer initialized for decisions")
            
            # Initialize KafkaDetectionProducer for detections
            try:
                import sys
                import importlib.util
                kafka_producer_path = project_root / "services" / "ai-perception" / "src" / "kafka" / "producer.py"
                if kafka_producer_path.exists():
                    spec = importlib.util.spec_from_file_location("kafka_producer", kafka_producer_path)
                    kafka_producer_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(kafka_producer_module)
                    KafkaDetectionProducer = kafka_producer_module.KafkaDetectionProducer
                self.kafka_detection_producer = KafkaDetectionProducer(
                    bootstrap_servers=kafka_servers[0] if kafka_servers else "localhost:9092",
                    client_id="youtube-decision-processor"
                )
                await self.kafka_detection_producer.start()
                logger.info("✅ Kafka detection producer initialized")
            except Exception as e:
                logger.warning(f"⚠️ Kafka detection producer initialization failed: {e}")
                logger.warning("   Detections will not be sent to Kafka, but decisions will work")
                self.kafka_detection_producer = None
            
            return True
        except Exception as e:
            logger.warning(f"⚠️ Kafka producer initialization failed: {e}")
            self.kafka_producer = None
            return False
    
    async def make_traffic_decision(self, detections: List[Dict], frame_width: int = 1920, frame_height: int = 1080) -> Optional[Dict]:
        """Make traffic decision based on current detections"""
        if not self.decision_engine:
            return None
        
        try:
            # Calculate traffic metrics from detections
            # Split detections by direction (simplified - in production would use actual direction)
            # For now, split by frame position (left/right or top/bottom)
            
            north_south_detections = []
            east_west_detections = []
            
            for det in detections:
                bbox = det.get('bbox', {})
                center_x = (bbox.get('x1', 0) + bbox.get('x2', 0)) / 2
                center_y = (bbox.get('y1', 0) + bbox.get('y2', 0)) / 2
                
                # Simple split: left half = north_south, right half = east_west
                # (In production, use actual road direction detection)
                if center_x < frame_width / 2:
                    north_south_detections.append(det)
                else:
                    east_west_detections.append(det)
            
            # Calculate metrics for each direction
            def calculate_metrics(detections_list):
                if not detections_list:
                    return {
                        'vehicle_count': 0,
                        'average_emission': 0.0,
                        'average_waiting_time': 0.0,
                        'average_velocity': 0.0,
                        'total_emission': 0.0,
                        'environmental_impact_score': 0.0
                    }
                
                vehicle_count = len(detections_list)
                
                # Calculate REAL emissions from detections (only non-zero values)
                emissions_list = [d.get('emission_co2', 0) for d in detections_list if d.get('emission_co2', 0) > 0]
                total_emission = sum(emissions_list) if emissions_list else 0.0
                avg_emission = total_emission / len(emissions_list) if emissions_list else 0.0
                
                # Calculate REAL speeds from detections (only non-zero values)
                # FIX: Handle None values properly - filter out None before comparison
                speeds_list = [d.get('speed', 0) for d in detections_list 
                              if d.get('speed') is not None and d.get('speed', 0) > 0]
                avg_velocity = sum(speeds_list) / len(speeds_list) if speeds_list else 0.0
                
                # Calculate waiting time from low speeds (< 5 km/h = waiting/idle)
                low_speed_count = sum(1 for s in speeds_list if s < 5.0)
                avg_waiting_time = (low_speed_count / vehicle_count * 30.0) if vehicle_count > 0 else 0.0
                
                # Environmental impact score (0-100, higher = worse)
                # Based on total emissions and vehicle count
                env_score = min(100.0, (total_emission / 100.0) + (vehicle_count * 2.0))
                
                return {
                    'vehicle_count': vehicle_count,
                    'average_emission': avg_emission,
                    'average_waiting_time': avg_waiting_time,
                    'average_velocity': avg_velocity,
                    'total_emission': total_emission,
                    'environmental_impact_score': env_score
                }
            
            self.traffic_metrics['north_south'] = calculate_metrics(north_south_detections)
            self.traffic_metrics['east_west'] = calculate_metrics(east_west_detections)
            
            # Make decision
            decision = self.decision_engine.make_decision(
                self.traffic_metrics['north_south'],
                self.traffic_metrics['east_west']
            )
            
            # Check if decision was created successfully
            if decision is None:
                logger.error("❌ Decision engine returned None - cannot proceed")
                return None
            
            logger.debug(f"Decision engine returned: {decision.recommended_phase.value} (confidence: {decision.confidence})")
            
            # Execute decision (only if valid)
            self.decision_engine.execute_decision(decision)
            
            # Format decision for display and Kafka
            decision_dict = {
                'decision_id': decision.decision_id,
                'timestamp': decision.timestamp.isoformat(),
                'current_phase': decision.current_phase.value,
                'recommended_phase': decision.recommended_phase.value,
                'priority': decision.priority.value,
                'reason': decision.reason,
                'confidence': decision.confidence,
                'expected_impact': decision.expected_impact,
                'traffic_metrics': self.traffic_metrics
            }
            
            self.current_decision = decision_dict
            self.decision_history.append(decision_dict)
            
            # Keep only last 100 decisions
            if len(self.decision_history) > 100:
                self.decision_history.pop(0)
            
            # Send to Kafka - FIX: Add timeout to prevent blocking
            if self.kafka_producer:
                try:
                    # FIX: Add timeout to prevent hanging when Kafka is unavailable
                    future = await asyncio.wait_for(
                        self.kafka_producer.send('decisions', value=decision_dict),
                        timeout=0.2  # Very short timeout - Kafka is optional
                    )
                    # Wait for send to complete with timeout
                    record_metadata = await asyncio.wait_for(future, timeout=0.2)
                    logger.info(f"📤 Decision sent to Kafka: {decision.recommended_phase.value} (ID: {decision.decision_id[:8]})")
                except asyncio.TimeoutError:
                    # FIX: Don't log error - Kafka is optional, just continue
                    if self.frame_count % 60 == 0:  # Only log occasionally
                        logger.debug("⚠️ Kafka send timeout (non-blocking) - continuing without Kafka")
                except Exception as e:
                    # FIX: Don't let Kafka errors block decision making
                    if self.frame_count % 60 == 0:  # Only log occasionally
                        logger.debug(f"⚠️ Kafka send error (non-blocking): {type(e).__name__}")
            
            return decision_dict
            
        except Exception as e:
            logger.error(f"❌ Error making traffic decision: {e}", exc_info=True)
            return None
    
    def draw_decision(self, frame: np.ndarray) -> np.ndarray:
        """Draw current traffic decision on frame with per-direction phases"""
        if not self.current_decision:
            # Draw a placeholder message if no decision yet
            height, width = frame.shape[:2]
            cv2.putText(
                frame,
                "Waiting for decision...",
                (width - 200, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (128, 128, 128),
                2
            )
            return frame
        
        annotated_frame = frame.copy()
        height, width = frame.shape[:2]
        
        # Get traffic metrics for per-direction display
        traffic_metrics = self.current_decision.get('traffic_metrics', {})
        ns_metrics = traffic_metrics.get('north_south', {})
        ew_metrics = traffic_metrics.get('east_west', {})
        
        # Determine per-direction phases based on decision logic
        recommended_phase = self.current_decision.get('recommended_phase', 'GREEN')
        ns_count = ns_metrics.get('vehicle_count', 0)
        ew_count = ew_metrics.get('vehicle_count', 0)
        
        if recommended_phase == 'GREEN':
            # Give GREEN to direction with more vehicles
            ns_phase = 'GREEN' if ns_count >= ew_count else 'RED'
            ew_phase = 'GREEN' if ew_count > ns_count else 'RED'
        elif recommended_phase == 'YELLOW':
            # Transition phase
            ns_phase = 'YELLOW' if ns_count >= ew_count else 'RED'
            ew_phase = 'YELLOW' if ew_count > ns_count else 'RED'
        else:
            # RED or ALL_RED
            ns_phase = 'RED'
            ew_phase = 'RED'
        
        # Decision display box (top-right corner) - expanded for per-direction display
        box_x = width - 380
        box_y = 10
        box_width = 370
        box_height = 240
        
        # Background box
        cv2.rectangle(
            annotated_frame,
            (box_x, box_y),
            (box_x + box_width, box_y + box_height),
            (0, 0, 0),
            -1
        )
        cv2.rectangle(
            annotated_frame,
            (box_x, box_y),
            (box_x + box_width, box_y + box_height),
            (0, 255, 0),
            2
        )
        
        # Decision text
        decision = self.current_decision
        y_offset = box_y + 25
        line_height = 22
        
        # Title
        cv2.putText(
            annotated_frame,
            "TRAFFIC DECISION",
            (box_x + 10, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2
        )
        
        y_offset += line_height + 5
        
        # Per-Direction Phases
        ns_color = (0, 255, 0) if ns_phase == 'GREEN' else (0, 165, 255) if ns_phase == 'YELLOW' else (0, 0, 255)
        ew_color = (0, 255, 0) if ew_phase == 'GREEN' else (0, 165, 255) if ew_phase == 'YELLOW' else (0, 0, 255)
        
        cv2.putText(
            annotated_frame,
            f"North-South: {ns_phase} ({ns_count} vehicles)",
            (box_x + 10, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            ns_color,
            2
        )
        
        y_offset += line_height
        
        cv2.putText(
            annotated_frame,
            f"East-West: {ew_phase} ({ew_count} vehicles)",
            (box_x + 10, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            ew_color,
            2
        )
        
        y_offset += line_height + 5
        
        # Overall Recommended Phase
        phase_color = (0, 255, 0) if decision['recommended_phase'] == 'GREEN' else (0, 165, 255) if decision['recommended_phase'] == 'YELLOW' else (0, 0, 255)
        cv2.putText(
            annotated_frame,
            f"Overall: {decision['recommended_phase']}",
            (box_x + 10, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            phase_color,
            2
        )
        
        y_offset += line_height
        
        # Priority
        priority_color = (0, 255, 255) if decision['priority'] == 'HIGH' else (255, 255, 0)
        cv2.putText(
            annotated_frame,
            f"Priority: {decision['priority']}",
            (box_x + 10, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            priority_color,
            1
        )
        
        y_offset += line_height
        
        # Reason (truncated if too long)
        reason = decision['reason'][:40] + "..." if len(decision['reason']) > 40 else decision['reason']
        cv2.putText(
            annotated_frame,
            f"Reason: {reason}",
            (box_x + 10, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (200, 200, 200),
            1
        )
        
        y_offset += line_height
        
        # Confidence
        cv2.putText(
            annotated_frame,
            f"Confidence: {decision['confidence']:.1%}",
            (box_x + 10, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (200, 200, 200),
            1
        )
        
        return annotated_frame
    
    def process_video(self, display: bool = True, save_output: bool = True):
        """Process YouTube stream in real-time with decision making"""
        # Extract YouTube stream URL
        self.stream_url = self._get_youtube_stream_url(self.youtube_url)
        if not self.stream_url:
            logger.error(f"❌ Failed to extract YouTube stream URL")
            return False
        
        # Open stream. FFmpeg timeouts MUST be passed at open time —
        # cap.set() after opening silently ignores them, which lets a
        # stalled HLS stream block cap.read() forever.
        logger.info(f"📺 Opening YouTube stream...")
        cap = cv2.VideoCapture(
            self.stream_url,
            cv2.CAP_FFMPEG,
            [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000,  # 10 s open timeout
                cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000,   # 5 s read timeout
            ],
        )
        
        if not cap.isOpened():
            logger.error(f"❌ Cannot open YouTube stream")
            return False
        
        # Initialize models
        if not self.initialize_models():
            logger.error("❌ Failed to initialize models")
            cap.release()
            return False
        
        # Initialize Kafka (async) - create event loop for async operations
        # FIX: Use new_event_loop() instead of deprecated get_event_loop()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # FIX: Add timeout to prevent hanging
        try:
            loop.run_until_complete(asyncio.wait_for(self.initialize_kafka(), timeout=5.0))
        except asyncio.TimeoutError:
            logger.warning("⚠️ Kafka initialization timeout - continuing without Kafka")
        except Exception as e:
            logger.warning(f"⚠️ Kafka initialization failed: {e} - continuing without Kafka")
        
        # Get video properties
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.video_fps = fps  # Store for CSV export
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        logger.info(f"📹 Stream Info:")
        logger.info(f"   Resolution: {width}x{height}")
        logger.info(f"   FPS: {fps}")
        logger.info(f"   YouTube URL: {self.youtube_url}")
        
        # IMPROVEMENT: Auto-calibrate pixel-to-meter ratio based on video resolution
        if self.speed_calculator:
            self.speed_calculator.fps = fps
            self.video_fps = fps
            
            # IMPROVEMENT: Auto-estimate pixel-to-meter ratio based on resolution
            # Higher resolution = smaller objects = larger pixel-to-meter ratio
            # Typical values:
            # - 1920x1080 (Full HD): ~0.05-0.08 m/pixel for intersection
            # - 1280x720 (HD): ~0.08-0.12 m/pixel
            # - 640x480 (SD): ~0.12-0.20 m/pixel
            import os
            if not os.getenv("PIXEL_TO_METER_RATIO"):
                if width >= 1920:
                    estimated_ratio = 0.06  # Full HD: smaller ratio (more pixels per meter)
                elif width >= 1280:
                    estimated_ratio = 0.08  # HD: medium ratio
                else:
                    estimated_ratio = 0.12  # SD: larger ratio (fewer pixels per meter)
                
                self.speed_calculator.pixel_to_meter_ratio = estimated_ratio
                logger.info(f"   ✅ Auto-calibrated pixel-to-meter ratio: {estimated_ratio:.4f} m/pixel")
            else:
                logger.info(f"   ✅ Using manual pixel-to-meter ratio: {self.speed_calculator.pixel_to_meter_ratio:.4f} m/pixel")
            
            logger.info(f"   ✅ Speed calculator FPS set to: {fps}")
        
        # Setup video writer
        writer = None
        if save_output:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(str(self.output_path), fourcc, fps, (width, height))
            logger.info(f"💾 Output will be saved to: {self.output_path}")
        
        self.start_time = time.time()
        
        # Start performance monitoring (Phase 1)
        if self.performance_collector:
            self.performance_collector.start()
            logger.info("📊 Performance monitoring started")
        
        # Start Python dashboard if requested (Phase 1, Week 2)
        if hasattr(self, '_show_dashboard') and self._show_dashboard and create_dashboard:
            try:
                self.dashboard = create_dashboard(self.performance_collector)
                if self.dashboard:
                    logger.info("📊 Python dashboard started")
                    # Dashboard runs in separate thread, no blocking
            except Exception as e:
                logger.warning(f"Could not start dashboard: {e}")
                self.dashboard = None
        
        logger.info("🚀 Starting YouTube stream processing with Decision Engine...")
        logger.info("   Press 'q' to quit, 's' to save and quit")
        
        # Performance settings
        PLATE_PROCESS_INTERVAL = 60
        ENABLE_OCR = True
        BRAND_PROCESS_INTERVAL = 20
        MULTIVIEW_PROCESS_INTERVAL = 30
        MAX_PLATES_PER_FRAME = 1
        OCR_TIMEOUT = 0.8
        DISPLAY_FRAME_SKIP = 1
        RESIZE_FOR_PROCESSING = True
        PROCESSING_WIDTH = 1280
        PROCESSING_HEIGHT = 720
        target_fps = min(fps, 30.0)
        frame_delay = 1.0 / target_fps
        
        logger.info(f"⚡ Performance settings:")
        logger.info(f"   Plate OCR: Every {PLATE_PROCESS_INTERVAL} frames")
        logger.info(f"   Brand: Every {BRAND_PROCESS_INTERVAL} frames")
        logger.info(f"   Decision: Every {self.decision_update_interval} frames")
        logger.info(f"   Target FPS: {target_fps}")
        
        # FIX: Add frame read retry counter
        consecutive_failures = 0
        max_consecutive_failures = 10
        
        try:
            while cap.isOpened():
                frame_start_time = time.time()
                ret, frame = cap.read()
                if not ret:
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(f"❌ Too many consecutive frame read failures ({consecutive_failures}). Stream may be disconnected.")
                        break
                    
                    # FIX: Exponential backoff for retries
                    wait_time = min(0.1 * (2 ** min(consecutive_failures, 5)), 2.0)  # Max 2 seconds
                    if self.frame_count % 10 == 0:  # Only log every 10 failures
                        logger.warning(f"⚠️ Failed to read frame from stream (attempt {consecutive_failures}/{max_consecutive_failures})")
                    time.sleep(wait_time)
                    continue
                
                # FIX: Reset failure counter on successful read
                consecutive_failures = 0
                
                self.frame_count += 1
                
                # FPS OPTIMIZATION: Resize frame for faster processing (if enabled)
                processing_frame = frame
                if RESIZE_FOR_PROCESSING and (frame.shape[1] > PROCESSING_WIDTH or frame.shape[0] > PROCESSING_HEIGHT):
                    # Calculate aspect ratio preserving dimensions
                    aspect_ratio = frame.shape[1] / frame.shape[0]
                    if aspect_ratio > (PROCESSING_WIDTH / PROCESSING_HEIGHT):
                        new_width = PROCESSING_WIDTH
                        new_height = int(PROCESSING_WIDTH / aspect_ratio)
                    else:
                        new_height = PROCESSING_HEIGHT
                        new_width = int(PROCESSING_HEIGHT * aspect_ratio)
                    processing_frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                
                # Process frame with all models
                detections = []
                detection_start_time = time.time()
                try:
                    # MVP: pipeline path (skips legacy per-frame logic on success).
                    if self.pipeline:
                        try:
                            runtime_cfg = get_atms_runtime_config()
                            dist_params = {
                                "vehicle_base_conf": runtime_cfg.detection.vehicle_base_conf,
                                "pedestrian_base_conf": runtime_cfg.detection.pedestrian_base_conf,
                                "other_base_conf": runtime_cfg.detection.other_base_conf,
                                "large_relative_size_threshold": runtime_cfg.detection.large_relative_size_threshold,
                                "medium_relative_size_threshold": runtime_cfg.detection.medium_relative_size_threshold,
                                "large_size_multiplier": runtime_cfg.detection.large_size_multiplier,
                                "medium_size_multiplier": runtime_cfg.detection.medium_size_multiplier,
                                "far_size_multiplier": runtime_cfg.detection.far_size_multiplier,
                            }

                            scale_x = (
                                frame.shape[1] / processing_frame.shape[1]
                                if processing_frame.shape != frame.shape
                                else 1.0
                            )
                            scale_y = (
                                frame.shape[0] / processing_frame.shape[0]
                                if processing_frame.shape != frame.shape
                                else 1.0
                            )

                            detections = self.pipeline.process_frame(
                                processing_frame,
                                self.frame_count,
                                tracking_frame=frame,
                                bbox_scale=(scale_x, scale_y),
                                process_plates=False,
                                process_brand=False,
                                process_multiview=False,
                                apply_distance_aware_filtering=True,
                                distance_aware_filter_params=dist_params,
                                compute_emissions_for_all_tracked_objects=True,
                                run_atms_prediction=False,
                                return_all_tracked_objects=True,
                                low_confidence_speed_to_none=True,
                                video_fps=self.video_fps,
                                actual_fps=self.actual_fps,
                            )

                            stage_time_ms = (time.time() - detection_start_time) * 1000

                            # Record detection and tracking metrics (approx: pipeline covers the whole stage)
                            if self.performance_collector:
                                vehicles = sum(
                                    1
                                    for d in detections
                                    if str(d.get("class", "")).lower()
                                    in ["car", "truck", "bus", "motorcycle", "bicycle"]
                                )
                                pedestrians = sum(
                                    1
                                    for d in detections
                                    if str(d.get("class", "")).lower()
                                    in ["pedestrian", "person"]
                                )
                                self.performance_collector.record_detection(
                                    stage_time_ms,
                                    len(detections),
                                    vehicles,
                                    pedestrians,
                                )
                                self.performance_collector.record_tracking(stage_time_ms)

                            # Store detections for CSV export.
                            for det in detections:
                                det["frame_number"] = self.frame_count
                                det["frame_timestamp"] = datetime.now(timezone.utc).isoformat()
                                det["video_time_seconds"] = (
                                    self.frame_count / self.video_fps if self.video_fps > 0 else 0
                                )
                                self.all_detections.append(det.copy())

                        except Exception as e:
                            logger.error(
                                f"Pipeline processing failed on frame {self.frame_count}: {e}"
                            )
                            detections = []
                    else:
                        # The legacy inline per-frame path was removed —
                        # atms_core/pipeline.py is the single implementation.
                        raise RuntimeError(
                            "ATMS pipeline not initialized - initialize_models() "
                            "must succeed before processing frames"
                        )

                except Exception as e:
                    logger.error(f"Error processing frame: {e}")
                    detections = []
                
                # Store detections count for this frame (used for display and decision)
                current_frame_detections = len(detections)
                
                # Send detections to Kafka (if available and detections exist)
                # datetime is already imported at top of file, don't re-import
                if self.kafka_detection_producer and detections and self.frame_count % 5 == 0:  # Send every 5 frames
                    try:
                        from shared.models.detection import DetectionMessage, Detection, BoundingBox, ObjectClass
                        
                        # Convert dict detections to Detection objects for Kafka
                        kafka_detections = []
                        for det_dict in detections[:50]:  # Limit to 50 for performance
                            try:
                                bbox_dict = det_dict.get('bbox', {})
                                bbox = BoundingBox(
                                    x1=bbox_dict.get('x1', 0),
                                    y1=bbox_dict.get('y1', 0),
                                    x2=bbox_dict.get('x2', 0),
                                    y2=bbox_dict.get('y2', 0),
                                    confidence=det_dict.get('confidence', 0)
                                )
                                
                                # Map class string to ObjectClass enum
                                class_str = det_dict.get('class', 'car').lower()
                                obj_class_map = {
                                    'car': ObjectClass.CAR,
                                    'truck': ObjectClass.TRUCK,
                                    'bus': ObjectClass.BUS,
                                    'motorcycle': ObjectClass.MOTORCYCLE,
                                    'bicycle': ObjectClass.BICYCLE,
                                    'pedestrian': ObjectClass.PEDESTRIAN,
                                    'person': ObjectClass.PEDESTRIAN
                                }
                                obj_class = obj_class_map.get(class_str, ObjectClass.CAR)
                                
                                detection = Detection(
                                    detection_id=det_dict.get('detection_id', f"det_{self.frame_count}_{len(kafka_detections)}"),
                                    object_class=obj_class,
                                    bbox=bbox,
                                    confidence=det_dict.get('confidence', 0),
                                    # FIX: Use datetime.now(timezone.utc) instead of deprecated utcnow()
                                    timestamp=datetime.now(timezone.utc),
                                    frame_id=det_dict.get('frame_id', f"youtube_{self.frame_count}"),
                                    sensor_id=f"youtube_stream_{self.youtube_url.split('watch?v=')[-1].split('&')[0] if 'watch?v=' in self.youtube_url else 'stream'}",
                                    track_id=det_dict.get('track_id'),
                                    speed=det_dict.get('speed'),
                                    vehicle_brand=det_dict.get('vehicle_brand'),
                                    license_plate=det_dict.get('license_plate'),
                                    license_plate_confidence=det_dict.get('license_plate_confidence'),
                                    emission_co2=det_dict.get('emission_co2'),
                                    fuel_consumption=det_dict.get('fuel_consumption')
                                )
                                kafka_detections.append(detection)
                            except Exception as e:
                                if self.frame_count % 60 == 0:
                                    logger.debug(f"Error converting detection for Kafka: {e}")
                                continue
                        
                        if kafka_detections and self.kafka_detection_producer:
                            # Send to Kafka using the detection producer - FIX: Add timeout and error handling
                            frame_id = f"youtube_{self.frame_count}"
                            sensor_id = f"youtube_stream_{self.youtube_url.split('watch?v=')[-1].split('&')[0] if 'watch?v=' in self.youtube_url else 'stream'}"
                            
                            try:
                                # FIX: Add timeout to prevent hanging - skip if Kafka unavailable
                                if not self.kafka_detection_producer:
                                    continue
                                
                                loop.run_until_complete(
                                    asyncio.wait_for(
                                        self.kafka_detection_producer.send_detections(
                                            topic='detections',
                                            detections=kafka_detections,
                                            frame_id=frame_id,
                                            sensor_id=sensor_id,
                                            frame_width=width,
                                            frame_height=height,
                                            processing_time_ms=0.0,
                                            model_name='YOLOv8',
                                            model_version='1.0',
                                            intersection_id=1
                                        ),
                                        timeout=0.3  # FIX: Short timeout to prevent freezing
                                    )
                                )
                            except (asyncio.TimeoutError, Exception) as e:
                                # FIX: Don't let Kafka errors block processing
                                if self.frame_count % 60 == 0:
                                    logger.debug(f"Kafka send timeout/error (non-blocking): {e}")
                                # Continue processing even if Kafka fails
                                pass
                            if self.frame_count % 30 == 0:
                                logger.info(f"📤 Sent {len(kafka_detections)} detections to Kafka")
                    except Exception as e:
                        if self.frame_count % 60 == 0:
                            logger.error(f"Error sending detections to Kafka: {e}")
                
                # Make traffic decision (every N frames) - ONLY if we have detections
                # Debug: Log when we should make a decision
                if self.frame_count % 30 == 0:  # Log every 30 frames
                    logger.debug(f"Frame {self.frame_count}: decision_engine={self.decision_engine is not None}, detections={len(detections)}, should_make_decision={self.frame_count % self.decision_update_interval == 0}")
                
                if self.decision_engine and detections and self.frame_count % self.decision_update_interval == 0:
                    try:
                        # FIX: Add timeout to prevent hanging
                        decision_result = loop.run_until_complete(
                            asyncio.wait_for(
                                self.make_traffic_decision(detections, width, height),
                                timeout=0.5  # FIX: Reduced timeout to prevent freezing
                            )
                        )
                        if decision_result:
                            phase = decision_result.get('recommended_phase', 'N/A')
                            logger.info(f"✅ Decision made: {phase} (frame {self.frame_count}, detections: {len(detections)})")
                            # Update metrics
                            if self.performance_collector and self.performance_collector.metrics:
                                self.performance_collector.metrics.increment_decisions()
                                confidence = decision_result.get('confidence', 0.0)
                                self.performance_collector.metrics.record_decision_confidence(confidence)
                                # Update traffic metrics
                                traffic_metrics = decision_result.get('traffic_metrics', {})
                                ns = traffic_metrics.get('north_south', {})
                                ew = traffic_metrics.get('east_west', {})
                                self.performance_collector.metrics.update_traffic_metrics(
                                    ns_vehicles=ns.get('vehicle_count', 0),
                                    ew_vehicles=ew.get('vehicle_count', 0),
                                    ns_emission=ns.get('total_emission', 0.0) / 1000.0,  # Convert to kg
                                    ew_emission=ew.get('total_emission', 0.0) / 1000.0
                                )
                        else:
                            logger.warning(f"⚠️ No decision returned (frame {self.frame_count}, detections: {len(detections)})")
                    except Exception as e:
                        logger.error(f"❌ Error making decision: {e}", exc_info=True)
                
                # Update FPS
                if self.frame_count > 0:
                    self.actual_fps = self.frame_count / (time.time() - self.start_time)
                    
                    # Update FPS in performance collector (non-blocking)
                    if self.performance_collector:
                        self.performance_collector.update_fps(self.actual_fps)
                
                # Record frame processing time (non-blocking)
                frame_processing_time_ms = (time.time() - frame_start_time) * 1000
                if self.performance_collector:
                    self.performance_collector.record_frame_processing(frame_processing_time_ms)
                
                # Draw detections and decision
                if self.frame_count % DISPLAY_FRAME_SKIP == 0:
                    annotated_frame = frame.copy()
                    
                    # Draw bounding boxes and labels
                    for det in detections[:30]:  # Limit to 30 for performance
                        bbox = det.get('bbox', {})
                        x1, y1 = int(bbox.get('x1', 0)), int(bbox.get('y1', 0))
                        x2, y2 = int(bbox.get('x2', 0)), int(bbox.get('y2', 0))
                        track_id = det.get('track_id', 'N/A')
                        class_name = det.get('class', 'unknown')
                        confidence = det.get('confidence', 0.0)
                        speed = det.get('speed')
                        brand = det.get('vehicle_brand')
                        plate = det.get('license_plate')
                        co2 = det.get('emission_co2')
                        
                        color = (0, 255, 0) if confidence > 0.5 else (0, 165, 255)
                        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                        
                        # Build label
                        label_parts = [f"ID:{track_id}", f"{class_name} {confidence:.2f}"]
                        if speed:
                            label_parts.append(f"Speed:{speed:.1f}km/h")
                        if brand:
                            label_parts.append(f"Brand:{brand}")
                        if plate:
                            label_parts.append(f"Plate:{plate}")
                        if co2:
                            label_parts.append(f"CO2:{co2:.1f}g/km")
                        
                        label = " | ".join(label_parts[:5])  # Limit to 5 items
                        
                        # Label background
                        (label_width, label_height), baseline = cv2.getTextSize(
                            label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                        )
                        cv2.rectangle(
                            annotated_frame,
                            (x1, y1 - label_height - 10),
                            (x1 + label_width, y1),
                            (0, 0, 0),
                            -1
                        )
                        
                        # Label text
                        cv2.putText(
                            annotated_frame,
                            label,
                            (x1, y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (255, 255, 255),
                            1
                        )
                        
                        # Draw trajectory
                        if track_id and track_id in self.trajectory_history:
                            trajectory = self.trajectory_history[track_id]
                            if len(trajectory) > 1:
                                points = np.array(trajectory, dtype=np.int32)
                                cv2.polylines(annotated_frame, [points], False, (255, 0, 255), 2)
                    
                    # Update dashboard with all trajectory data (once per frame, not per detection)
                    if self.frame_count % 5 == 0 and self.dashboard and DASHBOARD_AVAILABLE:
                        try:
                            # Collect all trajectories and convert to normalized coordinates
                            frame_h, frame_w = annotated_frame.shape[:2]
                            dashboard_trajectories = {}
                            for tid, traj in self.trajectory_history.items():
                                if len(traj) > 1:
                                    # Normalize coordinates (0-1) for dashboard
                                    normalized = [(p[0]/frame_w, p[1]/frame_h) for p in traj[-30:]]  # Last 30 points
                                    dashboard_trajectories[tid] = normalized
                            
                            if dashboard_trajectories:
                                self.dashboard.update_trajectories(dashboard_trajectories)
                        except Exception as e:
                            if self.frame_count % 60 == 0:
                                logger.debug(f"Error updating dashboard trajectories: {e}")
                    
                    # Draw decision (always try, even if no current_decision)
                    annotated_frame = self.draw_decision(annotated_frame)
                    
                    # Debug: Log if decision exists (every 60 frames)
                    if self.frame_count % 60 == 0:
                        if self.current_decision:
                            logger.info(f"📊 Drawing decision: {self.current_decision.get('recommended_phase', 'N/A')} (frame {self.frame_count})")
                        else:
                            logger.debug(f"⚠️ No current decision to draw (frame {self.frame_count})")
                    
                    # FIX: Track detections properly - use current frame detections for display
                    # current_frame_detections is already set above after processing
                    
                    # Draw statistics - FIX: Show current frame detections, not cumulative
                    elapsed = time.time() - self.start_time if self.start_time else 0
                    stats_text = [
                        f"FPS: {self.actual_fps:.1f}",
                        f"Detections: {current_frame_detections}",  # FIX: Show current frame, not cumulative
                        f"Time: {elapsed:.1f}s",
                        f"Frame: {self.frame_count}"
                    ]
                    y_pos = 30
                    for text in stats_text:
                        cv2.putText(
                            annotated_frame,
                            text,
                            (10, y_pos),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.6,
                            (0, 255, 0),
                            2
                        )
                        y_pos += 25
                    
                    # Display
                    if display:
                        cv2.imshow('YouTube Stream - Traffic Decision System', annotated_frame)
                        key = cv2.waitKey(1) & 0xFF
                        if key == ord('q'):
                            logger.info("⏹️  Stopped by user")
                            break
                        elif key == ord('s'):
                            logger.info("💾 Saving and stopping...")
                            break
                    
                    # Save frame
                    if writer:
                        writer.write(annotated_frame)
                
                # Maintain target FPS
                processing_time = time.time() - frame_start_time
                sleep_time = max(0, frame_delay - processing_time)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                
                # Log progress
                if self.frame_count % 100 == 0:
                    logger.info(f"📹 Processed {self.frame_count} frames, FPS: {self.actual_fps:.1f}, Detections: {self.total_detections}")
                    if self.current_decision:
                        logger.info(f"   🚦 Current Decision: {self.current_decision['recommended_phase']} (Priority: {self.current_decision['priority']})")
            
            cap.release()
            if writer:
                writer.release()
            
            # Cleanup Kafka
            if self.kafka_producer:
                loop.run_until_complete(self.kafka_producer.stop())
            
            if self.kafka_detection_producer:
                loop.run_until_complete(self.kafka_detection_producer.stop())
            
            # Stop performance monitoring
            if self.performance_collector:
                self.performance_collector.stop()
                logger.info("📊 Performance monitoring stopped")
            
            # Stop dashboard
            if self.dashboard:
                self.dashboard.stop()
                logger.info("📊 Dashboard stopped")
            
            # Export all data to CSV
            logger.info("📊 Exporting detection data to CSV files...")
            self.export_to_csv()
            
            logger.info(f"✅ Processing complete: {self.frame_count} frames processed")
            logger.info(f"💾 Output saved to: {self.output_path}")
            
            return True
            
        except KeyboardInterrupt:
            logger.info("⏹️  Interrupted by user")
            cap.release()
            if writer:
                writer.release()
            if self.kafka_producer:
                loop.run_until_complete(self.kafka_producer.stop())
            
            if self.kafka_detection_producer:
                loop.run_until_complete(self.kafka_detection_producer.stop())
            
            # Stop performance monitoring
            if self.performance_collector:
                self.performance_collector.stop()
            
            # Export CSV even on interrupt
            if self.all_detections:
                logger.info("📊 Exporting detection data to CSV files...")
                self.export_to_csv()
            
            return True
        except Exception as e:
            logger.error(f"❌ Error processing video: {e}", exc_info=True)
            cap.release()
            if writer:
                writer.release()
            if self.kafka_producer:
                loop.run_until_complete(self.kafka_producer.stop())
            
            if self.kafka_detection_producer:
                loop.run_until_complete(self.kafka_detection_producer.stop())
            
            # Stop performance monitoring
            if self.performance_collector:
                self.performance_collector.stop()
            
            # Export CSV even on error
            if self.all_detections:
                logger.info("📊 Exporting detection data to CSV files...")
                self.export_to_csv()
            
            return False
    
    def export_to_csv(self):
        """Export all collected detection data to CSV files"""
        if not self.all_detections:
            logger.warning("⚠️ No detections to export to CSV")
            return
        
        import csv
        from pathlib import Path
        # datetime already imported at top of file (line 15)
        
        # Create CSV export directory
        csv_dir = self.output_path.parent / "CSV_Exports"
        csv_dir.mkdir(exist_ok=True, parents=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_id = self.youtube_url.split('watch?v=')[-1].split('&')[0] if 'watch?v=' in self.youtube_url else 'youtube'
        
        # 1. All Detections CSV
        all_detections_file = csv_dir / f"YOUTUBE_{video_id}_all_detections_{timestamp}.csv"
        self._export_all_detections_csv(all_detections_file)
        
        # 2. License Plates CSV
        plates_file = csv_dir / f"YOUTUBE_{video_id}_license_plates_{timestamp}.csv"
        self._export_plates_csv(plates_file)
        
        # 3. Emissions CSV
        emissions_file = csv_dir / f"YOUTUBE_{video_id}_emissions_{timestamp}.csv"
        self._export_emissions_csv(emissions_file)
        
        # 4. Speed/Trajectory CSV
        speed_file = csv_dir / f"YOUTUBE_{video_id}_speed_trajectory_{timestamp}.csv"
        self._export_speed_csv(speed_file)
        
        # 5. Brand Detection CSV
        brand_file = csv_dir / f"YOUTUBE_{video_id}_brand_detection_{timestamp}.csv"
        self._export_brand_csv(brand_file)
        
        # 6. Summary Statistics CSV
        summary_file = csv_dir / f"YOUTUBE_{video_id}_summary_{timestamp}.csv"
        self._export_summary_csv(summary_file)
        
        logger.info(f"✅ CSV exports saved to: {csv_dir}")
        logger.info(f"   • All detections: {all_detections_file.name}")
        logger.info(f"   • License plates: {plates_file.name}")
        logger.info(f"   • Emissions: {emissions_file.name}")
        logger.info(f"   • Speed/Trajectory: {speed_file.name}")
        logger.info(f"   • Brand detection: {brand_file.name}")
        logger.info(f"   • Summary: {summary_file.name}")
    
    def _export_all_detections_csv(self, filepath: Path):
        """Export all detection data to CSV"""
        import csv
        fieldnames = [
            'frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
            'class', 'confidence', 'class_id',
            'bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2',
            'speed_kmh', 'speed_confidence', 'direction',
            'vehicle_brand', 'brand_confidence',
            'license_plate', 'license_plate_confidence',
            'emission_co2', 'fuel_consumption', 'emission_impact',
            'multiview_confidence', 'views'
        ]
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for det in self.all_detections:
                bbox = det.get('bbox', {})
                row = {
                    'frame_number': det.get('frame_number', ''),
                    'frame_timestamp': det.get('frame_timestamp', ''),
                    'video_time_seconds': round(det.get('video_time_seconds', 0), 3),
                    'track_id': det.get('track_id', ''),
                    'class': det.get('class', ''),
                    'confidence': round(det.get('confidence', 0), 3),
                    'class_id': det.get('class_id', ''),
                    'bbox_x1': int(bbox.get('x1', 0)) if isinstance(bbox, dict) else '',
                    'bbox_y1': int(bbox.get('y1', 0)) if isinstance(bbox, dict) else '',
                    'bbox_x2': int(bbox.get('x2', 0)) if isinstance(bbox, dict) else '',
                    'bbox_y2': int(bbox.get('y2', 0)) if isinstance(bbox, dict) else '',
                    'speed_kmh': round(det.get('speed', 0), 2) if det.get('speed') else '',
                    'speed_confidence': round(det.get('speed_confidence', 0), 3) if det.get('speed_confidence') else '',
                    'direction': round(det.get('direction', 0), 2) if det.get('direction') else '',
                    'vehicle_brand': det.get('vehicle_brand', ''),
                    'brand_confidence': round(det.get('brand_confidence', 0), 3) if det.get('brand_confidence') else '',
                    'license_plate': det.get('license_plate', ''),
                    'license_plate_confidence': round(det.get('license_plate_confidence', 0), 3) if det.get('license_plate_confidence') else '',
                    'emission_co2': round(det.get('emission_co2', 0), 2) if det.get('emission_co2') else '',
                    'fuel_consumption': round(det.get('fuel_consumption', 0), 2) if det.get('fuel_consumption') else '',
                    'emission_impact': det.get('emission_impact', ''),
                    'multiview_confidence': round(det.get('multiview_confidence', 0), 3) if det.get('multiview_confidence') else '',
                    'views': ','.join(det.get('views', [])) if isinstance(det.get('views'), list) else det.get('views', '')
                }
                writer.writerow(row)
    
    def _export_plates_csv(self, filepath: Path):
        """Export license plate data to CSV"""
        import csv
        plates_data = [det for det in self.all_detections if det.get('license_plate')]
        
        if not plates_data:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
                               'license_plate', 'license_plate_confidence', 'class', 'bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2'])
            return
        
        fieldnames = [
            'frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
            'license_plate', 'license_plate_confidence', 'class',
            'bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2'
        ]
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for det in plates_data:
                bbox = det.get('bbox', {})
                row = {
                    'frame_number': det.get('frame_number', ''),
                    'frame_timestamp': det.get('frame_timestamp', ''),
                    'video_time_seconds': round(det.get('video_time_seconds', 0), 3),
                    'track_id': det.get('track_id', ''),
                    'license_plate': det.get('license_plate', ''),
                    'license_plate_confidence': round(det.get('license_plate_confidence', 0), 3),
                    'class': det.get('class', ''),
                    'bbox_x1': int(bbox.get('x1', 0)) if isinstance(bbox, dict) else '',
                    'bbox_y1': int(bbox.get('y1', 0)) if isinstance(bbox, dict) else '',
                    'bbox_x2': int(bbox.get('x2', 0)) if isinstance(bbox, dict) else '',
                    'bbox_y2': int(bbox.get('y2', 0)) if isinstance(bbox, dict) else ''
                }
                writer.writerow(row)
    
    def _export_emissions_csv(self, filepath: Path):
        """Export emission data to CSV"""
        import csv
        emissions_data = [det for det in self.all_detections if det.get('emission_co2', 0) > 0]
        
        if not emissions_data:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
                               'class', 'speed_kmh', 'emission_co2', 'fuel_consumption', 'emission_impact'])
            return
        
        fieldnames = [
            'frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
            'class', 'speed_kmh', 'emission_co2', 'fuel_consumption', 'emission_impact'
        ]
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for det in emissions_data:
                row = {
                    'frame_number': det.get('frame_number', ''),
                    'frame_timestamp': det.get('frame_timestamp', ''),
                    'video_time_seconds': round(det.get('video_time_seconds', 0), 3),
                    'track_id': det.get('track_id', ''),
                    'class': det.get('class', ''),
                    'speed_kmh': round(det.get('speed', 0), 2) if det.get('speed') else '',
                    'emission_co2': round(det.get('emission_co2', 0), 2),
                    'fuel_consumption': round(det.get('fuel_consumption', 0), 2),
                    'emission_impact': det.get('emission_impact', '')
                }
                writer.writerow(row)
    
    def _export_speed_csv(self, filepath: Path):
        """Export speed and trajectory data to CSV"""
        import csv
        speed_data = [det for det in self.all_detections if det.get('speed', 0) > 0]
        
        if not speed_data:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
                               'speed_kmh', 'speed_confidence', 'direction', 'class'])
            return
        
        fieldnames = [
            'frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
            'speed_kmh', 'speed_confidence', 'direction', 'class'
        ]
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for det in speed_data:
                row = {
                    'frame_number': det.get('frame_number', ''),
                    'frame_timestamp': det.get('frame_timestamp', ''),
                    'video_time_seconds': round(det.get('video_time_seconds', 0), 3),
                    'track_id': det.get('track_id', ''),
                    'speed_kmh': round(det.get('speed', 0), 2),
                    'speed_confidence': round(det.get('speed_confidence', 0), 3) if det.get('speed_confidence') else '',
                    'direction': round(det.get('direction', 0), 2) if det.get('direction') else '',
                    'class': det.get('class', '')
                }
                writer.writerow(row)
    
    def _export_brand_csv(self, filepath: Path):
        """Export brand detection data to CSV"""
        import csv
        brand_data = [det for det in self.all_detections if det.get('vehicle_brand')]
        
        if not brand_data:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
                               'vehicle_brand', 'brand_confidence', 'class'])
            return
        
        fieldnames = [
            'frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
            'vehicle_brand', 'brand_confidence', 'class'
        ]
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for det in brand_data:
                row = {
                    'frame_number': det.get('frame_number', ''),
                    'frame_timestamp': det.get('frame_timestamp', ''),
                    'video_time_seconds': round(det.get('video_time_seconds', 0), 3),
                    'track_id': det.get('track_id', ''),
                    'vehicle_brand': det.get('vehicle_brand', ''),
                    'brand_confidence': round(det.get('brand_confidence', 0), 3) if det.get('brand_confidence') else '',
                    'class': det.get('class', '')
                }
                writer.writerow(row)
    
    def _export_summary_csv(self, filepath: Path):
        """Export summary statistics to CSV"""
        import csv
        if not self.all_detections:
            return
        
        # Calculate statistics
        total_frames = self.frame_count
        total_detections = len(self.all_detections)
        unique_tracks = len(set(det.get('track_id') for det in self.all_detections if det.get('track_id')))
        unique_plates = len(set(det.get('license_plate') for det in self.all_detections if det.get('license_plate')))
        unique_brands = len(set(det.get('vehicle_brand') for det in self.all_detections if det.get('vehicle_brand')))
        
        # Class distribution
        class_counts = {}
        for det in self.all_detections:
            cls = det.get('class', 'unknown')
            class_counts[cls] = class_counts.get(cls, 0) + 1
        
        # Average speed
        speeds = [det.get('speed') for det in self.all_detections if det.get('speed')]
        avg_speed = sum(speeds) / len(speeds) if speeds else 0
        
        # Total CO2 emissions
        co2_values = [det.get('emission_co2') for det in self.all_detections if det.get('emission_co2')]
        avg_co2 = sum(co2_values) / len(co2_values) if co2_values else 0
        
        fieldnames = ['metric', 'value', 'description']
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            video_id = self.youtube_url.split('watch?v=')[-1].split('&')[0] if 'watch?v=' in self.youtube_url else 'youtube'
            summary_data = [
                {'metric': 'youtube_url', 'value': self.youtube_url, 'description': 'YouTube video URL'},
                {'metric': 'total_frames', 'value': total_frames, 'description': 'Total frames processed'},
                {'metric': 'total_detections', 'value': total_detections, 'description': 'Total number of detections'},
                {'metric': 'unique_tracks', 'value': unique_tracks, 'description': 'Unique track IDs'},
                {'metric': 'unique_license_plates', 'value': unique_plates, 'description': 'Unique license plates detected'},
                {'metric': 'unique_brands', 'value': unique_brands, 'description': 'Unique vehicle brands detected'},
                {'metric': 'average_speed_kmh', 'value': round(avg_speed, 2), 'description': 'Average speed in km/h'},
                {'metric': 'average_co2_g_km', 'value': round(avg_co2, 2), 'description': 'Average CO2 emissions in g/km'},
                {'metric': 'processing_fps', 'value': round(self.actual_fps, 2), 'description': 'Average processing FPS'},
            ]
            
            for item in summary_data:
                writer.writerow(item)
            
            # Add class distribution
            writer.writerow({'metric': '', 'value': '', 'description': ''})
            writer.writerow({'metric': 'class_distribution', 'value': '', 'description': 'Vehicle class counts'})
            for cls, count in sorted(class_counts.items()):
                writer.writerow({'metric': f'class_{cls}', 'value': count, 'description': f'Number of {cls} detections'})


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='YouTube Live Stream Processor with Decision Engine')
    parser.add_argument('youtube_url', type=str, help='YouTube video URL (e.g., https://www.youtube.com/watch?v=...)')
    parser.add_argument('-o', '--output', type=str, help='Path to output video file (default: Processed_Videos/)')
    parser.add_argument('--no-display', action='store_true', help='Disable video display (faster processing)')
    parser.add_argument('--no-save', action='store_true', help='Do not save output video')
    parser.add_argument('--dashboard', action='store_true', help='Show Python dashboard (requires matplotlib)')
    
    args = parser.parse_args()
    
    youtube_url = args.youtube_url
    if 'youtube.com' not in youtube_url and 'youtu.be' not in youtube_url:
        logger.error(f"❌ Invalid YouTube URL: {youtube_url}")
        return 1
    
    output_path = Path(args.output) if args.output else None
    
    processor = YouTubeDecisionProcessor(youtube_url, output_path)
    
    # Set dashboard flag if requested
    if args.dashboard and MONITORING_AVAILABLE:
        processor._show_dashboard = True
        logger.info("📊 Dashboard will be shown (use --dashboard flag)")
    else:
        processor._show_dashboard = False
    
    success = processor.process_video(
        display=not args.no_display,
        save_output=not args.no_save
    )
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

