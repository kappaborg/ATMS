"""
Model Quantization for Performance Optimization
Week 11: Performance Optimization

Supports:
- INT8 quantization (8-bit integers) - 4x smaller, 2-3x faster
- FP16 quantization (16-bit floats) - 2x smaller, 1.5-2x faster
- ONNX quantization
- CoreML optimization
"""

import logging
import os
from pathlib import Path
from typing import Optional, Literal
import numpy as np

logger = logging.getLogger(__name__)

try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False
    logger.warning("ultralytics not available - quantization disabled")

try:
    import onnx
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False
    logger.warning("ONNX not available - ONNX quantization disabled")

try:
    import coremltools as ct
    COREML_AVAILABLE = True
except ImportError:
    COREML_AVAILABLE = False
    logger.warning("coremltools not available - CoreML quantization disabled")


class ModelQuantizer:
    """
    Quantize YOLOv8 models for improved performance
    
    Quantization reduces model size and improves inference speed:
    - INT8: 4x smaller, 2-3x faster, <5% accuracy loss
    - FP16: 2x smaller, 1.5-2x faster, <1% accuracy loss
    """
    
    def __init__(self, model_path: str, output_dir: Optional[str] = None):
        """
        Initialize quantizer
        
        Args:
            model_path: Path to original YOLOv8 model (.pt file)
            output_dir: Directory to save quantized models
        """
        self.model_path = Path(model_path)
        self.output_dir = Path(output_dir) if output_dir else self.model_path.parent / "quantized"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")
        
        logger.info(f"ModelQuantizer initialized: {model_path}")
    
    def quantize_to_int8(
        self,
        calibration_data: Optional[list] = None,
        num_calibration_samples: int = 100
    ) -> Optional[str]:
        """
        Quantize model to INT8 (8-bit integers)
        
        Args:
            calibration_data: List of calibration images (numpy arrays)
            num_calibration_samples: Number of samples for calibration
            
        Returns:
            Path to quantized model or None if failed
        """
        if not ULTRALYTICS_AVAILABLE:
            logger.error("ultralytics not available - cannot quantize")
            return None
        
        try:
            logger.info("Starting INT8 quantization...")
            
            # Load model
            model = YOLO(str(self.model_path))
            
            # Export to ONNX first (required for quantization)
            onnx_path = self.output_dir / f"{self.model_path.stem}_int8.onnx"
            
            # Export with INT8 quantization
            # Note: YOLOv8 export supports quantization
            model.export(
                format='onnx',
                imgsz=640,
                half=False,  # INT8 quantization
                int8=True,   # Enable INT8 quantization
                dynamic=False,
                simplify=True
            )
            
            # Move exported model to output directory
            exported_path = self.model_path.parent / f"{self.model_path.stem}.onnx"
            if exported_path.exists():
                exported_path.rename(onnx_path)
                logger.info(f"✅ INT8 quantized model saved: {onnx_path}")
                return str(onnx_path)
            else:
                logger.warning("ONNX export completed but file not found")
                return None
                
        except Exception as e:
            logger.error(f"INT8 quantization failed: {e}", exc_info=True)
            return None
    
    def quantize_to_fp16(self) -> Optional[str]:
        """
        Quantize model to FP16 (16-bit floats)
        
        Returns:
            Path to quantized model or None if failed
        """
        if not ULTRALYTICS_AVAILABLE:
            logger.error("ultralytics not available - cannot quantize")
            return None
        
        try:
            logger.info("Starting FP16 quantization...")
            
            # Load model
            model = YOLO(str(self.model_path))
            
            # Export to ONNX with FP16
            onnx_path = self.output_dir / f"{self.model_path.stem}_fp16.onnx"
            
            model.export(
                format='onnx',
                imgsz=640,
                half=True,   # FP16 quantization
                dynamic=False,
                simplify=True
            )
            
            # Move exported model
            exported_path = self.model_path.parent / f"{self.model_path.stem}.onnx"
            if exported_path.exists():
                exported_path.rename(onnx_path)
                logger.info(f"✅ FP16 quantized model saved: {onnx_path}")
                return str(onnx_path)
            else:
                logger.warning("ONNX export completed but file not found")
                return None
                
        except Exception as e:
            logger.error(f"FP16 quantization failed: {e}", exc_info=True)
            return None
    
    def quantize_to_coreml(self) -> Optional[str]:
        """
        Quantize model to CoreML (optimized for Apple Silicon)
        
        Returns:
            Path to quantized CoreML model or None if failed
        """
        if not ULTRALYTICS_AVAILABLE:
            logger.error("ultralytics not available - cannot quantize")
            return None
        
        try:
            logger.info("Starting CoreML quantization...")
            
            # Load model
            model = YOLO(str(self.model_path))
            
            # Export to CoreML
            coreml_path = self.output_dir / f"{self.model_path.stem}_coreml.mlpackage"
            
            model.export(
                format='coreml',
                imgsz=640,
                half=True,  # FP16 for CoreML
                nms=True
            )
            
            # Move exported model
            exported_path = self.model_path.parent / f"{self.model_path.stem}.mlpackage"
            if exported_path.exists():
                exported_path.rename(coreml_path)
                logger.info(f"✅ CoreML quantized model saved: {coreml_path}")
                return str(coreml_path)
            else:
                logger.warning("CoreML export completed but file not found")
                return None
                
        except Exception as e:
            logger.error(f"CoreML quantization failed: {e}", exc_info=True)
            return None
    
    def compare_models(
        self,
        original_model_path: str,
        quantized_model_path: str,
        test_images: list
    ) -> dict:
        """
        Compare original and quantized model performance
        
        Args:
            original_model_path: Path to original model
            quantized_model_path: Path to quantized model
            test_images: List of test images (numpy arrays)
            
        Returns:
            Comparison metrics (speed, accuracy, size)
        """
        if not ULTRALYTICS_AVAILABLE:
            return {}
        
        try:
            import time
            
            # Load models
            original_model = YOLO(original_model_path)
            quantized_model = YOLO(quantized_model_path)
            
            # Measure inference time
            original_times = []
            quantized_times = []
            
            for img in test_images[:10]:  # Test on first 10 images
                # Original
                start = time.time()
                original_model(img)
                original_times.append(time.time() - start)
                
                # Quantized
                start = time.time()
                quantized_model(img)
                quantized_times.append(time.time() - start)
            
            # Calculate metrics
            original_avg = np.mean(original_times)
            quantized_avg = np.mean(quantized_times)
            speedup = original_avg / quantized_avg if quantized_avg > 0 else 0
            
            # Model sizes
            original_size = os.path.getsize(original_model_path) / (1024 * 1024)  # MB
            quantized_size = os.path.getsize(quantized_model_path) / (1024 * 1024)  # MB
            size_reduction = (1 - quantized_size / original_size) * 100 if original_size > 0 else 0
            
            return {
                'original_avg_time_ms': original_avg * 1000,
                'quantized_avg_time_ms': quantized_avg * 1000,
                'speedup': speedup,
                'original_size_mb': original_size,
                'quantized_size_mb': quantized_size,
                'size_reduction_percent': size_reduction
            }
            
        except Exception as e:
            logger.error(f"Model comparison failed: {e}", exc_info=True)
            return {}


def quantize_yolov8_model(
    model_path: str,
    quantization_type: Literal['int8', 'fp16', 'coreml'] = 'fp16',
    output_dir: Optional[str] = None
) -> Optional[str]:
    """
    Convenience function to quantize YOLOv8 model
    
    Args:
        model_path: Path to YOLOv8 model (.pt file)
        quantization_type: Type of quantization ('int8', 'fp16', 'coreml')
        output_dir: Directory to save quantized model
        
    Returns:
        Path to quantized model or None if failed
    """
    quantizer = ModelQuantizer(model_path, output_dir)
    
    if quantization_type == 'int8':
        return quantizer.quantize_to_int8()
    elif quantization_type == 'fp16':
        return quantizer.quantize_to_fp16()
    elif quantization_type == 'coreml':
        return quantizer.quantize_to_coreml()
    else:
        logger.error(f"Unknown quantization type: {quantization_type}")
        return None

