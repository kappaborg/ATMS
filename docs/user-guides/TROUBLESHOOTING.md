# ATMS Troubleshooting Guide

**Last Updated:** October 1, 2025

---

## 🔧 Common Issues & Solutions

### **Issue 1: Logger KeyError: 'INFO'**

**Error:**
```
KeyError: 'INFO'
at structlog.make_filtering_bound_logger(level)
```

**Cause:** The logger was receiving a string `'INFO'` instead of an integer constant.

**Solution:** ✅ **FIXED**
- Updated `shared/utils/logger.py` to convert string to logging constant
- Now accepts: "INFO", "DEBUG", "WARNING", "ERROR"

**Verification:**
```python
# This now works:
logger = setup_logger("my-service", level="INFO")
```

---

### **Issue 2: Pydantic Model Namespace Warning**

**Error:**
```
UserWarning: Field "model_name" has conflict with protected namespace "model_"
```

**Cause:** Pydantic reserves the `model_` prefix for internal use.

**Solution:** ✅ **FIXED**
- Added `model_config = {"protected_namespaces": ()}` to affected models
- Fixed in: `DetectionMessage` and `PerformanceMetrics`

**Verification:**
```python
# No warnings now:
metrics = PerformanceMetrics(
    model_name="YOLOv8",
    model_version="8.0",
    ...
)
```

---

### **Issue 3: pytest-cov Not Found**

**Error:**
```
pytest: error: unrecognized arguments: --cov=src
```

**Cause:** `pytest-cov` package not installed in virtual environment.

**Solution:** ✅ **FIXED**
- Added `coverage==7.3.2` to `requirements.txt`
- Reinstall requirements: `pip install -r requirements.txt`

**Verification:**
```bash
pytest tests/ -v --cov=src --cov-report=term
```

---

## 🚀 Quick Fixes

### **Reinstall Dependencies**

```bash
cd /Users/kappasutra/Traffic/services/sensor-fusion
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### **Run Service**

```bash
cd /Users/kappasutra/Traffic/services/sensor-fusion
source venv/bin/activate
cd src
python main.py
```

**Expected Output:**
```
{"timestamp": "...", "level": "info", "event": "Starting Sensor Fusion Service..."}
{"timestamp": "...", "level": "info", "event": "Kafka producer started successfully"}
```

### **Run Tests**

```bash
cd /Users/kappasutra/Traffic/services/sensor-fusion
source venv/bin/activate
pytest tests/ -v
```

---

## 🐛 Other Common Issues

### **Import Error: No module named 'shared'**

**Cause:** Python can't find the shared modules.

**Solution:**
```bash
# The code already adds shared to path, but verify:
export PYTHONPATH="/Users/kappasutra/Traffic:$PYTHONPATH"
```

Or use the project structure correctly - the code has this built-in:
```python
sys.path.append(str(Path(__file__).parent.parent.parent.parent))
```

### **Kafka Connection Error**

**Error:**
```
Failed to start Kafka producer: [Errno 61] Connection refused
```

**Cause:** Kafka is not running.

**Solution:**
```bash
# Start infrastructure
make dev-up

# Or manually:
docker-compose -f docker-compose.dev.yml up -d kafka
```

**Mock Mode:**
The services work in mock mode without Kafka for testing!

### **CUDA/GPU Not Available**

**Warning:**
```
CUDA requested but not available, using CPU
```

**Solution:**
- This is expected if you don't have NVIDIA GPU
- Service will use CPU automatically
- To use CPU explicitly: Set `DEVICE=cpu` in `.env`

### **Model File Not Found**

**Error:**
```
FileNotFoundError: yolov8n.pt not found
```

**Solution:**
```bash
# YOLOv8 will auto-download on first run
# Or download manually:
cd /Users/kappasutra/Traffic/services/ai-perception
mkdir -p models
cd models
# Model downloads automatically via ultralytics
```

---

### **Issue 4: Prometheus Duplicate Metrics**

**Error:**
```
ValueError: Duplicated timeseries in CollectorRegistry
```

**Cause:** Uvicorn's reload feature re-imports the module, causing metrics to be registered twice.

**Solution:** ✅ **FIXED**
- Wrapped Prometheus metrics in try/except block
- Reuses existing metrics if already registered

**Code:**
```python
try:
    frames_processed = Counter(...)
except ValueError:
    # Metrics already registered (happens with uvicorn reload)
    from prometheus_client import REGISTRY
    frames_processed = REGISTRY._names_to_collectors.get('...')
```

**Alternative:** Run without reload:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --no-reload
```

---

## 6. Missing 'shared' Module Error

**Error:**
```
ModuleNotFoundError: No module named 'shared'
ImportError: No module named 'shared'
```

**Cause:**
- The shared package is not installed in the virtual environment
- Each service needs the shared package to access common utilities and models

**Solution:**

The shared package is now automatically installed via requirements.txt:

```bash
cd /Users/kappasutra/Traffic/services/sensor-fusion
source venv/bin/activate
pip install -r requirements.txt
```

This installs the shared package in development mode (`-e ../../shared`).

**Verification:**

```bash
python -c "import shared; print(shared.__version__)"
# Expected output: 1.0.0
```

**What Was Fixed:**
1. Created `shared/setup.py` - Makes shared installable as a package
2. Created `shared/__init__.py` - Package initialization
3. Updated all service `requirements.txt` files with `-e ../../shared`

**Manual Installation (if needed):**

```bash
cd /Users/kappasutra/Traffic/shared
pip install -e .
```

---

## 7. AIOKafka 'retries' Parameter Error

**Error:**
```
TypeError: AIOKafkaProducer.__init__() got an unexpected keyword argument 'retries'
```

**Cause:**
- The `retries` parameter was removed in newer versions of `aiokafka`
- When `enable_idempotence=True` is set, retries are automatically enabled
- The library handles retry logic internally

**Solution:**

Remove the `retries` parameter from `AIOKafkaProducer` initialization:

**Before (incorrect):**
```python
self.producer = AIOKafkaProducer(
    bootstrap_servers=self.bootstrap_servers,
    acks='all',
    retries=3,  # ❌ Not supported
    enable_idempotence=True
)
```

**After (correct):**
```python
self.producer = AIOKafkaProducer(
    bootstrap_servers=self.bootstrap_servers,
    acks='all',
    enable_idempotence=True,  # ✅ Includes automatic retries
    request_timeout_ms=30000,
    metadata_max_age_ms=300000
)
```

**What Was Fixed:**
- `services/sensor-fusion/src/kafka/producer.py` - Removed `retries=3`
- `services/ai-perception/src/kafka/producer.py` - Removed `retries=3`

**Note:** When `enable_idempotence=True`, the producer automatically:
- Retries failed requests
- Ensures exactly-once delivery semantics
- Handles duplicate detection

---

## 📝 Debugging Tips

### **Enable Debug Logging**

**In .env:**
```bash
LOG_LEVEL=DEBUG
```

**Or in code:**
```python
logger = setup_logger("my-service", level="DEBUG")
```

### **Check Service Health**

```bash
curl http://localhost:8000/health
```

**Expected:**
```json
{
  "status": "healthy",
  "service": "sensor-fusion",
  "timestamp": "2025-10-01T12:00:00Z",
  "details": {
    "cameras": {"camera_1": true},
    "kafka": true
  }
}
```

### **View Prometheus Metrics**

```bash
curl http://localhost:8000/metrics
```

---

## 🔍 Verification Checklist

After fixes, verify:

- [ ] Service starts without errors
- [ ] No Pydantic warnings
- [ ] Logger works correctly
- [ ] Tests run successfully
- [ ] Coverage report generates
- [ ] API endpoints respond
- [ ] Health check returns healthy

---

## 📞 Getting Help

### **Check Logs:**
```bash
# Service logs (if using systemd/docker)
docker logs atms-sensor-fusion

# Or console output when running directly
python main.py 2>&1 | tee service.log
```

### **Common Commands:**

```bash
# Check Python version
python --version  # Should be 3.11+

# Check installed packages
pip list | grep -E "pydantic|structlog|pytest"

# Verify paths
python -c "import sys; print('\n'.join(sys.path))"
```

---

## ✅ All Issues Fixed

The following issues have been resolved:

1. ✅ Logger type error → Fixed in `shared/utils/logger.py`
2. ✅ Pydantic warnings → Fixed in `shared/models/detection.py`
3. ✅ Missing pytest-cov → Added to `requirements.txt`
4. ✅ Prometheus duplicate metrics → Fixed in `main.py` (both services)
5. ✅ Missing 'shared' module → Created setup.py and added to requirements.txt
6. ✅ Pydantic config validation → Fixed in `config.py`
7. ✅ AIOKafka retries parameter → Removed deprecated parameter

**Status:** Ready to run and test! 🚀

---

**Last Updated:** October 1, 2025  
**All Fixes Applied:** ✅ Yes

