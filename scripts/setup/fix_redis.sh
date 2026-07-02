#!/bin/bash
# Quick fix for Redis connection issue
# This script installs Redis client library in the AI perception service

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           🔧 Fixing Redis Connection Issue 🔧               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Navigate to AI perception service
cd /Users/kappasutra/Traffic/services/ai-perception

# Activate virtual environment
echo "📦 Activating virtual environment..."
source venv/bin/activate

# Install Redis client libraries
echo ""
echo "📥 Installing Redis client libraries..."
echo ""
pip install redis redis[hiredis]

# Check installation
echo ""
echo "✅ Checking installation..."
python -c "import redis; print(f'Redis version: {redis.__version__}')" && echo "✅ Redis installed successfully!" || echo "❌ Installation failed!"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    ✅ Fix Complete! ✅                       ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                              ║"
echo "║  Next Steps:                                                 ║"
echo "║  1. Stop the running service (CTRL+C)                        ║"
echo "║  2. Restart: python src/integrated_perception_service.py    ║"
echo "║  3. Look for: INFO:__main__:✅ Redis connected              ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

