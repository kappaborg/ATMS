# ⚡ ATMS Quick Start

**Get up and running in 20 minutes!**

---

## 🚀 Fast Track Setup

### 1. Download YOLOv8 Model (2 min)

```bash
cd /Users/kappasutra/Traffic/services/ai-perception
mkdir -p models && cd models
wget https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.pt
```

---

### 2. Setup iPhone Camera (5 min)

**On iPhone:**
1. App Store → Install "IP Camera Lite"
2. Open app → "Turn on IP Camera Server"
3. Note IP address (e.g., 192.168.1.100)

**Test in browser:** `http://192.168.1.100:8080`

---

### 3. Configure Camera (3 min)

```bash
cd /Users/kappasutra/Traffic/services/sensor-fusion/src
nano config.py
```

**Find and change:**
```python
CAMERA_IDS: List[str] = ["camera_iphone"]
RTSP_URLS: Dict[str, str] = {
    "camera_iphone": "http://192.168.1.100:8080/video"  # YOUR IP
}
```

**Save:** `Ctrl+O`, `Enter`, `Ctrl+X`

---

### 4. Start Services (1 min)

**Terminal 1 - Sensor Fusion:**
```bash
cd /Users/kappasutra/Traffic/services/sensor-fusion/src
source ../venv/bin/activate
python main.py
```

**Terminal 2 - AI Perception:**
```bash
cd /Users/kappasutra/Traffic/services/ai-perception/src
source ../venv/bin/activate
python main.py
```

---

### 5. Test (1 min)

**Terminal 3:**
```bash
# Test health
curl http://localhost:8000/health | python3 -m json.tool
curl http://localhost:8001/health | python3 -m json.tool

# Test detection (if you have a test image)
curl -X POST http://localhost:8001/detect \
    -F "file=@test_image.jpg" | python3 -m json.tool
```

---

## ✅ Success Checklist

- [ ] YOLOv8 model downloaded (6MB)
- [ ] IP Camera app on iPhone
- [ ] Config updated with iPhone IP
- [ ] Sensor Fusion running on :8000
- [ ] AI Perception running on :8001
- [ ] Health endpoints responding

---

## 📊 Your Terminal Output is CORRECT!

**What you're seeing:**
```
✅ Service started on port 8000
⚠️  Kafka connection refused → Using mock mode (EXPECTED)
⚠️  Camera connection failed → Need to configure iPhone (EXPECTED)
✅ Service running successfully
```

**This is perfect!** The warnings are expected because:
1. No Kafka server (not needed for testing)
2. No RTSP cameras yet (will fix with iPhone)

**The service is working correctly in mock mode!**

---

## 🔧 Quick Commands

### Start Services
```bash
# Sensor Fusion
cd /Users/kappasutra/Traffic/services/sensor-fusion/src && source ../venv/bin/activate && python main.py

# AI Perception
cd /Users/kappasutra/Traffic/services/ai-perception/src && source ../venv/bin/activate && python main.py
```

### Test Services
```bash
# Health checks
curl http://localhost:8000/health
curl http://localhost:8001/health

# Metrics
curl http://localhost:8000/metrics
curl http://localhost:8001/metrics

# API docs
open http://localhost:8000/docs
open http://localhost:8001/docs
```

### Run Tests
```bash
# Sensor Fusion tests
cd /Users/kappasutra/Traffic/services/sensor-fusion
source venv/bin/activate
pytest tests/ -v

# AI Perception tests (60 tests)
cd /Users/kappasutra/Traffic/services/ai-perception
source venv/bin/activate
pytest tests/ -v --cov=src
```

### Stop Services
```bash
# In each terminal running a service
Ctrl+C
```

---

## 🆘 Quick Fixes

### Model Not Found
```bash
cd /Users/kappasutra/Traffic/services/ai-perception/models
wget https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.pt
```

### Shared Module Error
```bash
cd /Users/kappasutra/Traffic/services/sensor-fusion
source venv/bin/activate
pip install -e ../../shared
```

### Port Already in Use
```bash
kill -9 $(lsof -ti:8000)  # Kill process on port 8000
kill -9 $(lsof -ti:8001)  # Kill process on port 8001
```

### Camera Not Connecting
1. Check iPhone app is running
2. Verify same Wi-Fi network
3. Test: `curl http://192.168.1.100:8080/video`
4. Update IP in `config.py`

---

## 📚 Full Documentation

- **Setup:** [DOWNLOAD_AND_SETUP.md](DOWNLOAD_AND_SETUP.md)
- **iPhone:** [IPHONE_CAMERA_SETUP.md](IPHONE_CAMERA_SETUP.md)
- **Testing:** [TESTING_GUIDE.md](TESTING_GUIDE.md)
- **Issues:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

## 🎯 Next Steps

After basic setup works:

1. **Test with real iPhone camera** → See IPHONE_CAMERA_SETUP.md
2. **Run comprehensive tests** → See TESTING_GUIDE.md
3. **Benchmark performance** → See TESTING_GUIDE.md
4. **Start Week 3** → Object Tracking (DeepSORT)

---

**Total Setup Time:** ~20 minutes  
**Services:** 100% Complete (Week 1 + Week 2)  
**Status:** Ready to test! 🚀


