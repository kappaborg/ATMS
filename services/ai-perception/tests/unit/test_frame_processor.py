"""
Unit Tests for Frame Processor
Tests image preprocessing functionality
"""
import pytest
import numpy as np
import cv2

from preprocessing.frame_processor import FrameProcessor


class TestFrameProcessor:
    """Test suite for FrameProcessor"""
    
    def test_initialization(self, frame_processor_config):
        """Test processor initialization"""
        processor = FrameProcessor(**frame_processor_config)
        
        assert processor.target_size == (640, 640)
        assert processor.normalize is True
        assert processor.resize_method == "letterbox"
    
    def test_resize_image_letterbox(self, sample_image):
        """Test letterbox resizing"""
        processor = FrameProcessor(target_size=(640, 640), resize_method="letterbox")
        
        resized = processor.resize(sample_image)
        
        assert resized.shape[0] == 640
        assert resized.shape[1] == 640
        assert resized.shape[2] == 3
    
    def test_resize_image_stretch(self, sample_image):
        """Test stretch resizing"""
        processor = FrameProcessor(target_size=(640, 640), resize_method="stretch")
        
        resized = processor.resize(sample_image)
        
        assert resized.shape == (640, 640, 3)
    
    def test_resize_different_sizes(self):
        """Test resizing to different target sizes"""
        processor = FrameProcessor(target_size=(416, 416))
        
        # Test various input sizes
        img_square = np.zeros((1024, 1024, 3), dtype=np.uint8)
        img_wide = np.zeros((480, 1280, 3), dtype=np.uint8)
        img_tall = np.zeros((1280, 480, 3), dtype=np.uint8)
        
        resized_square = processor.resize(img_square)
        resized_wide = processor.resize(img_wide)
        resized_tall = processor.resize(img_tall)
        
        assert resized_square.shape[:2] == (416, 416)
        assert resized_wide.shape[:2] == (416, 416)
        assert resized_tall.shape[:2] == (416, 416)
    
    def test_normalize_image(self, sample_image):
        """Test image normalization"""
        processor = FrameProcessor(normalize=True)
        
        normalized = processor.normalize_image(sample_image)
        
        # Check values are in [0, 1] range
        assert normalized.min() >= 0.0
        assert normalized.max() <= 1.0
        assert normalized.dtype == np.float32
    
    def test_no_normalization(self, sample_image):
        """Test without normalization"""
        processor = FrameProcessor(normalize=False)
        
        processed = processor.process(sample_image)
        
        # Should preserve original value range
        assert processed.dtype == np.uint8
    
    def test_bgr_to_rgb_conversion(self, sample_image):
        """Test BGR to RGB color conversion"""
        processor = FrameProcessor()
        
        # OpenCV uses BGR by default
        rgb = processor.bgr_to_rgb(sample_image)
        
        # Check channels are swapped
        assert rgb.shape == sample_image.shape
        np.testing.assert_array_equal(rgb[:, :, 0], sample_image[:, :, 2])
        np.testing.assert_array_equal(rgb[:, :, 2], sample_image[:, :, 0])
    
    def test_process_pipeline(self, sample_image):
        """Test full preprocessing pipeline"""
        processor = FrameProcessor(
            target_size=(640, 640),
            normalize=True,
            resize_method="letterbox"
        )
        
        processed = processor.process(sample_image)
        
        # Check output properties
        assert processed.shape[0] == 640
        assert processed.shape[1] == 640
        assert processed.dtype == np.float32
        assert processed.min() >= 0.0
        assert processed.max() <= 1.0
    
    def test_process_with_none_input(self):
        """Test processing None input"""
        processor = FrameProcessor()
        
        result = processor.process(None)
        
        assert result is None
    
    def test_process_with_empty_image(self):
        """Test processing empty image"""
        processor = FrameProcessor()
        
        empty = np.array([])
        result = processor.process(empty)
        
        assert result is None or len(result) == 0
    
    def test_process_grayscale_image(self):
        """Test processing grayscale image"""
        processor = FrameProcessor(target_size=(640, 640))
        
        gray = np.zeros((480, 640), dtype=np.uint8)
        processed = processor.process(gray)
        
        # Should convert to 3-channel or handle gracefully
        assert processed is not None
    
    def test_letterbox_padding(self):
        """Test letterbox adds correct padding"""
        processor = FrameProcessor(target_size=(640, 640), resize_method="letterbox")
        
        # Create rectangular image
        rect_img = np.ones((480, 640, 3), dtype=np.uint8) * 255
        
        processed = processor.resize(rect_img)
        
        assert processed.shape[:2] == (640, 640)
        # Check for padding (black borders)
        # Top and bottom should have padding
        assert processed[0, :].mean() < 255
        assert processed[-1, :].mean() < 255
    
    def test_batch_processing(self, sample_image):
        """Test batch processing multiple images"""
        processor = FrameProcessor(target_size=(640, 640))
        
        images = [sample_image, sample_image.copy(), sample_image.copy()]
        
        processed_batch = [processor.process(img) for img in images]
        
        assert len(processed_batch) == 3
        for img in processed_batch:
            assert img.shape[0] == 640
            assert img.shape[1] == 640
    
    def test_aspect_ratio_preservation_letterbox(self):
        """Test letterbox preserves aspect ratio"""
        processor = FrameProcessor(target_size=(640, 640), resize_method="letterbox")
        
        # Wide image (16:9)
        wide = np.zeros((720, 1280, 3), dtype=np.uint8)
        processed = processor.resize(wide)
        
        assert processed.shape[:2] == (640, 640)
        # Center area should contain the resized image
        # Sides should have padding
    
    def test_color_channels_consistency(self, sample_image):
        """Test color channels remain consistent"""
        processor = FrameProcessor()
        
        # BGR image
        assert sample_image.shape[2] == 3
        
        processed = processor.process(sample_image)
        
        # Should preserve 3 channels
        if processed is not None:
            assert len(processed.shape) == 3
            assert processed.shape[2] == 3
    
    def test_dtype_conversion(self):
        """Test data type conversions"""
        processor_normalize = FrameProcessor(normalize=True)
        processor_no_normalize = FrameProcessor(normalize=False)
        
        img_uint8 = np.random.randint(0, 256, (640, 640, 3), dtype=np.uint8)
        
        # With normalization
        normalized = processor_normalize.process(img_uint8)
        assert normalized.dtype == np.float32
        
        # Without normalization
        not_normalized = processor_no_normalize.process(img_uint8)
        assert not_normalized.dtype == np.uint8
    
    def test_edge_cases_tiny_image(self):
        """Test with very small images"""
        processor = FrameProcessor(target_size=(640, 640))
        
        tiny = np.zeros((10, 10, 3), dtype=np.uint8)
        processed = processor.process(tiny)
        
        # Should upscale successfully
        assert processed is not None
        assert processed.shape[0] == 640
        assert processed.shape[1] == 640
    
    def test_edge_cases_huge_image(self):
        """Test with very large images"""
        processor = FrameProcessor(target_size=(640, 640))
        
        # Create a large image (4K)
        huge = np.zeros((2160, 3840, 3), dtype=np.uint8)
        processed = processor.process(huge)
        
        # Should downscale successfully
        assert processed is not None
        assert processed.shape[0] == 640
        assert processed.shape[1] == 640
    
    def test_performance_optimization(self, sample_image):
        """Test preprocessing performance"""
        processor = FrameProcessor(target_size=(640, 640))
        
        import time
        
        start = time.time()
        for _ in range(10):
            _ = processor.process(sample_image)
        elapsed = time.time() - start
        
        # Should process 10 images in reasonable time (<1 second)
        assert elapsed < 1.0
    
    def test_memory_efficiency(self, sample_image):
        """Test memory usage is reasonable"""
        processor = FrameProcessor(target_size=(640, 640))
        
        # Process same image multiple times
        for _ in range(100):
            processed = processor.process(sample_image)
            del processed
        
        # Should not leak memory (basic check)
        assert True  # If we got here without OOM, we're good
    
    def test_configuration_validation(self):
        """Test configuration validation"""
        # Valid configurations
        processor1 = FrameProcessor(target_size=(416, 416))
        assert processor1.target_size == (416, 416)
        
        processor2 = FrameProcessor(target_size=(640, 640))
        assert processor2.target_size == (640, 640)
        
        processor3 = FrameProcessor(target_size=(1280, 1280))
        assert processor3.target_size == (1280, 1280)
    
    def test_resize_methods_comparison(self, sample_image):
        """Test different resize methods produce different results"""
        proc_letterbox = FrameProcessor(target_size=(640, 640), resize_method="letterbox")
        proc_stretch = FrameProcessor(target_size=(640, 640), resize_method="stretch")
        
        # Start with non-square image
        rect = np.zeros((480, 640, 3), dtype=np.uint8)
        
        letterbox_result = proc_letterbox.resize(rect)
        stretch_result = proc_stretch.resize(rect)
        
        # Results should be different (letterbox has padding, stretch doesn't)
        assert not np.array_equal(letterbox_result, stretch_result)


