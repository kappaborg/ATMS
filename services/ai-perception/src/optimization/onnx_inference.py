"""
ONNX Runtime Inference Wrapper
Provides 2-3× faster inference as fallback option
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
import cv2

try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False
    ort = None

logger = logging.getLogger(__name__)


class ONNXInference:
    """
    ONNX Runtime inference wrapper for optimized model execution
    Cross-platform, works on both Apple Silicon and Intel
    """
    
    def __init__(self, model_path: str, device: str = 'cpu'):
        """
        Initialize ONNX inference
        
        Args:
            model_path: Path to .onnx file
            device: 'cpu' or 'cuda' (if available)
        """
        self.model_path = Path(model_path)
        self.device = device
        self.session = None
        self.input_name = None
        self.output_names = []
        self.is_loaded = False
        
        if not ONNX_AVAILABLE:
            logger.warning("ONNX Runtime not available. Install: pip install onnxruntime")
            return
        
        if not self.model_path.exists():
            logger.warning(f"ONNX model not found: {self.model_path}")
            return
        
        self.load_model()
    
    def load_model(self) -> bool:
        """Load ONNX model"""
        if not ONNX_AVAILABLE:
            return False
        
        try:
            # Create inference session
            providers = ['CPUExecutionProvider']
            if self.device == 'cuda' and 'CUDAExecutionProvider' in ort.get_available_providers():
                providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
            
            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            
            logger.info(f"Loading ONNX model: {self.model_path}")
            self.session = ort.InferenceSession(
                str(self.model_path),
                sess_options=sess_options,
                providers=providers
            )
            
            # Get input/output names
            self.input_name = self.session.get_inputs()[0].name
            self.output_names = [output.name for output in self.session.get_outputs()]
            
            self.is_loaded = True
            logger.info(f"✅ ONNX model loaded successfully (provider: {providers[0]})")
            return True
        except Exception as e:
            logger.error(f"Failed to load ONNX model: {e}")
            self.is_loaded = False
            return False
    
    def predict(self, frame: np.ndarray) -> Dict:
        """
        Run inference on frame
        
        Args:
            frame: Input frame (BGR format, uint8)
        
        Returns:
            Detection results dict
        """
        if not self.is_loaded:
            return {}
        
        try:
            # Preprocess frame
            input_tensor = self._preprocess(frame)
            
            # Run inference
            outputs = self.session.run(self.output_names, {self.input_name: input_tensor})
            
            # Parse outputs
            return self._parse_outputs(outputs)
            
        except Exception as e:
            logger.error(f"ONNX inference error: {e}")
            return {}
    
    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        """Preprocess frame for ONNX model"""
        # Get expected input shape
        input_shape = self.session.get_inputs()[0].shape
        
        # Resize if needed
        if len(input_shape) == 4:  # (batch, channels, height, width)
            target_h, target_w = input_shape[2], input_shape[3]
        else:
            target_h, target_w = 640, 640  # Default YOLO size
        
        # Resize frame
        resized = cv2.resize(frame, (target_w, target_h))
        
        # Convert BGR to RGB
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        
        # Normalize to [0, 1]
        normalized = rgb.astype(np.float32) / 255.0
        
        # Transpose to (C, H, W) and add batch dimension
        transposed = normalized.transpose(2, 0, 1)
        batched = np.expand_dims(transposed, axis=0)
        
        return batched
    
    def _parse_outputs(self, outputs: List[np.ndarray]) -> Dict:
        """Parse ONNX model outputs"""
        # YOLO ONNX output format: (batch, num_detections, 85)
        # 85 = 4 (bbox) + 1 (objectness) + 80 (classes)
        detections = []
        
        try:
            output = outputs[0]  # First output
            
            if len(output.shape) == 3:  # (batch, num_detections, features)
                output = output[0]  # Remove batch dimension
            
            for detection in output:
                # Extract bbox, confidence, class
                x_center, y_center, width, height = detection[:4]
                objectness = detection[4]
                class_scores = detection[5:]
                
                if objectness > 0.5:  # Objectness threshold
                    class_id = np.argmax(class_scores)
                    confidence = objectness * class_scores[class_id]
                    
                    if confidence > 0.5:  # Confidence threshold
                        # Convert center+size to x1,y1,x2,y2
                        x1 = x_center - width / 2
                        y1 = y_center - height / 2
                        x2 = x_center + width / 2
                        y2 = y_center + height / 2
                        
                        detections.append({
                            'bbox': [x1, y1, x2, y2],
                            'confidence': float(confidence),
                            'class_id': int(class_id)
                        })
            
            return {'detections': detections}
        except Exception as e:
            logger.error(f"Error parsing ONNX output: {e}")
            return {'detections': []}


class ONNXModelManager:
    """Manager for multiple ONNX models"""
    
    def __init__(self):
        self.models = {}
        self.model_paths = {
            'yolov8': 'services/ai-perception/models/yolov8n.onnx',
            'brand': 'models/car_brand_classification/outputs/car_brand_classification_robust/weights/best.onnx',
            'multiview_top': 'multiview_models/top_view_model/weights/best.onnx',
            'multiview_side': 'multiview_models/side_profile_model/weights/best.onnx',
            'multiview_front': 'multiview_models/front_bumper_model/weights/best.onnx',
            'tramway': 'models/tramway_training/tramway_runs/train_20251028_210058/weights/best.onnx',
            'license_plate': 'models/license_plate_training/outputs/license_plate_model_mps/weights/best.onnx'
        }
    
    def load_all_models(self, device: str = 'cpu') -> Dict[str, bool]:
        """Load all available ONNX models"""
        results = {}
        
        for name, path in self.model_paths.items():
            model_path = Path(path)
            if model_path.exists():
                try:
                    model = ONNXInference(str(model_path), device=device)
                    self.models[name] = model
                    results[name] = model.is_loaded
                    logger.info(f"{'✅' if model.is_loaded else '❌'} {name}: {model.is_loaded}")
                except Exception as e:
                    logger.error(f"Failed to load {name}: {e}")
                    results[name] = False
            else:
                logger.warning(f"Model not found: {path}")
                results[name] = False
        
        return results
    
    def get_model(self, name: str) -> Optional[ONNXInference]:
        """Get loaded model by name"""
        return self.models.get(name)
    
    def is_available(self) -> bool:
        """Check if ONNX Runtime is available"""
        return ONNX_AVAILABLE and len(self.models) > 0

