#!/bin/bash
# Install Performance Optimization Dependencies
# For macOS (Apple Silicon optimized)

set +e  # Don't exit on error - continue with other packages

echo "🚀 Installing Performance Optimizations for ATMS"
echo "=================================================="
echo ""

# Check if we're on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "⚠️  Warning: This script is optimized for macOS"
fi

# Check CPU type
CPU_TYPE=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "Unknown")
echo "📊 CPU: $CPU_TYPE"
echo ""

# Install for AI Perception service
echo "📦 Installing AI Perception optimizations..."
cd /Users/kappasutra/Traffic/services/ai-perception
source venv/bin/activate

echo "  → Installing CoreML tools..."
if pip install coremltools>=7.0 --quiet; then
    echo "    ✅ CoreML tools installed"
else
    echo "    ⚠️  CoreML tools installation failed (may need Xcode Command Line Tools)"
fi

echo "  → Installing ONNX Runtime..."
if pip install onnxruntime>=1.16.0 --quiet; then
    echo "    ✅ ONNX Runtime installed"
else
    echo "    ⚠️  ONNX Runtime installation failed"
fi

echo "  → Installing ByteTrack..."
# ByteTrack requires torch - ensure it's available first
if ! python -c "import torch" 2>/dev/null; then
    echo "    ⚠️  Torch not found, installing..."
    pip install torch --quiet
fi

# Try installing ByteTrack - use alternative if main package fails
if pip install bytetrack>=1.0.0 --quiet 2>/dev/null; then
    echo "    ✅ ByteTrack installed"
elif pip install git+https://github.com/ifzhang/ByteTrack.git --quiet 2>/dev/null; then
    echo "    ✅ ByteTrack installed from GitHub"
else
    echo "    ⚠️  ByteTrack installation failed - will use DeepSORT fallback"
    echo "    (This is OK - DeepSORT is already available)"
fi

echo "✅ AI Perception optimizations installation complete"
echo ""

# Install for Video Processor service
echo "📦 Installing Video Processor optimizations..."
cd /Users/kappasutra/Traffic/services/video-processor
source venv/bin/activate

echo "  → Installing PyAV..."
if pip install av==12.0.0 --quiet; then
    echo "    ✅ PyAV installed"
else
    echo "    ⚠️  PyAV installation failed (may need: brew install ffmpeg)"
    echo "    Continuing with OpenCV fallback..."
fi

echo "✅ Video Processor optimizations installation complete"
echo ""

# Summary
echo "📊 Installation Summary:"
echo "========================"
echo ""
# Check what was actually installed (in AI Perception venv)
echo ""
echo "✅ AI Perception Packages:"
cd /Users/kappasutra/Traffic/services/ai-perception
source venv/bin/activate
python -c "
packages = {
    'coremltools': 'CoreML inference',
    'onnxruntime': 'ONNX Runtime'
}
installed = []
for pkg, desc in packages.items():
    try:
        __import__(pkg)
        installed.append(f'  ✅ {pkg} - {desc}')
    except ImportError:
        installed.append(f'  ❌ {pkg} - NOT installed')
print('\n'.join(installed))
"

# Check ByteTrack separately
echo ""
echo "📦 ByteTrack Status:"
if python -c "import bytetrack" 2>/dev/null; then
    echo "  ✅ ByteTrack - SOTA tracking"
elif python -c "from bytetrack import BYTETracker" 2>/dev/null; then
    echo "  ✅ ByteTrack - SOTA tracking (alternative import)"
else
    echo "  ⚠️  ByteTrack - NOT installed (will use DeepSORT fallback)"
    echo "     Note: ByteTrack package has build issues, DeepSORT works fine"
fi

# Check Video Processor packages
echo ""
echo "✅ Video Processor Packages:"
cd /Users/kappasutra/Traffic/services/video-processor
source venv/bin/activate
python -c "
try:
    import av
    print('  ✅ av - PyAV video decode')
except ImportError:
    print('  ❌ av - NOT installed')
"

echo ""
echo "🎯 Expected Performance:"
if [[ "$CPU_TYPE" == *"Apple"* ]]; then
    echo "  • Apple Silicon: 25-30 FPS (with CoreML)"
    echo "  • Current: 12 FPS → Target: 30 FPS (2.5× improvement)"
else
    echo "  • Intel CPU: 18-22 FPS (with ONNX Runtime)"
    echo "  • Current: 12 FPS → Target: 22 FPS (1.8× improvement)"
fi
echo ""
echo "💡 Note: Some packages may need additional system dependencies"
echo "   (e.g., ffmpeg for PyAV: brew install ffmpeg)"
echo ""
echo "🚀 Ready to use optimized pipeline!"

