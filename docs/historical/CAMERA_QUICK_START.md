# 📹 Your Camera Quick Start Guide

## **Your Camera**: `http://192.168.0.11:8081/`

---

## 🎯 **Quick Steps to Use Your Camera**

### **Step 1: Start AI Perception Service**

The AI Perception service on port 8004 is the ONLY service that handles cameras.

```bash
cd /Users/kappasutra/Traffic/services/ai-perception
source venv/bin/activate
python src/integrated_perception_service.py
```

Wait for:
```
INFO:     Uvicorn running on http://0.0.0.0:8004
✅ All 4 CoreML models loaded
```

---

### **Step 2: Connect Your Camera**

Your camera is at: `http://192.168.0.11:8081/`

**Try these URLs** (test which one works):

#### **Option A: Direct video stream**
```bash
curl -X POST "http://localhost:8004/start" \
  -H "Content-Type: application/json" \
  -d '{"camera_url": "http://192.168.0.11:8081/video"}'
```

#### **Option B: MJPEG stream**
```bash
curl -X POST "http://localhost:8004/start" \
  -H "Content-Type: application/json" \
  -d '{"camera_url": "http://192.168.0.11:8081/video.mjpeg"}'
```

#### **Option C: Root path**
```bash
curl -X POST "http://localhost:8004/start" \
  -H "Content-Type: application/json" \
  -d '{"camera_url": "http://192.168.0.11:8081/"}'
```

#### **Option D: Stream endpoint**
```bash
curl -X POST "http://localhost:8004/start" \
  -H "Content-Type: application/json" \
  -d '{"camera_url": "http://192.168.0.11:8081/stream"}'
```

---

### **Step 3: Test Which URL Works**

Before sending to ATMS, test in browser or with curl:

```bash
# Test in browser
open http://192.168.0.11:8081/

# Or test with curl
curl -I http://192.168.0.11:8081/video
curl -I http://192.168.0.11:8081/video.mjpeg
curl -I http://192.168.0.11:8081/stream
```

Look for `HTTP/200 OK` response.

---

### **Step 4: Verify Detection Working**

```bash
# Check service status
curl http://localhost:8004/health | python3 -m json.tool

# Check detection stats (should show ~27 FPS)
curl http://localhost:8004/stats | python3 -m json.tool
```

Expected output:
```json
{
  "status": "running",
  "fps": 26.9,
  "camera": {
    "source": "http://192.168.0.11:8081/video",
    "connected": true
  },
  "detections": {
    "vehicles": 3,
    "license_plates": 2
  }
}
```

---

## 🔧 **Troubleshooting**

### **Problem: Can't connect to camera**

**Test 1: Check camera is accessible**
```bash
# From your Mac, test the camera
curl -I http://192.168.0.11:8081/

# Expected: HTTP/200 OK
```

**Test 2: Check what endpoints the camera has**
```bash
# Try opening in browser
open http://192.168.0.11:8081/

# Common endpoints:
# /video
# /video.mjpeg  
# /stream
# /cam
# /live
```

**Test 3: Network connectivity**
```bash
# Ping the camera
ping 192.168.0.11

# Should show response time < 10ms
```

---

### **Problem: Wrong camera URL**

Your camera app might use different paths. Check the app documentation or try:

```bash
# IP Webcam app paths:
http://192.168.0.11:8081/video
http://192.168.0.11:8081/videofeed
http://192.168.0.11:8081/stream.mjpg

# DroidCam paths:
http://192.168.0.11:8081/video
http://192.168.0.11:8081/mjpegfeed

# Generic paths:
http://192.168.0.11:8081/
http://192.168.0.11:8081/cam
http://192.168.0.11:8081/live
```

---

## 📝 **Test Camera URL Script**

Create a quick test:

```python
#!/usr/bin/env python3
import cv2

# Test your camera URL
camera_url = "http://192.168.0.11:8081/video"

print(f"Testing: {camera_url}")
cap = cv2.VideoCapture(camera_url)

if cap.isOpened():
    ret, frame = cap.read()
    if ret:
        print(f"✅ Camera working!")
        print(f"   Resolution: {frame.shape[1]}x{frame.shape[0]}")
    else:
        print("❌ Can't read frame")
else:
    print("❌ Can't open camera")

cap.release()
```

Run it:
```bash
cd /Users/kappasutra/Traffic/services/ai-perception
source venv/bin/activate
python test_camera.py
```

---

## 🚀 **Complete Commands**

```bash
# 1. Create log directories (already done)
mkdir -p services/ai-perception/logs

# 2. Start AI Perception
cd /Users/kappasutra/Traffic/services/ai-perception
source venv/bin/activate
python src/integrated_perception_service.py

# 3. In another terminal, connect camera
# (Replace /video with correct endpoint)
curl -X POST "http://localhost:8004/start" \
  -H "Content-Type: application/json" \
  -d '{"camera_url": "http://192.168.0.11:8081/video"}'

# 4. Check it's working
curl http://localhost:8004/stats | python3 -m json.tool
```

---

## 📱 **What Camera App Are You Using?**

Different apps use different URL formats:

**IP Webcam** (Android/iOS):
```
http://192.168.0.11:8081/video
http://192.168.0.11:8081/videofeed
```

**DroidCam**:
```
http://192.168.0.11:4747/video
http://192.168.0.11:4747/mjpegfeed
```

**Other Apps**:
- Check the app's settings
- Look for "Video Feed URL" or "Stream URL"
- Usually shows the exact URL to use

---

## ✅ **Quick Test Checklist**

- [ ] AI Perception service running on port 8004
- [ ] Can access camera in browser: `http://192.168.0.11:8081/`
- [ ] Tested camera URL with curl or browser
- [ ] Found correct endpoint (/video, /stream, etc.)
- [ ] Sent camera URL to AI Perception
- [ ] Verified detection working with stats endpoint

---

**Your camera is ready! Just need to find the correct endpoint path.** 📹🚀

