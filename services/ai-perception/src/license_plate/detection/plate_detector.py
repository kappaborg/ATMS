"""
License Plate Detection Module for ATMS
Optimized for real-time detection with high accuracy
"""

import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
import time
import logging
from collections import deque
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

class PlateRegion(Enum):
    """License plate regions"""
    FRONT = "front"
    REAR = "rear"
    UNKNOWN = "unknown"

@dataclass
class PlateDetection:
    """License plate detection result"""
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2
    confidence: float
    region: PlateRegion
    plate_image: np.ndarray
    timestamp: float
    track_id: Optional[int] = None

class YOLOPlateDetector:
    """
    YOLO-based license plate detector
    Optimized for real-time performance
    """
    
    def __init__(self, 
                 model_path: str = "/Users/kappasutra/Traffic/models/license_plate_training/outputs/license_plate_model_mps/weights/best.mlpackage",
                 confidence_threshold: float = 0.2,  # Lowered from 0.3 to 0.2 for better distance detection
                 iou_threshold: float = 0.45,
                 device: str = "cpu"):
        """
        Initialize YOLO plate detector
        
        Args:
            model_path: Path to YOLO model
            confidence_threshold: Minimum confidence for detection
            iou_threshold: IoU threshold for NMS
            device: Device to run inference on
        """
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.device = device
        
        # Load YOLO model
        self.model = None
        self._load_model()
        
        # Performance tracking
        self.detection_times = deque(maxlen=100)
        self.total_detections = 0
        
        logger.info(f"YOLO Plate Detector initialized: {model_path}")
    
    def _load_model(self):
        """Load YOLO model (with CoreML support for Apple Silicon)"""
        try:
            from ultralytics import YOLO
            from pathlib import Path
            
            model_path_obj = Path(self.model_path)
            
            # Try CoreML first if on Apple Silicon (MPS device)
            if self.device == 'mps' or self.device == 'cpu':
                coreml_path = model_path_obj.with_suffix('.mlpackage')
                possible_paths = [
                    coreml_path,
                    model_path_obj.parent / f"{model_path_obj.stem}.mlpackage",
                    Path(f"models/license_plate_training/outputs/license_plate_model_mps/weights/best.mlpackage"),
                ]
                
                for path in possible_paths:
                    if path.exists():
                        logger.info(f"✅ Loading CoreML license plate model: {path} (3-5× faster!)")
                        self.model = YOLO(str(path))  # YOLOv8 handles CoreML natively
                        logger.info("YOLO license plate model loaded successfully with CoreML")
                        return
            
            # Fallback to PyTorch
            if model_path_obj.exists():
                self.model = YOLO(str(self.model_path))
                logger.info("YOLO license plate model loaded successfully")
            else:
                logger.warning(f"License plate model not found at: {self.model_path}")
                self.model = None
        except Exception as e:
            logger.error(f"Failed to load YOLO license plate model: {e}")
            self.model = None
    
    def detect_plates(self, frame: np.ndarray) -> List[PlateDetection]:
        """
        Detect license plates in frame
        
        Args:
            frame: Input frame (BGR format)
        
        Returns:
            List of plate detections
        """
        if self.model is None:
            return []
        
        start_time = time.time()
        
        try:
            # Run YOLO inference
            results = self.model(frame, conf=self.confidence_threshold, iou=self.iou_threshold)
            
            detections = []
            
            for result in results:
                boxes = result.boxes
                if boxes is None or len(boxes) == 0:
                    continue
                
                # Get box data
                xyxy = boxes.xyxy.cpu().numpy()
                confs = boxes.conf.cpu().numpy()
                clss = boxes.cls.cpu().numpy()
                
                for i in range(len(boxes)):
                    x1, y1, x2, y2 = xyxy[i]
                    confidence = float(confs[i])
                    class_id = int(clss[i])
                    
                    # CRITICAL FIX: Expand bounding box to get larger plate crop for better OCR
                    # Add padding (20% on each side) to ensure we capture full plate
                    h, w = frame.shape[:2]
                    padding_x = int((x2 - x1) * 0.2)  # 20% padding
                    padding_y = int((y2 - y1) * 0.2)
                    
                    # Expand bbox with padding (ensure within frame bounds)
                    x1_expanded = max(0, int(x1) - padding_x)
                    y1_expanded = max(0, int(y1) - padding_y)
                    x2_expanded = min(w, int(x2) + padding_x)
                    y2_expanded = min(h, int(y2) + padding_y)
                    
                    # Extract plate region with padding
                    plate_roi = frame[y1_expanded:y2_expanded, x1_expanded:x2_expanded]
                    
                    if plate_roi.size == 0:
                        continue
                    
                    # Log expanded size for debugging
                    roi_h, roi_w = plate_roi.shape[:2]
                    if roi_h < 50 or roi_w < 100:
                        logger.warning(f"⚠️ Small plate crop even after padding: {roi_w}x{roi_h} (original: {int(x2-x1)}x{int(y2-y1)})")
                    
                    # Determine plate region (front/rear)
                    region = self._determine_plate_region(plate_roi, class_id)
                    
                    # Create detection (use expanded bbox for better OCR)
                    detection = PlateDetection(
                        bbox=(float(x1_expanded), float(y1_expanded), float(x2_expanded), float(y2_expanded)),
                        confidence=confidence,
                        region=region,
                        plate_image=plate_roi,
                        timestamp=time.time()
                    )
                    
                    detections.append(detection)
            
            # Update performance metrics
            processing_time = time.time() - start_time
            self.detection_times.append(processing_time)
            self.total_detections += len(detections)
            
            logger.debug(f"Detected {len(detections)} license plates in {processing_time*1000:.2f}ms")
            
            return detections
            
        except Exception as e:
            logger.error(f"Plate detection failed: {e}")
            return []
    
    def _determine_plate_region(self, plate_roi: np.ndarray, class_id: int) -> PlateRegion:
        """Determine if plate is front or rear"""
        # Simple heuristic based on aspect ratio and position
        height, width = plate_roi.shape[:2]
        aspect_ratio = width / height if height > 0 else 0
        
        # Front plates are typically wider
        if aspect_ratio > 2.5:
            return PlateRegion.FRONT
        elif aspect_ratio < 2.0:
            return PlateRegion.REAR
        else:
            return PlateRegion.UNKNOWN
    
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics"""
        avg_processing_time = np.mean(self.detection_times) if self.detection_times else 0
        
        return {
            'total_detections': self.total_detections,
            'avg_processing_time_ms': avg_processing_time * 1000,
            'max_processing_time_ms': max(self.detection_times) * 1000 if self.detection_times else 0,
            'model_loaded': self.model is not None
        }

class TraditionalPlateDetector:
    """
    Traditional computer vision-based plate detector
    Fallback method when YOLO is not available
    """
    
    def __init__(self, 
                 min_area: int = 2000,
                 max_area: int = 50000,
                 aspect_ratio_range: Tuple[float, float] = (2.0, 6.0)):
        """
        Initialize traditional plate detector
        
        Args:
            min_area: Minimum plate area
            max_area: Maximum plate area
            aspect_ratio_range: Valid aspect ratio range
        """
        self.min_area = min_area
        self.max_area = max_area
        self.aspect_ratio_range = aspect_ratio_range
        
        # Performance tracking
        self.detection_times = deque(maxlen=100)
        self.total_detections = 0
        
        logger.info("Traditional Plate Detector initialized")
    
    def detect_plates(self, frame: np.ndarray) -> List[PlateDetection]:
        """
        Detect license plates using traditional CV methods
        
        Args:
            frame: Input frame (BGR format)
        
        Returns:
            List of plate detections
        """
        start_time = time.time()
        
        try:
            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Apply Gaussian blur
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            
            # Edge detection
            edges = cv2.Canny(blurred, 50, 150)
            
            # Morphological operations
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
            
            # Find contours
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            detections = []
            
            for contour in contours:
                # Calculate area
                area = cv2.contourArea(contour)
                if area < self.min_area or area > self.max_area:
                    continue
                
                # Get bounding rectangle
                x, y, w, h = cv2.boundingRect(contour)
                aspect_ratio = w / h
                
                # Check aspect ratio
                if not (self.aspect_ratio_range[0] <= aspect_ratio <= self.aspect_ratio_range[1]):
                    continue
                
                # Extract plate region
                plate_roi = frame[y:y+h, x:x+w]
                
                if plate_roi.size == 0:
                    continue
                
                # Additional validation
                if self._is_valid_plate_region(plate_roi):
                    detection = PlateDetection(
                        bbox=(float(x), float(y), float(x+w), float(y+h)),
                        confidence=0.7,  # Traditional method confidence
                        region=PlateRegion.UNKNOWN,
                        plate_image=plate_roi,
                        timestamp=time.time()
                    )
                    
                    detections.append(detection)
            
            # Update performance metrics
            processing_time = time.time() - start_time
            self.detection_times.append(processing_time)
            self.total_detections += len(detections)
            
            logger.debug(f"Traditional method detected {len(detections)} plates in {processing_time*1000:.2f}ms")
            
            return detections
            
        except Exception as e:
            logger.error(f"Traditional plate detection failed: {e}")
            return []
    
    def _is_valid_plate_region(self, plate_roi: np.ndarray) -> bool:
        """Validate if region looks like a license plate"""
        if plate_roi.size == 0:
            return False
        
        # Convert to grayscale
        gray = cv2.cvtColor(plate_roi, cv2.COLOR_BGR2GRAY)
        
        # Check for text-like features
        # Apply threshold
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Count white pixels (text)
        white_pixels = np.sum(binary == 255)
        total_pixels = binary.size
        white_ratio = white_pixels / total_pixels
        
        # License plates should have reasonable text density
        return 0.1 <= white_ratio <= 0.7
    
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics"""
        avg_processing_time = np.mean(self.detection_times) if self.detection_times else 0
        
        return {
            'total_detections': self.total_detections,
            'avg_processing_time_ms': avg_processing_time * 1000,
            'max_processing_time_ms': max(self.detection_times) * 1000 if self.detection_times else 0
        }

class HybridPlateDetector:
    """
    Hybrid plate detector combining YOLO and traditional methods
    Provides best accuracy and reliability
    """
    
    def __init__(self, 
                 yolo_model_path: str = "yolov8n.pt",
                 yolo_confidence: float = 0.5,
                 traditional_fallback: bool = True,
                 fusion_threshold: float = 0.3):
        """
        Initialize hybrid plate detector
        
        Args:
            yolo_model_path: Path to YOLO model
            yolo_confidence: YOLO confidence threshold
            traditional_fallback: Use traditional method as fallback
            fusion_threshold: Threshold for combining results
        """
        self.traditional_fallback = traditional_fallback
        self.fusion_threshold = fusion_threshold
        
        # Initialize YOLO detector
        self.yolo_detector = YOLOPlateDetector(
            model_path=yolo_model_path,
            confidence_threshold=yolo_confidence
        )
        
        # Initialize traditional detector
        if traditional_fallback:
            self.traditional_detector = TraditionalPlateDetector()
        else:
            self.traditional_detector = None
        
        # Performance tracking
        self.detection_times = deque(maxlen=100)
        self.total_detections = 0
        self.yolo_detections = 0
        self.traditional_detections = 0
        
        logger.info("Hybrid Plate Detector initialized")
    
    def detect_plates(self, frame: np.ndarray) -> List[PlateDetection]:
        """
        Detect license plates using hybrid approach
        
        Args:
            frame: Input frame (BGR format)
        
        Returns:
            List of plate detections
        """
        start_time = time.time()
        
        # Get YOLO detections
        yolo_detections = self.yolo_detector.detect_plates(frame)
        self.yolo_detections += len(yolo_detections)
        
        # Get traditional detections if fallback enabled
        traditional_detections = []
        if self.traditional_detector:
            traditional_detections = self.traditional_detector.detect_plates(frame)
            self.traditional_detections += len(traditional_detections)
        
        # Fuse detections
        fused_detections = self._fuse_detections(yolo_detections, traditional_detections)
        
        # Update performance metrics
        processing_time = time.time() - start_time
        self.detection_times.append(processing_time)
        self.total_detections += len(fused_detections)
        
        logger.debug(f"Hybrid detection: {len(yolo_detections)} YOLO, {len(traditional_detections)} traditional, "
                    f"{len(fused_detections)} fused in {processing_time*1000:.2f}ms")
        
        return fused_detections
    
    def _fuse_detections(self, yolo_detections: List[PlateDetection], 
                        traditional_detections: List[PlateDetection]) -> List[PlateDetection]:
        """Fuse YOLO and traditional detections"""
        if not traditional_detections:
            return yolo_detections
        
        if not yolo_detections:
            return traditional_detections
        
        # Combine and remove duplicates
        all_detections = yolo_detections + traditional_detections
        fused_detections = []
        
        for detection in all_detections:
            # Check if detection overlaps with existing ones
            is_duplicate = False
            for existing in fused_detections:
                if self._detections_overlap(detection, existing):
                    # Keep the one with higher confidence
                    if detection.confidence > existing.confidence:
                        fused_detections.remove(existing)
                        fused_detections.append(detection)
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                fused_detections.append(detection)
        
        return fused_detections
    
    def _detections_overlap(self, det1: PlateDetection, det2: PlateDetection) -> bool:
        """Check if two detections overlap significantly"""
        x1_1, y1_1, x2_1, y2_1 = det1.bbox
        x1_2, y1_2, x2_2, y2_2 = det2.bbox
        
        # Calculate intersection
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)
        
        if x1_i >= x2_i or y1_i >= y2_i:
            return False
        
        intersection_area = (x2_i - x1_i) * (y2_i - y1_i)
        
        # Calculate union
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union_area = area1 + area2 - intersection_area
        
        # Calculate IoU
        iou = intersection_area / union_area if union_area > 0 else 0
        
        return iou > self.fusion_threshold
    
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics"""
        avg_processing_time = np.mean(self.detection_times) if self.detection_times else 0
        
        return {
            'total_detections': self.total_detections,
            'yolo_detections': self.yolo_detections,
            'traditional_detections': self.traditional_detections,
            'avg_processing_time_ms': avg_processing_time * 1000,
            'max_processing_time_ms': max(self.detection_times) * 1000 if self.detection_times else 0,
            'yolo_metrics': self.yolo_detector.get_performance_metrics(),
            'traditional_metrics': self.traditional_detector.get_performance_metrics() if self.traditional_detector else None
        }
