#!/usr/bin/env python3
"""
Pure Python Real-Time Video Processing System
=============================================
No web interface, no dashboard - just pure Python with OpenCV display
Processes video in real-time with all AI models and displays results directly
"""

import cv2
import numpy as np
import sys
import time
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import logging
import csv
import subprocess
import json
import asyncio
try:
    from aiokafka import AIOKafkaProducer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    # logger is not configured yet at import time — use logging directly.
    logging.warning("Kafka not available - decisions won't be sent to Kafka")

# Add project paths
# Repo root: services/video-processor/tools/ -> 3 levels up.
project_root = Path(__file__).resolve().parents[3]
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
from atms_core.pipeline import ATMSPipeline


class RealTimeVideoProcessor:
    """
    Pure Python Real-Time Video Processor
    Processes video with all AI models and displays results using OpenCV
    """
    
    def __init__(self, video_path: Path, output_path: Optional[Path] = None):
        self.video_path = video_path
        self.output_path = output_path or (project_root / "Processed_Videos" / f"{video_path.stem}_processed4.mp4")
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
        
        # Tracking and trajectory
        self.track_buffer: Dict[int, Dict] = {}
        self.trajectory_history: Dict[int, List[Tuple[float, float]]] = {}
        self.trajectory_max_length = 60
        self.actual_fps = 25.0  # Default, will be updated dynamically
        
        # Statistics
        self.frame_count = 0
        self.total_detections = 0
        self.start_time = None
        
        # Data storage for CSV export
        self.all_detections: List[Dict] = []  # Store all detection data
        self.video_start_time = datetime.now()
        
        # Data storage for CSV export
        self.all_detections: List[Dict] = []  # Store all detection data
        self.video_start_time = datetime.now()
    
    def _get_class_id(self, object_class) -> int:
        """Convert ObjectClass to class ID"""
        class_map = {
            'car': 2,
            'truck': 7,
            'bus': 5,
            'motorcycle': 3,
            'bicycle': 1,
            'pedestrian': 0,
            'person': 0
        }
        class_str = str(object_class).lower()
        for key, val in class_map.items():
            if key in class_str:
                return val
        return 0
        
    def initialize_models(self) -> bool:
        """Initialize all AI models"""
        try:
            logger.info("🔧 Initializing AI models...")
            
            # 1. YOLO Detector - Use trained model if available, otherwise default
            logger.info("   Loading YOLO detector...")
            
            # Auto-detect device for macOS (use MPS if available, enables CoreML)
            import platform
            import torch
            auto_device = model_config.DEVICE
            if platform.system() == "Darwin":  # macOS
                if torch.backends.mps.is_available():
                    auto_device = "mps"
                    logger.info("   🍎 macOS detected - using MPS (enables CoreML optimization)")
                else:
                    auto_device = "cpu"
                    logger.info("   🍎 macOS detected - using CPU (MPS not available)")
            
            # Try to find trained vehicle detection model (7 trained models available)
            # 1. Vehicle Classification (if exists)
            # 2-4. Multi-View models (top, side, front) - loaded separately
            # 5. Car Brand Classification - loaded separately
            # 6. License Plate - loaded separately
            # 7. Tramway - loaded separately (optional)
            
            trained_model_paths = [
                project_root / "models" / "vehicle_classification_training" / "weights" / "best.mlpackage",
                project_root / "models" / "vehicle_classification_training" / "weights" / "best.pt",
                # Check for any trained YOLO model in models directory
                project_root / "models" / "yolov8n.mlpackage",  # CoreML version
                project_root / "models" / "yolov8n.pt",  # Fallback
            ]
            
            model_path = model_config.MODEL_PATH
            for path in trained_model_paths:
                if path.exists():
                    model_path = str(path)
                    logger.info(f"   ✅ Found trained model: {path.name}")
                    break
            else:
                logger.info(f"   ℹ️  Using default model: {model_config.MODEL_PATH}")
                logger.info(f"   💡 To use trained models, place best.pt or best.mlpackage in models/")
            
            # Force CoreML usage on macOS by setting device to mps
            self.detector = YOLODetector(
                model_path=model_path,
                confidence_threshold=0.3,
                device=auto_device  # Use auto-detected device (mps on macOS)
            )
            
            # Load model explicitly to enable CoreML
            if not self.detector.load_model():
                logger.error("   ❌ Failed to load YOLO detector")
                return False
            
            logger.info(f"   ✅ YOLO Detector initialized (device: {auto_device}, CoreML: {self.detector.use_coreml})")
            
            # 2. License Plate Processor (ENABLED - but optimized)
            logger.info("   Loading License Plate Processor...")
            plate_model_path = project_root / "models" / "license_plate_training" / "outputs" / "license_plate_model_mps" / "weights" / "best.mlpackage"
            if not plate_model_path.exists():
                plate_model_path = project_root / "models" / "license_plate_training" / "outputs" / "license_plate_model_mps" / "weights" / "best.pt"
            
            if plate_model_path.exists():
                self.plate_processor = LicensePlateProcessor(
                    yolo_model_path=str(plate_model_path),
                    ocr_primary_method="professional",
                    confidence_threshold=0.15
                )
                logger.info(f"   ✅ License Plate Processor initialized (model: {plate_model_path.name})")
            else:
                logger.warning("   ⚠️ License plate model not found, skipping")
                self.plate_processor = None
            
            # 3. Brand Classifier (ENABLED - but optimized)
            logger.info("   Loading Brand Classifier...")
            # Auto-detect device for CoreML
            brand_model_path = project_root / "models" / "car_brand_classification" / "outputs" / "car_brand_classification_robust" / "weights" / "best.mlpackage"
            if not brand_model_path.exists():
                brand_model_path = project_root / "models" / "car_brand_classification" / "outputs" / "car_brand_classification_robust" / "weights" / "best.pt"
            
            if brand_model_path.exists():
                self.brand_classifier = BrandClassifier(
                    model_path=str(brand_model_path),
                    confidence_threshold=0.3,
                    device=auto_device  # Use auto-detected device
                )
                if self.brand_classifier.load_model():
                    logger.info(f"   ✅ Brand Classifier initialized (device: {auto_device}, model: {brand_model_path.name})")
                else:
                    self.brand_classifier = None
                    logger.warning("   ⚠️ Brand Classifier failed to load")
            else:
                logger.warning("   ⚠️ Brand model not found, skipping")
                self.brand_classifier = None
            
            # 4. Multi-View Detector (DISABLED by default - very expensive, causes FPS drops)
            ENABLE_MULTIVIEW = False  # Set to True to enable (will reduce FPS significantly)
            if ENABLE_MULTIVIEW:
                logger.info("   Loading Multi-View Detector...")
                try:
                    self.multiview_detector = MultiViewDetector(
                        top_model_path=str(project_root / "multiview_models" / "top_view_model" / "weights" / "best.mlpackage"),
                        side_model_path=str(project_root / "multiview_models" / "side_profile_model" / "weights" / "best.mlpackage"),
                        front_model_path=str(project_root / "multiview_models" / "front_bumper_model" / "weights" / "best.mlpackage"),
                        device=auto_device
                    )
                    if self.multiview_detector.load_models():
                        logger.info("   ✅ Multi-View Detector initialized")
                    else:
                        self.multiview_detector = None
                        logger.warning("   ⚠️ Multi-View Detector failed to load")
                except Exception as e:
                    logger.warning(f"   ⚠️ Multi-View Detector error: {e}")
                    self.multiview_detector = None
            else:
                logger.info("   ⏭️  Multi-View Detector DISABLED (set ENABLE_MULTIVIEW=True to enable - reduces FPS)")
                self.multiview_detector = None
            
            # 5. Tramway Detector (DISABLED by default - not needed for general traffic)
            ENABLE_TRAMWAY = False  # Set to True to enable tramway detection
            if ENABLE_TRAMWAY:
                logger.info("   Loading Tramway Detector...")
                tramway_model_path = project_root / "models" / "tramway_training" / "tramway_runs" / "train_20251028_210058" / "weights" / "best.mlpackage"
                if not tramway_model_path.exists():
                    tramway_model_path = project_root / "models" / "tramway_training" / "tramway_runs" / "train_20251028_210058" / "weights" / "best.pt"
                
                if tramway_model_path.exists():
                    try:
                        self.tramway_detector = TramwayDetector(
                            model_path=str(tramway_model_path),
                            device=auto_device
                        )
                        if self.tramway_detector.load_model():
                            logger.info("   ✅ Tramway Detector initialized")
                        else:
                            self.tramway_detector = None
                    except Exception as e:
                        logger.warning(f"   ⚠️ Tramway Detector error: {e}")
                        self.tramway_detector = None
                else:
                    logger.warning("   ⚠️ Tramway model not found, skipping")
                    self.tramway_detector = None
            else:
                logger.info("   ⏭️  Tramway Detector DISABLED (set ENABLE_TRAMWAY=True to enable)")
                self.tramway_detector = None
            
            # 6. Emission Calculators
            logger.info("   Loading Emission Calculators...")
            self.emission_calculator = EmissionCalculator()
            self.enhanced_emission_calculator = EnhancedEmissionCalculator()
            logger.info("   ✅ Emission Calculators initialized")
            
            # 7. Speed Calculator with auto-calibration
            logger.info("   Loading Speed Calculator...")
            import os
            pixel_to_meter = float(os.getenv("PIXEL_TO_METER_RATIO", "0.05"))
            fps = float(os.getenv("VIDEO_FPS", "25.0"))
            
            self.speed_calculator = SpeedCalculator(
                fps=fps,
                pixel_to_meter_ratio=pixel_to_meter,
                use_kalman=True,
                min_track_length=3,  # Lower threshold for faster speed calculation
                max_track_history=50  # Keep more history for better accuracy
            )
            
            # Store video FPS for later calibration
            self.video_fps = fps
            self.pixel_to_meter_ratio = pixel_to_meter
            
            logger.info(f"   ✅ Speed Calculator initialized (FPS: {fps}, Pixel-to-Meter: {pixel_to_meter:.4f} m/pixel)")
            logger.info(f"   💡 To calibrate: Set PIXEL_TO_METER_RATIO env var or use auto-calibration")
            
            # 8. ATMS System
            logger.info("   Loading ATMS System...")
            self.atms_system = IntegratedATMSSystem(
                intersection_id=1,
                prediction_horizon=5.0,
                optimization_enabled=True
            )
            logger.info("   ✅ ATMS System initialized")
            
            # 9. ByteTracker
            logger.info("   Loading ByteTracker...")
            self.tracker = SimpleByteTracker()
            logger.info("   ✅ ByteTracker initialized")

            # Create the shared pipeline core once all dependencies exist.
            self.pipeline = ATMSPipeline(
                detector=self.detector,
                tracker=self.tracker,
                speed_calculator=self.speed_calculator,
                enhanced_emission_calculator=self.enhanced_emission_calculator,
                atms_system=self.atms_system,
                trajectory_history=self.trajectory_history,
                trajectory_max_length=self.trajectory_max_length,
                plate_processor=self.plate_processor,
                brand_classifier=self.brand_classifier,
                multiview_detector=self.multiview_detector,
            )
            
            logger.info("✅ All AI models initialized successfully!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error initializing models: {e}", exc_info=True)
            return False
    
    def draw_detections(self, frame: np.ndarray, detections: List[Dict]) -> np.ndarray:
        """Draw all detections with labels on frame"""
        # OPTIMIZATION: Limit max detections to draw for performance
        MAX_DETECTIONS_TO_DRAW = 30
        if len(detections) > MAX_DETECTIONS_TO_DRAW:
            # Sort by confidence and take top N
            detections = sorted(detections, key=lambda x: x.get('confidence', 0), reverse=True)[:MAX_DETECTIONS_TO_DRAW]
        
        annotated_frame = frame.copy()
        
        for det in detections:
            # Extract bounding box
            bbox = det.get('bbox', {})
            x1, y1 = int(bbox.get('x1', 0)), int(bbox.get('y1', 0))
            x2, y2 = int(bbox.get('x2', 0)), int(bbox.get('y2', 0))
            
            # Get detection info
            track_id = det.get('track_id', 'N/A')
            class_name = det.get('class', 'unknown')
            confidence = det.get('confidence', 0.0)
            speed = det.get('speed')
            brand = det.get('vehicle_brand')
            plate = det.get('license_plate')
            co2 = det.get('emission_co2')
            fuel = det.get('fuel_consumption')
            
            # Draw bounding box
            color = (0, 255, 0) if confidence > 0.5 else (0, 165, 255)
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
            
            # Prepare label - show all available info
            label_parts = [f"ID:{track_id}", f"{class_name} {confidence:.2f}"]
            if speed:
                speed_conf = det.get('speed_confidence', 0.0)
                speed_method = det.get('speed_method', 'pixel')
                # Show speed with confidence indicator
                if speed_conf > 0.7:
                    label_parts.append(f"Speed:{speed:.1f}km/h ✓")
                elif speed_conf > 0.5:
                    label_parts.append(f"Speed:{speed:.1f}km/h")
                else:
                    label_parts.append(f"Speed:{speed:.1f}km/h ~")  # ~ indicates low confidence
            if brand:
                # Simplified brand display for performance
                label_parts.append(f"Brand:{brand}")
            if plate:
                # Simplified plate display for performance
                label_parts.append(f"Plate:{plate}")
            if co2:
                label_parts.append(f"CO2:{co2:.1f}g/km")
            if fuel:
                label_parts.append(f"Fuel:{fuel:.2f}L/100km")
            
            # Draw label with background - OPTIMIZATION: Limit label length
            label = " | ".join(label_parts[:6])  # Limit to 6 items max for performance
            (label_width, label_height), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            
            # Label background
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
        
        return annotated_frame
    
    def draw_statistics(self, frame: np.ndarray) -> np.ndarray:
        """Draw statistics overlay on frame"""
        elapsed = time.time() - self.start_time if self.start_time else 0
        fps = self.frame_count / elapsed if elapsed > 0 else 0
        
        # Calculate average speed if available
        avg_speed = 0.0
        speed_count = 0
        if hasattr(self, 'speed_calculator') and self.speed_calculator:
            for track_id in self.speed_calculator.speed_history:
                if len(self.speed_calculator.speed_history[track_id]) > 0:
                    speeds = list(self.speed_calculator.speed_history[track_id])
                    avg_speed += sum(speeds) / len(speeds)
                    speed_count += 1
            if speed_count > 0:
                avg_speed = avg_speed / speed_count
        
        stats = [
            f"Frame: {self.frame_count}",
            f"FPS: {fps:.1f}",
            f"Detections: {self.total_detections}",
            f"Time: {elapsed:.1f}s"
        ]
        
        # Add speed calibration info
        if hasattr(self, 'pixel_to_meter_ratio'):
            stats.append(f"Calibration: {self.pixel_to_meter_ratio:.4f} m/pixel")
        if avg_speed > 0:
            stats.append(f"Avg Speed: {avg_speed:.1f} km/h")
        
        y_offset = 30
        for stat in stats:
            cv2.putText(
                frame,
                stat,
                (10, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )
            y_offset += 30
        
        return frame
    
    def process_frame(
        self, 
        frame: np.ndarray, 
        frame_idx: int,
        process_plates: bool = True,
        process_brand: bool = True,
        process_multiview: bool = True,
        max_plates_per_frame: int = 2,
        ocr_timeout: float = 3.0
    ) -> List[Dict]:
        """Process a single frame with all AI models"""
        if getattr(self, "pipeline", None):
            return self.pipeline.process_frame(
                frame,
                frame_idx,
                process_plates=process_plates,
                process_brand=process_brand,
                process_multiview=process_multiview,
                max_plates_per_frame=max_plates_per_frame,
                ocr_timeout=ocr_timeout,
                video_fps=getattr(self, "video_fps", 25.0),
                actual_fps=getattr(self, "actual_fps", 25.0),
            )

        # The shared ATMSPipeline is constructed in initialize_models(); if it
        # is missing, model init failed and there is nothing valid to fall
        # back to. The former inline "legacy" path duplicated the pipeline
        # with divergent bugs (docs/REFACTORING_NOTES.md §2.1) and has been
        # removed — atms_core/pipeline.py is the single implementation.
        raise RuntimeError(
            "process_frame called before initialize_models() — the ATMS "
            "pipeline is not available."
        )

    
    def process_video(self, display: bool = True, save_output: bool = True):
        """Process video in real-time"""
        cap = cv2.VideoCapture(str(self.video_path))
        if not cap.isOpened():
            logger.error(f"❌ Cannot open video: {self.video_path}")
            return False
        
        # Get video properties
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        logger.info(f"📹 Video Info:")
        logger.info(f"   Resolution: {width}x{height}")
        logger.info(f"   FPS: {fps}")
        logger.info(f"   Total Frames: {total_frames}")
        
        # Auto-calibrate pixel-to-meter ratio if not set
        if self.speed_calculator and self.pixel_to_meter_ratio == 0.05:  # Default value
            logger.info("   🔧 Auto-calibrating pixel-to-meter ratio...")
            # Estimate based on video resolution (assume city street)
            estimated_ratio = self.speed_calculator.estimate_pixel_to_meter_ratio(
                frame_shape=(height, width),
                road_type="city"  # Can be "highway", "city", or "parking"
            )
            if estimated_ratio > 0:
                self.speed_calculator.pixel_to_meter_ratio = estimated_ratio
                self.pixel_to_meter_ratio = estimated_ratio
                logger.info(f"   ✅ Auto-calibrated: {estimated_ratio:.4f} m/pixel")
                logger.info(f"   💡 For better accuracy, set PIXEL_TO_METER_RATIO env var")
        
        # Update speed calculator FPS with actual video FPS
        if self.speed_calculator:
            self.speed_calculator.fps = fps
            self.video_fps = fps
            logger.info(f"   ✅ Speed calculator FPS set to: {fps}")
        
        # Setup video writer
        writer = None
        if save_output:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(str(self.output_path), fourcc, fps, (width, height))
            logger.info(f"💾 Output will be saved to: {self.output_path}")
        
        # Initialize models
        if not self.initialize_models():
            logger.error("❌ Failed to initialize models")
            cap.release()
            return False
        
        self.start_time = time.time()
        logger.info("🚀 Starting real-time video processing...")
        logger.info("   Press 'q' to quit, 's' to save and quit")
        
        # Performance optimization: MAXIMUM FPS settings for smooth video
        # CRITICAL: OCR is the main bottleneck - make it very rare
        PLATE_PROCESS_INTERVAL = 60  # Process plates every 60th frame - OCR is very slow!
        ENABLE_OCR = True  # ENABLED: OCR is important for plate detection
        BRAND_PROCESS_INTERVAL = 20  # Process brand every 20th frame - reduce frequency
        MULTIVIEW_PROCESS_INTERVAL = 30  # Process multiview every 30th frame - very expensive!
        MAX_PLATES_PER_FRAME = 1  # Limit OCR to only 1 highest confidence vehicle per frame
        OCR_TIMEOUT = 0.8  # Timeout for OCR (0.8 seconds max per plate - very aggressive)
        DISPLAY_FRAME_SKIP = 1  # Display every frame
        
        # Target FPS for processing - aim for 25-30 FPS (smooth video)
        target_fps = min(fps, 30.0)  # Cap at 30 FPS for smooth processing
        frame_delay = 1.0 / target_fps
        
        # Additional FPS optimizations
        RESIZE_FOR_PROCESSING = True  # Resize frames for faster processing
        PROCESSING_WIDTH = 1280  # Resize to 1280px width for processing (faster than full 1920px)
        PROCESSING_HEIGHT = 720  # Maintain aspect ratio
        
        logger.info(f"⚡ ULTRA-AGGRESSIVE Performance settings for 15-20 FPS:")
        logger.info(f"   Plate OCR: {'DISABLED' if not ENABLE_OCR else f'Every {PLATE_PROCESS_INTERVAL} frames, max {MAX_PLATES_PER_FRAME} per frame'}")
        logger.info(f"   Brand: Every {BRAND_PROCESS_INTERVAL} frames (using Brand Classifier + Multi-View)")
        logger.info(f"   Multi-View: Every {MULTIVIEW_PROCESS_INTERVAL} frames (used for brand detection)")
        logger.info(f"   Target FPS: {target_fps}")
        
        try:
            while cap.isOpened():
                frame_start_time = time.time()
                ret, frame = cap.read()
                if not ret:
                    break
                
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
                
                # Process frame with optimized model skipping (use resized frame for faster processing)
                detections = self.process_frame(
                    processing_frame,  # Use resized frame for faster processing
                    self.frame_count,
                    process_plates=(ENABLE_OCR and self.frame_count % PLATE_PROCESS_INTERVAL == 0),
                    process_brand=(self.frame_count % BRAND_PROCESS_INTERVAL == 0),
                    process_multiview=(self.frame_count % MULTIVIEW_PROCESS_INTERVAL == 0),
                    max_plates_per_frame=MAX_PLATES_PER_FRAME,
                    ocr_timeout=OCR_TIMEOUT
                )
                
                # Scale detection coordinates back to original frame size if resized
                if RESIZE_FOR_PROCESSING and processing_frame.shape != frame.shape:
                    scale_x = frame.shape[1] / processing_frame.shape[1]
                    scale_y = frame.shape[0] / processing_frame.shape[0]
                    for det in detections:
                        if 'bbox' in det:
                            bbox = det['bbox']
                            bbox['x1'] *= scale_x
                            bbox['y1'] *= scale_y
                            bbox['x2'] *= scale_x
                            bbox['y2'] *= scale_y
                self.total_detections += len(detections)
                
                # Store all detection data for CSV export
                frame_timestamp = datetime.now()
                for det in detections:
                    det_data = det.copy()
                    det_data['frame_number'] = self.frame_count
                    det_data['frame_timestamp'] = frame_timestamp.isoformat()
                    det_data['video_time_seconds'] = self.frame_count / (self.actual_fps if self.actual_fps > 0 else 25.0)
                    self.all_detections.append(det_data)
                
                # Update actual FPS continuously for speed calculation
                if self.frame_count > 0:
                    self.actual_fps = self.frame_count / (time.time() - self.start_time)
                
                # Debug: Log detection count every 30 frames
                if self.frame_count % 30 == 0:
                    if len(detections) == 0:
                        logger.warning(f"⚠️ Frame {self.frame_count}: No detections!")
                    else:
                        logger.info(f"✅ Frame {self.frame_count}: {len(detections)} detections, FPS: {self.actual_fps:.1f}")
                
                # Draw detections (only if we should display this frame)
                if self.frame_count % DISPLAY_FRAME_SKIP == 0:
                    annotated_frame = self.draw_detections(frame, detections)
                    annotated_frame = self.draw_statistics(annotated_frame)
                    
                    # Display
                    if display:
                        cv2.imshow('Real-Time Video Processing', annotated_frame)
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
                else:
                    # Still save frame even if not displaying
                    if writer:
                        annotated_frame = self.draw_detections(frame, detections)
                        annotated_frame = self.draw_statistics(annotated_frame)
                        writer.write(annotated_frame)
                
                # Maintain target FPS - but don't sleep if we're already slow
                processing_time = time.time() - frame_start_time
                sleep_time = max(0, frame_delay - processing_time)
                # Only sleep if we're processing faster than target (avoid making it slower)
                if sleep_time > 0 and processing_time < frame_delay * 0.8:  # Only sleep if we're 20% faster
                    time.sleep(sleep_time)
                
                # Progress update
                if self.frame_count % 30 == 0:
                    progress = (self.frame_count / total_frames) * 100
                    logger.info(f"   Progress: {progress:.1f}% ({self.frame_count}/{total_frames} frames)")
        
        except KeyboardInterrupt:
            logger.info("⏹️  Interrupted by user")
        finally:
            cap.release()
            if writer:
                writer.release()
            if display:
                cv2.destroyAllWindows()
            
            elapsed = time.time() - self.start_time
            logger.info("✅ Processing complete!")
            logger.info(f"   Processed {self.frame_count} frames in {elapsed:.1f}s")
            logger.info(f"   Average FPS: {self.frame_count / elapsed:.1f}")
            logger.info(f"   Total detections: {self.total_detections}")
            if save_output:
                logger.info(f"   Output saved to: {self.output_path}")
            
            # Export all data to CSV files
            logger.info("📊 Exporting detection data to CSV files...")
            self.export_to_csv()
        
        return True
    
    def export_to_csv(self):
        """Export all detection data to CSV files"""
        if not self.all_detections:
            logger.warning("⚠️ No detection data to export")
            return
        
        # Create CSV output directory
        csv_dir = self.output_path.parent / "CSV_Exports"
        csv_dir.mkdir(exist_ok=True, parents=True)
        
        video_name = self.video_path.stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 1. All Detections CSV (comprehensive)
        detections_file = csv_dir / f"{video_name}_all_detections_{timestamp}.csv"
        self._export_detections_csv(detections_file)
        
        # 2. License Plates CSV
        plates_file = csv_dir / f"{video_name}_license_plates_{timestamp}.csv"
        self._export_plates_csv(plates_file)
        
        # 3. Emissions CSV
        emissions_file = csv_dir / f"{video_name}_emissions_{timestamp}.csv"
        self._export_emissions_csv(emissions_file)
        
        # 4. Speed & Trajectory CSV
        speed_file = csv_dir / f"{video_name}_speed_trajectory_{timestamp}.csv"
        self._export_speed_trajectory_csv(speed_file)
        
        # 5. Brand Detection CSV
        brand_file = csv_dir / f"{video_name}_brand_detection_{timestamp}.csv"
        self._export_brand_csv(brand_file)
        
        # 6. Summary Statistics CSV
        summary_file = csv_dir / f"{video_name}_summary_{timestamp}.csv"
        self._export_summary_csv(summary_file)
        
        logger.info(f"✅ CSV files exported to: {csv_dir}")
        logger.info(f"   • All Detections: {detections_file.name}")
        logger.info(f"   • License Plates: {plates_file.name}")
        logger.info(f"   • Emissions: {emissions_file.name}")
        logger.info(f"   • Speed & Trajectory: {speed_file.name}")
        logger.info(f"   • Brand Detection: {brand_file.name}")
        logger.info(f"   • Summary: {summary_file.name}")
    
    def _export_detections_csv(self, filepath: Path):
        """Export all detection data to CSV"""
        if not self.all_detections:
            return
        
        fieldnames = [
            'frame_number', 'frame_timestamp', 'video_time_seconds',
            'track_id', 'detection_id', 'class', 'class_id', 'confidence',
            'bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2',
            'speed_kmh', 'speed_confidence', 'speed_method',
            'velocity_x', 'velocity_y', 'direction_deg',
            'vehicle_brand', 'brand_confidence', 'brand_method',
            'license_plate', 'license_plate_confidence', 'ocr_confidence',
            'multiview_confidence', 'views',
            'emission_co2', 'fuel_consumption', 'emission_impact',
            'trajectory_predicted', 'anomaly_detected'
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
                    'detection_id': det.get('detection_id', ''),
                    'class': det.get('class', ''),
                    'class_id': det.get('class_id', ''),
                    'confidence': round(det.get('confidence', 0), 3),
                    'bbox_x1': int(bbox.get('x1', 0)) if isinstance(bbox, dict) else '',
                    'bbox_y1': int(bbox.get('y1', 0)) if isinstance(bbox, dict) else '',
                    'bbox_x2': int(bbox.get('x2', 0)) if isinstance(bbox, dict) else '',
                    'bbox_y2': int(bbox.get('y2', 0)) if isinstance(bbox, dict) else '',
                    'speed_kmh': round(det.get('speed', 0), 2) if det.get('speed') else '',
                    'speed_confidence': round(det.get('speed_confidence', 0), 3) if det.get('speed_confidence') else '',
                    'speed_method': det.get('speed_method', ''),
                    'velocity_x': round(det.get('velocity', {}).get('x', 0), 3) if isinstance(det.get('velocity'), dict) else '',
                    'velocity_y': round(det.get('velocity', {}).get('y', 0), 3) if isinstance(det.get('velocity'), dict) else '',
                    'direction_deg': round(det.get('direction', 0), 2) if det.get('direction') else '',
                    'vehicle_brand': det.get('vehicle_brand', ''),
                    'brand_confidence': round(det.get('brand_confidence', 0), 3) if det.get('brand_confidence') else '',
                    'brand_method': det.get('brand_method', ''),
                    'license_plate': det.get('license_plate', ''),
                    'license_plate_confidence': round(det.get('license_plate_confidence', 0), 3) if det.get('license_plate_confidence') else '',
                    'ocr_confidence': round(det.get('ocr_confidence', 0), 3) if det.get('ocr_confidence') else '',
                    'multiview_confidence': round(det.get('multiview_confidence', 0), 3) if det.get('multiview_confidence') else '',
                    'views': ', '.join(det.get('views', [])) if isinstance(det.get('views'), list) else str(det.get('views', '')),
                    'emission_co2': round(det.get('emission_co2', 0), 2) if det.get('emission_co2') else '',
                    'fuel_consumption': round(det.get('fuel_consumption', 0), 2) if det.get('fuel_consumption') else '',
                    'emission_impact': det.get('emission_impact', ''),
                    'trajectory_predicted': str(det.get('trajectory_predicted', '')),
                    'anomaly_detected': 'Yes' if det.get('anomaly_detected') else 'No'
                }
                writer.writerow(row)
    
    def _export_plates_csv(self, filepath: Path):
        """Export license plate detections to CSV"""
        plates_data = [det for det in self.all_detections if det.get('license_plate')]
        
        if not plates_data:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id', 
                               'license_plate', 'ocr_confidence', 'detection_confidence', 
                               'bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2', 'class', 'speed_kmh'])
            return
        
        fieldnames = [
            'frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
            'license_plate', 'ocr_confidence', 'detection_confidence',
            'bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2', 'class', 'speed_kmh'
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
                    'ocr_confidence': round(det.get('ocr_confidence', 0), 3) if det.get('ocr_confidence') else '',
                    'detection_confidence': round(det.get('confidence', 0), 3),
                    'bbox_x1': int(bbox.get('x1', 0)) if isinstance(bbox, dict) else '',
                    'bbox_y1': int(bbox.get('y1', 0)) if isinstance(bbox, dict) else '',
                    'bbox_x2': int(bbox.get('x2', 0)) if isinstance(bbox, dict) else '',
                    'bbox_y2': int(bbox.get('y2', 0)) if isinstance(bbox, dict) else '',
                    'class': det.get('class', ''),
                    'speed_kmh': round(det.get('speed', 0), 2) if det.get('speed') else ''
                }
                writer.writerow(row)
    
    def _export_emissions_csv(self, filepath: Path):
        """Export emission data to CSV"""
        emissions_data = [det for det in self.all_detections if det.get('emission_co2') or det.get('fuel_consumption')]
        
        if not emissions_data:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
                               'class', 'speed_kmh', 'emission_co2_g_km', 'fuel_consumption_L_100km', 
                               'emission_impact', 'vehicle_brand'])
            return
        
        fieldnames = [
            'frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
            'class', 'speed_kmh', 'emission_co2_g_km', 'fuel_consumption_L_100km',
            'emission_impact', 'vehicle_brand'
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
                    'emission_co2_g_km': round(det.get('emission_co2', 0), 2) if det.get('emission_co2') else '',
                    'fuel_consumption_L_100km': round(det.get('fuel_consumption', 0), 2) if det.get('fuel_consumption') else '',
                    'emission_impact': det.get('emission_impact', ''),
                    'vehicle_brand': det.get('vehicle_brand', '')
                }
                writer.writerow(row)
    
    def _export_speed_trajectory_csv(self, filepath: Path):
        """Export speed and trajectory data to CSV"""
        speed_data = [det for det in self.all_detections if det.get('speed') or det.get('track_id')]
        
        if not speed_data:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
                               'speed_kmh', 'speed_confidence', 'speed_method', 'velocity_x', 'velocity_y',
                               'direction_deg', 'bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2', 'class'])
            return
        
        fieldnames = [
            'frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
            'speed_kmh', 'speed_confidence', 'speed_method', 'velocity_x', 'velocity_y',
            'direction_deg', 'bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2', 'class'
        ]
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for det in speed_data:
                bbox = det.get('bbox', {})
                row = {
                    'frame_number': det.get('frame_number', ''),
                    'frame_timestamp': det.get('frame_timestamp', ''),
                    'video_time_seconds': round(det.get('video_time_seconds', 0), 3),
                    'track_id': det.get('track_id', ''),
                    'speed_kmh': round(det.get('speed', 0), 2) if det.get('speed') else '',
                    'speed_confidence': round(det.get('speed_confidence', 0), 3) if det.get('speed_confidence') else '',
                    'speed_method': det.get('speed_method', ''),
                    'velocity_x': round(det.get('velocity', {}).get('x', 0), 3) if isinstance(det.get('velocity'), dict) else '',
                    'velocity_y': round(det.get('velocity', {}).get('y', 0), 3) if isinstance(det.get('velocity'), dict) else '',
                    'direction_deg': round(det.get('direction', 0), 2) if det.get('direction') else '',
                    'bbox_x1': int(bbox.get('x1', 0)) if isinstance(bbox, dict) else '',
                    'bbox_y1': int(bbox.get('y1', 0)) if isinstance(bbox, dict) else '',
                    'bbox_x2': int(bbox.get('x2', 0)) if isinstance(bbox, dict) else '',
                    'bbox_y2': int(bbox.get('y2', 0)) if isinstance(bbox, dict) else '',
                    'class': det.get('class', '')
                }
                writer.writerow(row)
    
    def _export_brand_csv(self, filepath: Path):
        """Export brand detection data to CSV"""
        brand_data = [det for det in self.all_detections if det.get('vehicle_brand')]
        
        if not brand_data:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
                               'vehicle_brand', 'brand_confidence', 'brand_method', 'class', 'multiview_confidence'])
            return
        
        fieldnames = [
            'frame_number', 'frame_timestamp', 'video_time_seconds', 'track_id',
            'vehicle_brand', 'brand_confidence', 'brand_method', 'class', 'multiview_confidence'
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
                    'brand_method': det.get('brand_method', ''),
                    'class': det.get('class', ''),
                    'multiview_confidence': round(det.get('multiview_confidence', 0), 3) if det.get('multiview_confidence') else ''
                }
                writer.writerow(row)
    
    def _export_summary_csv(self, filepath: Path):
        """Export summary statistics to CSV"""
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
        
        # Total CO2 emissions (estimate)
        co2_values = [det.get('emission_co2') for det in self.all_detections if det.get('emission_co2')]
        avg_co2 = sum(co2_values) / len(co2_values) if co2_values else 0
        
        fieldnames = [
            'metric', 'value', 'description'
        ]
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            summary_data = [
                {'metric': 'video_name', 'value': self.video_path.name, 'description': 'Input video file name'},
                {'metric': 'total_frames', 'value': total_frames, 'description': 'Total frames processed'},
                {'metric': 'total_detections', 'value': total_detections, 'description': 'Total number of detections'},
                {'metric': 'unique_tracks', 'value': unique_tracks, 'description': 'Unique track IDs'},
                {'metric': 'unique_license_plates', 'value': unique_plates, 'description': 'Unique license plates detected'},
                {'metric': 'unique_brands', 'value': unique_brands, 'description': 'Unique vehicle brands detected'},
                {'metric': 'average_speed_kmh', 'value': round(avg_speed, 2), 'description': 'Average speed in km/h'},
                {'metric': 'average_co2_g_km', 'value': round(avg_co2, 2), 'description': 'Average CO2 emissions in g/km'},
                {'metric': 'processing_fps', 'value': round(self.actual_fps, 2), 'description': 'Average processing FPS'},
            ]
            
            for row in summary_data:
                writer.writerow(row)
            
            # Class distribution
            writer.writerow({'metric': '', 'value': '', 'description': '--- Class Distribution ---'})
            for cls, count in sorted(class_counts.items(), key=lambda x: x[1], reverse=True):
                writer.writerow({
                    'metric': f'class_{cls}',
                    'value': count,
                    'description': f'Number of {cls} detections'
                })


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Real-Time Video Processing System')
    parser.add_argument('video', type=str, help='Path to input video file')
    parser.add_argument('-o', '--output', type=str, help='Path to output video file (default: Processed_Videos/)')
    parser.add_argument('--no-display', action='store_true', help='Disable video display (faster processing)')
    parser.add_argument('--no-save', action='store_true', help='Do not save output video')
    
    args = parser.parse_args()
    
    video_path = Path(args.video)
    if not video_path.exists():
        logger.error(f"❌ Video file not found: {video_path}")
        return 1
    
    output_path = Path(args.output) if args.output else None
    
    processor = RealTimeVideoProcessor(video_path, output_path)
    success = processor.process_video(
        display=not args.no_display,
        save_output=not args.no_save
    )
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

