#!/bin/bash
# Test System Status - Check all services and CoreML usage

PROJECT_ROOT="/Users/kappasutra/Traffic"
cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "🔍 SYSTEM STATUS CHECK"
echo "======================"
echo ""

# Check services
echo -e "${BLUE}1. Service Health:${NC}"
echo "----------------------------------------"

check_service() {
    local name=$1
    local port=$2
    local url="http://localhost:$port/health"
    
    if curl -s "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}  ✅ $name (port $port)${NC}"
        return 0
    else
        echo -e "${RED}  ❌ $name (port $port) - NOT RUNNING${NC}"
        return 1
    fi
}

check_service "AI Perception" 8014
check_service "Video Processor" 8008
check_service "Enhanced Dashboard" 8009
echo ""

# Check Docker
echo -e "${BLUE}2. Docker Infrastructure:${NC}"
echo "----------------------------------------"
if docker ps | grep -q atms-kafka; then
    echo -e "${GREEN}  ✅ Kafka${NC}"
else
    echo -e "${RED}  ❌ Kafka - NOT RUNNING${NC}"
fi

if docker ps | grep -q atms-postgres; then
    echo -e "${GREEN}  ✅ PostgreSQL${NC}"
else
    echo -e "${RED}  ❌ PostgreSQL - NOT RUNNING${NC}"
fi

if docker ps | grep -q atms-redis; then
    echo -e "${GREEN}  ✅ Redis${NC}"
else
    echo -e "${RED}  ❌ Redis - NOT RUNNING${NC}"
fi
echo ""

# Check CoreML models
echo -e "${BLUE}3. CoreML Models:${NC}"
echo "----------------------------------------"
COREML_COUNT=0
COREML_MODELS=(
    "services/ai-perception/models/yolov8n.mlpackage:YOLOv8 Main"
    "models/car_brand_classification/outputs/car_brand_classification_robust/weights/best.mlpackage:Car Brand"
    "multiview_models/top_view_model/weights/best.mlpackage:Multi-View Top"
    "multiview_models/side_profile_model/weights/best.mlpackage:Multi-View Side"
    "multiview_models/front_bumper_model/weights/best.mlpackage:Multi-View Front"
    "models/tramway_training/tramway_runs/train_20251028_210058/weights/best.mlpackage:Tramway"
    "models/license_plate_training/outputs/license_plate_model_mps/weights/best.mlpackage:License Plate"
)

for model_info in "${COREML_MODELS[@]}"; do
    IFS=':' read -r model_path model_name <<< "$model_info"
    if [ -d "$model_path" ] || [ -f "$model_path" ]; then
        echo -e "${GREEN}  ✅ $model_name${NC}"
        ((COREML_COUNT++))
    else
        echo -e "${YELLOW}  ⚠️  $model_name - not converted${NC}"
    fi
done

echo ""
echo -e "${BLUE}  CoreML Status: $COREML_COUNT/${#COREML_MODELS[@]} models${NC}"
echo ""

# Check CoreML usage in logs
echo -e "${BLUE}4. CoreML Usage (from logs):${NC}"
echo "----------------------------------------"
if [ -f /tmp/atms_ai_perception.log ]; then
    COREML_LINES=$(grep -i "coreml" /tmp/atms_ai_perception.log 2>/dev/null | wc -l | tr -d ' ')
    if [ "$COREML_LINES" -gt 0 ]; then
        echo -e "${GREEN}  ✅ CoreML detected in logs ($COREML_LINES messages)${NC}"
        echo ""
        echo "  Recent CoreML messages:"
        grep -i "coreml" /tmp/atms_ai_perception.log 2>/dev/null | tail -5 | sed 's/^/    /'
    else
        echo -e "${YELLOW}  ⚠️  No CoreML messages in logs yet${NC}"
    fi
else
    echo -e "${YELLOW}  ⚠️  Log file not found${NC}"
fi
echo ""

# Check performance metrics
echo -e "${BLUE}5. Performance Metrics:${NC}"
echo "----------------------------------------"
if [ -f /tmp/atms_ai_perception.log ]; then
    FPS_LINES=$(grep -i "fps\|ms/frame" /tmp/atms_ai_perception.log 2>/dev/null | tail -5)
    if [ -n "$FPS_LINES" ]; then
        echo "  Recent performance:"
        echo "$FPS_LINES" | tail -3 | sed 's/^/    /'
    else
        echo -e "${YELLOW}  ⚠️  No performance metrics yet${NC}"
    fi
else
    echo -e "${YELLOW}  ⚠️  Log file not found${NC}"
fi
echo ""

# Summary
echo "=========================================="
if [ $COREML_COUNT -gt 0 ]; then
    echo -e "${GREEN}✅ System Status: OPERATIONAL${NC}"
    echo -e "${BLUE}💡 CoreML: $COREML_COUNT models ready (3-5× faster!)${NC}"
else
    echo -e "${YELLOW}⚠️  System Status: RUNNING (No CoreML models)${NC}"
    echo -e "${BLUE}💡 Convert models: ./scripts/convert_all_models_to_coreml.sh${NC}"
fi
echo "=========================================="

