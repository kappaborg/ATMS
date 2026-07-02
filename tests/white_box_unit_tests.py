"""
White Box Unit Tests
Tests internal implementation details and code paths
"""
import unittest
import asyncio
import numpy as np
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "services" / "ai-perception" / "src"))
sys.path.insert(0, str(project_root / "services" / "video-processor" / "src"))

try:
    from detection.yolo_detector import YOLODetector
    from tracking.bytetrack_tracker import ByteTrackWrapper
    from optimization.async_processor import AsyncModelProcessor
    from trajectory_integration import IntegratedATMSSystem
    from pyav_decoder import PyAVDecoder
except ImportError:
    # Fallback to full path (with hyphens in directory names)
    import importlib.util
    import os
    
    # Try direct file imports
    ai_perception_src = project_root / "services" / "ai-perception" / "src"
    video_processor_src = project_root / "services" / "video-processor" / "src"
    
    # Load modules directly
    spec1 = importlib.util.spec_from_file_location("yolo_detector", ai_perception_src / "detection" / "yolo_detector.py")
    yolo_module = importlib.util.module_from_spec(spec1)
    spec1.loader.exec_module(yolo_module)
    YOLODetector = yolo_module.YOLODetector
    
    spec2 = importlib.util.spec_from_file_location("bytetrack_tracker", ai_perception_src / "tracking" / "bytetrack_tracker.py")
    bytetrack_module = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(bytetrack_module)
    ByteTrackWrapper = bytetrack_module.ByteTrackWrapper
    
    spec3 = importlib.util.spec_from_file_location("async_processor", ai_perception_src / "optimization" / "async_processor.py")
    async_module = importlib.util.module_from_spec(spec3)
    spec3.loader.exec_module(async_module)
    AsyncModelProcessor = async_module.AsyncModelProcessor
    
    spec4 = importlib.util.spec_from_file_location("trajectory_integration", ai_perception_src / "trajectory_integration.py")
    atms_module = importlib.util.module_from_spec(spec4)
    spec4.loader.exec_module(atms_module)
    IntegratedATMSSystem = atms_module.IntegratedATMSSystem
    
    spec5 = importlib.util.spec_from_file_location("pyav_decoder", video_processor_src / "pyav_decoder.py")
    pyav_module = importlib.util.module_from_spec(spec5)
    spec5.loader.exec_module(pyav_module)
    PyAVDecoder = pyav_module.PyAVDecoder


class TestYOLODetector(unittest.TestCase):
    """White box tests for YOLOv8 detector"""
    
    def setUp(self):
        self.detector = YOLODetector(
            model_path="yolov8n.pt",
            device="cpu",  # Use CPU for testing
            confidence_threshold=0.25
        )
    
    def test_coreml_initialization(self):
        """Test CoreML initialization logic"""
        # Test CoreML availability check
        self.assertIsNotNone(self.detector.use_coreml)
        self.assertIsInstance(self.detector.use_coreml, bool)
    
    def test_model_loading_path(self):
        """Test model loading path"""
        # Test that load_model returns bool
        result = self.detector.load_model()
        self.assertIsInstance(result, bool)
    
    def test_inference_path(self):
        """Test inference code path"""
        if not self.detector.is_loaded:
            self.detector.load_model()
        
        # Create test frame
        test_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        
        # Test async detect
        async def test():
            detections, metrics = await self.detector.detect(test_frame, "test_frame", "test_sensor")
            self.assertIsInstance(detections, list)
            self.assertIsNotNone(metrics)
        
        asyncio.run(test())
    
    def test_stats_tracking(self):
        """Test internal statistics tracking"""
        self.assertEqual(self.detector.inference_count, 0)
        self.assertEqual(self.detector.total_inference_time, 0.0)
        
        stats = self.detector.get_stats()
        self.assertIn('is_loaded', stats)
        self.assertIn('device', stats)
        self.assertIn('use_coreml', stats)


class TestByteTrackWrapper(unittest.TestCase):
    """White box tests for ByteTrack wrapper"""
    
    def setUp(self):
        self.tracker = ByteTrackWrapper(
            track_thresh=0.5,
            track_buffer=30,
            match_thresh=0.8,
            frame_rate=30
        )
    
    def test_initialization(self):
        """Test ByteTrack initialization"""
        self.assertIsNotNone(self.tracker.is_available)
        self.assertIsInstance(self.tracker.is_available, bool)
    
    def test_update_logic(self):
        """Test update method logic"""
        # Create test detections
        detections = [
            {
                'bbox': {'x1': 100, 'y1': 100, 'x2': 200, 'y2': 200},
                'confidence': 0.8,
                'class_id': 2
            },
            {
                'bbox': {'x1': 300, 'y1': 150, 'x2': 400, 'y2': 250},
                'confidence': 0.7,
                'class_id': 2
            }
        ]
        
        # Test update
        tracked = self.tracker.update(detections)
        self.assertIsInstance(tracked, list)
        self.assertEqual(len(tracked), len(detections))
        
        # Check that track_id is assigned
        for det in tracked:
            self.assertIn('track_id', det)
    
    def test_reset_functionality(self):
        """Test reset method"""
        # Update tracker
        detections = [{'bbox': {'x1': 100, 'y1': 100, 'x2': 200, 'y2': 200}, 'confidence': 0.8, 'class_id': 2}]
        self.tracker.update(detections)
        
        # Reset
        self.tracker.reset()
        
        # Should still work after reset
        tracked = self.tracker.update(detections)
        self.assertIsInstance(tracked, list)


class TestAsyncProcessor(unittest.TestCase):
    """White box tests for async parallel processor"""
    
    def setUp(self):
        self.processor = AsyncModelProcessor()
    
    def test_initialization(self):
        """Test processor initialization"""
        self.assertIsNotNone(self.processor.stats)
        self.assertEqual(self.processor.stats['total_batches'], 0)
    
    def test_parallel_execution(self):
        """Test parallel task execution"""
        async def task1():
            await asyncio.sleep(0.01)
            return 'result1'
        
        async def task2():
            await asyncio.sleep(0.01)
            return 'result2'
        
        async def test():
            results = await self.processor.process_parallel(
                frame=np.zeros((100, 100, 3)),
                tasks=[task1, task2],
                task_names=['task1', 'task2']
            )
            
            self.assertIn('task1', results)
            self.assertIn('task2', results)
            self.assertEqual(results['task1'], 'result1')
            self.assertEqual(results['task2'], 'result2')
        
        asyncio.run(test())
    
    def test_statistics_tracking(self):
        """Test statistics tracking"""
        async def dummy_task():
            await asyncio.sleep(0.001)
            return {}
        
        async def test():
            await self.processor.process_parallel(
                frame=np.zeros((100, 100, 3)),
                tasks=[dummy_task],
                task_names=['dummy']
            )
            
            stats = self.processor.get_statistics()
            self.assertGreater(stats['total_batches'], 0)
        
        asyncio.run(test())


class TestATMSSystem(unittest.TestCase):
    """White box tests for ATMS system"""
    
    def setUp(self):
        self.atms = IntegratedATMSSystem(
            intersection_id=1,
            prediction_horizon=5.0,
            optimization_enabled=True
        )
    
    def test_initialization(self):
        """Test ATMS initialization"""
        # object_tracker can be None if ByteTrack is used (byte_tracker is used instead)
        # Check that either object_tracker OR byte_tracker is available
        has_tracker = (
            (self.atms.object_tracker is not None) or 
            (self.atms.byte_tracker is not None and self.atms.byte_tracker.is_available)
        )
        self.assertTrue(has_tracker, "Either object_tracker or byte_tracker must be available")
        self.assertIsNotNone(self.atms.trajectory_predictor)
    
    def test_bytetrack_integration(self):
        """Test ByteTrack integration"""
        self.assertIsNotNone(self.atms.use_bytetrack)
        self.assertIsInstance(self.atms.use_bytetrack, bool)
    
    def test_process_frame_path(self):
        """Test process_frame code path"""
        detections = [
            {
                'bbox': (100, 100, 200, 200),
                'confidence': 0.8,
                'class_id': 'car',
                'object_type': 'vehicle'
            }
        ]
        
        async def test():
            result = await self.atms.process_frame(
                detections=detections,
                frame_id="test_frame"
            )
            
            self.assertIsNotNone(result)
            self.assertIsNotNone(result.tracked_objects)
            self.assertIsNotNone(result.trajectory_predictions)
        
        asyncio.run(test())
    
    def test_reset_functionality(self):
        """Test reset method"""
        self.atms.reset_system()
        self.assertEqual(self.atms.frame_count, 0)
        self.assertEqual(self.atms.total_objects_tracked, 0)


class TestPyAVDecoder(unittest.TestCase):
    """White box tests for PyAV decoder"""
    
    def test_initialization(self):
        """Test decoder initialization"""
        # Test with non-existent file (should handle gracefully)
        decoder = PyAVDecoder(Path("nonexistent.mp4"))
        self.assertIsNotNone(decoder.is_opened)
        self.assertIsInstance(decoder.is_opened, bool)
    
    def test_info_extraction(self):
        """Test video info extraction"""
        decoder = PyAVDecoder(Path("nonexistent.mp4"))
        info = decoder.get_info()
        self.assertIsInstance(info, dict)


if __name__ == '__main__':
    unittest.main()

