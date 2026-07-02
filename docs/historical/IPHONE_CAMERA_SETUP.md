# 📱 iPhone 15 Pro Camera Setup for ATMS

**Guide for using iPhone 15 Pro as a camera source for testing ATMS**

---

## 🎯 Overview

Your iPhone 15 Pro can be used as a high-quality camera source for ATMS testing. It features:
- **Main Camera:** 48MP wide camera
- **LiDAR Scanner:** Depth sensing capability (bonus feature!)
- **High-quality video:** Up to 4K @ 60fps
- **Wi-Fi streaming:** Can stream over local network

---

## 📋 Method 1: IP Camera App (Recommended - Easiest)

### Step 1: Install IP Camera App

**Option A: IP Camera Lite (Free)**
1. Open App Store on iPhone
2. Search for "IP Camera Lite"
3. Install the app
4. Launch the app

**Option B: iVCam (Recommended - Better quality)**
1. App Store → Search "iVCam"
2. Install on iPhone
3. Also install iVCam client on Mac: https://www.e2esoft.com/ivcam/

### Step 2: Configure IP Camera Lite

```
1. Open "IP Camera Lite" on iPhone
2. Tap "Turn on IP Camera Server"
3. Note the URL shown (e.g., http://192.168.1.100:8080)
4. The stream URL will be: http://192.168.1.100:8080/video
```

### Step 3: Update ATMS Configuration

Create or edit `.env` in `services/sensor-fusion/`:

```bash
# Camera Configuration
CAMERA_IDS=["camera_iphone"]
CAMERA_RESOLUTION=(1920, 1080)
CAMERA_FPS=30

# Replace with your iPhone's IP
CAMERA_RTSP_camera_iphone=http://192.168.1.100:8080/video
```

Or update the config file directly:

```bash
cd /Users/kappasutra/Traffic/services/sensor-fusion/src
```

Edit `config.py`:

```python
CAMERA_IDS: List[str] = ["camera_iphone"]
RTSP_URLS: Dict[str, str] = {
    "camera_iphone": "http://192.168.1.100:8080/video"  # Your iPhone IP
}
```

---

## 📋 Method 2: OBS Studio (Professional Grade)

### Step 1: Install OBS Studio on Mac

```bash
# Using Homebrew
brew install --cask obs

# Or download from: https://obsproject.com/
```

### Step 2: Setup iPhone as Camera Source

**Using OBS Camera for iOS:**
1. Install "OBS Camera" app from App Store on iPhone
2. Open OBS Studio on Mac
3. Sources → Add → "iOS Camera"
4. Connect iPhone via USB or Wi-Fi
5. Select your iPhone camera

**Using Continuity Camera (macOS Ventura+):**
1. Keep iPhone near Mac
2. OBS Studio → Sources → Add → "Video Capture Device"
3. Select your iPhone from the device list
4. Choose camera (Wide/Ultra-wide)

### Step 3: Start RTSP Server

**Install RTSP Simple Server:**

```bash
cd /Users/kappasutra/Traffic
mkdir rtsp-server
cd rtsp-server

# Download RTSP Simple Server
wget https://github.com/aler9/rtsp-simple-server/releases/download/v0.21.6/rtsp-simple-server_v0.21.6_darwin_amd64.tar.gz

# Extract
tar -xzf rtsp-simple-server_v0.21.6_darwin_amd64.tar.gz

# Run server
./rtsp-simple-server
```

**Configure OBS to stream to RTSP:**
1. OBS → Settings → Stream
2. Service: Custom
3. Server: `rtsp://localhost:8554/stream1`
4. Start Streaming

**Update ATMS config:**

```python
RTSP_URLS: Dict[str, str] = {
    "camera_iphone": "rtsp://localhost:8554/stream1"
}
```

---

## 📋 Method 3: NDI (Network Device Interface) - Best Quality

### Step 1: Install NDI Tools

```bash
# Download NDI Tools from:
# https://ndi.tv/tools/

# Install NDI HX Camera app on iPhone (App Store)
```

### Step 2: Setup

1. Install NDI HX Camera on iPhone
2. Install NDI Tools on Mac
3. Connect iPhone and Mac to same Wi-Fi
4. Open NDI HX Camera on iPhone
5. On Mac, use NDI Video Monitor to verify stream

### Step 3: Convert NDI to RTSP

```bash
# Install FFmpeg
brew install ffmpeg

# Stream NDI to RTSP (replace with your iPhone's NDI source name)
ffmpeg -f avfoundation -i "iPhone (NDI HX)" \
    -c:v libx264 -preset ultrafast -tune zerolatency \
    -f rtsp rtsp://localhost:8554/stream1
```

---

## 🚀 Quick Start (Recommended for Testing)

### Easiest Method: HTTP Stream with IP Camera Lite

**Step 1: Setup iPhone**
```
1. Install "IP Camera Lite" from App Store
2. Open app → "Turn on IP Camera Server"
3. Note the IP address shown (e.g., 192.168.1.100)
```

**Step 2: Test Stream**
```bash
# Open browser and visit:
http://192.168.1.100:8080

# You should see the camera feed
```

**Step 3: Update ATMS Camera Adapter**

The current camera adapter uses OpenCV which supports HTTP streams!

Edit `/Users/kappasutra/Traffic/services/sensor-fusion/src/config.py`:

```python
class CameraConfig(BaseSettings):
    CAMERA_IDS: List[str] = ["camera_iphone"]
    RTSP_URLS: Dict[str, str] = {
        "camera_iphone": "http://192.168.1.100:8080/video"  # Replace with your IP
    }
```

**Step 4: Restart Service**

```bash
cd /Users/kappasutra/Traffic/services/sensor-fusion/src
python main.py
```

---

## 🧪 Testing the Setup

### Test 1: Verify Camera Stream

```bash
# Test with VLC Media Player
# File → Open Network Stream → Enter your stream URL

# Or test with FFmpeg
ffmpeg -i http://192.168.1.100:8080/video -frames 1 test_frame.jpg
```

### Test 2: Test ATMS Integration

```bash
# Start sensor-fusion service
cd /Users/kappasutra/Traffic/services/sensor-fusion/src
python main.py

# In another terminal, check health
curl http://localhost:8000/health

# Check camera status
curl http://localhost:8000/cameras
```

### Test 3: Test AI Perception

```bash
# If camera is working, start AI perception
cd /Users/kappasutra/Traffic/services/ai-perception/src
python main.py

# Test detection on a frame
curl -X POST http://localhost:8001/detect \
    -F "file=@test_frame.jpg"
```

---

## 📊 Network Configuration

### Find Your iPhone's IP Address

**On iPhone:**
```
Settings → Wi-Fi → (i) next to connected network → IP Address
```

**On Mac (scan for iPhone):**
```bash
# Install nmap
brew install nmap

# Scan local network
nmap -sn 192.168.1.0/24 | grep -B 2 "iPhone"
```

### Ensure Same Network

Both iPhone and Mac must be on the **same Wi-Fi network**:
- iPhone: Settings → Wi-Fi → [Your Network]
- Mac: System Preferences → Network → Wi-Fi → [Same Network]

---

## 🎨 Using LiDAR Data (Future Enhancement)

Your iPhone 15 Pro's LiDAR scanner can provide depth data!

### For Week 4+ (LiDAR Integration):

**Using ARKit (iOS App Required):**
1. Create custom iOS app using ARKit
2. Capture RGB + Depth frames
3. Send to ATMS via WebSocket

**Benefits:**
- 3D point cloud data
- Accurate depth estimation
- Enhanced object detection
- Better occlusion handling

**Simple LiDAR Test App Structure:**
```swift
import ARKit

// Capture RGB + Depth
let arConfig = ARWorldTrackingConfiguration()
arConfig.frameSemantics = .sceneDepth

// Send to ATMS
socket.send(rgb: rgbFrame, depth: depthMap)
```

---

## 🔧 Troubleshooting

### Issue: Can't see camera stream

**Check:**
1. iPhone and Mac on same Wi-Fi?
2. Firewall blocking port 8080?
3. IP Camera app running on iPhone?

**Fix:**
```bash
# Check if port is accessible
nc -zv 192.168.1.100 8080

# If blocked, check macOS firewall:
System Preferences → Security & Privacy → Firewall
```

### Issue: Stream is laggy

**Solutions:**
1. Reduce resolution in IP Camera app
2. Use 5GHz Wi-Fi (not 2.4GHz)
3. Move iPhone closer to Wi-Fi router
4. Use USB connection with iVCam

### Issue: ATMS can't connect to stream

**Check:**
```bash
# Test stream with ffplay
ffplay http://192.168.1.100:8080/video

# Check ATMS logs
tail -f /tmp/sensor_fusion.log
```

**Verify config:**
```bash
cd /Users/kappasutra/Traffic/services/sensor-fusion/src
cat config.py | grep RTSP_URLS
```

---

## 📱 Recommended Apps Comparison

| App | Cost | Quality | Ease of Use | Features |
|-----|------|---------|-------------|----------|
| IP Camera Lite | Free | Good | ⭐⭐⭐⭐⭐ | HTTP stream, simple |
| iVCam | Free/Paid | Excellent | ⭐⭐⭐⭐ | USB+WiFi, low latency |
| NDI HX Camera | Paid | Excellent | ⭐⭐⭐ | Professional, NDI protocol |
| OBS Camera | Free | Good | ⭐⭐⭐⭐ | Integrates with OBS |

**Recommendation:** Start with **IP Camera Lite** (free, easy), upgrade to **iVCam** if you need better quality.

---

## 🚀 Next Steps After Setup

Once camera is working:

1. **Test Sensor Fusion:**
   - Verify frame capture
   - Check frame synchronization
   - Monitor Kafka messages (if running)

2. **Test AI Perception:**
   - Detect objects in real-time
   - Measure inference speed
   - Tune confidence thresholds

3. **Collect Test Data:**
   - Record sample traffic videos
   - Create ground truth annotations
   - Build test dataset

4. **Performance Testing:**
   - Measure FPS
   - Check GPU utilization
   - Optimize batch size

---

## 📚 Additional Resources

- **IP Camera Lite:** https://apps.apple.com/us/app/ip-camera-lite/id1013455241
- **iVCam:** https://www.e2esoft.com/ivcam/
- **RTSP Simple Server:** https://github.com/aler9/rtsp-simple-server
- **OBS Studio:** https://obsproject.com/
- **NDI Tools:** https://ndi.tv/tools/

---

**Status:** Ready to configure iPhone 15 Pro as camera source! 📱✅  
**Next:** Follow Quick Start method above to get started.


