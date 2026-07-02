# 🚗 License Plate Detection Model Training Guide

## Overview
This guide explains how to train a YOLOv8 model for license plate detection using your dataset.

## 📁 Files Created
- `train_license_plate_model.py` - Main Python training script
- `run_training.sh` - Bash wrapper script (recommended)
- `TRAINING_GUIDE.md` - This guide

## 🚀 Quick Start

### Option 1: Simple (Recommended)
```bash
./run_training.sh
```

### Option 2: Manual
```bash
# Activate virtual environment
source services/ai-perception/venv/bin/activate

# Run training script
python train_license_plate_model.py
```

## 📊 Training Configuration

### Model Settings
- **Model**: YOLOv8n (nano - fastest training)
- **Epochs**: 100
- **Batch Size**: 16
- **Image Size**: 640x640
- **Device**: CPU (CUDA not available)

### Dataset
- **Total Images**: 10,125
- **Training**: 7,057 images
- **Validation**: 2,048 images
- **Test**: 1,020 images
- **Classes**: 1 (License_Plate)

## ⏱️ Training Time
- **CPU Training**: 8-12 hours
- **Checkpoints**: Every 10 epochs
- **Best Model**: Saved automatically

## 📁 Output Files

### Training Results
- `models/license_plate_training/outputs/license_plate_model/`
  - `best.pt` - Best trained model
  - `last.pt` - Last epoch model
  - `results.png` - Training metrics
  - `confusion_matrix.png` - Confusion matrix
  - `val_batch0_pred.jpg` - Validation predictions

### Logs
- `models/license_plate_training/outputs/logs/`
  - Training logs and metrics

## 🔍 Monitoring Training

### Check Progress
```bash
# Check if training is running
ps aux | grep python

# View training directory
ls -la models/license_plate_training/outputs/

# Check latest results
ls -la models/license_plate_training/outputs/license_plate_model/
```

### View Logs
```bash
# View training logs
tail -f models/license_plate_training/outputs/logs/*.log
```

## 🎯 Expected Results

### Performance Metrics
- **mAP50**: 95%+ accuracy
- **Precision**: 90%+
- **Recall**: 90%+
- **F1 Score**: 90%+

### Model Size
- **YOLOv8n**: ~6MB
- **Inference Speed**: 10-20ms per image
- **FPS**: 50-100 (CPU)

## 🔧 Troubleshooting

### Common Issues

#### 1. Virtual Environment Not Found
```bash
# Check if venv exists
ls -la services/ai-perception/venv/

# If not found, create it
python3 -m venv services/ai-perception/venv
source services/ai-perception/venv/bin/activate
pip install torch ultralytics opencv-python
```

#### 2. Dataset Not Found
```bash
# Check dataset location
ls -la "data/license_plate_dataset/License Plate Recognition.v11i.yolov8 1/"

# Verify data.yaml exists
cat "data/license_plate_dataset/License Plate Recognition.v11i.yolov8 1/data.yaml"
```

#### 3. Out of Memory
```bash
# Reduce batch size in train_license_plate_model.py
# Change batch_size from 16 to 8 or 4
```

#### 4. Training Too Slow
```bash
# Use smaller model (yolov8n instead of yolov8x)
# Reduce epochs (100 to 50)
# Use GPU if available
```

## 📈 Training Progress

### Epochs 1-10: Initial Learning
- Model learns basic features
- Loss decreases rapidly
- Accuracy starts improving

### Epochs 11-50: Main Training
- Model learns complex patterns
- Validation accuracy improves
- Loss stabilizes

### Epochs 51-100: Fine-tuning
- Model optimizes for accuracy
- Final performance tuning
- Best model selection

## 🎉 Success Indicators

### Training Complete
- ✅ "TRAINING COMPLETED SUCCESSFULLY!" message
- ✅ `best.pt` file created
- ✅ `results.png` with training curves
- ✅ `confusion_matrix.png` generated

### Model Ready
- ✅ High mAP50 (>95%)
- ✅ Good precision/recall balance
- ✅ Low inference time
- ✅ Small model size

## 🚀 Next Steps

### 1. Test the Model
```bash
# Test on sample images
python -c "
from ultralytics import YOLO
model = YOLO('models/license_plate_training/outputs/license_plate_model/best.pt')
results = model('path/to/test/image.jpg')
results[0].show()
"
```

### 2. Export for Production
```bash
# Export to ONNX
python -c "
from ultralytics import YOLO
model = YOLO('models/license_plate_training/outputs/license_plate_model/best.pt')
model.export(format='onnx')
"
```

### 3. Integrate with ATMS
- Replace existing model in AI Perception service
- Update model path in configuration
- Test with real traffic data

## 📞 Support

### If Training Fails
1. Check error messages carefully
2. Verify all prerequisites are met
3. Check disk space (need ~2GB free)
4. Ensure virtual environment is activated

### Performance Issues
1. Reduce batch size
2. Use smaller model
3. Reduce epochs
4. Check system resources

## 🎯 Success!

Once training completes successfully, you'll have:
- ✅ **High-accuracy license plate detection model**
- ✅ **Production-ready model files**
- ✅ **Training metrics and visualizations**
- ✅ **Ready for ATMS integration**

Your license plate detection model will be ready to detect and recognize license plates in real-time traffic scenarios!
