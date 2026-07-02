"""
Unit Tests for Frame Synchronizer
Week 1: Sensor Fusion Service
"""
import pytest
from datetime import datetime, timedelta
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent.parent.parent))

from services.sensor_fusion.src.sync.synchronizer import FrameSynchronizer
from shared.models.base import CameraFrame


class TestFrameSynchronizer:
    """Test cases for FrameSynchronizer"""
    
    def test_synchronizer_initialization(self):
        """Test synchronizer initialization"""
        camera_ids = ["camera_1", "camera_2", "camera_3"]
        sync = FrameSynchronizer(camera_ids, sync_threshold_ms=100)
        
        assert len(sync.buffers) == 3
        assert sync.sync_count == 0
        assert all(cam_id in sync.buffers for cam_id in camera_ids)
    
    def test_add_frame(self, mock_camera_frame):
        """Test adding frame to buffer"""
        sync = FrameSynchronizer(["camera_1"])
        
        sync.add_frame("camera_1", mock_camera_frame)
        
        assert len(sync.buffers["camera_1"]) == 1
    
    def test_synchronized_frames_perfect_sync(self):
        """Test synchronization with perfectly synchronized frames"""
        sync = FrameSynchronizer(["camera_1", "camera_2"])
        
        # Create frames with same timestamp
        timestamp = datetime.utcnow()
        frame1 = CameraFrame(
            frame_id="f1",
            sensor_id="camera_1",
            timestamp=timestamp,
            width=100,
            height=100,
            format="JPEG",
            fps=30.0,
            frame_data=b"test"
        )
        frame2 = CameraFrame(
            frame_id="f2",
            sensor_id="camera_2",
            timestamp=timestamp,
            width=100,
            height=100,
            format="JPEG",
            fps=30.0,
            frame_data=b"test"
        )
        
        sync.add_frame("camera_1", frame1)
        sync.add_frame("camera_2", frame2)
        
        synced = sync.get_synchronized_frames()
        
        assert synced is not None
        assert len(synced) == 2
        assert "camera_1" in synced
        assert "camera_2" in synced
        assert sync.sync_count == 1
    
    def test_synchronized_frames_within_threshold(self):
        """Test synchronization with frames within threshold"""
        sync = FrameSynchronizer(["camera_1", "camera_2"], sync_threshold_ms=100)
        
        # Create frames with 50ms difference
        timestamp1 = datetime.utcnow()
        timestamp2 = timestamp1 + timedelta(milliseconds=50)
        
        frame1 = CameraFrame(
            frame_id="f1",
            sensor_id="camera_1",
            timestamp=timestamp1,
            width=100,
            height=100,
            format="JPEG",
            fps=30.0,
            frame_data=b"test"
        )
        frame2 = CameraFrame(
            frame_id="f2",
            sensor_id="camera_2",
            timestamp=timestamp2,
            width=100,
            height=100,
            format="JPEG",
            fps=30.0,
            frame_data=b"test"
        )
        
        sync.add_frame("camera_1", frame1)
        sync.add_frame("camera_2", frame2)
        
        synced = sync.get_synchronized_frames()
        
        assert synced is not None
        assert len(synced) == 2
    
    def test_synchronized_frames_outside_threshold(self):
        """Test synchronization with frames outside threshold"""
        sync = FrameSynchronizer(["camera_1", "camera_2"], sync_threshold_ms=100)
        
        # Create frames with 200ms difference
        timestamp1 = datetime.utcnow()
        timestamp2 = timestamp1 + timedelta(milliseconds=200)
        
        frame1 = CameraFrame(
            frame_id="f1",
            sensor_id="camera_1",
            timestamp=timestamp1,
            width=100,
            height=100,
            format="JPEG",
            fps=30.0,
            frame_data=b"test"
        )
        frame2 = CameraFrame(
            frame_id="f2",
            sensor_id="camera_2",
            timestamp=timestamp2,
            width=100,
            height=100,
            format="JPEG",
            fps=30.0,
            frame_data=b"test"
        )
        
        sync.add_frame("camera_1", frame1)
        sync.add_frame("camera_2", frame2)
        
        synced = sync.get_synchronized_frames()
        
        # Should not synchronize due to large time difference
        assert synced is None
    
    def test_buffer_status(self):
        """Test getting buffer status"""
        sync = FrameSynchronizer(["camera_1", "camera_2"])
        
        frame1 = CameraFrame(
            frame_id="f1",
            sensor_id="camera_1",
            timestamp=datetime.utcnow(),
            width=100,
            height=100,
            format="JPEG",
            fps=30.0,
            frame_data=b"test"
        )
        
        sync.add_frame("camera_1", frame1)
        
        status = sync.get_buffer_status()
        
        assert status["camera_1"] == 1
        assert status["camera_2"] == 0
    
    def test_get_stats(self):
        """Test getting synchronizer statistics"""
        sync = FrameSynchronizer(["camera_1", "camera_2"])
        
        stats = sync.get_stats()
        
        assert stats["sync_count"] == 0
        assert stats["camera_count"] == 2
        assert "buffer_status" in stats
    
    def test_reset(self):
        """Test resetting synchronizer"""
        sync = FrameSynchronizer(["camera_1"])
        
        frame = CameraFrame(
            frame_id="f1",
            sensor_id="camera_1",
            timestamp=datetime.utcnow(),
            width=100,
            height=100,
            format="JPEG",
            fps=30.0,
            frame_data=b"test"
        )
        
        sync.add_frame("camera_1", frame)
        sync.sync_count = 10
        
        sync.reset()
        
        assert len(sync.buffers["camera_1"]) == 0
        assert sync.sync_count == 0

