#!/bin/bash
# Start AI Perception Service Only (for camera detection)
# This is all you need for camera-based vehicle detection!

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║                                                                      ║"
echo "║       🚀 Starting AI Perception Service (Camera Ready) 🚀           ║"
echo "║                                                                      ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

# Check if Database is running
echo "📊 Checking Infrastructure..."
if docker ps | grep -q atms-postgres; then
    echo "  ✅ PostgreSQL running"
else
    echo "  ⚠️  PostgreSQL not running (optional for testing)"
fi

if docker ps | grep -q atms-redis; then
    echo "  ✅ Redis running"
else
    echo "  ⚠️  Redis not running (optional for testing)"
fi

if docker ps | grep -q kafka; then
    echo "  ✅ Kafka running"
else
    echo "  ⚠️  Kafka not running (optional for testing)"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "🤖 Starting AI Perception Service (Port 8004)"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Navigate to AI Perception service
cd /Users/kappasutra/Traffic/services/ai-perception

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "❌ Error: Virtual environment not found!"
    echo "   Run: python3 -m venv venv"
    exit 1
fi

# Activate venv and start service
echo "📦 Activating virtual environment..."
source venv/bin/activate

echo "🚀 Starting AI Perception Service..."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Service will start on: http://0.0.0.0:8004"
echo ""
echo "To connect your camera (http://192.168.0.11:8081/):"
echo "  In another terminal, run:"
echo ""
echo "  curl -X POST \"http://localhost:8004/start\" \\"
echo "    -H \"Content-Type: application/json\" \\"
echo "    -d '{\"camera_url\": \"http://192.168.0.11:8081/video\"}'"
echo ""
echo "Press CTRL+C to stop"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python src/integrated_perception_service.py

