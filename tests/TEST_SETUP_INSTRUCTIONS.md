# Test Setup Instructions

## Quick Start

### Option 1: Use Existing AI Perception Venv (Recommended)

```bash
# 1. Activate AI Perception venv
cd services/ai-perception
source venv/bin/activate

# 2. Install test dependencies
pip install pytest pytest-asyncio pytest-cov httpx numpy opencv-python

# 3. Run tests
cd ../../tests
./run_tests.sh
```

### Option 2: Create Dedicated Test Venv

```bash
# 1. Run setup script
./tests/setup_test_env.sh

# 2. Activate test venv
source tests/venv/bin/activate

# 3. Run tests
python3 -m pytest tests/ -v
```

## Manual Setup

If the scripts don't work, set up manually:

```bash
# 1. Create venv
python3 -m venv tests/venv
source tests/venv/bin/activate

# 2. Install dependencies
pip install -r tests/requirements.txt

# 3. Set PYTHONPATH
export PYTHONPATH="$PWD:$PWD/services/ai-perception/src:$PWD/services/video-processor/src"

# 4. Run tests
python3 -m pytest tests/ -v
```

## Troubleshooting

### Error: "No module named 'numpy'"
- Make sure you're using the venv: `source services/ai-perception/venv/bin/activate`
- Install dependencies: `pip install numpy opencv-python`

### Error: "No module named 'pytest'"
- Install pytest: `pip install pytest pytest-asyncio`

### Error: Import errors
- Check PYTHONPATH is set correctly
- Make sure you're in the project root directory
- Verify service directories exist: `services/ai-perception/src/`

### Error: "ModuleNotFoundError: No module named 'services'"
- The import paths have been fixed to work with both venv and system Python
- Make sure PYTHONPATH includes the project root

## Running Individual Tests

```bash
# Benchmark tests
python3 tests/benchmark_performance_tests.py

# White box tests
python3 -m pytest tests/white_box_unit_tests.py -v

# Black box tests
python3 -m pytest tests/black_box_integration_tests.py -v
```

## Notes

- Some tests require models to be loaded (may fail gracefully if not available)
- Benchmark tests need video files in `videos/` directory
- Integration tests require services to be running (use TestClient for mocking)

