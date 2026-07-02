"""
Tramway Detection Module
Integrates trained YOLOv8 tramway detection model
"""
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional
from ultralytics import YOLO
import logging

logger = logging.getLogger(__name__)


class TramwayDetector:
    """
    Tramway Detection using trained YOLOv8 model
    Model trained on 1,526 tramway images
    """
    
    def __init__(
        self,
        model_path: str = "/Users/kappasutra/Traffic/models/tramway_training/tramway_runs/train_20251028_210058/weights/best.pt",
        confidence_threshold: float = 0.60,
        iou_threshold: float = 0.45,
        device: str = 'cpu'
    ):
        """
        Initialize Tramway Detector
        
        Args:
            model_path: Path to trained tramway detection model
            confidence_threshold: Minimum confidence for tramway detection
            iou_threshold: IoU threshold for NMS
            device: Device to run inference on
        """
        self.model_path = Path(model_path)
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.device = device
        self.model = None
        self.is_loaded = False
        
        # Statistics
        self.total_detections = 0
        self.tramway_count = 0
        
    def load_model(self) -> bool:
        """Load the tramway detection model (with CoreML support for Apple Silicon)"""
        try:
            # Try CoreML first if on Apple Silicon (MPS device)
            if self.device == 'mps' or self.device == 'cpu':
                coreml_path = self.model_path.with_suffix('.mlpackage')
                possible_paths = [
                    coreml_path,
                    self.model_path.parent / f"{self.model_path.stem}.mlpackage",
                    Path(f"models/tramway_training/tramway_runs/train_20251028_210058/weights/best.mlpackage"),
                ]
                
                for path in possible_paths:
                    if path.exists():
                        logger.info(f"✅ Loading CoreML tramway model: {path} (3-5× faster!)")
                        self.model = YOLO(str(path))  # YOLOv8 handles CoreML natively
                        self.is_loaded = True
                        logger.info(f"✅ Tramway detector loaded successfully with CoreML")
                        return True
            
            # Fallback to PyTorch
            if not self.model_path.exists():
                logger.warning(f"Tramway model not found at: {self.model_path}")
                logger.info("Tramway detection will be disabled")
                return False
            
            logger.info(f"Loading tramway detection model from: {self.model_path}")
            self.model = YOLO(str(self.model_path))
            
            # Move model to device
            if self.device == 'cuda':
                self.model.to('cuda')
            
            self.is_loaded = True
            logger.info(f"✅ Tramway detector loaded successfully on {self.device}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load tramway model: {e}")
            self.is_loaded = False
            return False
    
    def detect(
        self,
        frame: np.ndarray,
        return_annotated: bool = False
    ) -> List[Dict]:
        """
        Detect tramways in frame
        
        Args:
            frame: Input frame
            return_annotated: Whether to return annotated frame
        
        Returns:
            List of tramway detections
        """
        if not self.is_loaded:
            return []
        
        try:
            results = self.model(frame, verbose=False)
            
            detections = []
            
            if len(results) == 0 or len(results[0].boxes) == 0:
                return []
            
            for box in results[0].boxes:
                confidence = float(box.conf[0])
                
                if confidence < self.confidence_threshold:
                    continue
                
                # Get bounding box
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                
                detection = {
                    'bbox': {
                        'x1': int(x1),
                        'y1': int(y1),
                        'x2': int(x2),
                        'y2': int(y2)
                    },
                    'confidence': round(confidence, 3),
                    'class': 'tramway',
                    'object_class': 'tramway',
                    'class_id': int(box.cls[0]),
                    'vehicle_type': 'tramway',
                    'detector': 'tramway_yolov8'
                }
                
                detections.append(detection)
                self.tramway_count += 1
            
            self.total_detections += len(detections)
            
            if len(detections) > 0:
                logger.debug(f"Detected {len(detections)} tramway(s)")
            
            return detections
            
        except Exception as e:
            logger.error(f"Tramway detection error: {e}")
            return []
    
    def is_tramway_priority(
        self,
        tramway_bbox: Dict,
        intersection_bbox: Dict
    ) -> bool:
        """
        Check if tramway is at intersection and needs priority
        
        Args:
            tramway_bbox: Tramway bounding box
            intersection_bbox: Intersection area bbox
        
        Returns:
            True if tramway needs priority
        """
        # Calculate overlap between tramway and intersection
        x1 = max(tramway_bbox['x1'], intersection_bbox['x1'])
        y1 = max(tramway_bbox['y1'], intersection_bbox['y1'])
        x2 = min(tramway_bbox['x2'], intersection_bbox['x2'])
        y2 = min(tramway_bbox['y2'], intersection_bbox['y2'])
        
        if x2 <= x1 or y2 <= y1:
            return False
        
        overlap_area = (x2 - x1) * (y2 - y1)
        tramway_area = (tramway_bbox['x2'] - tramway_bbox['x1']) * (tramway_bbox['y2'] - tramway_bbox['y1'])
        
        overlap_ratio = overlap_area / tramway_area if tramway_area > 0 else 0
        
        # If tramway overlaps >30% with intersection, give priority
        return overlap_ratio > 0.3
    
    def get_statistics(self) -> Dict:
        """Get tramway detection statistics"""
        return {
            'total_detections': self.total_detections,
            'tramway_count': self.tramway_count,
            'model_loaded': self.is_loaded
        }
    
    def reset_statistics(self):
        """Reset statistics counters"""
        self.total_detections = 0
        self.tramway_count = 0

