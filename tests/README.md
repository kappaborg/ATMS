# Test Suite

Comprehensive testing suite for the Traffic Analysis System.

## Setup

### Option 1: Use AI Perception Venv (Recommended)

```bash
# Activate AI Perception venv
cd services/ai-perception
source venv/bin/activate

# Install test dependencies
pip install pytest pytest-asyncio pytest-cov httpx numpy opencv-python

# Run tests
cd ../../tests
./run_tests.sh
```

### Option 2: Create Test Venv

```bash
# Create test venv
python3 -m venv tests/venv
source tests/venv/bin/activate

# Install dependencies
pip install -r tests/requirements.txt

# Run tests
python3 -m pytest tests/ -v
```

## Test Files

### 1. Benchmark Performance Tests
```bash
python3 tests/benchmark_performance_tests.py
```

Tests:
- YOLOv8 detector performance
- CoreML optimization benchmarks
- Async parallel processing speedup
- PyAV vs OpenCV comparison

### 2. White Box Unit Tests
```bash
python3 -m pytest tests/white_box_unit_tests.py -v
```

Tests internal implementation:
- YOLODetector logic
- ByteTrack wrapper
- AsyncProcessor
- ATMS system
- PyAV decoder

### 3. Black Box Integration Tests
```bash
python3 -m pytest tests/black_box_integration_tests.py -v
```

Tests system behavior:
- API endpoints
- Data flow
- Error handling
- Performance

## Notes

- Some tests require models to be loaded (may fail if models not available)
- Benchmark tests need video files in `videos/` directory
- Integration tests require services to be running

