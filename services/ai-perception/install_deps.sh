#!/bin/bash

cat << 'EOF'

╔══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║     📦 AI PERCEPTION - INSTALLING DEPENDENCIES                       ║
║                                                                       ║
╚══════════════════════════════════════════════════════════════════════╝

EOF

cd "$(dirname "$0")"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    echo "✅ Virtual environment created!"
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip setuptools wheel -q

# Install shared package first
echo ""
echo "📦 Installing shared package..."
pip install -e ../../shared

# Install core dependencies first
echo ""
echo "📦 Installing core dependencies..."
pip install fastapi==0.104.1 uvicorn[standard]==0.24.0 pydantic==2.5.0 pydantic-settings==2.1.0

# Install AI/ML packages (this takes the longest)
echo ""
echo "🧠 Installing AI/ML packages (this may take 3-5 minutes)..."
echo "   Installing: torch, torchvision, ultralytics, onnx, onnxruntime..."
pip install torch torchvision ultralytics onnx onnxruntime

# Install computer vision
echo ""
echo "📷 Installing computer vision packages..."
pip install opencv-python opencv-contrib-python Pillow

# Install data processing
echo ""
echo "🔢 Installing data processing packages..."
pip install numpy scipy

# Install async & messaging
echo ""
echo "⚡ Installing async & messaging packages..."
pip install aiofiles aiokafka aiohttp confluent-kafka

# Install config & monitoring
echo ""
echo "⚙️  Installing config & monitoring packages..."
pip install python-dotenv pyyaml prometheus-client python-json-logger structlog

# Install testing packages
echo ""
echo "🧪 Installing testing packages..."
pip install pytest pytest-asyncio pytest-cov pytest-mock httpx coverage

# Install code quality
echo ""
echo "✨ Installing code quality tools..."
pip install black ruff mypy

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ ALL DEPENDENCIES INSTALLED SUCCESSFULLY!"
echo ""
echo "📋 Installed packages:"
python -c "import torch; import ultralytics; import fastapi; print(f'  • PyTorch: {torch.__version__}'); print(f'  • Ultralytics: {ultralytics.__version__}'); print(f'  • FastAPI: {fastapi.__version__}')"
echo ""
echo "🚀 Ready to start AI Perception service!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""


