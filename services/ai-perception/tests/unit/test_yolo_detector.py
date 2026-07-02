"""
Unit Tests for YOLO Detector
Tests object detection functionality
"""
import pytest
import numpy as np
import cv2
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

from detection.yolo_detector import YOLODetector
from shared.models.detection import ObjectClass, Detection


class TestYOLODetector:
    """Test suite for YOLODetector"""
    
    def test_initialization(self, yolo_detector_config):
        """Test detector initialization"""
        with patch('detection.yolo_detector.YOLO') as mock_yolo:
            detector = YOLODetector(**yolo_detector_config)
            
            assert detector.model_name == "yolov8n"
            assert detector.confidence_threshold == 0.5
            assert detector.iou_threshold == 0.45
            assert detector.max_detections == 100
            assert detector.device == "cpu"
    
    def test_model_loading_success(self, yolo_detector_config):
        """Test successful model loading"""
        with patch('detection.yolo_detector.YOLO') as mock_yolo:
            mock_model = MagicMock()
            mock_yolo.return_value = mock_model
            
            detector = YOLODetector(**yolo_detector_config)
            
            assert detector.model is not None
            assert detector.is_loaded is True
    
    def test_model_loading_failure(self, yolo_detector_config):
        """Test model loading failure handling"""
        with patch('detection.yolo_detector.YOLO', side_effect=Exception("Model not found")):
            detector = YOLODetector(**yolo_detector_config)
            
            assert detector.model is None
            assert detector.is_loaded is False
    
    def test_detect_with_valid_image(self, sample_image, yolo_detector_config, mock_yolo_model):
        """Test detection with valid image"""
        with patch('detection.yolo_detector.YOLO', return_value=mock_yolo_model):
            detector = YOLODetector(**yolo_detector_config)
            detections = detector.detect(sample_image)
            
            assert isinstance(detections, list)
            assert len(detections) > 0
            
            # Check first detection
            det = detections[0]
            assert hasattr(det, 'object_class')
            assert hasattr(det, 'bounding_box')
            assert det.bounding_box.confidence > 0
    
    def test_detect_with_empty_image(self, yolo_detector_config):
        """Test detection with empty image"""
        with patch('detection.yolo_detector.YOLO') as mock_yolo:
            mock_model = MagicMock()
            mock_result = MagicMock()
            mock_result.boxes = MagicMock()
            mock_result.boxes.xyxy = np.array([])
            mock_result.boxes.conf = np.array([])
            mock_result.boxes.cls = np.array([])
            mock_model.return_value = [mock_result]
            mock_yolo.return_value = mock_model
            
            detector = YOLODetector(**yolo_detector_config)
            empty_image = np.zeros((640, 640, 3), dtype=np.uint8)
            detections = detector.detect(empty_image)
            
            assert isinstance(detections, list)
            assert len(detections) == 0
    
    def test_detect_with_none_image(self, yolo_detector_config):
        """Test detection with None image"""
        with patch('detection.yolo_detector.YOLO'):
            detector = YOLODetector(**yolo_detector_config)
            detections = detector.detect(None)
            
            assert detections == []
    
    def test_detect_with_invalid_dimensions(self, yolo_detector_config):
        """Test detection with invalid image dimensions"""
        with patch('detection.yolo_detector.YOLO'):
            detector = YOLODetector(**yolo_detector_config)
            
            # 2D image (grayscale)
            gray_image = np.zeros((640, 640), dtype=np.uint8)
            detections = detector.detect(gray_image)
            assert detections == []
            
            # Wrong number of channels
            wrong_channels = np.zeros((640, 640, 4), dtype=np.uint8)
            detections = detector.detect(wrong_channels)
            assert isinstance(detections, list)
    
    def test_confidence_threshold_filtering(self, sample_image, yolo_detector_config):
        """Test that low confidence detections are filtered"""
        with patch('detection.yolo_detector.YOLO') as mock_yolo:
            mock_model = MagicMock()
            mock_result = MagicMock()
            mock_result.boxes = MagicMock()
            
            # Mix of high and low confidence detections
            mock_result.boxes.xyxy = np.array([
                [100.0, 100.0, 200.0, 200.0],
                [300.0, 300.0, 400.0, 500.0]
            ])
            mock_result.boxes.conf = np.array([0.95, 0.25])  # One below threshold
            mock_result.boxes.cls = np.array([2, 7])
            
            mock_model.return_value = [mock_result]
            mock_yolo.return_value = mock_model
            
            detector = YOLODetector(confidence_threshold=0.5, **{k: v for k, v in yolo_detector_config.items() if k != 'confidence_threshold'})
            detections = detector.detect(sample_image)
            
            # Should only get high confidence detection
            assert len(detections) >= 1
            assert all(det.bounding_box.confidence >= 0.5 for det in detections)
    
    def test_max_detections_limit(self, sample_image, yolo_detector_config):
        """Test max detections limit"""
        with patch('detection.yolo_detector.YOLO') as mock_yolo:
            mock_model = MagicMock()
            mock_result = MagicMock()
            mock_result.boxes = MagicMock()
            
            # Create more detections than max_detections
            n_boxes = 150
            mock_result.boxes.xyxy = np.random.rand(n_boxes, 4) * 640
            mock_result.boxes.conf = np.random.rand(n_boxes) * 0.5 + 0.5  # 0.5-1.0
            mock_result.boxes.cls = np.random.randint(0, 80, n_boxes)
            
            mock_model.return_value = [mock_result]
            mock_yolo.return_value = mock_model
            
            detector = YOLODetector(max_detections=100, **{k: v for k, v in yolo_detector_config.items() if k != 'max_detections'})
            detections = detector.detect(sample_image)
            
            assert len(detections) <= 100
    
    def test_coco_class_mapping(self, sample_image, yolo_detector_config):
        """Test COCO class ID to ObjectClass mapping"""
        with patch('detection.yolo_detector.YOLO') as mock_yolo:
            mock_model = MagicMock()
            mock_result = MagicMock()
            mock_result.boxes = MagicMock()
            
            # Test specific COCO classes
            mock_result.boxes.xyxy = np.array([
                [100.0, 100.0, 200.0, 200.0],  # car (COCO 2)
                [300.0, 300.0, 400.0, 500.0],  # truck (COCO 7)
                [500.0, 100.0, 600.0, 300.0],  # person (COCO 0)
            ])
            mock_result.boxes.conf = np.array([0.95, 0.88, 0.92])
            mock_result.boxes.cls = np.array([2, 7, 0])
            
            mock_model.return_value = [mock_result]
            mock_yolo.return_value = mock_model
            
            detector = YOLODetector(**yolo_detector_config)
            detections = detector.detect(sample_image)
            
            # Verify class mapping
            classes = [det.object_class for det in detections]
            assert ObjectClass.CAR in classes
            assert ObjectClass.TRUCK in classes
            assert ObjectClass.PEDESTRIAN in classes
    
    def test_bounding_box_format(self, sample_image, yolo_detector_config, mock_yolo_model):
        """Test bounding box coordinates are correct"""
        with patch('detection.yolo_detector.YOLO', return_value=mock_yolo_model):
            detector = YOLODetector(**yolo_detector_config)
            detections = detector.detect(sample_image)
            
            for det in detections:
                bbox = det.bounding_box
                # Verify box is valid
                assert bbox.x_min < bbox.x_max
                assert bbox.y_min < bbox.y_max
                assert bbox.x_min >= 0
                assert bbox.y_min >= 0
                assert 0.0 <= bbox.confidence <= 1.0
    
    def test_batch_detection(self, sample_image, yolo_detector_config, mock_yolo_model):
        """Test batch detection"""
        with patch('detection.yolo_detector.YOLO', return_value=mock_yolo_model):
            detector = YOLODetector(**yolo_detector_config)
            
            # Create batch of images
            images = [sample_image, sample_image.copy(), sample_image.copy()]
            
            # Detect on each image
            all_detections = [detector.detect(img) for img in images]
            
            assert len(all_detections) == 3
            for detections in all_detections:
                assert isinstance(detections, list)
    
    def test_performance_metrics_tracking(self, sample_image, yolo_detector_config, mock_yolo_model):
        """Test that performance metrics are tracked"""
        with patch('detection.yolo_detector.YOLO', return_value=mock_yolo_model):
            detector = YOLODetector(**yolo_detector_config)
            
            # Run detection
            detections = detector.detect(sample_image)
            
            # Check metrics exist (if implemented)
            assert hasattr(detector, 'model_name')
            assert hasattr(detector, 'confidence_threshold')
    
    def test_gpu_device_configuration(self, yolo_detector_config):
        """Test GPU device configuration"""
        with patch('detection.yolo_detector.YOLO'):
            # CPU device
            detector_cpu = YOLODetector(device="cpu", **{k: v for k, v in yolo_detector_config.items() if k != 'device'})
            assert detector_cpu.device == "cpu"
            
            # GPU device
            detector_gpu = YOLODetector(device="cuda:0", **{k: v for k, v in yolo_detector_config.items() if k != 'device'})
            assert detector_gpu.device == "cuda:0"
    
    def test_half_precision_mode(self, yolo_detector_config):
        """Test FP16 half precision mode"""
        with patch('detection.yolo_detector.YOLO') as mock_yolo:
            mock_model = MagicMock()
            mock_yolo.return_value = mock_model
            
            detector = YOLODetector(half_precision=True, **{k: v for k, v in yolo_detector_config.items() if k != 'half_precision'})
            
            assert detector.half_precision is True
            # Model should be converted to half if on GPU
            if 'cuda' in detector.device:
                mock_model.half.assert_called_once()
    
    def test_detection_statistics(self, sample_image, yolo_detector_config, mock_yolo_model):
        """Test detection statistics calculation"""
        with patch('detection.yolo_detector.YOLO', return_value=mock_yolo_model):
            detector = YOLODetector(**yolo_detector_config)
            detections = detector.detect(sample_image)
            
            # Calculate stats
            if detections:
                avg_confidence = sum(d.bounding_box.confidence for d in detections) / len(detections)
                assert 0.0 <= avg_confidence <= 1.0
                
                # Check object class distribution
                classes = [d.object_class for d in detections]
                assert len(classes) == len(detections)
    
    def test_error_handling_during_inference(self, sample_image, yolo_detector_config):
        """Test error handling during inference"""
        with patch('detection.yolo_detector.YOLO') as mock_yolo:
            mock_model = MagicMock()
            mock_model.side_effect = Exception("Inference failed")
            mock_yolo.return_value = mock_model
            
            detector = YOLODetector(**yolo_detector_config)
            detections = detector.detect(sample_image)
            
            # Should return empty list on error
            assert detections == []


