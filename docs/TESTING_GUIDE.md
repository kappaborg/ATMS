# Complete System Testing Guide

**Date**: December 2, 2025  
**Status**: Ready for Testing

---

## 🔍 Step 1: Check System Errors

Before testing, check for any errors:

```bash
./scripts/check_system_errors.sh
```

This will check:
- ✅ Python dependencies
- ✅ Service logs for errors
- ✅ Port conflicts
- ✅ Critical files
- ✅ Python imports

---

## 🔧 Step 2: Fix Dependencies (If Needed)

If dependencies are missing, install them:

```bash
./scripts/fix_dependencies.sh
```

Or manually:
```bash
pip3 install opencv-python numpy ultralytics aiokafka yt-dlp
```

---

## 🎥 Step 3: Test YouTube Video

### Quick Test (Recommended)
```bash
./scripts/quick_test_youtube.sh "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"
```

### Complete Test (With Options)
```bash
./scripts/test_youtube_complete.sh "https://www.youtube.com/watch?v=YOUR_VIDEO_ID" \
    --duration 120 \
    --dashboard
```

**Options:**
- `--duration <seconds>` - Test duration (default: 60)
- `--no-display` - Disable video display (faster)
- `--no-save` - Don't save output video
- `--dashboard` - Show Python dashboard

---

## 📊 What the Test Does

1. **Checks Prerequisites**
   - Python and dependencies
   - Services (optional)
   - Docker infrastructure (optional)

2. **Processes YouTube Video**
   - Extracts stream URL using `yt-dlp`
   - Processes frames with all AI models:
     - ✅ Vehicle Detection (YOLOv8)
     - ✅ License Plate Recognition
     - ✅ Brand Classification
     - ✅ Multi-View Detection
     - ✅ Tramway Detection
     - ✅ Speed Calculation
     - ✅ Emission Calculation
     - ✅ Decision Engine
     - ✅ Trajectory Tracking

3. **Outputs**
   - Processing log: `test_output/youtube_*/processing.log`
   - Output video: `test_output/youtube_*/output_video.mp4`
   - CSV exports: Detection data, emissions, etc.

---

## 🐛 Common Issues and Fixes

### Issue 1: Missing Dependencies
**Error**: `ModuleNotFoundError: No module named 'cv2'`

**Fix**:
```bash
./scripts/fix_dependencies.sh
```

### Issue 2: YouTube URL Extraction Failed
**Error**: `❌ Failed to extract stream URL`

**Fix**:
```bash
pip3 install --upgrade yt-dlp
```

### Issue 3: Services Not Running
**Warning**: `⚠️ Service not running (optional)`

**Note**: Services are optional. YouTube processor can run standalone.

**To start services**:
```bash
./scripts/start_all_services.sh
```

### Issue 4: Kafka Connection Errors
**Error**: `Connection refused` to Kafka

**Fix**:
```bash
# Start Docker infrastructure
docker-compose -f docker-compose.yml up -d kafka zookeeper
```

**Note**: Kafka is optional for YouTube testing. The processor will work without it.

---

## 📝 Example Test Session

```bash
# 1. Check for errors
./scripts/check_system_errors.sh

# 2. Fix dependencies if needed
./scripts/fix_dependencies.sh

# 3. Test with YouTube video
./scripts/quick_test_youtube.sh "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# 4. Check output
ls -lh test_output/youtube_*/
cat test_output/youtube_*/processing.log | tail -50
```

---

## ✅ Expected Output

When running successfully, you should see:

```
🎬 Starting YouTube Video Processing
═══════════════════════════════════════════════════════════════

✅ Models initialized:
   ✅ YOLO Detector
   ✅ License Plate Processor
   ✅ Brand Classifier
   ✅ Multi-View Detector
   ✅ Tramway Detector
   ✅ Speed Calculator
   ✅ Emission Calculator
   ✅ Decision Engine

Processing frames...
Frame 1/1800: 2 vehicles detected
Frame 2/1800: 3 vehicles detected
...

✅ Processing complete!
   - Frames processed: 1800
   - Average FPS: 25.5
   - Total detections: 450
   - Decisions made: 60
```

---

## 📊 Monitoring Output

The processor shows:
- **Frame-by-frame progress**
- **Detection counts** (vehicles, pedestrians, etc.)
- **License plates detected**
- **Vehicle brands identified**
- **Speed calculations**
- **Emission calculations**
- **Traffic decisions** (GREEN/YELLOW/RED)
- **FPS** (frames per second)

---

## 🎯 Next Steps After Testing

1. **Check Output Files**
   - Review processing log
   - Watch output video
   - Analyze CSV exports

2. **Test Different Videos**
   - Try different YouTube URLs
   - Test with various traffic conditions
   - Test with different durations

3. **Integration Testing**
   - Test with services running
   - Test Kafka integration
   - Test database storage

---

## 📞 Troubleshooting

If you encounter issues:

1. **Check Error Logs**:
   ```bash
   tail -f test_output/youtube_*/processing.log
   ```

2. **Verify Dependencies**:
   ```bash
   python3 -c "import cv2, numpy, ultralytics, aiokafka, yt_dlp; print('OK')"
   ```

3. **Test YouTube URL**:
   ```bash
   yt-dlp --list-formats "YOUR_YOUTUBE_URL"
   ```

4. **Check System Resources**:
   - Ensure enough RAM
   - Check disk space
   - Monitor CPU usage

---

**Status**: ✅ Ready for Testing

