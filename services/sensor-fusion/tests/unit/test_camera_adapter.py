"""
Unit Tests for Camera Adapter
Week 1: Sensor Fusion Service
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
import numpy as np
import cv2

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent.parent.parent))

from services.sensor_fusion.src.adapters.camera import CameraAdapter


class TestCameraAdapter:
    """Test cases for CameraAdapter"""
    
    @pytest.mark.asyncio
    async def test_camera_initialization(self, camera_config):
        """Test camera adapter initialization"""
        camera = CameraAdapter(**camera_config)
        
        assert camera.camera_id == camera_config["camera_id"]
        assert camera.rtsp_url == camera_config["rtsp_url"]
        assert camera.resolution == camera_config["resolution"]
        assert not camera.is_connected
        assert camera.frame_count == 0
    
    @pytest.mark.asyncio
    async def test_frame_validation_valid(self):
        """Test frame validation with valid frame"""
        camera = CameraAdapter("test", "rtsp://test", (640, 480))
        
        # Create valid frame
        frame = np.random.randint(50, 200, (480, 640, 3), dtype=np.uint8)
        
        assert camera._validate_frame(frame) is True
    
    @pytest.mark.asyncio
    async def test_frame_validation_too_dark(self):
        """Test frame validation with too dark frame"""
        camera = CameraAdapter("test", "rtsp://test", (640, 480))
        
        # Create dark frame
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        assert camera._validate_frame(frame) is False
    
    @pytest.mark.asyncio
    async def test_frame_validation_too_bright(self):
        """Test frame validation with too bright frame"""
        camera = CameraAdapter("test", "rtsp://test", (640, 480))
        
        # Create bright frame
        frame = np.ones((480, 640, 3), dtype=np.uint8) * 255
        
        assert camera._validate_frame(frame) is False
    
    @pytest.mark.asyncio
    async def test_frame_validation_no_variance(self):
        """Test frame validation with no variance (blank frame)"""
        camera = CameraAdapter("test", "rtsp://test", (640, 480))
        
        # Create uniform frame
        frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
        
        assert camera._validate_frame(frame) is False
    
    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test getting camera statistics"""
        camera = CameraAdapter("test", "rtsp://test", (640, 480), fps=30)
        
        stats = await camera.get_stats()
        
        assert stats["camera_id"] == "test"
        assert stats["is_connected"] is False
        assert stats["frame_count"] == 0
        assert stats["resolution"] == "640x480"
        assert stats["target_fps"] == 30

