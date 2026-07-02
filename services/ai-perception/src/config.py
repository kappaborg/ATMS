"""
AI Perception Service - Configuration
Week 2 Implementation
"""
import sys
import os
import time
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Dict, Optional, Tuple

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))
from shared.utils.config import BaseConfig


class ModelConfig(BaseSettings):
    """YOLOv8 Model Configuration"""
    
    # Model selection
    MODEL_NAME: str = "yolov8n"  # n (nano), s (small), m (medium), l (large), x (extra large)
    MODEL_PATH: str = "models/yolov8n.pt"
    MODEL_VERSION: str = "8.0"
    
    # Model optimization
    USE_ONNX: bool = False
    ONNX_PATH: str = "models/yolov8n.onnx"
    USE_TENSORRT: bool = False
    
    # Week 11: Model Quantization
    USE_QUANTIZED_MODEL: bool = False  # Enable quantized model if available
    QUANTIZATION_TYPE: str = "fp16"  # "int8", "fp16", "coreml"
    QUANTIZED_MODEL_PATH: Optional[str] = None  # Auto-detected if None
    
    # Device configuration
    DEVICE: str = "cpu"  # cuda, cpu, mps (for Apple Silicon)
    GPU_ID: int = 0
    HALF_PRECISION: bool = False  # FP16 for faster inference on GPU (disable on CPU)
    
    # Detection parameters
    CONFIDENCE_THRESHOLD: float = 0.15  # Lowered to catch more detections
    IOU_THRESHOLD: float = 0.45  # NMS threshold
    MAX_DETECTIONS: int = 300
    
    # Input size
    INPUT_SIZE: Tuple[int, int] = (640, 640)  # (width, height)
    
    # Object classes to detect (COCO classes)
    # Temporarily set to empty list [] to detect ALL classes for debugging
    DETECT_CLASSES: Optional[List[int]] = None  # None = detect all 80 COCO classes
    # Original: [0, 1, 2, 3, 5, 7]  # person, bicycle, car, motorcycle, bus, truck
    
    # Class mapping (COCO dataset class IDs)
    # Full COCO mapping: https://github.com/ultralytics/ultralytics/blob/main/ultralytics/cfg/datasets/coco.yaml
    CLASS_NAMES: Dict[int, str] = {
        0: "pedestrian",      # COCO: person
        1: "bicycle",         # COCO: bicycle
        2: "car",             # COCO: car
        3: "motorcycle",      # COCO: motorcycle
        5: "bus",             # COCO: bus
        7: "truck",           # COCO: truck
        9: "traffic_light",   # COCO: traffic light
        11: "stop_sign",      # COCO: stop sign
        # Add more COCO classes if needed
    }
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MODEL_",
        case_sensitive=True,
        extra="ignore"  # Ignore extra environment variables
    )


class PerceptionConfig(BaseConfig):
    """AI Perception Service Configuration"""
    
    # Service specific
    SERVICE_NAME: str = "ai-perception"
    SERVICE_VERSION: str = "1.0.0"
    API_PORT: int = 8014  # Default 8014, can override with API_PORT env var
    
    # Kafka Topics
    KAFKA_TOPIC_CAMERA_FRAMES: str = "camera-frames"
    KAFKA_TOPIC_DETECTIONS: str = "detections"
    KAFKA_TOPIC_TRAFFIC_METRICS: str = "traffic-metrics"
    KAFKA_TOPIC_EMISSION_DATA: str = "emission-data"
    KAFKA_TOPIC_LICENSE_PLATES: str = "license-plates"
    KAFKA_TOPIC_TRAJECTORY_DATA: str = "trajectory-data"
    KAFKA_TOPIC_TRAJECTORY_ANOMALIES: str = "trajectory-anomalies"
    KAFKA_GROUP_ID: str = "ai-perception-group"  # Fixed group ID (was changing each time, causing offset issues)
    
    # Processing
    BATCH_SIZE: int = 4
    BATCH_TIMEOUT_MS: int = 100
    PROCESSING_THREADS: int = 2
    
    # Frame preprocessing
    ENABLE_PREPROCESSING: bool = True
    NORMALIZE: bool = True
    RESIZE_METHOD: str = "letterbox"  # letterbox, resize, crop
    
    # Performance
    ENABLE_GPU: bool = True
    ASYNC_INFERENCE: bool = True
    MAX_QUEUE_SIZE: int = 100
    
    # Week 11: Optimization settings
    ENABLE_MEMORY_POOL: bool = True
    ENABLE_CACHING: bool = True
    ENABLE_PROFILING: bool = False  # Enable for debugging/benchmarking
    ENABLE_REDIS_CACHE: bool = False
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    MEMORY_CACHE_SIZE: int = 1000
    MEMORY_CACHE_TTL: float = 300.0  # 5 minutes
    
    # Monitoring
    COLLECT_METRICS: bool = True
    METRICS_INTERVAL: int = 10  # seconds
    LOG_DETECTIONS: bool = True  # Set to True for debugging
    
    # Visualization (for debugging)
    SAVE_DEBUG_FRAMES: bool = False
    DEBUG_OUTPUT_DIR: str = "debug_output"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"  # Ignore extra environment variables
    )


# Initialize configurations
# Allow API_PORT to be overridden by environment variable
perception_config = PerceptionConfig()
if os.environ.get("API_PORT"):
    perception_config.API_PORT = int(os.environ.get("API_PORT"))
model_config = ModelConfig()

