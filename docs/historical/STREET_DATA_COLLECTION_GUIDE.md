# 🚗 Street Data Collection Guide

Complete guide for collecting 2 hours of real traffic detection data.

## 📋 Overview

This guide will help you:
- Set up a stable 2-hour data collection session
- Monitor detections in real-time
- Save all data for analysis
- Analyze results after collection

---

## 🎯 Objectives

1. **Validate** YOLOv8 detection on real traffic
2. **Measure** performance (FPS, accuracy, detection rates)
3. **Collect** dataset for traffic metrics development
4. **Identify** optimization needs

---

## 🔧 Prerequisites

### Hardware
- ✅ iPhone with IP Camera app installed
- ✅ iPhone charging cable (plugged in during collection)
- ✅ Stable mount for iPhone (tripod, window mount, etc.)
- ✅ Mac with sufficient disk space (~500MB-1GB for 2 hours)

### Software
- ✅ All services installed and tested
- ✅ Kafka running
- ✅ Camera tested and working

---

## 🚀 Step-by-Step Instructions

### 1. Position Your iPhone Camera

📷 **Camera Placement Tips:**
- Good view of traffic (cars, trucks, pedestrians)
- Stable mount (avoid shaking)
- Adequate lighting (avoid direct sun glare)
- iPhone plugged into power
- Keep IP Camera app in foreground
- Disable auto-lock on iPhone

🎯 **Recommended Views:**
- Street intersection (best for ATMS)
- Highway segment
- Parking lot entrance
- Pedestrian crosswalk

---

### 2. Start Infrastructure & Services

```bash
cd /Users/kappasutra/Traffic

# Run the master startup script
./scripts/start_data_collection.sh
```

This script will:
1. ✅ Run health checks
2. ✅ Verify all services are running
3. ✅ Check Kafka connectivity
4. ✅ Test camera connection
5. ✅ Create data directories
6. ✅ Display next steps

---

### 3. Start Monitoring Tools

You need **3 separate terminal windows**:

#### Terminal 1: Real-Time Monitoring Dashboard

```bash
cd /Users/kappasutra/Traffic
python3 scripts/monitor_detections.py
```

**What it shows:**
- Live FPS
- Detection counts
- Objects by class
- Processing time
- Progress toward 2-hour goal

**Refreshes every second**

---

#### Terminal 2: Data Saver (Critical!)

```bash
cd /Users/kappasutra/Traffic
python3 scripts/save_detections.py
```

**What it does:**
- Saves ALL detections to JSONL file
- Prevents data loss
- Creates timestamped files in `data/detections/`
- Progress updates every 10 frames

**DO NOT CLOSE THIS TERMINAL** during collection!

---

#### Terminal 3: Service Logs (Optional)

Keep an eye on your service terminals for errors:
- Sensor Fusion: Port 8000
- AI Perception: Port 8001

---

### 4. Monitor Collection

**While Running:**

1. **Check Real-Time Dashboard** (Terminal 1)
   - Is FPS stable? (Target: 10-30 FPS)
   - Are objects being detected?
   - Any errors?

2. **Check Data Saver** (Terminal 2)
   - Is it saving frames?
   - File size growing?

3. **Check Kafka UI** (Optional)
   - http://localhost:8080
   - Topics: `camera-frames`, `detections`
   - Message counts increasing?

4. **Spot Check Detection Quality**
   - Are cars/trucks/pedestrians detected correctly?
   - False positives?
   - False negatives?

**Warning Signs:**
- ⚠️ FPS drops below 5
- ⚠️ No detections for >1 minute
- ⚠️ Data saver stops saving
- ⚠️ Service crashes

If you see warnings, **stop collection**, fix issues, and restart.

---

### 5. After 2 Hours

#### Stop Collection

1. Stop monitoring dashboard (Terminal 1): `Ctrl+C`
2. Stop data saver (Terminal 2): `Ctrl+C`
   - Note the output file path!

#### Verify Data Saved

```bash
ls -lh /Users/kappasutra/Traffic/data/detections/
```

You should see a file like:
```
detections_20251002_140000.jsonl  (500MB - 1GB)
```

---

### 6. Analyze Results

Run the analysis tool:

```bash
cd /Users/kappasutra/Traffic

python3 scripts/analyze_detections.py data/detections/detections_YYYYMMDD_HHMMSS.jsonl
```

**Analysis Report Includes:**
- ⏱️ Collection duration
- 📹 Total frames, average FPS
- 🚗 Total detections by class
- 🎯 Confidence distribution
- 🚦 Traffic insights (vehicles/minute, pedestrians/minute)
- 💡 Recommendations for optimization

---

## 📊 Expected Results

### Good Collection Session:
- ✅ 7,200+ frames (2 hours @ 1 FPS minimum)
- ✅ 10-30 FPS average
- ✅ 1,000+ vehicle detections
- ✅ 50-80% average confidence
- ✅ Multiple object classes detected
- ✅ Data file 500MB - 1GB

### Issues to Fix:
- ❌ FPS < 5 → Need optimization (TensorRT, smaller model)
- ❌ < 100 detections → Camera position/view issue
- ❌ Low confidence < 40% → Camera quality/lighting issue
- ❌ Missing classes → Model not detecting properly

---

## 🔍 Troubleshooting

### Problem: No Detections

**Solutions:**
1. Check camera view (can YOU see vehicles?)
2. Check lighting (too dark? too bright?)
3. Verify services are running
4. Check Kafka UI for messages

### Problem: Low FPS (<5)

**Solutions:**
1. Close other applications
2. Check CPU/memory usage
3. Consider model optimization
4. Use smaller model (yolov8n)

### Problem: Service Crashes

**Solutions:**
1. Check service logs for errors
2. Restart services
3. Run health check: `./scripts/health_check.sh`
4. Check camera connection

### Problem: Data Not Saving

**Solutions:**
1. Check disk space
2. Verify data saver is running
3. Check file permissions
4. Look for errors in Terminal 2

---

## 📁 Files Created

After collection, you'll have:

```
/Users/kappasutra/Traffic/
├── data/
│   └── detections/
│       └── detections_20251002_140000.jsonl  ← Your data!
```

**File Format:** JSONL (one JSON object per line)

Each line contains:
```json
{
  "message_id": "...",
  "timestamp": "2025-10-02T14:30:45.123456Z",
  "frame_id": "1234",
  "sensor_id": "camera_iphone",
  "detections": [
    {
      "detection_id": "1234_0",
      "object_class": "car",
      "confidence": 0.85,
      "bbox": {"x1": 100, "y1": 200, "x2": 300, "y2": 400}
    }
  ],
  "total_objects": 1,
  "processing_time_ms": 45.2
}
```

---

## 🎯 Next Steps After Collection

Based on analysis results:

### If Performance is Good (FPS > 15, Good Detections):
1. ✅ Proceed to Week 3: Object Tracking (DeepSORT)
2. ✅ Use collected data for tracking development
3. ✅ Implement traffic metrics

### If Performance Needs Improvement:
1. ⚡ Optimize model (TensorRT, FP16)
2. ⚡ Batch inference
3. ⚡ Consider yolov8n → yolov8s tradeoff
4. ⚡ Hardware acceleration

### If Detection Quality is Poor:
1. 🔧 Adjust camera position
2. 🔧 Improve lighting
3. 🔧 Try different detection thresholds
4. 🔧 Fine-tune model on your data

---

## 📞 Quick Commands Reference

```bash
# Start everything
./scripts/start_data_collection.sh

# Health check
./scripts/health_check.sh

# Monitor detections
python3 scripts/monitor_detections.py

# Save detections
python3 scripts/save_detections.py

# Analyze results
python3 scripts/analyze_detections.py data/detections/FILE.jsonl

# Check Kafka UI
open http://localhost:8080
```

---

## ✅ Pre-Flight Checklist

Before starting 2-hour collection:

- [ ] iPhone positioned at street view
- [ ] iPhone plugged into power
- [ ] IP Camera app running in foreground
- [ ] Health check passes
- [ ] Kafka running
- [ ] Services running (Sensor Fusion, AI Perception)
- [ ] Camera connection tested
- [ ] Disk space available (>2GB free)
- [ ] 3 terminals ready
- [ ] Monitoring dashboard tested
- [ ] Data saver tested

**When all checked, you're ready to start!** 🚀

---

## 📈 Success Metrics

After collection, you should be able to answer:

1. **Performance:**
   - What is the average FPS?
   - Is it stable or fluctuating?
   - Processing time per frame?

2. **Detection Quality:**
   - How many vehicles detected?
   - Detection rate (detected / actual)?
   - Average confidence?
   - False positive rate?

3. **Traffic Insights:**
   - Vehicles per minute?
   - Peak traffic times?
   - Object class distribution?

4. **System Stability:**
   - Any crashes?
   - Any data loss?
   - Camera disconnections?

These insights will guide your Week 3 development! 🎯

---

**Good luck with your data collection!** 🚀

If you encounter issues, refer to the troubleshooting section or check service logs.


