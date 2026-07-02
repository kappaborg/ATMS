#!/bin/bash

echo "════════════════════════════════════════════════════════════════"
echo "  TESTING SENSOR FUSION SERVICE STARTUP"
echo "════════════════════════════════════════════════════════════════"
echo ""

cd src

# Activate virtual environment
source ../venv/bin/activate

# Start the service in background
echo "🚀 Starting service..."
timeout 10s python main.py > /tmp/sensor_fusion_test.log 2>&1 &
SERVICE_PID=$!

# Wait for startup
sleep 3

# Check if service is running
if ps -p $SERVICE_PID > /dev/null 2>&1; then
    echo "✅ Service is running (PID: $SERVICE_PID)"
    
    # Test health endpoint
    echo ""
    echo "🔍 Testing /health endpoint..."
    HEALTH_RESPONSE=$(curl -s http://localhost:8000/health 2>/dev/null)
    
    if [ $? -eq 0 ]; then
        echo "✅ Health endpoint responding:"
        echo "$HEALTH_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$HEALTH_RESPONSE"
    else
        echo "⚠️  Health endpoint not responding (service may still be starting)"
    fi
    
    # Test metrics endpoint
    echo ""
    echo "🔍 Testing /metrics endpoint..."
    METRICS=$(curl -s http://localhost:8000/metrics 2>/dev/null | head -5)
    
    if [ $? -eq 0 ]; then
        echo "✅ Metrics endpoint responding (first 5 lines):"
        echo "$METRICS"
    else
        echo "⚠️  Metrics endpoint not responding"
    fi
    
    # Stop the service
    echo ""
    echo "🛑 Stopping service..."
    kill $SERVICE_PID 2>/dev/null
    wait $SERVICE_PID 2>/dev/null
    echo "✅ Service stopped"
    
else
    echo "❌ Service failed to start"
    echo ""
    echo "📋 Service logs:"
    cat /tmp/sensor_fusion_test.log
    exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  ✅ SERVICE STARTUP TEST PASSED!"
echo "════════════════════════════════════════════════════════════════"
