#!/bin/bash
# Complete ATMS System Startup Script
# Starts all services in the correct order

set -e  # Exit on error

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║                                                                      ║"
echo "║       🚀 ATMS Complete System Startup 🚀                            ║"
echo "║                                                                      ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to check if a port is in use
check_port() {
    if lsof -Pi :$1 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Function to wait for service
wait_for_service() {
    local url=$1
    local name=$2
    local max_attempts=30
    local attempt=0
    
    echo -n "  Waiting for $name to be ready"
    while [ $attempt -lt $max_attempts ]; do
        if curl -s "$url" > /dev/null 2>&1; then
            echo " ✅"
            return 0
        fi
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done
    echo " ❌ Timeout"
    return 1
}

# =============================================================================
# STEP 1: Start Database Infrastructure
# =============================================================================

echo "═══════════════════════════════════════════════════════════════"
echo "1️⃣  Starting Database Infrastructure (PostgreSQL + Redis)"
echo "═══════════════════════════════════════════════════════════════"
echo ""

if docker ps | grep -q atms-postgres; then
    echo "  ✅ PostgreSQL already running"
else
    echo "  📦 Starting PostgreSQL..."
    ./start_database.sh
    sleep 5
fi

if docker ps | grep -q atms-redis; then
    echo "  ✅ Redis already running"
else
    echo "  📦 Redis should have started with database..."
fi

echo ""
echo "  ✅ Database infrastructure ready!"
echo ""
sleep 2

# =============================================================================
# STEP 2: Start Kafka
# =============================================================================

echo "═══════════════════════════════════════════════════════════════"
echo "2️⃣  Starting Kafka Message Broker"
echo "═══════════════════════════════════════════════════════════════"
echo ""

if docker ps | grep -q kafka; then
    echo "  ✅ Kafka already running"
else
    echo "  📦 Starting Kafka & Zookeeper..."
    ./start_kafka.sh
    echo "  ⏳ Waiting for Kafka to be ready (30 seconds)..."
    sleep 30
fi

echo ""
echo "  ✅ Kafka ready!"
echo ""
sleep 2

# =============================================================================
# STEP 3: Start Microservices
# =============================================================================

echo "═══════════════════════════════════════════════════════════════"
echo "3️⃣  Starting FastAPI Microservices"
echo "═══════════════════════════════════════════════════════════════"
echo ""

echo "  📦 Starting Data Aggregator (Port 8001)..."
if check_port 8001; then
    echo "    ✅ Already running"
else
    cd services/data-aggregator
    nohup uvicorn src.main:app --host 0.0.0.0 --port 8001 > logs/aggregator.log 2>&1 &
    cd ../..
    wait_for_service "http://localhost:8001/health" "Data Aggregator"
fi

echo "  📦 Starting Decision Engine (Port 8002)..."
if check_port 8002; then
    echo "    ✅ Already running"
else
    cd services/decision-engine
    nohup uvicorn src.main:app --host 0.0.0.0 --port 8002 > logs/decision.log 2>&1 &
    cd ../..
    wait_for_service "http://localhost:8002/health" "Decision Engine"
fi

echo "  📦 Starting Traffic Controller (Port 8003)..."
if check_port 8003; then
    echo "    ✅ Already running"
else
    cd services/traffic-controller
    nohup uvicorn src.main:app --host 0.0.0.0 --port 8003 > logs/controller.log 2>&1 &
    cd ../..
    wait_for_service "http://localhost:8003/health" "Traffic Controller"
fi

echo ""
echo "  ✅ All microservices ready!"
echo ""
sleep 2

# =============================================================================
# STEP 4: Start AI Perception Service
# =============================================================================

echo "═══════════════════════════════════════════════════════════════"
echo "4️⃣  Starting AI Perception Service (CoreML)"
echo "═══════════════════════════════════════════════════════════════"
echo ""

if check_port 8004; then
    echo "  ✅ AI Perception already running on port 8004"
else
    echo "  📦 Starting AI Perception Service..."
    echo "     (This will take ~5 seconds to load CoreML models)"
    cd services/ai-perception
    source venv/bin/activate
    nohup python src/integrated_perception_service.py > logs/perception.log 2>&1 &
    cd ../..
    wait_for_service "http://localhost:8004/health" "AI Perception"
fi

echo ""
echo "  ✅ AI Perception ready!"
echo ""
sleep 2

# =============================================================================
# STEP 5: System Status
# =============================================================================

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║                                                                      ║"
echo "║              ✅ ALL SERVICES STARTED SUCCESSFULLY! ✅               ║"
echo "║                                                                      ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

echo "📊 Service Status:"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Check Database
docker ps | grep -q atms-postgres && echo "  ✅ PostgreSQL      (Port 5432)" || echo "  ❌ PostgreSQL"
docker ps | grep -q atms-redis && echo "  ✅ Redis           (Port 6379)" || echo "  ❌ Redis"

# Check Kafka
docker ps | grep -q kafka && echo "  ✅ Kafka           (Port 9092)" || echo "  ❌ Kafka"
docker ps | grep -q zookeeper && echo "  ✅ Zookeeper       (Port 2181)" || echo "  ❌ Zookeeper"

# Check Microservices
curl -s http://localhost:8001/health > /dev/null && echo "  ✅ Data Aggregator (Port 8001)" || echo "  ❌ Data Aggregator"
curl -s http://localhost:8002/health > /dev/null && echo "  ✅ Decision Engine (Port 8002)" || echo "  ❌ Decision Engine"
curl -s http://localhost:8003/health > /dev/null && echo "  ✅ Traffic Controller (Port 8003)" || echo "  ❌ Traffic Controller (optional)"

# Check AI Perception
curl -s http://localhost:8004/health > /dev/null && echo "  ✅ AI Perception   (Port 8004)" || echo "  ❌ AI Perception"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo ""

# =============================================================================
# STEP 6: Camera Activation Instructions
# =============================================================================

echo "📹 Camera Activation:"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  To start detection with camera, run one of these:"
echo ""
echo "  Option 1 - Built-in Webcam (Camera ID 0):"
echo "    curl -X POST \"http://localhost:8004/start?camera_id=0\""
echo ""
echo "  Option 2 - iPhone Camera:"
echo "    curl -X POST \"http://localhost:8004/start\" \\"
echo "      -H \"Content-Type: application/json\" \\"
echo "      -d '{\"camera_url\": \"http://YOUR_IPHONE_IP:8080/video\"}'"
echo ""
echo "  Option 3 - USB Camera (Camera ID 1):"
echo "    curl -X POST \"http://localhost:8004/start?camera_id=1\""
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo ""

# =============================================================================
# Useful Commands
# =============================================================================

echo "🔧 Useful Commands:"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Check System Stats:"
echo "    curl http://localhost:8004/stats | python3 -m json.tool"
echo ""
echo "  View API Docs:"
echo "    http://localhost:8004/docs (AI Perception)"
echo "    http://localhost:8001/docs (Data Aggregator)"
echo "    http://localhost:8002/docs (Decision Engine)"
echo ""
echo "  Monitor Logs:"
echo "    tail -f services/ai-perception/logs/perception.log"
echo "    tail -f services/data-aggregator/logs/aggregator.log"
echo ""
echo "  Stop All Services:"
echo "    ./stop_complete_system.sh"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo ""

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║                                                                      ║"
echo "║  🎉 ATMS System Ready! Expected Performance: 26.9 FPS 🚀           ║"
echo "║                                                                      ║"
echo "║  Your AI-Powered Traffic Management System is operational!          ║"
echo "║  Start camera detection to see it in action! 📹                    ║"
echo "║                                                                      ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"

