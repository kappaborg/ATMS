"""
AI Perception Service - YOLOv8 Object Detector
Week 2: Professional YOLOv8 Integration with Optimization
"""
import asyncio
import os
import time
from typing import List, Optional, Tuple, Any
import numpy as np
import torch
from pathlib import Path
import sys

# Fabricating detections is only acceptable in explicitly-marked test runs.
# Without this opt-in, a missing ultralytics install is a hard failure —
# a traffic system must never silently emit synthetic data.
MOCK_DETECTIONS_ALLOWED = os.getenv("ATMS_ALLOW_MOCK_DETECTIONS", "").lower() in (
    "1", "true", "yes"
)

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent.parent))
from shared.utils.logger import get_logger
from shared.models.detection import Detection, BoundingBox, ObjectClass, PerformanceMetrics

logger = get_logger(__name__)

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    logger.warning("Ultralytics YOLOv8 not available, using mock mode")

# Week 11: Performance optimizations
try:
    from optimization.model_quantization import ModelQuantizer
    QUANTIZATION_AVAILABLE = True
except ImportError:
    QUANTIZATION_AVAILABLE = False
    ModelQuantizer = None

try:
    from optimization.memory_pool import FrameMemoryPool
    MEMORY_POOL_AVAILABLE = True
except ImportError:
    MEMORY_POOL_AVAILABLE = False
    FrameMemoryPool = None

try:
    from optimization.cache_manager import CacheManager
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    CacheManager = None

try:
    from optimization.performance_profiler import PerformanceProfiler, FrameRateMonitor
    PROFILER_AVAILABLE = True
except ImportError:
    PROFILER_AVAILABLE = False
    PerformanceProfiler = None
    FrameRateMonitor = None

# CoreML optimization for Apple Silicon
# Note: YOLOv8 has native CoreML support, so we don't need a separate wrapper
# We'll detect CoreML models by file extension (.mlpackage)
import platform
COREML_OPTIMIZATION_AVAILABLE = platform.system() == "Darwin"  # Available on macOS
CoreMLInference = None  # Not needed - YOLOv8 handles CoreML natively


class YOLODetector:
    """
    Professional YOLOv8 Object Detector
    
    Features:
    - GPU acceleration support
    - Model optimization (ONNX/TensorRT)
    - Async inference
    - Batch processing
    - Performance monitoring
    - Comprehensive error handling
    """
    
    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        device: str = "cuda",
        confidence_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        input_size: Tuple[int, int] = (640, 640),
        half_precision: bool = True,
        detect_classes: Optional[List[int]] = None,
        class_names: Optional[dict] = None,
        # Week 11: Optimization options
        enable_memory_pool: bool = True,
        enable_caching: bool = True,
        enable_profiling: bool = False,
        cache_manager: Optional[Any] = None
    ):
        """
        Initialize YOLOv8 detector
        
        Args:
            model_path: Path to YOLOv8 model weights
            device: Device to run on (cuda/cpu/mps)
            confidence_threshold: Minimum confidence for detections
            iou_threshold: NMS IoU threshold
            input_size: Input image size (width, height)
            half_precision: Use FP16 for faster inference
            detect_classes: List of class IDs to detect
            class_names: Mapping of class IDs to names
        """
        self.model_path = model_path
        self.device = device
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        # CRITICAL: CoreML models have FIXED input sizes (usually 640x640)
        # We'll set input_size after determining if CoreML is available
        self._requested_input_size = input_size
        self.input_size = input_size  # Will be adjusted if CoreML is used
        self.half_precision = half_precision
        self.detect_classes = detect_classes or [0, 1, 2, 3, 5, 7]  # Common traffic classes
        self.class_names = class_names or self._default_class_names()
        
        self.model = None
        self.use_coreml = False  # Whether to use CoreML (YOLOv8 handles CoreML natively)
        self.is_loaded = False
        self.inference_count = 0
        self.total_inference_time = 0.0
        
        # Initialize logger FIRST before using it in optimizations
        self.logger = logger.bind(
            model_path=model_path,
            device=device,
            use_coreml=False  # Will be updated below
        )
        
        # Week 11: Performance optimizations
        if enable_memory_pool and MEMORY_POOL_AVAILABLE and FrameMemoryPool:
            try:
                self._memory_pool = FrameMemoryPool(
                    pool_size=10,
                    default_shape=(1080, 1920, 3),
                    dtype=np.uint8
                )
                self.logger.info("Memory pool enabled")
            except Exception as e:
                self.logger.warning(f"Memory pool initialization failed: {e}")
                self._memory_pool = None
        else:
            self._memory_pool = None
        
        # Use provided cache manager or create new one
        if enable_caching:
            if cache_manager:
                self._cache_manager = cache_manager
            elif CACHE_AVAILABLE:
                try:
                    self._cache_manager = CacheManager(
                        enable_memory_cache=True,
                        enable_redis_cache=False  # Can be enabled via config
                    )
                    self.logger.info("Cache manager enabled")
                except Exception as e:
                    self.logger.warning(f"Cache manager initialization failed: {e}")
                    self._cache_manager = None
            else:
                self._cache_manager = None
        else:
            self._cache_manager = None
        
        if enable_profiling and PROFILER_AVAILABLE:
            try:
                self._profiler = PerformanceProfiler()
                self._fps_monitor = FrameRateMonitor()
                self.logger.info("Performance profiling enabled")
            except Exception as e:
                self.logger.warning(f"Profiler initialization failed: {e}")
                self._profiler = None
                self._fps_monitor = None
        else:
            self._profiler = None
            self._fps_monitor = None
        
        # Try to use CoreML on Apple Silicon (MPS device) - BEST SOLUTION for macOS!
        # Also try on CPU for macOS (CoreML works on CPU too, just slower)
        import platform
        is_macos = platform.system() == "Darwin"
        
        if (device == "mps" or (device == "cpu" and is_macos)) and COREML_OPTIMIZATION_AVAILABLE:
            # Check multiple possible CoreML paths
            model_path_obj = Path(model_path)
            possible_paths = [
                str(model_path_obj.with_suffix('.mlpackage')),  # Same name, .mlpackage extension
                str(model_path_obj.parent / f"{model_path_obj.stem}.mlpackage"),
                f"services/ai-perception/models/{model_path_obj.stem}.mlpackage",
                f"models/{model_path_obj.stem}.mlpackage",
                str(model_path_obj),  # Already .mlpackage
            ]
            
            for path in possible_paths:
                path_obj = Path(path)
                if path_obj.exists() and (path_obj.suffix == '.mlpackage' or path_obj.is_dir()):
                    self.use_coreml = True
                    self.logger.info(f"✅ CoreML optimization available: {path} (3-5× faster!)")
                    break
        
        # Update logger with final use_coreml value (re-bind with updated use_coreml)
        if hasattr(self, 'logger'):
            self.logger = logger.bind(
                model_path=model_path,
                device=device,
                use_coreml=self.use_coreml
            )
    
    def _default_class_names(self) -> dict:
        """Default COCO class names for traffic"""
        return {
            0: "pedestrian",
            1: "bicycle",
            2: "car",
            3: "motorcycle",
            5: "bus",
            7: "truck",
            9: "traffic_light",
            11: "stop_sign"
        }
    
    def load_model(self) -> bool:
        """
        Load YOLOv8 model
        
        Returns:
            bool: True if loaded successfully
        """
        if not YOLO_AVAILABLE:
            if not MOCK_DETECTIONS_ALLOWED:
                raise RuntimeError(
                    "ultralytics (YOLOv8) is not installed and mock detections are "
                    "not enabled. Install the model dependencies, or set "
                    "ATMS_ALLOW_MOCK_DETECTIONS=1 ONLY for test environments — "
                    "mock mode fabricates detections every frame."
                )
            self.logger.warning(
                "YOLO not available — MOCK MODE ENABLED via ATMS_ALLOW_MOCK_DETECTIONS. "
                "All detections from this process are SYNTHETIC."
            )
            self.is_loaded = True
            return True
        
        try:
            # Try CoreML first if available and on Apple Silicon (BEST SOLUTION for macOS!)
            if self.use_coreml:
                try:
                    # Try multiple possible CoreML paths
                    model_path_obj = Path(self.model_path)
                    possible_paths = [
                        str(model_path_obj.with_suffix('.mlpackage')),  # Same directory
                        str(model_path_obj.parent / f"{model_path_obj.stem}.mlpackage"),  # Explicit
                        f"services/ai-perception/models/{model_path_obj.stem}.mlpackage",  # Models directory
                        f"models/{model_path_obj.stem}.mlpackage",  # Relative models
                    ]
                    
                    coreml_path = None
                    for path in possible_paths:
                        if Path(path).exists():
                            coreml_path = path
                            break
                    
                    if coreml_path:
                        # YOLOv8 has native CoreML support - use it directly!
                        # This is much better than our custom wrapper
                        self.logger.info(f"🚀 Loading CoreML model: {coreml_path} (3-5× faster on Apple Silicon)")
                        self.model = YOLO(coreml_path)  # YOLOv8 handles CoreML natively!
                        self.use_coreml = True
                        # CRITICAL: CoreML models have FIXED input sizes (usually 640x640)
                        # Must use 640x640 for CoreML, cannot use 416x416
                        self.input_size = (640, 640)
                        self.logger.info(f"✅ CoreML model loaded! Using fixed input size: {self.input_size} (CoreML requirement)")
                        self.is_loaded = True
                        return True
                    else:
                        self.logger.debug(f"CoreML model not found at any of: {possible_paths}, using PyTorch")
                except Exception as e:
                    self.logger.warning(f"CoreML loading error: {e}, falling back to PyTorch")
            
            # Also try CoreML if model_path is already .mlpackage (direct CoreML file)
            import platform
            if platform.system() == "Darwin":  # macOS
                try:
                    model_path_obj = Path(self.model_path)
                    # Check if model_path is already .mlpackage file or directory
                    if (model_path_obj.suffix == '.mlpackage' or 
                        (model_path_obj.is_dir() and (model_path_obj / "Manifest.json").exists())):
                        self.logger.info(f"🚀 Detected .mlpackage model, using CoreML: {self.model_path}")
                        self.model = YOLO(str(self.model_path))
                        self.use_coreml = True
                        # CRITICAL: CoreML models have FIXED input sizes (usually 640x640)
                        # Must use 640x640 for CoreML, cannot use 416x416
                        self.input_size = (640, 640)
                        self.logger.info(f"✅ CoreML model loaded! Using fixed input size: {self.input_size} (CoreML requirement)")
                        self.is_loaded = True
                        return True
                except Exception as e:
                    self.logger.debug(f"Direct CoreML load failed: {e}, trying PyTorch")
            
            # Fallback to standard YOLO (PyTorch)
            self.logger.info("Loading YOLOv8 model...", model_path=self.model_path)
            
            # Load model
            self.model = YOLO(self.model_path)
            
            # For PyTorch models, we can use optimized input size (416x416 for speed)
            # Only if it was the default 640x640 and we're not using CoreML
            if not self.use_coreml and self._requested_input_size == (640, 640):
                self.input_size = (416, 416)  # Optimize for PyTorch
                self.logger.info(f"Using optimized input size: {self.input_size} (PyTorch allows dynamic sizing)")
            
            # Set device
            if self.device == "cuda" and torch.cuda.is_available():
                self.model.to(self.device)
                
                # Enable half precision if requested
                if self.half_precision:
                    self.model.half()
                    self.logger.info("FP16 (half precision) enabled")
            elif self.device == "mps" and hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                self.model.to("mps")
                self.logger.info("MPS (Apple Silicon) acceleration enabled")
            else:
                if self.device == "cuda":
                    self.logger.warning("CUDA requested but not available, using CPU")
                elif self.device == "mps":
                    self.logger.warning("MPS requested but not available, using CPU")
                self.device = "cpu"
                self.model.to("cpu")
            
            self.is_loaded = True
            
            # Get model info
            if hasattr(self.model, 'names'):
                num_classes = len(self.model.names)
                self.logger.info(
                    "Model loaded successfully",
                    device=self.device,
                    num_classes=num_classes,
                    half_precision=self.half_precision
                )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load model: {e}", exc_info=True)
            self.is_loaded = False
            return False
    
    async def detect(
        self,
        image: np.ndarray,
        frame_id: str,
        sensor_id: str
    ) -> Tuple[List[Detection], PerformanceMetrics]:
        """
        Detect objects in image
        
        Args:
            image: Input image (BGR format)
            frame_id: Frame identifier
            sensor_id: Sensor identifier
            
        Returns:
            Tuple of (detections list, performance metrics)
        """
        # Week 11: Check cache first
        if self._cache_manager:
            cached = self._cache_manager.get_cached_detections(frame_id, sensor_id)
            if cached is not None:
                self.logger.debug("Using cached detections", frame_id=frame_id)
                # Return cached with metrics
                metrics = PerformanceMetrics(
                    model_name="YOLOv8-Cached",
                    inference_time_ms=0.1,  # Cache hit is very fast
                    preprocessing_time_ms=0,
                    postprocessing_time_ms=0,
                    total_time_ms=0.1,
                    fps=10000.0,  # Very high FPS for cache hits
                    num_detections=len(cached),
                    avg_confidence=np.mean([d.confidence for d in cached]) if cached else 0.0
                )
                return cached, metrics
        
        if not self.is_loaded:
            self.logger.warning("Model not loaded, attempting to load...")
            if not self.load_model():
                return [], self._empty_metrics()
        
        # Mock mode — reachable only with the explicit test-time opt-in.
        if not YOLO_AVAILABLE or self.model is None:
            if not MOCK_DETECTIONS_ALLOWED:
                raise RuntimeError(
                    "Detector has no loaded model and mock detections are not "
                    "enabled (ATMS_ALLOW_MOCK_DETECTIONS)."
                )
            return self._mock_detections(frame_id, sensor_id), self._mock_metrics()
        
        # Week 11: Start profiling
        profiler_context = None
        if self._profiler:
            profiler_context = self._profiler.profile_function("detect")
            profiler_context.__enter__()
        
        start_time = time.time()
        preprocessing_time = 0
        inference_time = 0
        postprocessing_time = 0
        
        try:
            # Preprocessing
            prep_start = time.time()
            # YOLOv8 handles preprocessing internally, but we track timing
            preprocessing_time = (time.time() - prep_start) * 1000
            
            # Inference
            inf_start = time.time()
            
            # Run inference in thread pool (YOLOv8 handles CoreML natively if use_coreml=True)
            # CoreML models loaded via YOLO() work exactly like PyTorch models
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                self._run_inference,
                image
            )
            
            inference_time = (time.time() - inf_start) * 1000
            
            # Postprocessing
            post_start = time.time()
            detections = self._parse_results(results, frame_id, sensor_id)
            postprocessing_time = (time.time() - post_start) * 1000
            
            total_time = (time.time() - start_time) * 1000
            
            # Update statistics
            self.inference_count += 1
            self.total_inference_time += total_time
            
            # Week 11: Record FPS
            if self._fps_monitor:
                self._fps_monitor.record_frame(total_time / 1000.0)
            
            # Week 11: End profiling
            if profiler_context:
                profiler_context.__exit__(None, None, None)
            
            # Create performance metrics
            metrics = PerformanceMetrics(
                model_name="YOLOv8",
                inference_time_ms=inference_time,
                preprocessing_time_ms=preprocessing_time,
                postprocessing_time_ms=postprocessing_time,
                total_time_ms=total_time,
                fps=1000.0 / total_time if total_time > 0 else 0,
                num_detections=len(detections),
                avg_confidence=np.mean([d.confidence for d in detections]) if detections else 0.0
            )
            
            # Week 11: Cache results
            if self._cache_manager:
                self._cache_manager.cache_detections(frame_id, sensor_id, detections)
            
            self.logger.debug(
                "Detection complete",
                frame_id=frame_id,
                num_detections=len(detections),
                total_time_ms=round(total_time, 2),
                fps=round(metrics.fps, 2)
            )
            
            return detections, metrics
            
        except Exception as e:
            self.logger.error(f"Detection error: {e}", exc_info=True)
            # Week 11: End profiling on error
            if profiler_context:
                profiler_context.__exit__(None, None, None)
            return [], self._empty_metrics()
    
    def _run_inference(self, image: np.ndarray):
        """Run YOLO inference (blocking, called in thread pool) - OPTIMIZED for performance"""
        # CRITICAL: For CoreML, don't pass imgsz - let CoreML use its fixed size
        # For PyTorch, we can specify imgsz for optimization
        inference_kwargs = {
            'conf': self.confidence_threshold,
            'iou': self.iou_threshold,
            'classes': self.detect_classes,
            'verbose': False,
            'agnostic_nms': False,  # Class-aware NMS (faster)
            'max_det': 50,  # Limit max detections (faster post-processing)
            'retina_masks': False,  # Disable retina masks (not needed for detection)
            'stream': False  # Single frame mode (faster than stream mode)
        }
        
        # Only specify imgsz for PyTorch models (CoreML has fixed size)
        if not self.use_coreml:
            inference_kwargs['imgsz'] = self.input_size
            inference_kwargs['half'] = self.half_precision  # FP16 only for PyTorch
        
        results = self.model(image, **inference_kwargs)
        return results
    
    def _run_coreml_inference(self, image: np.ndarray):
        """Run CoreML inference (blocking, called in thread pool) - 3-5× faster on Apple Silicon"""
        # YOLOv8 handles CoreML natively, so we can use the same inference method
        # The model object is already a CoreML model if use_coreml is True
        return self._run_inference(image)
    
    def _parse_results(
        self,
        results,
        frame_id: str,
        sensor_id: str
    ) -> List[Detection]:
        """
        Parse YOLO results into Detection objects
        
        Args:
            results: YOLO results
            frame_id: Frame identifier
            sensor_id: Sensor identifier
            
        Returns:
            List of Detection objects
        """
        detections = []
        
        try:
            # YOLOv8 returns a list of Results objects
            for result in results:
                boxes = result.boxes
                
                if boxes is not None:
                    self.logger.debug(f"YOLOv8 found {len(boxes)} raw detections before filtering")
                else:
                    self.logger.debug("YOLOv8 found NO detections (boxes is None)")
                
                if boxes is None or len(boxes) == 0:
                    continue
                
                # Get box data
                xyxy = boxes.xyxy.cpu().numpy()  # Bounding boxes
                confs = boxes.conf.cpu().numpy()  # Confidences
                clss = boxes.cls.cpu().numpy()  # Classes
                
                for i in range(len(boxes)):
                    # Get box coordinates
                    x1, y1, x2, y2 = xyxy[i]
                    confidence = float(confs[i])
                    class_id = int(clss[i])
                    
                    self.logger.debug(f"Detection {i}: class_id={class_id}, confidence={confidence:.2f}, bbox=[{x1:.1f}, {y1:.1f}, {x2:.1f}, {y2:.1f}]")

                    # Map class to our ObjectClass enum
                    object_class = self._map_class(class_id)
                    
                    # Create BoundingBox
                    bbox = BoundingBox(
                        x1=float(x1),
                        y1=float(y1),
                        x2=float(x2),
                        y2=float(y2),
                        confidence=confidence
                    )
                    
                    # Create Detection
                    from datetime import datetime
                    detection = Detection(
                        detection_id=f"{frame_id}_{i}",
                        object_class=object_class,
                        bbox=bbox,
                        confidence=confidence,
                        timestamp=datetime.utcnow(),
                        frame_id=frame_id,
                        sensor_id=sensor_id
                    )
                    
                    detections.append(detection)
            
        except Exception as e:
            self.logger.error(f"Error parsing results: {e}", exc_info=True)
        
        return detections
    
    def _map_class(self, class_id: int) -> ObjectClass:
        """Map COCO class ID to ObjectClass enum"""
        class_name = self.class_names.get(class_id, "unknown")
        
        # Map to ObjectClass enum
        mapping = {
            "pedestrian": ObjectClass.PEDESTRIAN,
            "bicycle": ObjectClass.BICYCLE,
            "car": ObjectClass.CAR,
            "motorcycle": ObjectClass.MOTORCYCLE,
            "bus": ObjectClass.BUS,
            "truck": ObjectClass.TRUCK,
            "traffic_light": ObjectClass.TRAFFIC_LIGHT,
            "stop_sign": ObjectClass.TRAFFIC_SIGN,
        }
        
        return mapping.get(class_name, ObjectClass.UNKNOWN)
    
    def _empty_metrics(self) -> PerformanceMetrics:
        """Return empty performance metrics"""
        return PerformanceMetrics(
            model_name="YOLOv8",
            inference_time_ms=0,
            preprocessing_time_ms=0,
            postprocessing_time_ms=0,
            total_time_ms=0,
            fps=0,
            num_detections=0,
            avg_confidence=0
        )
    
    def _mock_metrics(self) -> PerformanceMetrics:
        """Return mock performance metrics"""
        return PerformanceMetrics(
            model_name="YOLOv8-Mock",
            inference_time_ms=10.0,
            preprocessing_time_ms=2.0,
            postprocessing_time_ms=3.0,
            total_time_ms=15.0,
            fps=66.7,
            num_detections=2,
            avg_confidence=0.85
        )
    
    def _mock_detections(self, frame_id: str, sensor_id: str) -> List[Detection]:
        """Generate mock detections for testing"""
        from datetime import datetime
        
        return [
            Detection(
                detection_id=f"{frame_id}_mock_1",
                object_class=ObjectClass.CAR,
                bbox=BoundingBox(x1=100, y1=100, x2=200, y2=200, confidence=0.9),
                confidence=0.9,
                timestamp=datetime.utcnow(),
                frame_id=frame_id,
                sensor_id=sensor_id
            ),
            Detection(
                detection_id=f"{frame_id}_mock_2",
                object_class=ObjectClass.PEDESTRIAN,
                bbox=BoundingBox(x1=300, y1=150, x2=350, y2=300, confidence=0.85),
                confidence=0.85,
                timestamp=datetime.utcnow(),
                frame_id=frame_id,
                sensor_id=sensor_id
            )
        ]
    
    async def detect_batch(
        self,
        images: List[np.ndarray],
        frame_ids: List[str],
        sensor_ids: List[str]
    ) -> List[Tuple[List[Detection], PerformanceMetrics]]:
        """
        Detect objects in batch of images
        
        Args:
            images: List of input images
            frame_ids: List of frame identifiers
            sensor_ids: List of sensor identifiers
            
        Returns:
            List of (detections, metrics) tuples
        """
        results = []
        
        for image, frame_id, sensor_id in zip(images, frame_ids, sensor_ids):
            detections, metrics = await self.detect(image, frame_id, sensor_id)
            results.append((detections, metrics))
        
        return results
    
    def get_stats(self) -> dict:
        """Get detector statistics"""
        avg_time = (
            self.total_inference_time / self.inference_count
            if self.inference_count > 0
            else 0
        )
        
        stats = {
            "is_loaded": self.is_loaded,
            "device": self.device,
            "model_path": self.model_path,
            "inference_count": self.inference_count,
            "avg_inference_time_ms": round(avg_time, 2),
            "avg_fps": round(1000.0 / avg_time, 2) if avg_time > 0 else 0,
            "half_precision": self.half_precision,
            "use_coreml": self.use_coreml,
            "coreml_available": COREML_OPTIMIZATION_AVAILABLE
        }
        
        # Week 11: Add optimization stats
        if self._memory_pool:
            stats["memory_pool"] = self._memory_pool.get_stats()
        
        if self._cache_manager:
            stats["cache"] = self._cache_manager.get_stats()
        
        if self._fps_monitor:
            stats["fps_monitor"] = self._fps_monitor.get_stats()
        
        if self._profiler:
            stats["profiler"] = self._profiler.get_stats()
        
        return stats
    
    def unload(self):
        """Unload model from memory"""
        if self.model is not None:
            del self.model
            self.model = None
            
            # Clear CUDA cache if using GPU
            if self.device == "cuda" and torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            self.is_loaded = False
            self.logger.info("Model unloaded")

