# 📱 Phone Camera Setup Guide

## 🔧 Connecting Your Phone Camera

### **Method 1: USB Connection (Recommended)**

1. **Connect via USB:**
   - Connect your phone to your computer via USB cable
   - Enable "File Transfer" or "MTP" mode on your phone
   - Your phone should appear as a camera device

2. **Verify Connection:**
   ```bash
   # Check available cameras
   ls /dev/video*
   ```

3. **Test Camera:**
   ```bash
   # Test camera with OpenCV
   python3 -c "import cv2; cap = cv2.VideoCapture(0); print('Camera 0:', cap.isOpened()); cap.release()"
   ```

### **Method 2: IP Camera App (Alternative)**

1. **Install IP Camera App:**
   - Download "IP Webcam" or similar app from your phone's app store
   - Open the app and start the camera server
   - Note the IP address (usually http://192.168.x.x:8080)

2. **Connect via IP:**
   - The script will automatically detect the IP camera stream
   - No USB connection needed

### **Method 3: Wireless Connection**

1. **Enable Hotspot:**
   - Turn on your phone's hotspot
   - Connect your computer to the hotspot
   - Use IP camera app for wireless connection

## 🚀 Running the Street Test

### **1. Start the Street Test:**
```bash
cd /Users/kappasutra/Traffic
source services/ai-perception/venv/bin/activate
python3 street_test_phone_camera.py
```

### **2. Test Controls:**
- **'q'** - Quit the test
- **'s'** - Save current detection
- **'c'** - Capture current frame
- **'r'** - Show results

### **3. What to Test:**
- **Moving vehicles** - Test detection while cars are moving
- **Different angles** - Test from various viewing angles
- **Different distances** - Test from close and far distances
- **Different lighting** - Test in daylight and low light
- **Different plate types** - Test various license plate formats

## 📊 Expected Results

### **✅ Our System Should:**
- **Detect license plates** in real-time
- **Recognize text** with high accuracy
- **Work in various conditions** (daylight, low light, moving vehicles)
- **Process quickly** (real-time performance)

### **📈 Performance Metrics:**
- **OCR Success Rate:** Target 90%+ in street conditions
- **Model Confidence:** Target 70%+ average
- **Processing Speed:** Real-time (30+ FPS)
- **Detection Rate:** Target 80%+ for visible plates

## 🔧 Troubleshooting

### **Camera Not Detected:**
1. **Check USB connection** - Ensure phone is connected properly
2. **Enable camera permissions** - Allow camera access on your phone
3. **Try different camera index** - The script tries cameras 0-4 automatically
4. **Restart the script** - Sometimes a restart helps

### **Poor Performance:**
1. **Check lighting** - Ensure good lighting conditions
2. **Stabilize phone** - Keep phone steady for better detection
3. **Adjust distance** - Get closer to license plates
4. **Check angle** - Point camera directly at plates

### **No Detections:**
1. **Verify model loading** - Check if our custom model loaded successfully
2. **Check confidence threshold** - Lower confidence if needed
3. **Test with clear plates** - Try with clearly visible plates first
4. **Check camera quality** - Ensure camera is working properly

## 📱 Phone Camera Tips

### **For Best Results:**
1. **Use good lighting** - Daylight or bright indoor lighting
2. **Keep phone steady** - Avoid shaky hands
3. **Point directly at plates** - Avoid extreme angles
4. **Get close enough** - License plates should be clearly visible
5. **Use landscape mode** - Better for license plate detection

### **Testing Scenarios:**
1. **Parked cars** - Test with stationary vehicles
2. **Moving traffic** - Test with moving vehicles
3. **Different distances** - Test from 5-50 feet away
4. **Various angles** - Test from front, side, and rear
5. **Different lighting** - Test in various lighting conditions

## 🎯 Success Criteria

### **✅ Street Test Passes If:**
- **90%+ OCR success rate** in street conditions
- **Real-time processing** without lag
- **Consistent detection** across different scenarios
- **Good performance** in various lighting conditions

### **📊 Performance Targets:**
- **OCR Success Rate:** 90%+
- **Model Confidence:** 70%+
- **Processing Speed:** Real-time
- **Detection Rate:** 80%+ for visible plates

## 🏆 Expected Outcome

**Our custom trained license plate model should perform excellently in real-world street conditions, demonstrating:**

1. **✅ High accuracy** - 90%+ OCR success rate
2. **✅ Real-time processing** - Smooth, fast detection
3. **✅ Robust performance** - Works in various conditions
4. **✅ Production readiness** - Ready for deployment

**This street test will validate our system's real-world performance!** 🚀
