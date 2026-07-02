#!/bin/bash
# Start ATMS Services - AI Perception and Video Processor
# Usage: ./scripts/start_services.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "🚀 Starting ATMS Services..."
echo ""

# Check if ports are free
check_port() {
    local port=$1
    if lsof -ti:$port > /dev/null 2>&1; then
        echo "⚠️  Port $port is already in use!"
        read -p "Kill process on port $port? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            lsof -ti:$port | xargs kill -9 2>/dev/null
            echo "✅ Killed process on port $port"
        else
            echo "❌ Cannot start service - port $port is in use"
            exit 1
        fi
    fi
}

check_port 8014
check_port 8018

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Starting services in background..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Start AI Perception (Port 8014)
echo "📡 Starting AI Perception Service on port 8014..."
cd "$PROJECT_ROOT/services/ai-perception"
source venv/bin/activate
nohup uvicorn src.main:app --host 0.0.0.0 --port 8014 > /tmp/ai-perception.log 2>&1 &
AI_PID=$!
echo "✅ AI Perception started (PID: $AI_PID)"
echo "   Logs: tail -f /tmp/ai-perception.log"
echo ""

# Wait a bit for AI Perception to initialize
sleep 3

# Start Video Processor (Port 8018)
echo "🎥 Starting Video Processor Service on port 8018..."
cd "$PROJECT_ROOT/services/video-processor"
source venv/bin/activate
nohup uvicorn src.main:app --host 0.0.0.0 --port 8018 > /tmp/video-processor.log 2>&1 &
VIDEO_PID=$!
echo "✅ Video Processor started (PID: $VIDEO_PID)"
echo "   Logs: tail -f /tmp/video-processor.log"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Both services started!"
echo ""
echo "📊 Service URLs:"
echo "   • AI Perception: http://localhost:8014"
echo "   • Video Processor: http://localhost:8018"
echo ""
echo "📝 View logs:"
echo "   • AI Perception: tail -f /tmp/ai-perception.log"
echo "   • Video Processor: tail -f /tmp/video-processor.log"
echo ""
echo "🛑 Stop services:"
echo "   kill $AI_PID $VIDEO_PID"
echo "   OR: ./scripts/stop_services.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

