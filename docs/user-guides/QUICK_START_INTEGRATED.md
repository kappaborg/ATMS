# 🚀 Quick Start - Integrated ATMS System

## One URL for Everything!

### **🌐 http://localhost:8011**

That's it! Everything you need in one place.

---

## 🎯 What You Can Do

### 1. Upload Traffic Videos
- Click the upload area (right panel)
- Select any traffic video (MP4, AVI, MOV, etc.)
- Click "Upload & Analyze"

### 2. Watch Real-Time Analysis
- Video streams automatically
- Bounding boxes drawn on vehicles
- All AI model outputs displayed
- Smooth 20 FPS playback

### 3. See Live Statistics
- Frames processed
- Detections count
- Current FPS

---

## 🎬 What You'll See on Each Vehicle

```
car 0.78       ← Object type + confidence
ID:T1          ← Tracking ID
45km/h         ← Speed estimate
LP:ABC123      ← License plate
Type:sedan     ← Vehicle classification
CO2:125.5g     ← Emission calculation
```

---

## 🎨 Color Guide

- 🟢 **Green** = Cars
- 🔵 **Blue** = Trucks
- 🟠 **Orange** = Buses
- 🟡 **Cyan** = Pedestrians (>50% confidence only)
- 🟣 **Purple** = Motorcycles
- 🟡 **Yellow** = Bicycles

---

## 📊 Info Panel (On Video)

Top-left corner shows:
- High-confidence detections count
- Vehicle breakdown by type
- Active AI models
- Real-time timestamp

---

## ✅ System Status

Check health: http://localhost:8011/health

```json
{
  "status": "healthy",
  "kafka": true,
  "websockets": 1,
  "stats": {...}
}
```

---

## 🔧 Troubleshooting

### Video not streaming?
1. Check WebSocket status (top of right panel)
2. Should say "✅ Connected"
3. If not, refresh the page

### No detections showing?
1. Wait a few seconds after upload
2. AI processes frames in real-time
3. Only shows detections >50% confidence

### Upload fails?
1. Check file format (MP4 recommended)
2. Check file size (<500MB recommended)
3. Check AI Perception is running:
   ```bash
   ps aux | grep ai_perception
   ```

---

## 🚀 System Architecture

```
Your Browser (localhost:8011)
        ↓
Integrated System (Upload + Display)
        ↓
Kafka (Message Queue)
        ↓
AI Perception (7 Models)
        ↓
Back to Integrated System
        ↓
WebSocket → Your Browser
```

---

## 🤖 AI Models Active

1. **YOLOv8** - Object detection
2. **Multi-Object Tracking** - Track IDs
3. **Speed Estimation** - From trajectory
4. **License Plate Recognition** - OCR
5. **Vehicle Classification** - Car types
6. **Emission Calculation** - CO2 estimates
7. **Trajectory Prediction** - Movement patterns

---

## 📝 Example Test

1. Open: http://localhost:8011
2. Upload: Any traffic video
3. Watch: Real-time detections appear
4. Verify: 
   - Bounding boxes
   - Labels with confidence
   - Track IDs
   - Statistics updating

---

## 🎉 Ready to Go!

**Just open http://localhost:8011 and start uploading!**

No complex setup, no multiple URLs, no confusion.

**Everything integrated, professional, and working!** 🚀

