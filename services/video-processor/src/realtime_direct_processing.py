#!/usr/bin/env python3
"""
Real-Time Direct Video Processing
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
import base64

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

logger = logging.getLogger(__name__)


class DirectVideoProcessor:
    """
    Direct Video Processor - No Kafka Round-Trip
    Processes video frames directly using AI models, displays immediately, then sends results to Kafka
    """
    
    def __init__(self, websocket_connections: List = None, kafka_producer=None):
        self.websocket_connections = websocket_connections or []
        self.kafka_producer = kafka_producer
        
        # Import AI models
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
        
        # Results for Kafka (async sending)
        self.results_queue: List[Dict] = []
        
    async def initialize_models(self):
        """Initialize all AI models"""
        try:
            # Import config - fix path
            ai_perception_src = project_root / "services" / "ai-perception" / "src"
            if str(ai_perception_src) not in sys.path:
                sys.path.insert(0, str(ai_perception_src))
            from config import model_config
            
            # Initialize YOLO detector
            from detection.yolo_detector import YOLODetector
            self.detector = YOLODetector(
                model_path=model_config.MODEL_PATH,
                confidence_threshold=0.3,
                device=model_config.DEVICE
            )
            logger.info("✅ YOLO Detector initialized")
            
            # Initialize License Plate Processor
            from license_plate_processor import LicensePlateProcessor
            plate_model_path = str(project_root / "models" / "license_plate_training" / "outputs" / "license_plate_model_mps" / "weights" / "best.mlpackage")
            self.plate_processor = LicensePlateProcessor(
                yolo_model_path=plate_model_path,
                ocr_primary_method="professional",
                confidence_threshold=0.15
            )
            logger.info("✅ License Plate Processor initialized")
            
            # Initialize Brand Classifier
            from brand.brand_classifier import BrandClassifier
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
            
            # Initialize Emission Calculators
            from emission.emission_calculator import EmissionCalculator
            from calculations.enhanced_emission_calculator import EnhancedEmissionCalculator
            self.emission_calculator = EmissionCalculator()
            self.enhanced_emission_calculator = EnhancedEmissionCalculator()
            logger.info("✅ Emission Calculators initialized")
            
            # Initialize Speed Calculator
            from calculations.speed_calculator import SpeedCalculator
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
            from trajectory_integration import IntegratedATMSSystem
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
    
    async def process_video_realtime(self, video_path: Path, video_id: str):
        """
        Process video in real-time: process → display → send to Kafka
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.error(f"Cannot open video: {video_path}")
            return
        
        frame_idx = 0
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_delay = 1.0 / fps
        
        logger.info(f"🎬 Starting REAL-TIME processing: {video_path}")
        logger.info(f"   FPS: {fps}, Frame delay: {frame_delay:.3f}s")
        
        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                
                start_time = time.time()
                
                # Process frame directly (no Kafka round-trip)
                results = await self._process_frame_direct(frame, frame_idx, video_id)
                
                # Display immediately via WebSocket
                await self._display_frame_realtime(frame, results, frame_idx)
                
                # Send results to Kafka (async, non-blocking)
                if self.kafka_producer:
                    asyncio.create_task(self._send_results_to_kafka(results, video_id, frame_idx))
                
                # Maintain frame rate
                processing_time = time.time() - start_time
                sleep_time = max(0, frame_delay - processing_time)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                
                frame_idx += 1
                
                if frame_idx % 30 == 0:
                    logger.info(f"📹 Processed {frame_idx} frames (real-time)")
            
            cap.release()
            logger.info(f"✅ Real-time processing complete: {frame_idx} frames")
            
        except Exception as e:
            logger.error(f"Error in real-time processing: {e}", exc_info=True)
            cap.release()
    
    async def _process_frame_direct(self, frame: np.ndarray, frame_idx: int, video_id: str) -> Dict:
        """Process a single frame directly (no Kafka)"""
        results = {
            'frame_idx': frame_idx,
            'frame_id': f"video_{video_id}_frame_{frame_idx}",
            'detections': [],
            'license_plates': [],
            'emissions': [],
            'trajectory_data': []
        }
        
        if not self.detector:
            return results
        
        try:
            # Step 1: Object Detection
            detections = self.detector.detect(frame)
            
            if not detections:
                return results
            
            # Step 2: ATMS Tracking
            detection_dicts = []
            for det in detections:
                det_dict = {
                    'bbox': [det.bbox.x1, det.bbox.y1, det.bbox.x2, det.bbox.y2],
                    'confidence': det.confidence,
                    'class': det.object_class.value if hasattr(det.object_class, 'value') else str(det.object_class)
                }
                detection_dicts.append(det_dict)
            
            atms_result = await self.atms_system.process_frame(detection_dicts, frame_id=results['frame_id'])
            
            # Step 3: Process each detection (parallel)
            tasks = []
            for idx, det in enumerate(detections):
                tasks.append(self._process_detection(frame, det, idx, atms_result, frame_idx, results))
            
            await asyncio.gather(*tasks, return_exceptions=True)
            
            return results
            
        except Exception as e:
            logger.error(f"Error processing frame {frame_idx}: {e}", exc_info=True)
            return results
    
    async def _process_detection(self, frame: np.ndarray, detection, idx: int, atms_result, frame_idx: int, results: Dict):
        """Process a single detection with all models"""
        try:
            det_result = {
                'bbox': [detection.bbox.x1, detection.bbox.y1, detection.bbox.x2, detection.bbox.y2],
                'class': detection.object_class.value if hasattr(detection.object_class, 'value') else str(detection.object_class),
                'confidence': detection.confidence
            }
            
            # Get track ID from ATMS
            if atms_result and atms_result.tracked_objects:
                for tracked_obj in atms_result.tracked_objects:
                    if hasattr(tracked_obj, 'track_id') and tracked_obj.track_id:
                        det_result['track_id'] = tracked_obj.track_id
                        break
            
            if 'track_id' not in det_result:
                det_result['track_id'] = hash((idx, frame_idx)) % 100000
            
            # Extract ROI
            x1, y1, x2, y2 = map(int, det_result['bbox'])
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
            
            if x2 <= x1 or y2 <= y1:
                results['detections'].append(det_result)
                return
            
            roi = frame[y1:y2, x1:x2]
            
            # License Plate
            if self.plate_processor:
                try:
                    plate_results = self.plate_processor.process_frame(roi)
                    if plate_results:
                        best_plate = plate_results[0]
                        if hasattr(best_plate, 'plate_text') and best_plate.plate_text:
                            det_result['license_plate'] = best_plate.plate_text.text if hasattr(best_plate.plate_text, 'text') else str(best_plate.plate_text)
                            det_result['license_plate_confidence'] = best_plate.plate_text.confidence if hasattr(best_plate.plate_text, 'confidence') else 0.0
                            
                            results['license_plates'].append({
                                'track_id': det_result['track_id'],
                                'plate_text': det_result['license_plate'],
                                'confidence': det_result['license_plate_confidence']
                            })
                except Exception as e:
                    logger.debug(f"Plate processing error: {e}")
            
            # Brand Classification
            if self.brand_classifier and det_result['class'].lower() in ['car', 'truck', 'suv', 'bus']:
                try:
                    brand_result = self.brand_classifier.classify_vehicle(roi, det_result['bbox'])
                    if brand_result:
                        det_result['vehicle_brand'] = brand_result.get('brand')
                        det_result['brand_confidence'] = brand_result.get('confidence', 0.0)
                except Exception as e:
                    logger.debug(f"Brand classification error: {e}")
            
            # Speed Calculation
            if self.speed_calculator:
                center_x = (x1 + x2) / 2
                center_y = (y1 + y2) / 2
                self.speed_calculator.update_track(det_result['track_id'], (center_x, center_y), frame_idx)
                speed_result = self.speed_calculator.calculate_speed(det_result['track_id'])
                if speed_result and speed_result.confidence > 0.5:
                    det_result['speed'] = speed_result.speed_kmh
                    det_result['velocity'] = {'x': speed_result.velocity_x, 'y': speed_result.velocity_y}
                    det_result['direction'] = speed_result.direction_deg
            
            # Emission Calculation
            if self.enhanced_emission_calculator and 'speed' in det_result and det_result['speed'] > 0:
                emissions = self.enhanced_emission_calculator.calculate_emissions_from_speed(
                    vehicle_type=det_result['class'],
                    speed_kmh=det_result['speed'],
                    distance_km=0.001
                )
                det_result['emission_co2'] = emissions.get('co2_g_km', 0)
                det_result['fuel_consumption'] = emissions.get('fuel_l_100km', 0)
                
                results['emissions'].append({
                    'track_id': det_result['track_id'],
                    'vehicle_type': det_result['class'],
                    'speed_kmh': det_result['speed'],
                    'co2_g_km': det_result['emission_co2'],
                    'fuel_l_100km': det_result['fuel_consumption']
                })
            
            # Trajectory Data
            if 'track_id' in det_result:
                results['trajectory_data'].append({
                    'track_id': det_result['track_id'],
                    'velocity': det_result.get('velocity'),
                    'direction': det_result.get('direction'),
                    'speed': det_result.get('speed')
                })
            
            results['detections'].append(det_result)
            
        except Exception as e:
            logger.error(f"Error processing detection {idx}: {e}")
    
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
    
    async def _display_frame_realtime(self, frame: np.ndarray, results: Dict, frame_idx: int):
        """Display frame immediately via WebSocket"""
        try:
            # Draw detections
            annotated = self.draw_detections(frame, results)
            
            # Encode to JPEG
            _, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
            frame_base64 = base64.b64encode(buffer).decode('utf-8')
            
            # Send to all WebSocket connections
            message = {
                'type': 'frame_update',
                'frame': frame_base64,
                'frame_idx': frame_idx,
                'detections': len(results.get('detections', []))
            }
            
            disconnected = []
            for ws in self.websocket_connections:
                try:
                    await ws.send_json(message)
                except Exception as e:
                    logger.debug(f"WebSocket send error: {e}")
                    disconnected.append(ws)
            
            # Remove disconnected connections
            for ws in disconnected:
                if ws in self.websocket_connections:
                    self.websocket_connections.remove(ws)
                    
        except Exception as e:
            logger.error(f"Error displaying frame: {e}")
    
    async def _send_results_to_kafka(self, results: Dict, video_id: str, frame_idx: int):
        """Send processed results to Kafka (async, non-blocking)"""
        if not self.kafka_producer:
            return
        
        try:
            from datetime import datetime
            frame_id = f"video_{video_id}_frame_{frame_idx}"
            sensor_id = f"video_{video_id}"
            
            # Send emissions
            if results.get('emissions'):
                emission_message = {
                    'frame_id': frame_id,
                    'sensor_id': sensor_id,
                    'intersection_id': 1,
                    'timestamp': datetime.utcnow().isoformat(),
                    'emissions': results['emissions']
                }
                await self.kafka_producer.send('emission-data', emission_message)
                logger.debug(f"✅ Sent {len(results['emissions'])} emission records to Kafka")
            
            # Send license plates
            if results.get('license_plates'):
                plate_message = {
                    'frame_id': frame_id,
                    'sensor_id': sensor_id,
                    'intersection_id': 1,
                    'timestamp': datetime.utcnow().isoformat(),
                    'license_plates': results['license_plates']
                }
                await self.kafka_producer.send('license-plates', plate_message)
                logger.debug(f"✅ Sent {len(results['license_plates'])} license plate records to Kafka")
            
            # Send trajectory data
            if results.get('trajectory_data'):
                trajectory_message = {
                    'frame_id': frame_id,
                    'sensor_id': sensor_id,
                    'intersection_id': 1,
                    'timestamp': datetime.utcnow().isoformat(),
                    'trajectory_data': results['trajectory_data']
                }
                await self.kafka_producer.send('trajectory-data', trajectory_message)
                logger.debug(f"✅ Sent {len(results['trajectory_data'])} trajectory records to Kafka")
                
        except Exception as e:
            logger.error(f"Error sending results to Kafka: {e}", exc_info=True)

