"""
Car Brand Classification Module
Integrates trained YOLOv8 car brand classification model
"""
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, Optional, Tuple, List
from ultralytics import YOLO
import logging

logger = logging.getLogger(__name__)

# Repo root: services/ai-perception/src/brand/ -> 4 levels up.
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_BRAND_MODEL = (
    _PROJECT_ROOT
    / "models/car_brand_classification/outputs/car_brand_classification_robust/weights/best.pt"
)


class BrandClassifier:
    """
    Car Brand Classification using trained YOLOv8 model
    Model trained on 32 car brands with 4,391 images
    """

    def __init__(
        self,
        model_path: str = str(_DEFAULT_BRAND_MODEL),
        confidence_threshold: float = 0.55,
        device: str = 'cpu'
    ):
        """
        Initialize Brand Classifier
        
        Args:
            model_path: Path to trained brand classification model
            confidence_threshold: Minimum confidence for brand detection
            device: Device to run inference on ('cpu' or 'cuda')
        """
        self.model_path = Path(model_path)
        self.confidence_threshold = confidence_threshold
        self.device = device
        self.model = None
        self.is_loaded = False
        
        # Fallback label list for the original 32-brand model ONLY. The
        # authoritative mapping is read from the checkpoint's own
        # `model.names` in load_model() — a positional list silently
        # mislabels every prediction if a different model (e.g. the
        # 54-class dvm_car_v1) is swapped in.
        self._fallback_brand_names = [
            'Audi', 'BMW', 'Chevrolet', 'Dodge', 'Ford', 'GMC', 'Honda',
            'Hyundai', 'Infiniti', 'Jeep', 'Kia', 'Lexus', 'Mazda',
            'Mercedes-Benz', 'Nissan', 'Ram', 'Subaru', 'Tesla', 'Toyota',
            'Volkswagen', 'Volvo', 'Acura', 'Buick', 'Cadillac', 'Chrysler',
            'Genesis', 'Land Rover', 'Lincoln', 'Mini', 'Mitsubishi',
            'Porsche', 'Other'
        ]
        self.brand_names: Dict[int, str] = {
            i: name for i, name in enumerate(self._fallback_brand_names)
        }
        
        # Statistics
        self.total_classifications = 0
        self.successful_classifications = 0
        
    def load_model(self) -> bool:
        """Load the brand classification model (with CoreML support for Apple Silicon)"""
        try:
            # Try CoreML first if on Apple Silicon (MPS device)
            if self.device == 'mps' or self.device == 'cpu':
                # Only CoreML variants of the REQUESTED model — never fall
                # back to a different checkpoint (that silently swaps models).
                coreml_path = self.model_path.with_suffix('.mlpackage')
                possible_paths = [
                    coreml_path,
                    self.model_path.parent / f"{self.model_path.stem}.mlpackage",
                ]
                
                for path in possible_paths:
                    if path.exists():
                        logger.info(f"✅ Loading CoreML brand model: {path} (3-5× faster!)")
                        self.model = YOLO(str(path))  # YOLOv8 handles CoreML natively
                        self._adopt_model_names()
                        self.is_loaded = True
                        logger.info(f"Brand classifier loaded successfully with CoreML")
                        logger.info(f"Model supports {len(self.brand_names)} brands")
                        return True
            
            # Fallback to PyTorch
            if not self.model_path.exists():
                logger.error(f"Brand model not found at: {self.model_path}")
                return False
            
            logger.info(f"Loading brand classification model from: {self.model_path}")
            self.model = YOLO(str(self.model_path))
            self._adopt_model_names()

            # Move model to device
            if self.device == 'cuda':
                self.model.to('cuda')

            self.is_loaded = True
            logger.info(f"Brand classifier loaded successfully on {self.device}")
            logger.info(f"Model supports {len(self.brand_names)} brands")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load brand model: {e}")
            self.is_loaded = False
            return False

    def _adopt_model_names(self) -> None:
        """Use the checkpoint's own class-name mapping when available.

        Guards against label drift: a positional list breaks silently the
        moment a retrained/different model is dropped in.
        """
        names = getattr(self.model, "names", None)
        if isinstance(names, (list, tuple)):
            names = dict(enumerate(names))
        if not isinstance(names, dict) or not names:
            logger.warning(
                "Brand model exposes no class names — falling back to the "
                "built-in 32-brand list. Verify it matches this checkpoint!"
            )
            return
        # Ultralytics defaults to stringified indices when metadata is
        # missing; that mapping is useless for labelling.
        if all(str(v).isdigit() for v in names.values()):
            logger.warning(
                "Brand model class names are bare indices — falling back to "
                "the built-in 32-brand list. Verify it matches this checkpoint!"
            )
            return
        self.brand_names = {int(k): str(v) for k, v in names.items()}
        logger.info(f"Adopted {len(self.brand_names)} class names from the model checkpoint")

    def classify_vehicle(
        self,
        frame: np.ndarray,
        bbox: Dict[str, int],
        vehicle_class: str = 'car'
    ) -> Optional[Dict]:
        """
        Classify vehicle brand from cropped image
        
        Args:
            frame: Full frame image
            bbox: Bounding box dict with x1, y1, x2, y2
            vehicle_class: Type of vehicle (only classify cars/SUVs/trucks)
        
        Returns:
            Dict with brand, confidence, or None if classification fails
        """
        if not self.is_loaded:
            return None
        
        # Only classify cars, SUVs, trucks
        if vehicle_class.lower() not in ['car', 'truck', 'suv', 'vehicle']:
            return None
        
        try:
            # Extract bounding box and ensure integers
            x1 = int(bbox['x1'])
            y1 = int(bbox['y1'])
            x2 = int(bbox['x2'])
            y2 = int(bbox['y2'])
            
            # Validate bbox
            h, w = frame.shape[:2]
            x1 = max(0, min(x1, w - 1))
            y1 = max(0, min(y1, h - 1))
            x2 = max(x1 + 1, min(x2, w))
            y2 = max(y1 + 1, min(y2, h))
            
            # Crop vehicle region
            vehicle_crop = frame[y1:y2, x1:x2]
            
            if vehicle_crop.size == 0:
                return None
            
            # Expand crop slightly for better brand detection (10% padding)
            pad_x = max(1, int((x2 - x1) * 0.1))
            pad_y = max(1, int((y2 - y1) * 0.1))
            
            x1_pad = max(0, int(x1 - pad_x))
            y1_pad = max(0, int(y1 - pad_y))
            x2_pad = min(w, int(x2 + pad_x))
            y2_pad = min(h, int(y2 + pad_y))
            
            vehicle_crop_padded = frame[y1_pad:y2_pad, x1_pad:x2_pad]
            
            # Run brand classification
            results = self.model(vehicle_crop_padded, verbose=False)
            
            self.total_classifications += 1
            
            if len(results) == 0 or len(results[0].boxes) == 0:
                return None

            # Get best detection — explicitly the highest-confidence box
            # (result ordering is not guaranteed across backends).
            boxes = results[0].boxes
            confs = boxes.conf.cpu().numpy() if hasattr(boxes.conf, "cpu") else np.asarray(boxes.conf)
            best_idx = int(np.argmax(confs))
            confidence = float(confs[best_idx])
            class_id = int(boxes.cls[best_idx])

            # Filter by confidence
            if confidence < self.confidence_threshold:
                return None

            # Get brand name from the checkpoint-derived mapping
            brand_name = self.brand_names.get(class_id, "Unknown")
            
            self.successful_classifications += 1
            
            result = {
                'brand': brand_name,
                'confidence': round(confidence, 3),
                'class_id': class_id,
                'method': 'yolov8_brand_classifier'
            }
            
            logger.debug(f"Brand detected: {brand_name} ({confidence:.2%})")
            
            return result
            
        except Exception as e:
            logger.error(f"Brand classification error: {e}")
            return None
    
    def classify_batch(
        self,
        frame: np.ndarray,
        detections: List[Dict]
    ) -> List[Dict]:
        """
        Classify brands for multiple vehicles in a frame
        
        Args:
            frame: Full frame image
            detections: List of detection dicts with bbox and class
        
        Returns:
            List of detections with added brand information
        """
        if not self.is_loaded:
            return detections
        
        enhanced_detections = []
        
        for det in detections:
            # Add brand classification
            brand_info = self.classify_vehicle(
                frame,
                det.get('bbox', {}),
                det.get('class', 'unknown')
            )
            
            # Add brand info to detection
            if brand_info:
                det['vehicle_brand'] = brand_info['brand']
                det['brand_confidence'] = brand_info['confidence']
            else:
                det['vehicle_brand'] = None
                det['brand_confidence'] = 0.0
            
            enhanced_detections.append(det)
        
        return enhanced_detections
    
    def get_statistics(self) -> Dict:
        """Get classification statistics"""
        success_rate = (
            self.successful_classifications / self.total_classifications * 100
            if self.total_classifications > 0 else 0
        )
        
        return {
            'total_classifications': self.total_classifications,
            'successful_classifications': self.successful_classifications,
            'success_rate': round(success_rate, 2),
            'model_loaded': self.is_loaded,
            'supported_brands': len(self.brand_names)
        }
    
    def reset_statistics(self):
        """Reset statistics counters"""
        self.total_classifications = 0
        self.successful_classifications = 0

