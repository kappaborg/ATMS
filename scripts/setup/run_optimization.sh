#!/bin/bash
# Run Model Optimization with proper environment

echo "🚀 Starting Model Optimization..."
echo ""

# Check if we're in the right directory
cd /Users/kappasutra/Traffic

# Activate venv
if [ -d "services/ai-perception/venv" ]; then
    echo "✅ Activating virtual environment..."
    source services/ai-perception/venv/bin/activate
    
    # Install required packages if needed
    echo "📦 Checking dependencies..."
    pip install -q ultralytics torch torchvision 2>/dev/null || echo "Dependencies already installed"
    
    echo ""
    echo "🔧 Running optimization script..."
    echo "=" * 60
    
    # Run the optimization
    python3 model_quantization_tensorrt.py --all
    
    echo ""
    echo "✅ Optimization complete!"
    
else
    echo "❌ Virtual environment not found"
    echo "Creating new venv..."
    python3 -m venv optimization_venv
    source optimization_venv/bin/activate
    pip install ultralytics torch torchvision
    python3 model_quantization_tensorrt.py --all
fi

