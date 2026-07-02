#!/bin/bash

cat << 'EOF'

╔══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║          🎯 AI PERCEPTION SERVICE - STARTING                         ║
║                                                                       ║
╚══════════════════════════════════════════════════════════════════════╝

EOF

cd "$(dirname "$0")"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found!"
    echo ""
    echo "Please run the installation script first:"
    echo "  ./install_deps.sh"
    echo ""
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Quick dependency check
if ! python -c "import fastapi" 2>/dev/null; then
    echo "❌ Dependencies not installed!"
    echo ""
    echo "Please run the installation script first:"
    echo "  ./install_deps.sh"
    echo ""
    exit 1
fi

echo "✅ Dependencies verified!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🚀 Starting AI Perception Service on port 8001..."
echo ""
echo "📹 This service will:"
echo "   • Run custom trained YOLOv8 model (94.76% mAP50)"
echo "   • Detect: license plates with high accuracy"
echo "   • OCR text extraction with EasyOCR"
echo "   • Provide API endpoints for testing"
echo "   • Run in MOCK mode (Kafka not required)"
echo ""
echo "🌐 Available endpoints:"
echo "   • Health: http://localhost:8001/health"
echo "   • Docs: http://localhost:8001/docs"
echo "   • Test Detection: POST http://localhost:8001/detect/test"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "⏳ Loading custom trained license plate model (this may take a few seconds)..."
echo ""

# Start the service
cd src
python main.py
