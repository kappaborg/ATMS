#!/bin/bash
# Complete YouTube Video Test Script
# Tests YouTube video processing with all services and models

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "═══════════════════════════════════════════════════════════════"
echo "🎥 Complete YouTube Video Test"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Check if YouTube URL is provided
if [ -z "$1" ]; then
    echo -e "${YELLOW}Usage: $0 <youtube_url> [options]${NC}"
    echo ""
    echo "Options:"
    echo "  --duration <seconds>    Test duration (default: 60)"
    echo "  --no-display            Disable video display"
    echo "  --no-save               Don't save output video"
    echo "  --dashboard             Show Python dashboard"
    echo ""
    echo "Example:"
    echo "  $0 'https://www.youtube.com/watch?v=...' --duration 120"
    echo ""
    exit 1
fi

YOUTUBE_URL="$1"
DURATION=${DURATION:-60}
DISPLAY_FLAG=""
SAVE_FLAG=""
DASHBOARD_FLAG=""

# Parse additional arguments
shift
while [[ $# -gt 0 ]]; do
    case $1 in
        --duration)
            DURATION="$2"
            shift 2
            ;;
        --no-display)
            DISPLAY_FLAG="--no-display"
            shift
            ;;
        --no-save)
            SAVE_FLAG="--no-save"
            shift
            ;;
        --dashboard)
            DASHBOARD_FLAG="--dashboard"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

echo -e "${BLUE}YouTube URL: $YOUTUBE_URL${NC}"
echo -e "${BLUE}Duration: $DURATION seconds${NC}"
echo ""

# Step 1: Check Python and dependencies
echo "📋 Step 1: Checking Prerequisites..."
echo "----------------------------------------"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3 not found${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python3 found: $(python3 --version)${NC}"

# Check critical dependencies
echo "  Checking dependencies..."
MISSING_DEPS=()

check_dep() {
    if python3 -c "import $1" 2>/dev/null; then
        echo -e "${GREEN}    ✅ $1${NC}"
    else
        echo -e "${RED}    ❌ $1 (missing)${NC}"
        MISSING_DEPS+=("$1")
    fi
}

check_dep "cv2"
check_dep "numpy"
check_dep "ultralytics"
check_dep "aiokafka"
check_dep "yt_dlp"

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}⚠️  Missing dependencies detected${NC}"
    echo "  Installing missing dependencies..."
    pip3 install opencv-python numpy ultralytics aiokafka yt-dlp 2>&1 | grep -E "(Successfully|Requirement|ERROR)" || true
    echo ""
fi

# Step 2: Check if services are running (optional)
echo ""
echo "📋 Step 2: Checking Services (Optional)..."
echo "----------------------------------------"

check_service() {
    local port=$1
    local name=$2
    
    if curl -s -f -m 2 "http://localhost:$port/health" > /dev/null 2>&1; then
        echo -e "${GREEN}  ✅ $name (port $port) - Running${NC}"
        return 0
    else
        echo -e "${YELLOW}  ⚠️  $name (port $port) - Not running (optional)${NC}"
        return 1
    fi
}

check_service 8004 "AI Perception"
check_service 8007 "Decision Engine"
check_service 8009 "Analytics"

echo ""
echo -e "${BLUE}Note: Services are optional. YouTube processor can run standalone.${NC}"
echo ""

# Step 3: Check Docker infrastructure (optional)
echo "📋 Step 3: Checking Docker Infrastructure (Optional)..."
echo "----------------------------------------"

if command -v docker &> /dev/null && docker ps > /dev/null 2>&1; then
    if docker ps | grep -q kafka; then
        echo -e "${GREEN}  ✅ Kafka is running${NC}"
    else
        echo -e "${YELLOW}  ⚠️  Kafka not running (optional for testing)${NC}"
    fi
else
    echo -e "${YELLOW}  ⚠️  Docker not available (optional)${NC}"
fi

echo ""

# Step 4: Create output directory
OUTPUT_DIR="test_output/youtube_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_DIR"
echo -e "${BLUE}Output directory: $OUTPUT_DIR${NC}"
echo ""

# Step 5: Run YouTube processor
echo "═══════════════════════════════════════════════════════════════"
echo "🎬 Starting YouTube Video Processing"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Check if youtube_decision_processor.py exists
if [ ! -f "youtube_decision_processor.py" ]; then
    echo -e "${RED}❌ youtube_decision_processor.py not found${NC}"
    exit 1
fi

# Build command
CMD="python3 youtube_decision_processor.py \"$YOUTUBE_URL\""

if [ -n "$DISPLAY_FLAG" ]; then
    CMD="$CMD $DISPLAY_FLAG"
fi

if [ -n "$SAVE_FLAG" ]; then
    CMD="$CMD $SAVE_FLAG"
fi

if [ -n "$DASHBOARD_FLAG" ]; then
    CMD="$CMD $DASHBOARD_FLAG"
fi

if [ -n "$OUTPUT_DIR" ]; then
    CMD="$CMD -o \"$OUTPUT_DIR/output_video.mp4\""
fi

echo -e "${BLUE}Command:${NC}"
echo "  $CMD"
echo ""
echo -e "${YELLOW}Processing video... (This may take a while)${NC}"
echo ""

# Run the processor
eval $CMD 2>&1 | tee "$OUTPUT_DIR/processing.log"

EXIT_CODE=${PIPESTATUS[0]}

echo ""
echo "═══════════════════════════════════════════════════════════════"

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✅ YouTube Video Test Complete!${NC}"
else
    echo -e "${RED}❌ YouTube Video Test Failed (exit code: $EXIT_CODE)${NC}"
fi

echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "📁 Output Files:"
echo "  - Processing log: $OUTPUT_DIR/processing.log"
if [ -z "$SAVE_FLAG" ]; then
    echo "  - Output video: $OUTPUT_DIR/output_video.mp4 (if saved)"
fi
echo ""
echo "📊 Check the log file for detailed output and any errors."
echo ""

exit $EXIT_CODE

