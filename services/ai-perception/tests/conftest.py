"""
AI Perception Service - Pytest Configuration
Shared fixtures and test utilities
"""
import pytest
import sys
import os
from pathlib import Path
import numpy as np
import cv2
from typing import Dict, Any
from unittest.mock import MagicMock, AsyncMock

# Add src and shared to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from shared.models.base import CameraFrame, SensorDataMessage
from shared.models.detection import Detection, BoundingBox, ObjectClass


@pytest.fixture
def sample_image():
    """Generate a sample test image (640x640 RGB)"""
    # Create a simple test image with some shapes
    img = np.zeros((640, 640, 3), dtype=np.uint8)
    
    # Add some colored rectangles to simulate objects
    cv2.rectangle(img, (100, 100), (200, 200), (255, 0, 0), -1)  # Blue car
    cv2.rectangle(img, (300, 300), (400, 500), (0, 255, 0), -1)  # Green truck
    cv2.circle(img, (500, 150), 30, (0, 0, 255), -1)  # Red circle (person)
    
    return img


@pytest.fixture
def sample_image_path(tmp_path, sample_image):
    """Save sample image to temporary file"""
    img_path = tmp_path / "test_frame.jpg"
    cv2.imwrite(str(img_path), sample_image)
    return str(img_path)


@pytest.fixture
def sample_camera_frame(sample_image):
    """Generate a sample CameraFrame object"""
    # Convert image to bytes
    _, buffer = cv2.imencode('.jpg', sample_image)
    frame_bytes = buffer.tobytes()
    
    return CameraFrame(
        sensor_id="camera_1",
        frame_id="frame_001",
        timestamp=1696248000.0,
        width=640,
        height=640,
        format="BGR",
        fps=30,
        frame_data=frame_bytes
    )


@pytest.fixture
def sample_detection():
    """Generate a sample Detection object"""
    return Detection(
        object_id=1,
        object_class=ObjectClass.CAR,
        bounding_box=BoundingBox(
            x_min=100.0,
            y_min=100.0,
            x_max=200.0,
            y_max=200.0,
            confidence=0.95
        )
    )


@pytest.fixture
def sample_detections():
    """Generate multiple sample detections"""
    return [
        Detection(
            object_id=1,
            object_class=ObjectClass.CAR,
            bounding_box=BoundingBox(
                x_min=100.0, y_min=100.0,
                x_max=200.0, y_max=200.0,
                confidence=0.95
            )
        ),
        Detection(
            object_id=2,
            object_class=ObjectClass.TRUCK,
            bounding_box=BoundingBox(
                x_min=300.0, y_min=300.0,
                x_max=400.0, y_max=500.0,
                confidence=0.88
            )
        ),
        Detection(
            object_id=3,
            object_class=ObjectClass.PEDESTRIAN,
            bounding_box=BoundingBox(
                x_min=470.0, y_min=120.0,
                x_max=530.0, y_max=180.0,
                confidence=0.92
            )
        )
    ]


@pytest.fixture
def mock_yolo_model():
    """Mock YOLO model for testing"""
    mock_model = MagicMock()
    
    # Mock prediction results
    mock_result = MagicMock()
    mock_result.boxes = MagicMock()
    
    # Mock boxes data (xyxy, conf, cls)
    mock_result.boxes.xyxy = np.array([
        [100.0, 100.0, 200.0, 200.0],
        [300.0, 300.0, 400.0, 500.0],
        [470.0, 120.0, 530.0, 180.0]
    ])
    mock_result.boxes.conf = np.array([0.95, 0.88, 0.92])
    mock_result.boxes.cls = np.array([2, 7, 0])  # car, truck, person in COCO
    
    mock_model.return_value = [mock_result]
    
    return mock_model


@pytest.fixture
def mock_kafka_producer():
    """Mock Kafka producer for testing"""
    producer = AsyncMock()
    producer.is_connected = True
    producer.send_message = AsyncMock(return_value=True)
    return producer


@pytest.fixture
def mock_kafka_consumer():
    """Mock Kafka consumer for testing"""
    consumer = AsyncMock()
    consumer.is_connected = True
    consumer.consume_messages = AsyncMock()
    return consumer


@pytest.fixture
def perception_config():
    """Get AI Perception configuration"""
    from config import PerceptionConfig
    return PerceptionConfig()


@pytest.fixture
def yolo_detector_config():
    """Configuration for YOLO detector tests"""
    return {
        "model_name": "yolov8n",
        "confidence_threshold": 0.5,
        "iou_threshold": 0.45,
        "max_detections": 100,
        "device": "cpu",  # Use CPU for tests
        "half_precision": False
    }


@pytest.fixture
def frame_processor_config():
    """Configuration for frame processor tests"""
    return {
        "target_size": (640, 640),
        "normalize": True,
        "resize_method": "letterbox"
    }


@pytest.fixture(autouse=True)
def reset_prometheus_registry():
    """Reset Prometheus registry before each test to avoid duplicates"""
    from prometheus_client import REGISTRY
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass
    yield


# Async test support
@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


