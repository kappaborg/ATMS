"""
Sensor Fusion Service - Configuration
Week 1 Implementation
"""
import sys
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Dict, Optional

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))
from shared.utils.config import BaseConfig


class CameraConfig(BaseSettings):
    """Camera configuration"""
    CAMERA_IDS: List[str] = ["camera_iphone"]
    RTSP_URLS: Dict[str, str] = {
        "camera_iphone": "http://192.168.0.14:8081/video",  # iPhone 15 Pro - MJPEG stream
    }
    CAMERA_AUTH: Dict[str, tuple] = {
        # Format: "camera_id": ("username", "password")
        # Leave empty tuple () if no auth required
        "camera_iphone": ("admin", "kappa"),  # HTTP Basic Auth credentials
    }
    CAMERA_ROTATIONS: Dict[str, int] = {
        "camera_iphone": 270,  # Rotate 270 degrees (90 counter-clockwise) to make  upright
    }
    CAMERA_RESOLUTION: tuple = (1920, 1080)
    CAMERA_FPS: int = 30
    FRAME_BUFFER_SIZE: int = 10
    RECONNECT_DELAY: int = 5  # seconds
    MAX_RECONNECT_ATTEMPTS: int = 3
    
    model_config = SettingsConfigDict(

        env_file=".env",
        env_prefix="CAMERA_",
        case_sensitive=True,
        extra="ignore"  # Allow extra fields from .env that we don't use
    )


class SensorFusionConfig(BaseConfig):
    """Sensor Fusion Service Configuration"""
    
    # Service specific
    SERVICE_NAME: str = "sensor-fusion"
    SERVICE_VERSION: str = "1.0.0"
    
    # Kafka Topics
    KAFKA_TOPIC_SENSOR_DATA: str = "sensor-data"
    KAFKA_TOPIC_CAMERA_FRAMES: str = "camera-frames"
    KAFKA_TOPIC_LIDAR_POINTS: str = "lidar-points"
    
    # Performance Settings
    PROCESSING_THREADS: int = 4
    ASYNC_BUFFER_SIZE: int = 100
    BATCH_SIZE: int = 10
    BATCH_TIMEOUT_MS: int = 100
    
    # Camera Settings
    ENABLE_CAMERAS: bool = True
    ENABLE_LIDAR: bool = False  # Week 1: Camera only
    ENABLE_THERMAL: bool = False
    ENABLE_RADAR: bool = False
    
    # Data Quality
    MIN_FRAME_QUALITY: float = 0.8
    ENABLE_FRAME_VALIDATION: bool = True
    
    # Monitoring
    HEALTH_CHECK_INTERVAL: int = 30  # seconds
    METRICS_COLLECTION_INTERVAL: int = 10  # seconds
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )


# Initialize configurations
sensor_fusion_config = SensorFusionConfig()
camera_config = CameraConfig()

