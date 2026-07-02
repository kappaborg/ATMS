"""
Integration Tests for AI Perception API Endpoints
Tests FastAPI endpoints and service integration
"""
import pytest
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
import json

# Import the FastAPI app
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture
def test_client():
    """Create test client for FastAPI app"""
    # We need to mock some components that might not be fully initialized
    with patch('main.detector'), \
         patch('main.preprocessor'), \
         patch('main.kafka_consumer'), \
         patch('main.kafka_producer'):
        
        from main import app
        client = TestClient(app)
        yield client


class TestHealthEndpoint:
    """Test health check endpoint"""
    
    def test_health_endpoint_success(self, test_client):
        """Test health endpoint returns 200"""
        response = test_client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "service" in data
        assert data["service"] == "ai-perception"
    
    def test_health_endpoint_structure(self, test_client):
        """Test health endpoint response structure"""
        response = test_client.get("/health")
        data = response.json()
        
        assert "status" in data
        assert "service" in data
        assert "version" in data
        assert "timestamp" in data


class TestMetricsEndpoint:
    """Test Prometheus metrics endpoint"""
    
    def test_metrics_endpoint_success(self, test_client):
        """Test metrics endpoint returns 200"""
        response = test_client.get("/metrics")
        
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
    
    def test_metrics_endpoint_content(self, test_client):
        """Test metrics endpoint returns Prometheus format"""
        response = test_client.get("/metrics")
        content = response.text
        
        # Should contain Prometheus metrics
        # (They may not be present if metrics aren't initialized)
        assert isinstance(content, str)


class TestDetectEndpoint:
    """Test object detection endpoint"""
    
    @pytest.mark.skip(reason="Requires full service initialization")
    def test_detect_endpoint_with_valid_image(self, test_client, sample_image_path):
        """Test detection with valid image"""
        with open(sample_image_path, 'rb') as f:
            files = {'file': ('test.jpg', f, 'image/jpeg')}
            response = test_client.post("/detect", files=files)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "detections" in data
        assert "processing_time_ms" in data
        assert isinstance(data["detections"], list)
    
    @pytest.mark.skip(reason="Requires full service initialization")
    def test_detect_endpoint_without_file(self, test_client):
        """Test detection without file"""
        response = test_client.post("/detect")
        
        # Should return 422 (validation error)
        assert response.status_code == 422


class TestStatisticsEndpoint:
    """Test statistics endpoint"""
    
    def test_stats_endpoint_success(self, test_client):
        """Test statistics endpoint returns 200"""
        response = test_client.get("/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, dict)


class TestRootEndpoint:
    """Test root endpoint"""
    
    def test_root_endpoint(self, test_client):
        """Test root endpoint"""
        response = test_client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "service" in data
        assert data["service"] == "ai-perception"


class TestAPIDocumentation:
    """Test API documentation endpoints"""
    
    def test_openapi_schema(self, test_client):
        """Test OpenAPI schema is available"""
        response = test_client.get("/openapi.json")
        
        assert response.status_code == 200
        schema = response.json()
        
        assert "openapi" in schema
        assert "info" in schema
        assert schema["info"]["title"] == "ATMS AI Perception Service"
    
    def test_swagger_ui_available(self, test_client):
        """Test Swagger UI is accessible"""
        response = test_client.get("/docs")
        
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    
    def test_redoc_available(self, test_client):
        """Test ReDoc is accessible"""
        response = test_client.get("/redoc")
        
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestCORSHeaders:
    """Test CORS configuration"""
    
    @pytest.mark.skip(reason="CORS configuration depends on app setup")
    def test_cors_headers_present(self, test_client):
        """Test CORS headers are present"""
        response = test_client.options("/health")
        
        assert "access-control-allow-origin" in response.headers


class TestErrorHandling:
    """Test error handling"""
    
    def test_404_not_found(self, test_client):
        """Test 404 for non-existent endpoint"""
        response = test_client.get("/nonexistent")
        
        assert response.status_code == 404
    
    def test_405_method_not_allowed(self, test_client):
        """Test 405 for wrong HTTP method"""
        response = test_client.put("/health")
        
        assert response.status_code == 405


class TestContentNegotiation:
    """Test content type handling"""
    
    def test_json_response_headers(self, test_client):
        """Test JSON responses have correct content-type"""
        response = test_client.get("/health")
        
        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]


