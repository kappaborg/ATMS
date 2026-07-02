#!/bin/bash
# Convert ALL Trained Models to CoreML Format
# This script converts all your trained models for maximum performance on Apple Silicon

set -e

PROJECT_ROOT="/Users/kappasutra/Traffic"
SCRIPT_DIR="$PROJECT_ROOT/scripts"
VENV_PYTHON="$PROJECT_ROOT/services/ai-perception/venv/bin/python3"

echo "🚀 Converting ALL Trained Models to CoreML Format"
echo "=================================================="
echo ""

# Activate venv if needed
if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ Virtual environment not found. Please activate it first."
    exit 1
fi

# Models to convert
MODELS=(
    # Main YOLOv8 detector (already converted, but verify)
    "services/ai-perception/models/yolov8n.pt:services/ai-perception/models/yolov8n.mlpackage"
    
    # Car Brand Classification
    "models/car_brand_classification/outputs/car_brand_classification_robust/weights/best.pt:models/car_brand_classification/outputs/car_brand_classification_robust/weights/best.mlpackage"
    
    # Multi-View Models (3 models)
    "multiview_models/top_view_model/weights/best.pt:multiview_models/top_view_model/weights/best.mlpackage"
    "multiview_models/side_profile_model/weights/best.pt:multiview_models/side_profile_model/weights/best.mlpackage"
    "multiview_models/front_bumper_model/weights/best.pt:multiview_models/front_bumper_model/weights/best.mlpackage"
    
    # Tramway Detection
    "models/tramway_training/tramway_runs/train_20251028_210058/weights/best.pt:models/tramway_training/tramway_runs/train_20251028_210058/weights/best.mlpackage"
    
    # License Plate Detection
    "models/license_plate_training/outputs/license_plate_model_mps/weights/best.pt:models/license_plate_training/outputs/license_plate_model_mps/weights/best.mlpackage"
)

cd "$PROJECT_ROOT"

SUCCESS_COUNT=0
FAILED_COUNT=0
SKIPPED_COUNT=0

for model_pair in "${MODELS[@]}"; do
    IFS=':' read -r input_path output_path <<< "$model_pair"
    
    # Resolve absolute paths
    input_abs="$PROJECT_ROOT/$input_path"
    output_abs="$PROJECT_ROOT/$output_path"
    
    echo ""
    echo "📦 Processing: $(basename $input_path)"
    echo "   Input:  $input_path"
    echo "   Output: $output_path"
    
    # Check if input exists
    if [ ! -f "$input_abs" ]; then
        echo "   ⚠️  Input file not found, skipping..."
        ((SKIPPED_COUNT++))
        continue
    fi
    
    # Check if output already exists
    if [ -d "$output_abs" ] || [ -f "$output_abs" ]; then
        echo "   ℹ️  CoreML model already exists, skipping..."
        ((SKIPPED_COUNT++))
        continue
    fi
    
    # Create output directory
    output_dir=$(dirname "$output_abs")
    mkdir -p "$output_dir"
    
    # Convert model
    echo "   🔄 Converting to CoreML..."
    if "$VENV_PYTHON" "$SCRIPT_DIR/convert_to_coreml.py" "$input_abs" --output "$output_abs" --input-shape 640 640; then
        echo "   ✅ Success!"
        ((SUCCESS_COUNT++))
    else
        echo "   ❌ Failed!"
        ((FAILED_COUNT++))
    fi
done

echo ""
echo "=================================================="
echo "📊 Conversion Summary"
echo "=================================================="
echo "✅ Successful: $SUCCESS_COUNT"
echo "❌ Failed:     $FAILED_COUNT"
echo "⏭️  Skipped:    $SKIPPED_COUNT"
echo ""

if [ $SUCCESS_COUNT -gt 0 ]; then
    echo "🎉 CoreML models ready! Restart AI Perception service to use them."
    echo ""
    echo "💡 Expected performance: 3-5× faster inference on Apple Silicon!"
fi

if [ $FAILED_COUNT -gt 0 ]; then
    echo "⚠️  Some models failed to convert. Check errors above."
    exit 1
fi

exit 0

