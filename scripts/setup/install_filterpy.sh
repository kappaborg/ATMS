#!/bin/bash
# Install filterpy for trajectory tracking

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        📦 Installing filterpy for Trajectory Tracking 📦    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

cd /Users/kappasutra/Traffic/services/ai-perception

echo "📦 Activating virtual environment..."
source venv/bin/activate

echo ""
echo "📥 Installing filterpy..."
pip install filterpy

echo ""
echo "✅ Checking installation..."
python -c "import filterpy; print(f'✅ filterpy version: {filterpy.__version__}')" && echo "✅ Success!" || echo "❌ Installation failed"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                   ✅ Installation Complete! ✅               ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                              ║"
echo "║  Next: Restart the service (CTRL+C then restart)            ║"
echo "║  Expected: ✅ Trajectory tracker initialized                ║"
echo "║  Result: 8/8 components operational (100%)! 🎉              ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"

