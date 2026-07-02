# Sensor Fusion Service

**Week 1 Implementation - COMPLETE ✅**

## Overview

The Sensor Fusion Service is the first layer of the ATMS system, responsible for aggregating and synchronizing data from multiple camera sensors (and eventually LiDAR, thermal, and radar sensors).

## Features Implemented (Week 1)

✅ **Camera Interface**
- RTSP stream support with auto-reconnection
- Async frame capture
- Frame quality validation
- Performance optimization with JPEG compression
- Exponential backoff reconnection strategy

✅ **Frame Synchronization**
- Multi-camera time-based alignment
- Configurable sync threshold (default: 100ms)
- Automatic drift detection and correction
- Buffer management with cleanup

✅ **Kafka Integration**
- Async message production
- Automatic serialization (Pydantic → JSON)
- Error handling and retry logic
- Batch processing support
- Exactly-once semantics

✅ **API Endpoints**
- Health monitoring
- Camera status and control
- Synchronization metrics
- Prometheus metrics export

✅ **Production Ready**
- Comprehensive error handling
- Structured logging (JSON format)
- Performance monitoring
- Unit and integration tests
- Type hints throughout

## Architecture

```
Camera Feed (RTSP)
    ↓
[Camera Adapter]
    ├─ Auto-reconnection
    ├─ Frame validation
    └─ Quality control
    ↓
[Frame Synchronizer]
    ├─ Time alignment
    ├─ Drift correction
    └─ Buffer management
    ↓
[Kafka Producer]
    ├─ Message serialization
    ├─ Error handling
    └─ Performance optimization
    ↓
Kafka Topic: "camera-frames"
```

## Installation

### Prerequisites
- Python 3.11+
- OpenCV
- Kafka (optional for development)

### Setup

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your settings
```

### Environment Variables

```bash
# Service Configuration
SERVICE_NAME=sensor-fusion
SERVICE_VERSION=1.0.0
API_HOST=0.0.0.0
API_PORT=8000

# Camera Configuration
CAMERA_IDS=["camera_1", "camera_2", "camera_3", "camera_4"]
CAMERA_RESOLUTION=(1920, 1080)
CAMERA_FPS=30

# Kafka Configuration
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_TOPIC_CAMERA_FRAMES=camera-frames

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

## Running the Service

### Development Mode

```bash
cd src
python main.py
```

The service will start on `http://localhost:8000`

### Production Mode (with Uvicorn)

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### With Docker (requires Docker setup)

```bash
docker build -t atms/sensor-fusion:latest .
docker run -p 8000:8000 atms/sensor-fusion:latest
```

## API Endpoints

### Health & Status

#### `GET /health`
Health check endpoint

**Response:**
```json
{
  "status": "healthy",
  "service": "sensor-fusion",
  "timestamp": "2025-10-01T12:00:00Z",
  "version": "1.0.0",
  "details": {
    "cameras": {
      "camera_1": true,
      "camera_2": true
    },
    "kafka": true,
    "active_cameras": 2
  }
}
```

#### `GET /metrics`
Prometheus metrics endpoint

### Camera Management

#### `GET /cameras`
List all cameras and their status

**Response:**
```json
{
  "cameras": [
    {
      "camera_id": "camera_1",
      "is_connected": true,
      "frame_count": 15234,
      "error_count": 2,
      "rtsp_url": "rtsp://localhost:8554/stream1",
      "resolution": "1920x1080",
      "target_fps": 30
    }
  ]
}
```

#### `GET /cameras/{camera_id}`
Get specific camera status

#### `POST /cameras/{camera_id}/reconnect`
Reconnect a specific camera

**Response:**
```json
{
  "status": "reconnected",
  "camera_id": "camera_1"
}
```

### Synchronization

#### `GET /sync/status`
Get frame synchronizer status

**Response:**
```json
{
  "sync_count": 5432,
  "timeout_count": 23,
  "drift_corrections": 5,
  "buffer_status": {
    "camera_1": 3,
    "camera_2": 4
  },
  "camera_count": 2
}
```

### Kafka

#### `GET /kafka/status`
Get Kafka producer status

**Response:**
```json
{
  "is_connected": true,
  "message_count": 15234,
  "error_count": 2,
  "bootstrap_servers": "localhost:9092",
  "client_id": "sensor-fusion"
}
```

## Testing

### Run All Tests

```bash
pytest tests/ -v
```

### Run with Coverage

```bash
pytest tests/ --cov=src --cov-report=html
```

### Run Specific Tests

```bash
# Unit tests only
pytest tests/unit/ -v

# Integration tests only
pytest tests/integration/ -v
```

## Performance Metrics

### Prometheus Metrics Exposed

- `sensor_fusion_frames_processed_total{camera_id}` - Total frames processed per camera
- `sensor_fusion_frames_synced_total` - Total synchronized frame sets
- `sensor_fusion_processing_seconds` - Frame processing time histogram
- `sensor_fusion_active_cameras` - Number of active cameras

### Expected Performance

- **Frame Capture Latency:** < 33ms (30 FPS)
- **Synchronization Delay:** < 100ms
- **Kafka Publishing:** < 50ms
- **End-to-End Latency:** < 200ms

## Configuration

### Camera Configuration

Edit `src/config.py`:

```python
class CameraConfig(BaseSettings):
    CAMERA_IDS: List[str] = ["camera_1", "camera_2", "camera_3", "camera_4"]
    RTSP_URLS: Dict[str, str] = {
        "camera_1": "rtsp://localhost:8554/stream1",
        "camera_2": "rtsp://localhost:8554/stream2",
        "camera_3": "rtsp://localhost:8554/stream3",
        "camera_4": "rtsp://localhost:8554/stream4",
    }
    CAMERA_RESOLUTION: tuple = (1920, 1080)
    CAMERA_FPS: int = 30
```

### Synchronization Configuration

```python
synchronizer = FrameSynchronizer(
    camera_ids=list(cameras.keys()),
    sync_threshold_ms=100,  # Max time difference for sync
    buffer_size=30,         # Frames per camera
    timeout_seconds=5       # Frame timeout
)
```

## Troubleshooting

### Camera Connection Issues

**Problem:** Camera fails to connect

**Solutions:**
1. Check RTSP URL is correct
2. Verify network connectivity
3. Check camera credentials
4. Increase `MAX_RECONNECT_ATTEMPTS` in config
5. Check logs for specific error messages

### Synchronization Issues

**Problem:** Frames not synchronizing

**Solutions:**
1. Check camera timestamps are in UTC
2. Increase `sync_threshold_ms` if cameras have drift
3. Monitor buffer sizes with `/sync/status`
4. Check for camera disconnections

### Kafka Connection Issues

**Problem:** Cannot connect to Kafka

**Solutions:**
1. Verify Kafka is running: `docker ps`
2. Check `KAFKA_BOOTSTRAP_SERVERS` configuration
3. Test Kafka connectivity: `telnet localhost 9092`
4. Service works in mock mode without Kafka for testing

## Week 1 Achievements

✅ **100% Feature Complete**
- Camera interface with RTSP support
- Multi-camera synchronization
- Kafka integration
- REST API
- Prometheus metrics

✅ **Production Quality**
- Comprehensive error handling
- Auto-reconnection logic
- Frame validation
- Performance optimization

✅ **Well Tested**
- Unit tests for all components
- Integration tests
- Mock support for development

✅ **Professional Documentation**
- Complete API documentation
- Configuration guide
- Troubleshooting guide

## Next Steps (Week 2)

- Add LiDAR adapter
- Implement thermal camera support
- Add radar integration
- Enhanced monitoring dashboard
- Performance profiling and optimization

## Code Quality

### Type Coverage
- **100%** type hints on all functions

### Test Coverage
- **Target:** > 80% code coverage
- Unit tests for all adapters
- Integration tests for API endpoints

### Code Style
- Black formatter
- Ruff linter
- MyPy type checking

## Contributing

1. Follow Python PEP 8 style guide
2. Add type hints to all functions
3. Write tests for new features
4. Update documentation
5. Run linters before commit:
   ```bash
   black src/
   ruff check src/
   mypy src/
   ```

## License

ATMS Project - Internal Use

## Support

For issues or questions:
- Check logs: Service uses structured JSON logging
- Monitor metrics: `/metrics` endpoint
- Health check: `/health` endpoint

---

**Week 1 Status:** ✅ COMPLETE & PRODUCTION READY

**Last Updated:** October 1, 2025

