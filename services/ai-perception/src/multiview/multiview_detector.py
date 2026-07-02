"""
Multi-View Detection Module
Fuses detections from 3 different viewpoints: Top, Side, Front
"""
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from ultralytics import YOLO
import logging

logger = logging.getLogger(__name__)


class MultiViewDetector:
    """
    Multi-View Vehicle Detection using 3 trained YOLOv8 models
    - Top View: Bird's eye view detection
    - Side Profile: Side angle detection
    - Front Bumper: Front-facing detection
    
    Fuses results using confidence weighting for improved accuracy
    """
    
    def __init__(
        self,
        top_model_path: str = "/Users/kappasutra/Traffic/multiview_models/top_view_model/weights/best.pt",
        side_model_path: str = "/Users/kappasutra/Traffic/multiview_models/side_profile_model/weights/best.pt",
        front_model_path: str = "/Users/kappasutra/Traffic/multiview_models/front_bumper_model/weights/best.pt",
        confidence_threshold: float = 0.50,
        iou_threshold: float = 0.45,
        device: str = 'cpu',
        enable_fusion: bool = True
    ):
        """
        Initialize Multi-View Detector
        
        Args:
            top_model_path: Path to top view model
            side_model_path: Path to side profile model
            front_model_path: Path to front bumper model
            confidence_threshold: Minimum confidence for detections
            iou_threshold: IoU threshold for NMS
            device: Device to run inference on
            enable_fusion: Whether to fuse detections from all views
        """
        self.top_model_path = Path(top_model_path)
        self.side_model_path = Path(side_model_path)
        self.front_model_path = Path(front_model_path)
        
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.device = device
        self.enable_fusion = enable_fusion
        
        # Models
        self.top_model = None
        self.side_model = None
        self.front_model = None
        
        self.is_loaded = False
        
        # Statistics
        self.total_detections = 0
        self.fused_detections = 0
        
        # View weights (can be adjusted based on performance)
        self.view_weights = {
            'top': 0.35,
            'side': 0.35,
            'front': 0.30
        }
    
    def load_models(self) -> bool:
        """Load all multi-view models (with CoreML support for Apple Silicon)"""
        try:
            logger.info("Loading multi-view detection models...")
            
            # Helper to load model with CoreML support
            def load_model_with_coreml(pt_path: Path, model_name: str):
                if self.device == 'mps' or self.device == 'cpu':
                    # Try CoreML first
                    coreml_path = pt_path.with_suffix('.mlpackage')
                    possible_paths = [
                        coreml_path,
                        pt_path.parent / f"{pt_path.stem}.mlpackage",
                    ]
                    
                    for path in possible_paths:
                        if path.exists():
                            logger.info(f"✅ Loading CoreML {model_name} model: {path} (3-5× faster!)")
                            return YOLO(str(path))  # YOLOv8 handles CoreML natively
                
                # Fallback to PyTorch
                if pt_path.exists():
                    logger.info(f"Loading {model_name} model from: {pt_path}")
                    return YOLO(str(pt_path))
                else:
                    logger.warning(f"⚠️  {model_name} model not found: {pt_path}")
                    return None
            
            # Load top view model
            self.top_model = load_model_with_coreml(self.top_model_path, "Top view")
            if self.top_model:
                logger.info(f"✅ Top view model loaded")
            
            # Load side profile model
            self.side_model = load_model_with_coreml(self.side_model_path, "Side profile")
            if self.side_model:
                logger.info(f"✅ Side profile model loaded")
            
            # Load front bumper model
            self.front_model = load_model_with_coreml(self.front_model_path, "Front bumper")
            if self.front_model:
                logger.info(f"✅ Front bumper model loaded")
            
            # Check if at least one model loaded
            models_loaded = sum([
                self.top_model is not None,
                self.side_model is not None,
                self.front_model is not None
            ])
            
            if models_loaded == 0:
                logger.error("No multi-view models could be loaded")
                return False
            
            self.is_loaded = True
            logger.info(f"Multi-view detector ready ({models_loaded}/3 models loaded)")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load multi-view models: {e}")
            self.is_loaded = False
            return False
    
    def detect_single_view(
        self,
        frame: np.ndarray,
        model: YOLO,
        view_name: str
    ) -> List[Dict]:
        """
        Run detection on a single view
        
        Args:
            frame: Input frame
            model: YOLO model for this view
            view_name: Name of the view (top/side/front)
        
        Returns:
            List of detections from this view
        """
        if model is None:
            return []
        
        try:
            results = model(frame, verbose=False)
            
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
                    'view': view_name,
                    'class': 'vehicle',
                    'class_id': int(box.cls[0])
                }
                
                detections.append(detection)
            
            return detections
            
        except Exception as e:
            logger.error(f"Detection error for {view_name} view: {e}")
            return []
    
    def calculate_iou(self, box1: Dict, box2: Dict) -> float:
        """Calculate IoU between two bounding boxes"""
        x1 = max(box1['x1'], box2['x1'])
        y1 = max(box1['y1'], box2['y1'])
        x2 = min(box1['x2'], box2['x2'])
        y2 = min(box1['y2'], box2['y2'])
        
        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        
        area1 = (box1['x2'] - box1['x1']) * (box1['y2'] - box1['y1'])
        area2 = (box2['x2'] - box2['x1']) * (box2['y2'] - box2['y1'])
        
        union = area1 + area2 - intersection
        
        return intersection / union if union > 0 else 0
    
    def fuse_detections(
        self,
        top_dets: List[Dict],
        side_dets: List[Dict],
        front_dets: List[Dict]
    ) -> List[Dict]:
        """
        Fuse detections from all views using confidence weighting
        
        Args:
            top_dets: Detections from top view
            side_dets: Detections from side view
            front_dets: Detections from front view
        
        Returns:
            Fused detections with enhanced confidence
        """
        if not self.enable_fusion:
            # Just combine all detections without fusion
            return top_dets + side_dets + front_dets
        
        all_detections = []
        
        # Combine all detections with view weights
        for det in top_dets:
            det['weighted_conf'] = det['confidence'] * self.view_weights['top']
            det['view_count'] = 1
            all_detections.append(det)
        
        for det in side_dets:
            det['weighted_conf'] = det['confidence'] * self.view_weights['side']
            det['view_count'] = 1
            all_detections.append(det)
        
        for det in front_dets:
            det['weighted_conf'] = det['confidence'] * self.view_weights['front']
            det['view_count'] = 1
            all_detections.append(det)
        
        if len(all_detections) == 0:
            return []
        
        # Group overlapping detections from different views
        fused = []
        processed = set()
        
        for i, det1 in enumerate(all_detections):
            if i in processed:
                continue
            
            # Find all detections that overlap with this one
            group = [det1]
            processed.add(i)
            
            for j, det2 in enumerate(all_detections[i+1:], start=i+1):
                if j in processed:
                    continue
                
                iou = self.calculate_iou(det1['bbox'], det2['bbox'])
                
                if iou > self.iou_threshold and det1['view'] != det2['view']:
                    group.append(det2)
                    processed.add(j)
            
            # Fuse group
            if len(group) == 1:
                # Single detection
                fused.append(group[0])
            else:
                # Multiple views detected same object - fuse
                fused_det = self._fuse_group(group)
                fused.append(fused_det)
                self.fused_detections += 1
        
        self.total_detections += len(fused)
        
        return fused
    
    def _fuse_group(self, group: List[Dict]) -> Dict:
        """Fuse a group of overlapping detections"""
        # Average the bounding boxes weighted by confidence
        total_weight = sum([d['weighted_conf'] for d in group])
        
        x1 = sum([d['bbox']['x1'] * d['weighted_conf'] for d in group]) / total_weight
        y1 = sum([d['bbox']['y1'] * d['weighted_conf'] for d in group]) / total_weight
        x2 = sum([d['bbox']['x2'] * d['weighted_conf'] for d in group]) / total_weight
        y2 = sum([d['bbox']['y2'] * d['weighted_conf'] for d in group]) / total_weight
        
        # Enhanced confidence from multiple views
        avg_conf = sum([d['confidence'] for d in group]) / len(group)
        multiview_boost = 0.05 * (len(group) - 1)  # Boost for each additional view
        enhanced_conf = min(1.0, avg_conf + multiview_boost)
        
        views = [d['view'] for d in group]
        
        return {
            'bbox': {
                'x1': int(x1),
                'y1': int(y1),
                'x2': int(x2),
                'y2': int(y2)
            },
            'confidence': round(enhanced_conf, 3),
            'multiview_confidence': round(enhanced_conf, 3),
            'view': 'multiview_fused',
            'views': views,
            'view_count': len(views),
            'class': 'vehicle',
            'fusion_method': 'weighted_average'
        }
    
    def detect(self, frame: np.ndarray) -> List[Dict]:
        """
        Run multi-view detection on frame
        
        Args:
            frame: Input frame
        
        Returns:
            Fused detections from all views
        """
        if not self.is_loaded:
            return []
        
        try:
            # Run detection on each view
            top_dets = self.detect_single_view(frame, self.top_model, 'top')
            side_dets = self.detect_single_view(frame, self.side_model, 'side')
            front_dets = self.detect_single_view(frame, self.front_model, 'front')
            
            logger.debug(f"Multi-view detections: top={len(top_dets)}, side={len(side_dets)}, front={len(front_dets)}")
            
            # Fuse detections
            fused_dets = self.fuse_detections(top_dets, side_dets, front_dets)
            
            return fused_dets
            
        except Exception as e:
            logger.error(f"Multi-view detection error: {e}")
            return []
    
    def get_statistics(self) -> Dict:
        """Get multi-view detection statistics"""
        fusion_rate = (
            self.fused_detections / self.total_detections * 100
            if self.total_detections > 0 else 0
        )
        
        return {
            'total_detections': self.total_detections,
            'fused_detections': self.fused_detections,
            'fusion_rate': round(fusion_rate, 2),
            'models_loaded': {
                'top': self.top_model is not None,
                'side': self.side_model is not None,
                'front': self.front_model is not None
            },
            'is_loaded': self.is_loaded
        }
    
    def reset_statistics(self):
        """Reset statistics"""
        self.total_detections = 0
        self.fused_detections = 0

