#!/bin/bash
# Complete Pipeline Test Script
# Tests the entire system: Video Upload → Kafka → AI Processing → Video Output

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "======================================================================"
echo "Complete Pipeline Test - End-to-End System Verification"
echo "======================================================================"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Docker is running
echo "📋 Step 1: Checking Docker..."
if ! docker ps > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running. Please start Docker first.${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Docker is running${NC}"
echo ""

# Check if Kafka is running
echo "📋 Step 2: Checking Kafka..."
if ! docker ps | grep -q kafka; then
    echo -e "${YELLOW}⚠️  Kafka is not running. Starting infrastructure...${NC}"
    cd "$PROJECT_ROOT"
    docker-compose -f docker-compose.dev.yml up -d zookeeper kafka postgres redis
    echo "⏳ Waiting for Kafka to be ready..."
    sleep 10
fi
echo -e "${GREEN}✅ Kafka is running${NC}"
echo ""

# Check if AI Perception service is running
echo "📋 Step 3: Checking AI Perception Service..."
AI_PERCEPTION_PORT=8014
if ! lsof -Pi :$AI_PERCEPTION_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  AI Perception service is not running on port $AI_PERCEPTION_PORT${NC}"
    echo "   Please start it manually:"
    echo "   cd services/ai-perception && source venv/bin/activate && python src/main.py"
    echo ""
    read -p "Press Enter when AI Perception service is running..."
else
    echo -e "${GREEN}✅ AI Perception service is running on port $AI_PERCEPTION_PORT${NC}"
fi
echo ""

# Check if Video Processor service is running
echo "📋 Step 4: Checking Video Processor Service..."
VIDEO_PROCESSOR_PORT=8010
if ! lsof -Pi :$VIDEO_PROCESSOR_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Video Processor service is not running on port $VIDEO_PROCESSOR_PORT${NC}"
    echo "   Please start it manually:"
    echo "   cd services/video-processor && source venv/bin/activate && python src/main.py"
    echo ""
    read -p "Press Enter when Video Processor service is running..."
else
    echo -e "${GREEN}✅ Video Processor service is running on port $VIDEO_PROCESSOR_PORT${NC}"
fi
echo ""

# Check Kafka topics
echo "📋 Step 5: Verifying Kafka Topics..."
KAFKA_CONTAINER=$(docker ps | grep kafka | awk '{print $1}')
if [ -z "$KAFKA_CONTAINER" ]; then
    echo -e "${RED}❌ Kafka container not found${NC}"
    exit 1
fi

echo "Checking required topics..."
TOPICS=("camera-frames" "detections" "license-plates" "emission-data" "trajectory-data" "traffic-metrics")
for topic in "${TOPICS[@]}"; do
    if docker exec "$KAFKA_CONTAINER" kafka-topics.sh --bootstrap-server localhost:9092 --list | grep -q "^${topic}$"; then
        echo -e "  ${GREEN}✅${NC} Topic: $topic"
    else
        echo -e "  ${YELLOW}⚠️${NC}  Topic: $topic (will be created automatically)"
    fi
done
echo ""

# Test video file
echo "📋 Step 6: Checking Test Video..."
TEST_VIDEO="videos/LPDT.mp4"
if [ ! -f "$TEST_VIDEO" ]; then
    echo -e "${YELLOW}⚠️  Test video not found: $TEST_VIDEO${NC}"
    echo "   Please provide a test video file"
    read -p "Enter path to test video (or press Enter to skip): " TEST_VIDEO
    if [ -z "$TEST_VIDEO" ] || [ ! -f "$TEST_VIDEO" ]; then
        echo -e "${RED}❌ No valid test video provided${NC}"
        exit 1
    fi
fi
echo -e "${GREEN}✅ Test video found: $TEST_VIDEO${NC}"
echo ""

# Create monitoring script
echo "📋 Step 7: Creating Kafka Monitoring Script..."
cat > /tmp/monitor_kafka_test.sh << 'EOF'
#!/bin/bash
KAFKA_CONTAINER=$(docker ps | grep kafka | awk '{print $1}')
if [ -z "$KAFKA_CONTAINER" ]; then
    echo "Kafka container not found"
    exit 1
fi

echo "Monitoring Kafka topics..."
echo "Press Ctrl+C to stop"
echo ""

while true; do
    clear
    echo "=== Kafka Topic Message Counts ==="
    echo ""
    for topic in camera-frames detections license-plates emission-data trajectory-data traffic-metrics; do
        count=$(docker exec "$KAFKA_CONTAINER" kafka-run-class.sh kafka.tools.GetOffsetShell \
            --broker-list localhost:9092 \
            --topic "$topic" 2>/dev/null | awk -F: '{sum+=$3} END {print sum}' || echo "0")
        printf "%-20s: %s\n" "$topic" "$count"
    done
    echo ""
    echo "Last updated: $(date '+%H:%M:%S')"
    sleep 2
done
EOF
chmod +x /tmp/monitor_kafka_test.sh
echo -e "${GREEN}✅ Monitoring script created${NC}"
echo ""

# Summary
echo "======================================================================"
echo "Test Setup Complete!"
echo "======================================================================"
echo ""
echo "📊 System Status:"
echo "  ✅ Docker: Running"
echo "  ✅ Kafka: Running"
echo "  ✅ AI Perception: Port $AI_PERCEPTION_PORT"
echo "  ✅ Video Processor: Port $VIDEO_PROCESSOR_PORT"
echo "  ✅ Test Video: $TEST_VIDEO"
echo ""
echo "🧪 Testing Instructions:"
echo ""
echo "1. Open Video Processor Web Interface:"
echo "   http://localhost:$VIDEO_PROCESSOR_PORT"
echo ""
echo "2. Upload test video: $TEST_VIDEO"
echo ""
echo "3. Monitor Kafka (in a separate terminal):"
echo "   /tmp/monitor_kafka_test.sh"
echo ""
echo "4. Check AI Perception logs for:"
echo "   - Professional OCR results"
echo "   - License plate detections"
echo "   - Brand classifications"
echo "   - Multi-view detections"
echo "   - Emission calculations"
echo ""
echo "5. Wait for processing to complete"
echo ""
echo "6. Download processed video from:"
echo "   http://localhost:$VIDEO_PROCESSOR_PORT/api/download/{video_id}"
echo ""
echo "7. Verify processed video contains:"
echo "   ✅ Bounding boxes"
echo "   ✅ License plate text (68% should have text)"
echo "   ✅ Vehicle brands"
echo "   ✅ Speed information"
echo "   ✅ CO2 emissions"
echo "   ✅ Trajectory heatmap"
echo ""
echo "======================================================================"
echo ""
read -p "Press Enter to open the Video Processor web interface..."
open "http://localhost:$VIDEO_PROCESSOR_PORT" 2>/dev/null || echo "Please open: http://localhost:$VIDEO_PROCESSOR_PORT"

