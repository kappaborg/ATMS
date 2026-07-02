# 🚊 Tramway Detection - Quick Start Guide

**Time to Complete:** 35-65 minutes  
**Target Accuracy:** mAP50 > 95%  
**Status:** ✅ Ready to Train

---

## 🚀 One-Command Training

```bash
cd /Users/kappasutra/Traffic/models/tramway_training
./run_complete_training.sh
```

**That's it!** The automated pipeline will:
1. ⬇️ Download dataset from Roboflow (2-5 min)
2. 🚀 Train YOLOv8 model (30-60 min)
3. 🔍 Test and validate (1-2 min)
4. 📦 Export to CoreML & ONNX (1-2 min)
5. 💻 Generate integration code (< 1 min)

---

## 📊 What You'll Get

### After Training Completes:

```
✅ Trained Model (mAP50 > 95%)
   📍 Location: tramway_runs/train_*/weights/best.pt
   📏 Size: ~6-7 MB
   ⚡ Speed: 25-35 FPS on Apple M1/M2

✅ Performance Metrics
   • mAP50: > 95%
   • mAP50-95: > 80%
   • Precision: > 90%
   • Recall: > 85%

✅ Exported Formats
   • PyTorch (.pt)
   • CoreML (.mlpackage) - Apple Silicon optimized
   • ONNX (.onnx) - Universal deployment

✅ Training Analytics
   • Training curves (results.png)
   • Confusion matrix (confusion_matrix.png)
   • Validation predictions
   • Speed benchmarks

✅ Integration Code
   • tramway_integration_code.py
   • Ready to add to ATMS
```

---

## 🎯 Training Configuration

The system is pre-configured for **maximum accuracy**:

| Setting | Value | Purpose |
|---------|-------|---------|
| Model | YOLOv8n | Fast + Accurate |
| Epochs | 100 | With early stopping |
| Optimizer | AdamW | Better generalization |
| Augmentation | Enabled | Prevent overfitting |
| Device | Auto-detect | MPS/CUDA/CPU |
| Export | Multi-format | CoreML + ONNX |

---

## 📈 Expected Timeline

### On Apple M1/M2 (MPS):

| Phase | Duration | What Happens |
|-------|----------|--------------|
| **Download** | 2-5 min | Roboflow dataset download |
| **Training** | 30-60 min | 100 epochs, auto-save best |
| **Testing** | 1-2 min | Validation + benchmarks |
| **Export** | 1-2 min | CoreML + ONNX export |
| **Total** | **35-70 min** | **Complete system ready** |

### On NVIDIA GPU:

| Phase | Duration |
|-------|----------|
| Download | 2-5 min |
| Training | 20-40 min |
| Testing | 1 min |
| Export | 1 min |
| **Total** | **25-50 min** |

---

## 🔍 What to Watch For

### ✅ Good Signs During Training:

```
✅ Loss decreasing steadily
✅ mAP increasing to >95%
✅ Validation loss stable or decreasing
✅ No "out of memory" errors
✅ Consistent time per epoch
```

### ⚠️ Warning Signs:

```
⚠️ Loss plateauing or increasing
⚠️ mAP not improving after 50 epochs
⚠️ Validation loss increasing (overfitting)
⚠️ Very slow progress (check GPU usage)
```

---

## 📁 Output Files

After completion, you'll have:

```
models/tramway_training/
├── Tramway-5/                  # Downloaded dataset
├── tramway_runs/               # Training outputs
│   └── train_YYYYMMDD_HHMMSS/
│       ├── weights/
│       │   ├── best.pt         ← Deploy this!
│       │   ├── best.mlpackage  ← Apple Silicon
│       │   └── best.onnx       ← Universal
│       ├── results.png         ← Training curves
│       └── confusion_matrix.png
├── tramway_test_results/       # Test outputs
└── tramway_integration_code.py # Integration code
```

---

## 🔗 Integration (After Training)

### Step 1: Add to AI Perception Service

```python
# File: services/ai-perception/src/integrated_perception_service.py

from tramway_integration_code import TramwayDetector

class IntegratedPerceptionService:
    def __init__(self):
        # ... existing code ...
        self.tramway_detector = TramwayDetector()
    
    async def process_frame(self, frame):
        tramway_detections = self.tramway_detector.detect(frame)
        # ... store in database, update decision engine ...
```

### Step 2: Update Database

```sql
-- File: database/migrations/010_add_tramway_detections.sql

ALTER TABLE traffic_detections 
ADD COLUMN is_tramway BOOLEAN,
ADD COLUMN tramway_line VARCHAR(50);
```

### Step 3: Decision Engine

```python
# File: services/decision-engine/src/tramway_priority.py

if detection['object_type'] == 'tramway':
    await self.create_green_wave(trajectory)
```

---

## 🛠️ If Accuracy < 95%

Try these improvements **in order**:

### 1. Use Larger Model (easiest)
```python
# Edit train_tramway_model.py, line 58:
model = YOLO('yolov8s.pt')  # or 'yolov8m.pt'
```

### 2. Increase Epochs
```python
# Edit train_tramway_model.py, line 93:
epochs=150  # or 200
```

### 3. Fine-tune Learning Rate
```python
# Edit train_tramway_model.py, line 100:
lr0=0.001  # Lower for fine-tuning
```

### 4. Add More Augmentation
```python
# Edit train_tramway_model.py:
mosaic=1.0,
mixup=0.15,  # Add this
copy_paste=0.1  # Add this
```

---

## 📊 Model Comparison

If default YOLOv8n doesn't achieve 95%, try:

| Model | Accuracy | Speed | When to Use |
|-------|----------|-------|-------------|
| **YOLOv8n** | 90-95% | 35 FPS | Real-time (start here) |
| **YOLOv8s** | 93-97% | 20 FPS | If accuracy < 95% |
| **YOLOv8m** | 95-98% | 12 FPS | Guaranteed 95%+ |
| **YOLOv8l** | 96-99% | 8 FPS | Absolute maximum |

To change model:
```bash
# Edit train_tramway_model.py
model = YOLO('yolov8m.pt')  # Change this line
```

---

## 📚 Documentation

| Document | Location | Purpose |
|----------|----------|---------|
| **This Guide** | `TRAMWAY_TRAINING_QUICKSTART.md` | Quick start |
| **Full README** | `models/tramway_training/README.md` | Complete guide |
| **System Overview** | `TRAMWAY_DETECTION_SYSTEM.md` | Architecture |
| **Integration** | `APPLICATION_INTEGRATION_GUIDE.md` | ATMS integration |
| **Database** | `DATABASE_SCHEMA_ANALYSIS.md` | Schema details |

---

## ✅ Success Criteria

Training is successful when you achieve:

- [x] ✅ Setup complete
- [ ] ⏳ Dataset downloaded
- [ ] ⏳ Model trained
- [ ] ⏳ mAP50 > 95%
- [ ] ⏳ FPS > 20
- [ ] ⏳ Exported to CoreML/ONNX

---

## 🎯 Next Steps After Training

1. **Verify Results**
   ```bash
   open tramway_runs/train_*/results.png
   ```

2. **Check Test Images**
   ```bash
   open tramway_test_results/
   ```

3. **Integrate with ATMS**
   ```bash
   cat tramway_integration_code.py
   ```

4. **Deploy to Production**
   - Copy `best.pt` to AI Perception Service
   - Update database schema
   - Test end-to-end

---

## 💡 Pro Tips

1. **Monitor Training**: Keep terminal open to watch progress
2. **Check GPU Usage**: Ensure MPS/CUDA is active (faster)
3. **Save Outputs**: Training results auto-saved every epoch
4. **View Curves**: Open `results.png` to monitor training
5. **Test Early**: Run `test_tramway_model.py` after training

---

## 🚀 Start Now!

```bash
cd /Users/kappasutra/Traffic/models/tramway_training
./run_complete_training.sh
```

**Estimated time:** 35-65 minutes  
**Target accuracy:** mAP50 > 95%  
**Real-time FPS:** > 20  

**Let's achieve perfect tramway detection! 🎯**

---

**Document Version:** 1.0  
**Last Updated:** October 14, 2025  
**Location:** `/Users/kappasutra/Traffic/TRAMWAY_TRAINING_QUICKSTART.md`

