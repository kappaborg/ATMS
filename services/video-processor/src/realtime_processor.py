#!/usr/bin/env python3
"""
Real-Time Video Processor - Direct Processing (No Kafka Round-Trip)
Processes video locally, displays immediately, then sends to Kafka
Based on: https://www.geeksforgeeks.org/python/detect-and-recognize-car-license-plate-from-a-video-in-real-time/
"""
import cv2
import numpy as np
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import sys
import time

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

# Import AI models directly (no Kafka dependency)
try:
    from services.ai_perception.src.detection.yolo_detector import YOLODetector
    from services.ai_perception.src.license_plate_processor import LicensePlateProcessor
    from services.ai_perception.src.brand.brand_classifier import BrandClassifier
    from services.ai_perception.src.multiview.multiview_detector import MultiViewDetector
    from services.ai_perception.src.tramway.tramway_detector import TramwayDetector
    from services.ai_perception.src.emission.emission_calculator import EmissionCalculator
    from services.ai_perception.src.calculations.speed_calculator import SpeedCalculator
    from services.ai_perception.src.calculations.enhanced_emission_calculator import EnhancedEmissionCalculator
    from services.ai_perception.src.trajectory_integration import IntegratedATMSSystem
    MODELS_AVAILABLE = True
except ImportError as e:
    MODELS_AVAILABLE = False
    logging.warning(f"AI models not available: {e}")

logger = logging.getLogger(__name__)


class RealTimeVideoProcessor:
    """
    Real-Time Video Processor
    Processes video directly (no Kafka round-trip) for maximum performance
    """
    
    def __init__(self):
        self.detector = None
        self.plate_processor = None
        self.brand_classifier = None
        self.multiview_detector = None
        self.tramway_detector = None
        self.emission_calculator = None
        self.enhanced_emission_calculator = None
        self.speed_calculator = None
        self.atms_system = None
        
        # Tracking
        self.track_buffer: Dict[int, Dict] = {}
        self.trajectory_history: Dict[int, List[Tuple[float, float]]] = {}
        
        # Results storage (for Kafka sending)
        self.processed_results: List[Dict] = []
        
    def initialize_models(self):
        """Initialize all AI models"""
        if not MODELS_AVAILABLE:
            logger.error("AI models not available")
            return False
        
        try:
            # Initialize YOLO detector
            from services.ai_perception.src.config import model_config
            self.detector = YOLODetector(
                model_path=model_config.MODEL_PATH,
                confidence_threshold=0.3,
                device=model_config.DEVICE
            )
            logger.info("✅ YOLO Detector initialized")
            
            # Initialize License Plate Processor
            plate_model_path = str(project_root / "models" / "license_plate_training" / "outputs" / "license_plate_model_mps" / "weights" / "best.mlpackage")
            self.plate_processor = LicensePlateProcessor(
                yolo_model_path=plate_model_path,
                ocr_primary_method="professional",
                confidence_threshold=0.15
            )
            logger.info("✅ License Plate Processor initialized")
            
            # Initialize Brand Classifier
            brand_model_path = str(project_root / "models" / "brand_classification" / "outputs" / "brand_model_mps" / "weights" / "best.mlpackage")
            self.brand_classifier = BrandClassifier(
                model_path=brand_model_path,
                confidence_threshold=0.3,
                device=model_config.DEVICE
            )
            if self.brand_classifier.load_model():
                logger.info("✅ Brand Classifier initialized")
            else:
                self.brand_classifier = None
                logger.warning("⚠️ Brand Classifier disabled")
            
            # Initialize Multi-View Detector
            multiview_model_path = str(project_root / "models" / "multiview_detection" / "outputs" / "multiview_model_mps" / "weights")
            self.multiview_detector = MultiViewDetector(
                top_model_path=str(Path(multiview_model_path) / "top" / "best.mlpackage"),
                side_model_path=str(Path(multiview_model_path) / "side" / "best.mlpackage"),
                front_model_path=str(Path(multiview_model_path) / "front" / "best.mlpackage"),
                confidence_threshold=0.5,
                device=model_config.DEVICE
            )
            if self.multiview_detector.load_models():
                logger.info("✅ Multi-View Detector initialized")
            else:
                self.multiview_detector = None
                logger.warning("⚠️ Multi-View Detector disabled")
            
            # Initialize Tramway Detector
            tramway_model_path = str(project_root / "models" / "tramway_detection" / "outputs" / "tramway_model_mps" / "weights" / "best.mlpackage")
            self.tramway_detector = TramwayDetector(
                model_path=tramway_model_path,
                confidence_threshold=0.6,
                device=model_config.DEVICE
            )
            if self.tramway_detector.load_model():
                logger.info("✅ Tramway Detector initialized")
            else:
                self.tramway_detector = None
                logger.warning("⚠️ Tramway Detector disabled")
            
            # Initialize Emission Calculators
            self.emission_calculator = EmissionCalculator()
            self.enhanced_emission_calculator = EnhancedEmissionCalculator()
            logger.info("✅ Emission Calculators initialized")
            
            # Initialize Speed Calculator
            import os
            pixel_to_meter = float(os.getenv("PIXEL_TO_METER_RATIO", "0.05"))
            fps = float(os.getenv("VIDEO_FPS", "25.0"))
            self.speed_calculator = SpeedCalculator(
                fps=fps,
                pixel_to_meter_ratio=pixel_to_meter,
                use_kalman=True
            )
            logger.info("✅ Speed Calculator initialized")
            
            # Initialize ATMS System
            self.atms_system = IntegratedATMSSystem(
                intersection_id=1,
                prediction_horizon=5.0,
                optimization_enabled=True
            )
            logger.info("✅ ATMS System initialized")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error initializing models: {e}", exc_info=True)
            return False
    
    async def process_frame_realtime(self, frame: np.ndarray, frame_idx: int, video_id: str) -> Dict:
        """
        Process a single frame in real-time
        Returns: Detection results with all model outputs
        """
        if not self.detector:
            return {}
        
        results = {
            'frame_idx': frame_idx,
            'frame_id': f"video_{video_id}_frame_{frame_idx}",
            'detections': [],
            'license_plates': [],
            'emissions': [],
            'trajectory_data': []
        }
        
        try:
            # Step 1: Object Detection (YOLO)
            detections = self.detector.detect(frame)
            
            if not detections:
                return results
            
            # Step 2: ATMS Tracking (for track IDs and trajectory)
            detection_dicts = []
            for det in detections:
                det_dict = {
                    'bbox': [det.bbox.x1, det.bbox.y1, det.bbox.x2, det.bbox.y2],
                    'confidence': det.confidence,
                    'class': det.object_class.value if hasattr(det.object_class, 'value') else str(det.object_class)
                }
                detection_dicts.append(det_dict)
            
            atms_result = await self.atms_system.process_frame(detection_dicts, frame_id=results['frame_id'])
            
            # Step 3: Process each detection with all models (parallel)
            tasks = []
            for idx, det in enumerate(detections):
                tasks.append(self._process_detection_parallel(frame, det, idx, atms_result, frame_idx))
            
            # Run all models in parallel
            detection_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Step 4: Collect results
            for det_result in detection_results:
                if isinstance(det_result, Exception):
                    logger.error(f"Detection processing error: {det_result}")
                    continue
                
                if det_result:
                    results['detections'].append(det_result)
                    
                    # Collect license plates
                    if 'license_plate' in det_result and det_result['license_plate']:
                        results['license_plates'].append({
                            'track_id': det_result.get('track_id'),
                            'plate_text': det_result['license_plate'],
                            'confidence': det_result.get('license_plate_confidence', 0.0),
                            'bbox': det_result.get('bbox')
                        })
                    
                    # Collect emissions
                    if 'emission_co2' in det_result:
                        results['emissions'].append({
                            'track_id': det_result.get('track_id'),
                            'vehicle_type': det_result.get('class'),
                            'speed_kmh': det_result.get('speed', 0),
                            'co2_g_km': det_result.get('emission_co2', 0),
                            'fuel_l_100km': det_result.get('fuel_consumption', 0)
                        })
                    
                    # Collect trajectory data
                    if 'track_id' in det_result and det_result['track_id']:
                        results['trajectory_data'].append({
                            'track_id': det_result['track_id'],
                            'velocity': det_result.get('velocity'),
                            'direction': det_result.get('direction'),
                            'speed': det_result.get('speed')
                        })
            
            return results
            
        except Exception as e:
            logger.error(f"Error processing frame {frame_idx}: {e}", exc_info=True)
            return results
    
    async def _process_detection_parallel(self, frame: np.ndarray, detection, idx: int, atms_result, frame_idx: int) -> Optional[Dict]:
        """Process a single detection with all models in parallel"""
        try:
            result = {
                'bbox': [detection.bbox.x1, detection.bbox.y1, detection.bbox.x2, detection.bbox.y2],
                'class': detection.object_class.value if hasattr(detection.object_class, 'value') else str(detection.object_class),
                'confidence': detection.confidence
            }
            
            # Get track ID from ATMS
            if atms_result and atms_result.tracked_objects:
                for tracked_obj in atms_result.tracked_objects:
                    if hasattr(tracked_obj, 'track_id') and tracked_obj.track_id:
                        # Match by bbox overlap
                        tracked_bbox = tracked_obj.bbox if hasattr(tracked_obj, 'bbox') else None
                        if tracked_bbox:
                            iou = self._calculate_iou(
                                result['bbox'],
                                tracked_bbox if isinstance(tracked_bbox, (list, tuple)) else [tracked_bbox.x1, tracked_bbox.y1, tracked_bbox.x2, tracked_bbox.y2]
                            )
                            if iou > 0.5:
                                result['track_id'] = tracked_obj.track_id
                                break
            
            # If no track_id, generate temporary one
            if 'track_id' not in result:
                result['track_id'] = hash((idx, frame_idx)) % 100000
            
            # Extract ROI
            x1, y1, x2, y2 = map(int, result['bbox'])
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
            
            if x2 <= x1 or y2 <= y1:
                return result
            
            roi = frame[y1:y2, x1:x2]
            
            # Run all models in parallel
            tasks = []
            
            # License Plate Detection & OCR
            if self.plate_processor:
                tasks.append(self._process_license_plate(roi, result))
            
            # Brand Classification
            if self.brand_classifier and result['class'].lower() in ['car', 'truck', 'suv', 'bus']:
                tasks.append(self._process_brand(roi, result))
            
            # Multi-View Detection
            if self.multiview_detector:
                tasks.append(self._process_multiview(roi, result))
            
            # Speed Calculation
            if self.speed_calculator and 'track_id' in result:
                center_x = (x1 + x2) / 2
                center_y = (y1 + y2) / 2
                self.speed_calculator.update_track(result['track_id'], (center_x, center_y), frame_idx)
                speed_result = self.speed_calculator.calculate_speed(result['track_id'])
                if speed_result and speed_result.confidence > 0.5:
                    result['speed'] = speed_result.speed_kmh
                    result['velocity'] = {'x': speed_result.velocity_x, 'y': speed_result.velocity_y}
                    result['direction'] = speed_result.direction_deg
            
            # Emission Calculation
            if self.enhanced_emission_calculator and 'speed' in result and result['speed'] > 0:
                emissions = self.enhanced_emission_calculator.calculate_emissions_from_speed(
                    vehicle_type=result['class'],
                    speed_kmh=result['speed'],
                    distance_km=0.001
                )
                result['emission_co2'] = emissions.get('co2_g_km', 0)
                result['fuel_consumption'] = emissions.get('fuel_l_100km', 0)
            
            # Wait for parallel tasks
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing detection {idx}: {e}")
            return None
    
    async def _process_license_plate(self, roi: np.ndarray, result: Dict):
        """Process license plate detection and OCR"""
        try:
            plate_results = self.plate_processor.process_frame(roi)
            if plate_results:
                best_plate = plate_results[0]
                if hasattr(best_plate, 'plate_text') and best_plate.plate_text:
                    result['license_plate'] = best_plate.plate_text.text if hasattr(best_plate.plate_text, 'text') else str(best_plate.plate_text)
                    result['license_plate_confidence'] = best_plate.plate_text.confidence if hasattr(best_plate.plate_text, 'confidence') else 0.0
        except Exception as e:
            logger.debug(f"License plate processing error: {e}")
    
    async def _process_brand(self, roi: np.ndarray, result: Dict):
        """Process brand classification"""
        try:
            brand_result = self.brand_classifier.classify_vehicle(roi, result['bbox'])
            if brand_result:
                result['vehicle_brand'] = brand_result.get('brand')
                result['brand_confidence'] = brand_result.get('confidence', 0.0)
        except Exception as e:
            logger.debug(f"Brand classification error: {e}")
    
    async def _process_multiview(self, roi: np.ndarray, result: Dict):
        """Process multi-view detection"""
        try:
            views = self.multiview_detector.detect_views(roi)
            if views:
                result['multiview_confidence'] = views.get('confidence', 0.0)
                result['views'] = views.get('views', [])
        except Exception as e:
            logger.debug(f"Multi-view detection error: {e}")
    
    def _calculate_iou(self, box1: List[float], box2: List[float]) -> float:
        """Calculate IoU between two boxes"""
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2
        
        # Intersection
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)
        
        if x2_i <= x1_i or y2_i <= y1_i:
            return 0.0
        
        intersection = (x2_i - x1_i) * (y2_i - y1_i)
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union = area1 + area2 - intersection
        
        return intersection / union if union > 0 else 0.0
    
    def draw_detections(self, frame: np.ndarray, results: Dict) -> np.ndarray:
        """Draw all detections on frame"""
        annotated = frame.copy()
        
        color_map = {
            'car': (0, 255, 0),
            'truck': (255, 165, 0),
            'bus': (255, 0, 255),
            'motorcycle': (255, 255, 0),
            'person': (255, 0, 0)
        }
        
        for det in results.get('detections', []):
            x1, y1, x2, y2 = map(int, det['bbox'])
            obj_class = det.get('class', 'vehicle')
            color = color_map.get(obj_class, (255, 255, 255))
            
            # Draw bounding box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            
            # Build label
            label_parts = []
            if 'track_id' in det:
                label_parts.append(f"ID:{det['track_id']}")
            label_parts.append(f"{obj_class}")
            if 'speed' in det and det['speed'] > 0:
                label_parts.append(f"{det['speed']:.0f}km/h")
            if 'vehicle_brand' in det:
                label_parts.append(det['vehicle_brand'])
            if 'license_plate' in det:
                label_parts.append(det['license_plate'])
            if 'emission_co2' in det:
                label_parts.append(f"CO2:{det['emission_co2']:.0f}g")
            
            label = " | ".join(label_parts)
            
            # Draw label
            (text_width, text_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(annotated, (x1, y1 - text_height - 10), (x1 + text_width, y1), color, -1)
            cv2.putText(annotated, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        
        return annotated

