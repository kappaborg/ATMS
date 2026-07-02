# 🔍 Pre-Flight Checklist: 2-Hour Data Collection

**Before starting the 2-hour street data collection, verify ALL systems are working perfectly.**

---

## 📋 Overview

This checklist ensures:
- ✅ All services are operational
- ✅ Detection accuracy is optimal
- ✅ Multi-class detection is working
- ✅ System is stable for long-running operation
- ✅ Data persistence is reliable
- ✅ No data loss will occur

---

## ✅ Checklist

### **1. System Health Check** ⚠️ CRITICAL

**Run:**
```bash
cd /Users/kappasutra/Traffic
./scripts/health_check.sh
```

**Expected Output:**
```
✅ Docker is running
✅ Kafka container is running
✅ Kafka (port 9092) is listening
✅ Zookeeper container is running
✅ Kafka UI container is running
✅ Kafka UI is responding
✅ Sensor Fusion is running
✅ Sensor Fusion API (port 8000) is listening
✅ AI Perception is running
✅ AI Perception API (port 8001) is listening
✅ iPhone camera is reachable
✅ Topic 'camera-frames' exists
✅ Topic 'detections' exists

ALL SYSTEMS OPERATIONAL ✅
```

**Status:** [ ] PASS / [ ] FAIL

---

### **2. Service API Health Checks**

#### **2.1 Sensor Fusion Service**

**Run:**
```bash
curl http://localhost:8000/health
```

**Expected:**
```json
{
  "status": "healthy",
  "service": "sensor-fusion",
  "active_cameras": 1
}
```

**Status:** [ ] PASS / [ ] FAIL

---

#### **2.2 AI Perception Service**

**Run:**
```bash
curl http://localhost:8001/health
```

**Expected:**
```json
{
  "status": "healthy",
  "service": "ai-perception",
  "model_loaded": true
}
```

**Status:** [ ] PASS / [ ] FAIL

---

### **3. Multi-Class Detection Test** ⚠️ CRITICAL

**Purpose:** Verify the system detects ALL object classes, not just pedestrians.

#### **3.1 Test with Multiple Objects**

**Instructions:**
1. Position iPhone camera to see:
   - ✅ At least one vehicle (car, truck, or bus)
   - ✅ At least one person
   - ✅ Good lighting
   - ✅ Clear view

2. Run monitoring for 30 seconds:
   ```bash
   cd /Users/kappasutra/Traffic
   timeout 30 ./monitor.sh
   ```

3. Check detection output shows multiple classes

**Expected Output:**
```
🚗 DETECTIONS BY CLASS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
car             │    XXX │  XX.X% │ ...
pedestrian      │    XXX │  XX.X% │ ...
[other classes if present]
```

**Questions to Answer:**
- [ ] Are cars being detected? (class: "car")
- [ ] Are pedestrians being detected? (class: "pedestrian")
- [ ] Is confidence above 50% on average?
- [ ] Are multiple object classes detected simultaneously?

**Status:** [ ] PASS / [ ] FAIL

---

#### **3.2 Verify Detection in Saved Data**

**Run:**
```bash
# Save 30 seconds of data
timeout 30 ./save_data.sh

# Analyze the saved file
./analyze.sh data/detections/detections_*.jsonl | grep -A 10 "DETECTIONS BY CLASS"
```

**Expected:**
- Multiple object classes in the output
- Not 100% of a single class

**Status:** [ ] PASS / [ ] FAIL

---

### **4. Detection Accuracy Check**

#### **4.1 Current Configuration**

**Verify settings:**
```bash
cd /Users/kappasutra/Traffic/services/ai-perception
grep -E "(CONFIDENCE_THRESHOLD|DETECT_CLASSES|INPUT_SIZE)" src/config.py
```

**Expected:**
```python
CONFIDENCE_THRESHOLD: float = 0.15  # Lower = more detections
DETECT_CLASSES: Optional[List[int]] = None  # None = detect all classes
INPUT_SIZE: Tuple[int, int] = (640, 640)
```

**Status:** [ ] PASS / [ ] FAIL

---

#### **4.2 Confidence Distribution**

**From recent test data:**
```bash
./analyze.sh data/detections/detections_20251002_231351.jsonl | grep -A 10 "CONFIDENCE DISTRIBUTION"
```

**Current Results:**
```
0-25%      │      0 │   0.0%
25-50%     │    180 │   5.5%  ⚠️
50-75%     │    661 │  20.2%
75-90%     │  2,433 │  74.3%  ✅ GOOD
90-100%    │      0 │   0.0%

Average Confidence: 76.3%  ✅ EXCELLENT
```

**Analysis:**
- ✅ 74.3% of detections have 75-90% confidence (excellent!)
- ⚠️ 5.5% have 25-50% confidence (acceptable with 0.15 threshold)
- ✅ Average 76.3% is very good

**Status:** [ ] PASS / [ ] FAIL

---

#### **4.3 Recommendation: Adjust Threshold?**

**Current threshold:** 0.15 (very permissive)

**Options:**

| Threshold | Effect | Recommendation |
|-----------|--------|----------------|
| 0.15 | Catch more objects, more false positives | ✅ Keep for street testing |
| 0.25 | Balanced (default) | Use after initial test |
| 0.35 | Higher accuracy, fewer detections | Use if too many false positives |

**Decision:** [ ] Keep 0.15 / [ ] Change to _____

---

### **5. Camera Stability Test**

#### **5.1 Connection Resilience**

**Test automatic reconnection:**

1. Start monitoring:
   ```bash
   ./monitor.sh
   ```

2. While monitoring is running:
   - Close IP Camera app on iPhone
   - Wait 10 seconds
   - Reopen IP Camera app

3. Check if connection automatically resumes

**Expected:**
- Service logs show "connection lost" then "reconnected"
- Monitoring dashboard continues after brief pause

**Status:** [ ] PASS / [ ] FAIL

---

#### **5.2 Frame Rate Stability**

**Monitor FPS for 2 minutes:**
```bash
timeout 120 ./monitor.sh
```

**Check:**
- [ ] FPS is relatively stable (±2 FPS variance is OK)
- [ ] No long freezes (>5 seconds)
- [ ] Average FPS is 10+ (13+ is excellent)

**Observed FPS:** _____ (Current: 13.28 ✅)

**Status:** [ ] PASS / [ ] FAIL

---

### **6. Kafka Message Flow Test**

#### **6.1 Message Production**

**Check Kafka UI:**
1. Open http://localhost:8080
2. Navigate to Topics → `camera-frames`
3. Navigate to Topics → `detections`

**Verify:**
- [ ] `camera-frames` message count is increasing
- [ ] `detections` message count is increasing
- [ ] Both are roughly equal (±10% is normal)

**Status:** [ ] PASS / [ ] FAIL

---

#### **6.2 Message Content**

**Check message structure:**

1. In Kafka UI, click on `detections` topic
2. Click "Messages"
3. Select newest message
4. Verify JSON structure

**Expected fields:**
```json
{
  "message_id": "...",
  "timestamp": "...",
  "frame_id": "...",
  "sensor_id": "camera_iphone",
  "detections": [
    {
      "detection_id": "...",
      "object_class": "car" or "pedestrian" etc,
      "confidence": 0.XX,
      "bbox": {...}
    }
  ],
  "total_objects": X,
  "objects_by_class": {...}
}
```

**Status:** [ ] PASS / [ ] FAIL

---

### **7. Data Persistence Test**

#### **7.1 Data Saver Reliability**

**Test:**
```bash
# Run for 1 minute
timeout 60 ./save_data.sh

# Check file was created
ls -lh data/detections/
```

**Verify:**
- [ ] File exists
- [ ] File size is reasonable (>100KB for 1 minute)
- [ ] File is growing during collection

**Status:** [ ] PASS / [ ] FAIL

---

#### **7.2 Data Integrity**

**Verify saved data is valid:**
```bash
# Count lines (should be ~800-1000 for 1 minute at 13 FPS)
wc -l data/detections/detections_*.jsonl

# Verify JSON is valid
head -1 data/detections/detections_*.jsonl | python3 -m json.tool > /dev/null && echo "✅ Valid JSON"
```

**Status:** [ ] PASS / [ ] FAIL

---

### **8. Performance Stress Test**

#### **8.1 5-Minute Continuous Operation**

**Purpose:** Ensure system is stable for extended operation

**Run:**
```bash
# Terminal 1: Monitor
timeout 300 ./monitor.sh

# Terminal 2: Save data
timeout 300 ./save_data.sh
```

**Observe:**
- [ ] FPS remains stable
- [ ] No memory leaks (check Activity Monitor)
- [ ] CPU usage is reasonable (<80%)
- [ ] No crashes or restarts

**Metrics After 5 Minutes:**
- Total Frames: _____ (Expected: ~4,000)
- Average FPS: _____ (Expected: 13+)
- Total Detections: _____ (Variable)
- File Size: _____ (Expected: 3-5 MB)

**Status:** [ ] PASS / [ ] FAIL

---

#### **8.2 System Resources**

**Check resource usage:**
```bash
# CPU and Memory
top -l 1 | grep -A 10 "CPU usage"

# Disk space (need >2GB for 2-hour collection)
df -h /Users/kappasutra/Traffic
```

**Verify:**
- [ ] CPU usage <80%
- [ ] Memory available >2GB
- [ ] Disk space >2GB free

**Status:** [ ] PASS / [ ] FAIL

---

### **9. Error Handling Test**

#### **9.1 Service Recovery**

**Test:**
1. Note current detection count in Kafka UI
2. Restart AI Perception service:
   ```bash
   # In AI Perception terminal: Ctrl+C
   # Then restart: python src/main.py
   ```
3. Wait 30 seconds
4. Check if detections resume

**Expected:**
- Service restarts successfully
- Kafka consumer reconnects automatically
- Detections resume flowing

**Status:** [ ] PASS / [ ] FAIL

---

### **10. iPhone Camera Checklist**

#### **10.1 Physical Setup**

- [ ] iPhone is plugged into power
- [ ] iPhone screen is set to "Never" auto-lock
- [ ] IP Camera app is running in foreground
- [ ] Camera has clear view of target area
- [ ] No obstructions in frame
- [ ] Good lighting (not too dark, no glare)
- [ ] Stable mount (no shaking)

#### **10.2 Network**

- [ ] iPhone connected to same WiFi as Mac
- [ ] WiFi signal is strong (3+ bars)
- [ ] No other devices consuming bandwidth
- [ ] Router is stable (not overheating)

#### **10.3 Camera Settings**

**Verify in `services/sensor-fusion/src/config.py`:**
```python
RTSP_URLS: Dict[str, str] = {
    "camera_iphone": "http://192.168.0.10:8081/video",
}
CAMERA_AUTH: Dict[str, tuple] = {
    "camera_iphone": ("admin", "kappa"),
}
CAMERA_ROTATIONS: Dict[str, int] = {
    "camera_iphone": 270,  # Correct orientation
}
```

**Status:** [ ] PASS / [ ] FAIL

---

### **11. Street View Preparation**

#### **11.1 Camera Positioning for Street**

**For optimal traffic detection:**

- [ ] Camera positioned at 2nd floor or higher (better angle)
- [ ] Clear view of street/intersection
- [ ] Can see multiple lanes
- [ ] Can see pedestrian crosswalk (if applicable)
- [ ] Vehicles fill 20-50% of frame when passing
- [ ] Not pointing into sun (avoid glare)
- [ ] Covers 20-30 meter stretch of road

#### **11.2 Expected Detection Rates**

**For a typical street (2-hour collection):**

| Object Type | Expected Count | Notes |
|-------------|----------------|-------|
| Cars | 2,000-8,000 | Main traffic |
| Trucks/Buses | 200-1,000 | Depends on route |
| Motorcycles | 50-500 | Variable |
| Bicycles | 50-500 | Depends on bike lanes |
| Pedestrians | 100-2,000 | Depends on foot traffic |
| Animals | 0-50 | Dogs, cats if present |

**If your counts are WAY below these → camera position issue**

---

### **12. Final Verification Steps**

#### **12.1 Quick Multi-Class Test**

**Before starting 2-hour collection:**

1. Position camera at street view
2. Run 2-minute test:
   ```bash
   timeout 120 ./monitor.sh
   ```
3. Verify you see:
   - ✅ Cars being detected
   - ✅ Other object types (pedestrians, trucks, bikes)
   - ✅ FPS is stable (10+)
   - ✅ Confidence is good (60%+)

**Status:** [ ] PASS / [ ] FAIL

---

#### **12.2 Data Analysis Test**

```bash
# Save 2 minutes of data
timeout 120 ./save_data.sh

# Analyze it
./analyze.sh data/detections/detections_*.jsonl
```

**Check report shows:**
- [ ] Multiple object classes detected
- [ ] Average confidence >60%
- [ ] FPS >10
- [ ] Reasonable vehicle/minute rate

**Status:** [ ] PASS / [ ] FAIL

---

## 📊 Pre-Flight Summary

### **Critical Requirements (MUST PASS ALL)**

- [ ] 1. System Health Check passes completely
- [ ] 2. Both service APIs respond to health checks
- [ ] 3. Multi-class detection working (not just pedestrians)
- [ ] 4. Confidence distribution is acceptable
- [ ] 5. Kafka messages flowing correctly
- [ ] 6. Data saver creates valid files
- [ ] 7. 5-minute stress test completes successfully
- [ ] 8. iPhone camera stable and connected
- [ ] 9. Positioned at street view with traffic visible
- [ ] 10. 2-minute pre-test shows multi-class detections

### **Performance Targets**

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| FPS | 10+ | 13.28 | ✅ |
| Confidence | 60%+ | 76.3% | ✅ |
| Latency | <200ms | ~150ms | ✅ |
| CPU Usage | <80% | ~50% | ✅ |

---

## ⚠️ STOP CONDITIONS

**DO NOT start 2-hour collection if:**

1. ❌ Health check fails
2. ❌ Only detecting one class (e.g., only pedestrians)
3. ❌ FPS <5
4. ❌ Services keep crashing
5. ❌ Data not being saved
6. ❌ Camera not positioned at street view
7. ❌ No vehicles visible in test run

**Fix issues first, then retry checklist!**

---

## ✅ GO CONDITIONS

**Start 2-hour collection when:**

1. ✅ ALL critical requirements pass
2. ✅ Multi-class detection verified on street view
3. ✅ System stable for 5+ minutes
4. ✅ FPS ≥10
5. ✅ Average confidence ≥60%
6. ✅ Data saving and analysis working
7. ✅ iPhone battery charging
8. ✅ Network stable

---

## 🚀 Ready to Launch!

**When all checks pass:**

```bash
# Terminal 1: Start monitoring
./monitor.sh

# Terminal 2: Start data saver
./save_data.sh

# Wait 2 hours (7,200 seconds)

# Stop both with Ctrl+C

# Analyze results
./analyze.sh data/detections/detections_*.jsonl
```

---

## 📝 Checklist Completion

**Date:** _____________  
**Time:** _____________  
**Tested By:** _____________  

**Overall Status:** [ ] READY FOR 2-HOUR COLLECTION / [ ] NEEDS FIXES

**Notes:**
```
[Write any observations or issues here]




```

---

**Document Version:** 1.0  
**Last Updated:** October 2, 2025  
**Status:** Pre-Flight Verification Tool


