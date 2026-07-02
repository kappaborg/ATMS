# 📹 IP Camera Setup Guide for ATMS

## **Which Server/Service Handles IP Cameras?**

---

## 🎯 **Answer: AI Perception Service (Port 8004)**

The **AI Perception Service** is the only service that directly handles camera input (IP cameras, USB cameras, webcams).

**Service Details**:
- **Service**: `integrated_perception_service.py`
- **Port**: 8004
- **Location**: `/Users/kappasutra/Traffic/services/ai-perception/src/`
- **Purpose**: Camera input, video processing, CoreML inference, detection

---

## 📊 **System Architecture for Camera Input**

```
IP Camera / iPhone Camera
        ↓
   (Video Stream)
        ↓
AI Perception Service (Port 8004) ← Only service that handles cameras
        ↓
   CoreML Models (Detection)
        ↓
   Kafka Topics (Data streaming)
        ↓
Other Microservices (Data processing)
```

**Key Point**: Other services (Data Aggregator, Decision Engine, Traffic Controller) do NOT handle cameras directly. They only process detection results from Kafka.

---

## 🔍 **Currently Running Services (From Your Screenshot)**

Based on your Docker Desktop:

| Service | Container | Port | Status | Handles Camera? |
|---------|-----------|------|--------|-----------------|
| **kafka-ui** | provectuslabs/kafka | 8080 | ✅ Running | ❌ No (UI only) |
| **kafka** | confluentinc/cp-kafka | 9092 | ✅ Running | ❌ No (messaging) |
| **zookeeper** | confluentinc/cp-zookeeper | 2181 | ✅ Running | ❌ No (coordination) |
| **postgres** | postgres:15-alpine | 5432 | ✅ Running | ❌ No (database) |
| **redis** | redis:7-alpine | 6379 | ✅ Running | ❌ No (cache) |
| **pgadmin** | dpage/pgadmin4 | 5050 | ⚠️ Starting | ❌ No (DB admin) |

**Missing**: AI Perception Service (Port 8004) ← **This is what handles cameras!**

---

## 🚀 **How to Setup IP Camera**

### **Step 1: Start AI Perception Service**

The AI Perception Service is the ONLY service that can handle IP cameras:

```bash
cd /Users/kappasutra/Traffic/services/ai-perception
source venv/bin/activate
python src/integrated_perception_service.py
```

**Expected Output**:
```
INFO:     Uvicorn running on http://0.0.0.0:8004
✅ All 4 CoreML models loaded
✅ Service ready to accept camera input
```

---

### **Step 2: Configure IP Camera URL**

Once AI Perception is running, send camera URL:

#### **For iPhone Camera (DroidCam/IP Webcam)**:

**Option A: DroidCam** (Recommended)
1. Install DroidCam app on iPhone
2. Note the IP address shown (e.g., `http://192.168.1.100:4747`)
3. Use this URL:

```bash
curl -X POST "http://localhost:8004/start" \
  -H "Content-Type: application/json" \
  -d '{"camera_url": "http://192.168.1.100:4747/video"}'
```

**Option B: IP Webcam App**
1. Install IP Webcam app
2. Note IP shown (e.g., `http://192.168.1.100:8080`)
3. Use this URL:

```bash
curl -X POST "http://localhost:8004/start" \
  -H "Content-Type: application/json" \
  -d '{"camera_url": "http://192.168.1.100:8080/video"}'
```

#### **For RTSP Camera** (Professional IP cameras):

```bash
curl -X POST "http://localhost:8004/start" \
  -H "Content-Type: application/json" \
  -d '{"camera_url": "rtsp://username:password@192.168.1.100:554/stream1"}'
```

#### **For HTTP/MJPEG Stream**:

```bash
curl -X POST "http://localhost:8004/start" \
  -H "Content-Type: application/json" \
  -d '{"camera_url": "http://192.168.1.100/video.mjpeg"}'
```

---

## 📱 **iPhone Camera Setup (Detailed)**

### **Recommended Apps**:

1. **DroidCam** (Best for iOS)
   - App Store: Search "DroidCam"
   - Free version available
   - Stable connection
   - Low latency

2. **IP Webcam** (Alternative)
   - Good quality
   - More features
   - Slightly higher latency

### **Step-by-Step**:

#### **1. Install DroidCam on iPhone**
```
iPhone → App Store → Search "DroidCam" → Install
```

#### **2. Start DroidCam**
- Open app
- Note the WiFi IP address shown (e.g., `192.168.1.150`)
- Note the port (usually `4747`)
- Keep app running

#### **3. Test Connection** (From your Mac)

```bash
# Test if stream is accessible
curl -I http://192.168.1.150:4747/video

# Expected: HTTP/200 OK response
```

#### **4. Connect to ATMS**

```bash
# Make sure AI Perception is running on port 8004
curl http://localhost:8004/health

# Then start camera detection
curl -X POST "http://localhost:8004/start" \
  -H "Content-Type: application/json" \
  -d '{"camera_url": "http://192.168.1.150:4747/video"}'
```

#### **5. Verify Detection**

```bash
# Check if detection is working
curl http://localhost:8004/stats | python3 -m json.tool

# Expected output:
{
  "status": "running",
  "fps": 26.9,
  "camera": {
    "source": "http://192.168.1.150:4747/video",
    "resolution": "1280x720",
    "connected": true
  },
  "detections": {
    "vehicles": 5,
    "license_plates": 3
  }
}
```

---

## 🔧 **Troubleshooting IP Camera Connection**

### **Problem 1: Can't connect to iPhone camera**

**Check 1: Same WiFi Network**
```bash
# Your Mac and iPhone must be on same WiFi
# Check your Mac's IP
ifconfig | grep "inet " | grep -v 127.0.0.1

# Example output: 192.168.1.X
# iPhone should be 192.168.1.Y
```

**Check 2: Test camera URL directly**
```bash
# Open in browser or test with curl
curl -I http://IPHONE_IP:4747/video

# Should return: HTTP/200 OK
```

**Check 3: Firewall**
```bash
# Make sure Mac firewall allows incoming connections
# System Settings → Network → Firewall
```

### **Problem 2: Low FPS or Laggy Video**

**Solution 1: Reduce Resolution**
```bash
# In DroidCam app settings:
# Video Quality → Set to "Medium" or "Low"
# Resolution → Set to 720p or 480p
```

**Solution 2: Check Network**
```bash
# Test network speed between iPhone and Mac
ping IPHONE_IP

# Should have <10ms latency
```

### **Problem 3: Connection Drops**

**Solution**: Use WiFi instead of cellular
```bash
# Make sure iPhone is connected to WiFi, not cellular data
# iPhone → Settings → WiFi → Connected to same network as Mac
```

---

## 🎥 **Other IP Camera Options**

### **Professional IP Cameras** (Hikvision, Dahua, etc.):

**RTSP Stream**:
```bash
# Standard RTSP format
rtsp://username:password@camera_ip:554/Streaming/Channels/101

# Example for Hikvision
rtsp://admin:password@192.168.1.100:554/Streaming/Channels/101

# Example for Dahua  
rtsp://admin:password@192.168.1.101:554/cam/realmonitor?channel=1&subtype=0
```

**HTTP Stream**:
```bash
# Some cameras support HTTP/MJPEG
http://camera_ip/video.mjpeg
http://camera_ip/cgi-bin/video.cgi
```

### **USB IP Camera Adapters**:

If you have a USB camera that you want to use remotely:

```bash
# Use tools like mjpg-streamer
mjpg_streamer -i "input_uvc.so -d /dev/video0" -o "output_http.so -p 8080"

# Then access via
http://localhost:8080/?action=stream
```

---

## 📊 **Camera Stream Formats Supported**

The AI Perception Service (via OpenCV) supports:

| Format | Protocol | Example | Support |
|--------|----------|---------|---------|
| **RTSP** | rtsp:// | `rtsp://192.168.1.100:554/stream` | ✅ Yes |
| **HTTP/MJPEG** | http:// | `http://192.168.1.100/video.mjpeg` | ✅ Yes |
| **HTTP Stream** | http:// | `http://192.168.1.100:8080/video` | ✅ Yes |
| **Local File** | file:// | `file:///path/to/video.mp4` | ✅ Yes |
| **USB Camera** | Camera ID | `0`, `1`, `2`, etc. | ✅ Yes |

---

## 🔍 **How to Find Your Camera's Stream URL**

### **Method 1: Check Camera Documentation**
- Look for "RTSP URL" or "Stream URL" in manual
- Usually format: `rtsp://ip:port/path`

### **Method 2: Use ONVIF Device Manager** (For IP cameras)
```bash
# Download ONVIF Device Manager (free)
# It will scan network and find IP cameras
# Shows RTSP URLs automatically
```

### **Method 3: Try Common URLs**
```bash
# Hikvision
rtsp://admin:password@IP:554/Streaming/Channels/101
rtsp://admin:password@IP:554/Streaming/Channels/1

# Dahua
rtsp://admin:password@IP:554/cam/realmonitor?channel=1&subtype=0

# Generic
rtsp://IP:554/
rtsp://IP:554/live
rtsp://IP:554/stream1
```

---

## ✅ **Quick Test Script**

Create `test_camera_url.py`:

```python
#!/usr/bin/env python3
import cv2
import sys

def test_camera(url):
    print(f"Testing camera URL: {url}")
    
    cap = cv2.VideoCapture(url)
    
    if not cap.isOpened():
        print("❌ Failed to open camera")
        return False
    
    ret, frame = cap.read()
    if not ret:
        print("❌ Failed to read frame")
        return False
    
    print(f"✅ Camera working!")
    print(f"   Resolution: {frame.shape[1]}x{frame.shape[0]}")
    print(f"   FPS: {cap.get(cv2.CAP_PROP_FPS)}")
    
    cap.release()
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_camera_url.py <camera_url>")
        print("Example: python test_camera_url.py http://192.168.1.100:4747/video")
        sys.exit(1)
    
    test_camera(sys.argv[1])
```

**Usage**:
```bash
python test_camera_url.py "http://192.168.1.150:4747/video"
```

---

## 📝 **Summary**

### **Which Service Handles IP Cameras?**
✅ **AI Perception Service (Port 8004)** - This is the ONLY service that handles cameras

### **Your Current Setup**:
- ✅ Kafka running (Port 9092)
- ✅ PostgreSQL running (Port 5432)
- ✅ Redis running (Port 6379)
- ⚠️ **Need to start**: AI Perception Service (Port 8004)

### **To Use IP Camera**:
1. Start AI Perception Service on port 8004
2. Get iPhone IP from DroidCam app
3. Send camera URL to `http://localhost:8004/start`
4. System will process at 26.9 FPS with CoreML!

---

## 🚀 **Quick Commands**

```bash
# 1. Start AI Perception (if not running)
cd /Users/kappasutra/Traffic/services/ai-perception
source venv/bin/activate
python src/integrated_perception_service.py

# 2. Connect iPhone camera
curl -X POST "http://localhost:8004/start" \
  -H "Content-Type: application/json" \
  -d '{"camera_url": "http://YOUR_IPHONE_IP:4747/video"}'

# 3. Check stats
curl http://localhost:8004/stats | python3 -m json.tool
```

---

**Your infrastructure is ready! Just need to start AI Perception Service to use IP cameras!** 📹🚀

