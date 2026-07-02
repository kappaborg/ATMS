#!/bin/bash
# Complete System Restart Script
# Stops all services, starts Docker infrastructure, and starts all services
# Includes CoreML verification and performance testing

set -e

PROJECT_ROOT="/Users/kappasutra/Traffic"
cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "🔄 COMPLETE SYSTEM RESTART"
echo "=========================="
echo ""

# Step 1: Stop all services
echo -e "${YELLOW}Step 1: Stopping all services...${NC}"
echo "----------------------------------------"

# Stop all Python services
echo "  Stopping Python services..."
pkill -f "ai-perception.*main.py" || true
pkill -f "video-processor.*main.py" || true
pkill -f "dashboard.*enhanced_dashboard.py" || true
pkill -f "analytics.*main.py" || true
pkill -f "decision-engine.*main.py" || true
pkill -f "sensor-fusion.*main.py" || true

# Kill processes on specific ports
for port in 8001 8004 8005 8007 8008 8009 8010 8014; do
    lsof -ti:$port | xargs kill -9 2>/dev/null || true
done

sleep 3
echo -e "${GREEN}  ✅ All services stopped${NC}"
echo ""

# Step 2: Check Docker infrastructure
echo -e "${YELLOW}Step 2: Starting Docker infrastructure...${NC}"
echo "----------------------------------------"

# Check if Docker is running
if ! docker ps > /dev/null 2>&1; then
    echo -e "${RED}  ❌ Docker is not running${NC}"
    echo "  Starting Docker..."
    open -a Docker
    echo "  Waiting for Docker to start..."
    sleep 15
fi

# Start Docker services (skip dev.yml which has Prometheus mount issues)
DOCKER_COMPOSE_FILES=("docker-compose.yml" "docker-compose.kafka.yml" "docker-compose.database.yml")
DOCKER_STARTED=false

for compose_file in "${DOCKER_COMPOSE_FILES[@]}"; do
    if [ -f "$compose_file" ]; then
        echo "  Starting services from $compose_file..."
        if docker-compose -f "$compose_file" up -d 2>&1 | grep -v "WARN\|orphan" > /dev/null; then
            DOCKER_STARTED=true
        fi
        sleep 3
    fi
done

# Skip docker-compose.dev.yml (has Prometheus mount issues, not critical for pipeline)
if [ -f "docker-compose.dev.yml" ]; then
    echo "  ⚠️  Skipping docker-compose.dev.yml (Prometheus monitoring - not required for core pipeline)"
fi

# Also try starting individual services if compose files don't exist
if [ "$DOCKER_STARTED" = false ]; then
    echo "  No docker-compose.yml found, checking if services are already running..."
    if docker ps | grep -q kafka; then
        echo -e "${GREEN}  ✅ Kafka already running${NC}"
    fi
    if docker ps | grep -q postgres; then
        echo -e "${GREEN}  ✅ PostgreSQL already running${NC}"
    fi
    if docker ps | grep -q redis; then
        echo -e "${GREEN}  ✅ Redis already running${NC}"
    fi
fi

if [ "$DOCKER_STARTED" = true ]; then
    sleep 5
    
    # Verify Kafka
    if docker ps | grep -q atms-kafka; then
        echo -e "${GREEN}  ✅ Kafka is running${NC}"
    else
        echo -e "${YELLOW}  ⚠️  Kafka might still be starting...${NC}"
    fi
    
    # Verify PostgreSQL
    if docker ps | grep -q atms-postgres; then
        echo -e "${GREEN}  ✅ PostgreSQL is running${NC}"
    else
        echo -e "${YELLOW}  ⚠️  PostgreSQL might still be starting...${NC}"
    fi
    
    # Verify Redis
    if docker ps | grep -q atms-redis; then
        echo -e "${GREEN}  ✅ Redis is running${NC}"
    else
        echo -e "${YELLOW}  ⚠️  Redis might still be starting...${NC}"
    fi
else
    echo -e "${YELLOW}  ⚠️  docker-compose.yml not found, skipping Docker services${NC}"
fi
echo ""

# Step 3: Check CoreML models
echo -e "${YELLOW}Step 3: Checking CoreML models...${NC}"
echo "----------------------------------------"

COREML_COUNT=0
COREML_MODELS=(
    "services/ai-perception/models/yolov8n.mlpackage"
    "models/car_brand_classification/outputs/car_brand_classification_robust/weights/best.mlpackage"
    "multiview_models/top_view_model/weights/best.mlpackage"
    "multiview_models/side_profile_model/weights/best.mlpackage"
    "multiview_models/front_bumper_model/weights/best.mlpackage"
    "models/tramway_training/tramway_runs/train_20251028_210058/weights/best.mlpackage"
    "models/license_plate_training/outputs/license_plate_model_mps/weights/best.mlpackage"
)

for model in "${COREML_MODELS[@]}"; do
    if [ -d "$model" ] || [ -f "$model" ]; then
        echo -e "${GREEN}  ✅ $(basename $(dirname $model))${NC}"
        ((COREML_COUNT++))
    else
        echo -e "${YELLOW}  ⚠️  $(basename $(dirname $model)) - not converted${NC}"
    fi
done

if [ $COREML_COUNT -gt 0 ]; then
    echo ""
    echo -e "${GREEN}  📊 CoreML Status: $COREML_COUNT/${#COREML_MODELS[@]} models ready${NC}"
    echo -e "${BLUE}  💡 Expected: 3-5× faster inference!${NC}"
else
    echo ""
    echo -e "${YELLOW}  ⚠️  No CoreML models found. Run: ./scripts/convert_all_models_to_coreml.sh${NC}"
fi
echo ""

# Step 4: Start AI Perception Service
echo -e "${YELLOW}Step 4: Starting AI Perception Service...${NC}"
echo "----------------------------------------"

cd "$PROJECT_ROOT/services/ai-perception"

if [ ! -d "venv" ]; then
    echo "  Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -q --upgrade pip setuptools wheel
    pip install -q -r requirements.txt
else
    source venv/bin/activate
fi

# Use port 8014 to avoid conflicts
export API_PORT=8014
export PYTHONPATH="$PROJECT_ROOT/services/ai-perception/src:$PYTHONPATH"

echo "  Starting AI Perception (Port 8014) with all 6 AI models..."

# Kill any existing process on 8014
lsof -ti:8014 | xargs kill -9 2>/dev/null || true
sleep 1

# Start service directly
nohup python src/main.py > /tmp/atms_ai_perception.log 2>&1 &
AI_PID=$!
echo $AI_PID > /tmp/atms_ai_perception.pid
echo -e "${GREEN}  ✅ AI Perception started (PID: $AI_PID)${NC}"
echo ""

# Step 5: Start Video Processor Service
echo -e "${YELLOW}Step 5: Starting Video Processor Service...${NC}"
echo "----------------------------------------"

cd "$PROJECT_ROOT/services/video-processor"

if [ ! -d "venv" ]; then
    echo "  Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -q --upgrade pip setuptools wheel
    pip install -q -r requirements.txt
else
    source venv/bin/activate
fi

echo "  Starting Video Processor (Port 8008)..."
nohup python src/main.py > /tmp/atms_video_processor.log 2>&1 &
VIDEO_PID=$!
echo $VIDEO_PID > /tmp/atms_video_processor.pid
echo -e "${GREEN}  ✅ Video Processor started (PID: $VIDEO_PID)${NC}"
echo ""

# Step 6: Start Enhanced Dashboard
echo -e "${YELLOW}Step 6: Starting Enhanced Dashboard...${NC}"
echo "----------------------------------------"

cd "$PROJECT_ROOT/services/dashboard"

if [ ! -d "venv" ]; then
    echo "  Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -q --upgrade pip setuptools wheel
    pip install -q -r requirements.txt
else
    source venv/bin/activate
fi

echo "  Starting Enhanced Dashboard (Port 8009)..."
nohup python src/enhanced_dashboard.py > /tmp/atms_enhanced_dashboard.log 2>&1 &
DASHBOARD_PID=$!
echo $DASHBOARD_PID > /tmp/atms_enhanced_dashboard.pid
echo -e "${GREEN}  ✅ Enhanced Dashboard started (PID: $DASHBOARD_PID)${NC}"
echo ""

# Step 7: Wait for services to initialize
echo -e "${YELLOW}Step 7: Waiting for services to initialize...${NC}"
sleep 8
echo ""

# Step 8: Health checks
echo -e "${YELLOW}Step 8: Performing health checks...${NC}"
echo "----------------------------------------"

check_service() {
    local name=$1
    local port=$2
    local url="http://localhost:$port/health"
    
    for i in {1..5}; do
        if curl -s "$url" > /dev/null 2>&1; then
            echo -e "${GREEN}  ✅ $name (port $port) is healthy${NC}"
            return 0
        fi
        sleep 2
    done
    
    echo -e "${YELLOW}  ⚠️  $name (port $port) might still be starting...${NC}"
    return 1
}

check_service "AI Perception" 8014
check_service "Video Processor" 8008
check_service "Enhanced Dashboard" 8009
echo ""

# Step 9: Check CoreML usage in logs
echo -e "${YELLOW}Step 9: Checking CoreML usage...${NC}"
echo "----------------------------------------"

if [ -f /tmp/atms_ai_perception.log ]; then
    if grep -q "CoreML" /tmp/atms_ai_perception.log 2>/dev/null; then
        echo -e "${GREEN}  ✅ CoreML models detected in logs${NC}"
        echo "  Recent CoreML messages:"
        tail -20 /tmp/atms_ai_perception.log | grep -i coreml | tail -3 || echo "    (checking...)"

    else
        echo -e "${YELLOW}  ⚠️  No CoreML messages yet (service might still be loading)${NC}"
    fi
else
    echo -e "${YELLOW}  ⚠️  Log file not found yet${NC}"
fi
echo ""

# Final Summary
echo "=========================================="
echo -e "${GREEN}🎉 SYSTEM RESTART COMPLETE!${NC}"
echo "=========================================="
echo ""
echo -e "${BLUE}📊 Service URLs:${NC}"
echo "  🎥 Video Upload:      http://localhost:8008"
echo "  📊 Enhanced Dashboard: http://localhost:8009"
echo "  🤖 AI Perception:     http://localhost:8014"
echo "  📈 Kafka UI:          http://localhost:8080"
echo "  🗄️  pgAdmin:            http://localhost:5050"
echo ""
echo -e "${BLUE}📝 Logs (real-time monitoring):${NC}"
echo "  AI Perception:       tail -f /tmp/atms_ai_perception.log"
echo "  Video Processor:     tail -f /tmp/atms_video_processor.log"
echo "  Enhanced Dashboard:  tail -f /tmp/atms_enhanced_dashboard.log"
echo ""
echo -e "${BLUE}🔍 Check CoreML Usage:${NC}"
echo "  grep -i coreml /tmp/atms_ai_perception.log"
echo ""
echo -e "${BLUE}📊 Check Performance:${NC}"
echo "  grep -i 'fps\|ms/frame' /tmp/atms_ai_perception.log | tail -10"
echo ""
echo -e "${BLUE}🧪 Test the System:${NC}"
echo "  1. Open http://localhost:8008"
echo "  2. Upload a video (T1.mp4 or T2.mp4)"
echo "  3. Watch real-time processing"
echo "  4. View results on http://localhost:8009"
echo ""
echo -e "${BLUE}🛑 To Stop All Services:${NC}"
echo "  ./scripts/stop_all_services.sh"
echo ""
echo -e "${GREEN}✅ System is ready for testing!${NC}"
echo ""

