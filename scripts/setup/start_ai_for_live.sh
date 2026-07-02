#!/bin/bash
# Start AI Perception for Live Stream Processing

cd /Users/kappasutra/Traffic/services/ai-perception

# Activate virtual environment
source venv/bin/activate

# Set Python path
export PYTHONPATH=/Users/kappasutra/Traffic/services/ai-perception/src:$PYTHONPATH

# Kill any existing AI Perception
lsof -ti :8014 | xargs kill -9 2>/dev/null || true

echo "🚀 Starting AI Perception for Live Stream..."
echo "📍 Working directory: $(pwd)"
echo "🐍 Python path: $PYTHONPATH"

# Start AI Perception
cd src
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8014 > /tmp/ai_perception_live.log 2>&1 &
AI_PID=$!

echo "✅ AI Perception started on PID: $AI_PID"
echo "📊 Health check: http://localhost:8014/health"
echo "📜 Logs: tail -f /tmp/ai_perception_live.log"

sleep 3

# Check if it's running
if curl -s http://localhost:8014/health > /dev/null; then
    echo "✅ AI Perception is HEALTHY and ready to process live stream!"
else
    echo "❌ AI Perception failed to start. Check logs:"
    tail -20 /tmp/ai_perception_live.log
fi

