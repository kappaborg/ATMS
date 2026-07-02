"""
Test Configuration and Fixtures
Week 1: Sensor Fusion Service Tests
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
import numpy as np
import cv2
from datetime import datetime

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from shared.models.base import CameraFrame


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_camera_frame():
    """Create a mock camera frame"""
    # Create a test frame (100x100 blue image)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[:, :] = (255, 0, 0)  # Blue
    
    # Encode to JPEG
    _, buffer = cv2.imencode('.jpg', frame)
    frame_bytes = buffer.tobytes()
    
    return CameraFrame(
        frame_id="test_frame_1",
        sensor_id="camera_1",
        timestamp=datetime.utcnow(),
        width=100,
        height=100,
        format="JPEG",
        fps=30.0,
        frame_data=frame_bytes
    )


@pytest.fixture
def mock_rtsp_url():
    """Mock RTSP URL"""
    return "rtsp://localhost:8554/test"


@pytest.fixture
def camera_config():
    """Camera configuration for tests"""
    return {
        "camera_id": "test_camera",
        "rtsp_url": "rtsp://localhost:8554/test",
        "resolution": (640, 480),
        "fps": 30,
        "buffer_size": 10,
        "reconnect_delay": 1,
        "max_reconnect_attempts": 2
    }


@pytest.fixture
def kafka_config():
    """Kafka configuration for tests"""
    return {
        "bootstrap_servers": "localhost:9092",
        "client_id": "test-sensor-fusion",
        "compression_type": "gzip"
    }

