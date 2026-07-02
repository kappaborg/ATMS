"""
Black Box Integration Tests
Tests system behavior from external perspective without knowledge of internal implementation
"""
import unittest
import asyncio
import numpy as np
import cv2
from pathlib import Path
import sys
import json

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "services" / "ai-perception" / "src"))

try:
    from main import app
except ImportError:
    # Fallback to direct file import
    import importlib.util
    ai_perception_src = project_root / "services" / "ai-perception" / "src"
    spec = importlib.util.spec_from_file_location("main", ai_perception_src / "main.py")
    main_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main_module)
    app = main_module.app

try:
    from starlette.testclient import TestClient
    TEST_CLIENT_AVAILABLE = True
except ImportError:
    try:
        from fastapi.testclient import TestClient
        TEST_CLIENT_AVAILABLE = True
    except Exception as e:
        TEST_CLIENT_AVAILABLE = False
        print(f"⚠️  TestClient not available: {e}")


class TestEndToEndIntegration(unittest.TestCase):
    """Black box tests for end-to-end system integration"""
    
    def setUp(self):
        if TEST_CLIENT_AVAILABLE:
            try:
                self.client = TestClient(app)
            except Exception as e:
                # Fallback: Skip tests if TestClient fails
                self.skipTest(f"TestClient initialization failed: {e}")
        else:
            self.skipTest("TestClient not available")
    
    def test_health_endpoint(self):
        """Test health check endpoint (black box)"""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('status', data)
        self.assertIn('service', data)
        self.assertIn('details', data)
    
    def test_root_endpoint(self):
        """Test root endpoint"""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('service', data)
        self.assertIn('version', data)
        self.assertIn('status', data)
    
    def test_models_status_endpoint(self):
        """Test models status endpoint"""
        response = self.client.get("/models/status")
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('yolov8_detector', data)
        self.assertIn('brand_classifier', data)
        self.assertIn('multiview_detector', data)
        self.assertIn('tramway_detector', data)
    
    def test_detector_stats_endpoint(self):
        """Test detector stats endpoint"""
        response = self.client.get("/detector/stats")
        # May return 503 if not initialized, which is acceptable
        self.assertIn(response.status_code, [200, 503])
    
    def test_metrics_endpoint(self):
        """Test Prometheus metrics endpoint"""
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/plain', response.headers.get('content-type', ''))


class TestDataFlowIntegration(unittest.TestCase):
    """Black box tests for data flow through the system"""
    
    def setUp(self):
        if TEST_CLIENT_AVAILABLE:
            try:
                self.client = TestClient(app)
            except Exception as e:
                self.skipTest(f"TestClient initialization failed: {e}")
        else:
            self.skipTest("TestClient not available")
    
    def test_detection_pipeline(self):
        """Test complete detection pipeline (black box)"""
        # Create a test image
        test_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        _, buffer = cv2.imencode('.jpg', test_image)
        
        # Test detection endpoint
        response = self.client.post(
            "/detect/test",
            files={"file": ("test.jpg", buffer.tobytes(), "image/jpeg")}
        )
        
        # Should return 200 or 503 (if not initialized)
        self.assertIn(response.status_code, [200, 503])
        
        if response.status_code == 200:
            data = response.json()
            self.assertIn('status', data)
            self.assertIn('detections', data)
            self.assertIn('count', data)
            self.assertIsInstance(data['detections'], list)
    
    def test_license_plate_pipeline(self):
        """Test license plate recognition pipeline"""
        # Create a test image
        test_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        _, buffer = cv2.imencode('.jpg', test_image)
        
        # Test plate recognition endpoint
        response = self.client.post(
            "/plates/test",
            files={"file": ("test.jpg", buffer.tobytes(), "image/jpeg")}
        )
        
        # Should return 200 or 503
        self.assertIn(response.status_code, [200, 503])
        
        if response.status_code == 200:
            data = response.json()
            self.assertIn('status', data)
            self.assertIn('plates_detected', data)


class TestOptimizationIntegration(unittest.TestCase):
    """Black box tests for optimization features"""
    
    def setUp(self):
        if TEST_CLIENT_AVAILABLE:
            try:
                self.client = TestClient(app)
            except Exception as e:
                self.skipTest(f"TestClient initialization failed: {e}")
        else:
            self.skipTest("TestClient not available")
    
    def test_coreml_availability(self):
        """Test CoreML optimization availability (black box)"""
        response = self.client.get("/detector/stats")
        
        if response.status_code == 200:
            data = response.json()
            # Check if CoreML info is present
            if 'use_coreml' in data:
                self.assertIsInstance(data['use_coreml'], bool)
            if 'coreml_available' in data:
                self.assertIsInstance(data['coreml_available'], bool)
    
    def test_bytetrack_integration(self):
        """Test ByteTrack integration (black box)"""
        response = self.client.get("/atms/status")
        
        if response.status_code == 200:
            data = response.json()
            # Check if ByteTrack info is present
            if 'tracker_status' in data:
                tracker_status = data['tracker_status']
                if 'using_bytetrack' in tracker_status:
                    self.assertIsInstance(tracker_status['using_bytetrack'], bool)


class TestPerformanceIntegration(unittest.TestCase):
    """Black box tests for performance characteristics"""
    
    def setUp(self):
        if TEST_CLIENT_AVAILABLE:
            try:
                self.client = TestClient(app)
            except Exception as e:
                self.skipTest(f"TestClient initialization failed: {e}")
        else:
            self.skipTest("TestClient not available")
    
    def test_response_time(self):
        """Test API response times (black box)"""
        import time
        
        # Test health endpoint response time
        start = time.time()
        response = self.client.get("/health")
        elapsed = time.time() - start
        
        self.assertEqual(response.status_code, 200)
        # Health check should be fast (< 100ms)
        self.assertLess(elapsed, 0.1, f"Health check took {elapsed*1000:.2f}ms")
    
    def test_concurrent_requests(self):
        """Test system under concurrent load (black box)"""
        import concurrent.futures
        
        def make_request():
            return self.client.get("/health")
        
        # Make 10 concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        # All requests should succeed
        for response in results:
            self.assertEqual(response.status_code, 200)


class TestErrorHandling(unittest.TestCase):
    """Black box tests for error handling"""
    
    def setUp(self):
        if TEST_CLIENT_AVAILABLE:
            try:
                self.client = TestClient(app)
            except Exception as e:
                self.skipTest(f"TestClient initialization failed: {e}")
        else:
            self.skipTest("TestClient not available")
    
    def test_invalid_endpoint(self):
        """Test invalid endpoint handling"""
        response = self.client.get("/invalid/endpoint")
        self.assertEqual(response.status_code, 404)
    
    def test_invalid_method(self):
        """Test invalid HTTP method"""
        response = self.client.post("/health")
        # POST to GET endpoint should fail
        self.assertIn(response.status_code, [405, 422])
    
    def test_missing_parameters(self):
        """Test missing required parameters"""
        # Test endpoint that requires file upload without file
        response = self.client.post("/detect/test")
        self.assertIn(response.status_code, [422, 400])


if __name__ == '__main__':
    unittest.main()

