#!/bin/bash
# ============================================
# Demo System Verification Script
# ============================================
# Verifies all configurations, connections, and integrations
# Run this before your presentation demo

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}🔍 DEMO SYSTEM VERIFICATION${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# Track errors
ERRORS=0
WARNINGS=0

# Function to check command
check_command() {
    if command -v "$1" &> /dev/null; then
        echo -e "${GREEN}✅ $1 is installed${NC}"
        return 0
    else
        echo -e "${RED}❌ $1 is NOT installed${NC}"
        ((ERRORS++))
        return 1
    fi
}

# Function to check port
check_port() {
    if lsof -Pi :$1 -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Port $1 is open (service running)${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠️  Port $1 is not open (service may not be running)${NC}"
        ((WARNINGS++))
        return 1
    fi
}

# Function to check file
check_file() {
    if [ -f "$1" ]; then
        echo -e "${GREEN}✅ File exists: $1${NC}"
        return 0
    else
        echo -e "${RED}❌ File missing: $1${NC}"
        ((ERRORS++))
        return 1
    fi
}

# Function to check Python import
check_python_import() {
    python3 -c "import $1" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Python module '$1' is available${NC}"
        return 0
    else
        echo -e "${RED}❌ Python module '$1' is NOT available${NC}"
        ((ERRORS++))
        return 1
    fi
}

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}1. SYSTEM REQUIREMENTS${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

check_command "python3"
check_command "pip3"
check_command "yt-dlp"
check_command "docker"
check_command "docker-compose"

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}2. PYTHON DEPENDENCIES${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

check_python_import "cv2"
check_python_import "numpy"
check_python_import "torch"
check_python_import "ultralytics"
check_python_import "aiokafka"
check_python_import "asyncio"
check_python_import "prometheus_client"
check_python_import "psutil"

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}3. CORE FILES${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

check_file "youtube_decision_processor.py"
check_file "ai_decision_system.py"
check_file "services/ai-perception/src/detection/yolo_detector.py"
check_file "services/ai-perception/src/calculations/speed_calculator.py"
check_file "services/ai-perception/src/calculations/enhanced_emission_calculator.py"
check_file "services/ai-perception/src/tracking/bytetrack_simple.py"

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}4. MODEL FILES${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check for model files (at least one should exist)
MODEL_FOUND=0
if [ -f "models/vehicle_classification_training/weights/best.mlpackage" ] || \
   [ -f "models/vehicle_classification_training/weights/best.pt" ] || \
   [ -f "models/yolov8n.mlpackage" ] || \
   [ -f "models/yolov8n.pt" ]; then
    echo -e "${GREEN}✅ YOLO model found${NC}"
    MODEL_FOUND=1
else
    echo -e "${YELLOW}⚠️  YOLO model not found (will use default)${NC}"
    ((WARNINGS++))
fi

if [ -f "models/license_plate_training/outputs/license_plate_model_mps/weights/best.mlpackage" ] || \
   [ -f "models/license_plate_training/outputs/license_plate_model_mps/weights/best.pt" ]; then
    echo -e "${GREEN}✅ License plate model found${NC}"
else
    echo -e "${YELLOW}⚠️  License plate model not found (optional)${NC}"
    ((WARNINGS++))
fi

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}5. INFRASTRUCTURE SERVICES${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${YELLOW}Note: These services are optional - system will work without them${NC}"
check_port 9092  # Kafka
check_port 5432  # PostgreSQL
check_port 6379  # Redis
check_port 9090  # Prometheus

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}6. CONFIGURATION CHECK${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check environment variables
if [ -z "$KAFKA_BOOTSTRAP_SERVERS" ]; then
    echo -e "${YELLOW}⚠️  KAFKA_BOOTSTRAP_SERVERS not set (will use default: localhost:9092)${NC}"
    ((WARNINGS++))
else
    echo -e "${GREEN}✅ KAFKA_BOOTSTRAP_SERVERS is set: $KAFKA_BOOTSTRAP_SERVERS${NC}"
fi

if [ -z "$PIXEL_TO_METER_RATIO" ]; then
    echo -e "${YELLOW}⚠️  PIXEL_TO_METER_RATIO not set (will auto-calibrate)${NC}"
    ((WARNINGS++))
else
    echo -e "${GREEN}✅ PIXEL_TO_METER_RATIO is set: $PIXEL_TO_METER_RATIO${NC}"
fi

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}7. PYTHON SYNTAX CHECK${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

python3 -m py_compile youtube_decision_processor.py 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ youtube_decision_processor.py syntax is valid${NC}"
else
    echo -e "${RED}❌ youtube_decision_processor.py has syntax errors${NC}"
    ((ERRORS++))
fi

python3 -m py_compile ai_decision_system.py 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ ai_decision_system.py syntax is valid${NC}"
else
    echo -e "${RED}❌ ai_decision_system.py has syntax errors${NC}"
    ((ERRORS++))
fi

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}8. IMPORT TEST${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

python3 << 'EOF'
import sys
import traceback

errors = []
warnings = []

# Test critical imports
imports_to_test = [
    ("cv2", "OpenCV"),
    ("numpy", "NumPy"),
    ("torch", "PyTorch"),
    ("ultralytics", "Ultralytics YOLO"),
    ("asyncio", "asyncio"),
]

for module_name, description in imports_to_test:
    try:
        __import__(module_name)
        print(f"✅ {description} imported successfully")
    except ImportError as e:
        print(f"❌ {description} import failed: {e}")
        errors.append(f"{description}: {e}")

# Test optional imports
optional_imports = [
    ("aiokafka", "Kafka (optional)"),
    ("prometheus_client", "Prometheus (optional)"),
    ("psutil", "psutil (optional)"),
]

for module_name, description in optional_imports:
    try:
        __import__(module_name)
        print(f"✅ {description} imported successfully")
    except ImportError:
        print(f"⚠️  {description} not available (optional)")
        warnings.append(description)

# Test project-specific imports
try:
    sys.path.insert(0, "services/ai-perception/src")
    from detection.yolo_detector import YOLODetector
    print("✅ YOLODetector imported successfully")
except Exception as e:
    print(f"❌ YOLODetector import failed: {e}")
    errors.append(f"YOLODetector: {e}")

try:
    from calculations.speed_calculator import SpeedCalculator
    print("✅ SpeedCalculator imported successfully")
except Exception as e:
    print(f"❌ SpeedCalculator import failed: {e}")
    errors.append(f"SpeedCalculator: {e}")

try:
    from calculations.enhanced_emission_calculator import EnhancedEmissionCalculator
    print("✅ EnhancedEmissionCalculator imported successfully")
except Exception as e:
    print(f"❌ EnhancedEmissionCalculator import failed: {e}")
    errors.append(f"EnhancedEmissionCalculator: {e}")

try:
    from tracking.bytetrack_simple import SimpleByteTracker
    print("✅ SimpleByteTracker imported successfully")
except Exception as e:
    print(f"❌ SimpleByteTracker import failed: {e}")
    errors.append(f"SimpleByteTracker: {e}")

if errors:
    print(f"\n❌ {len(errors)} critical import errors found")
    sys.exit(1)
else:
    print(f"\n✅ All critical imports successful")
    if warnings:
        print(f"⚠️  {len(warnings)} optional modules not available (system will work without them)")
    sys.exit(0)
EOF

IMPORT_EXIT=$?
if [ $IMPORT_EXIT -ne 0 ]; then
    ((ERRORS++))
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}📊 VERIFICATION SUMMARY${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ All critical checks passed!${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}⚠️  $WARNINGS warnings (non-critical)${NC}"
    fi
    echo ""
    echo -e "${GREEN}🎉 System is ready for demo!${NC}"
    exit 0
else
    echo -e "${RED}❌ $ERRORS critical errors found${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}⚠️  $WARNINGS warnings${NC}"
    fi
    echo ""
    echo -e "${RED}⚠️  Please fix errors before running demo${NC}"
    exit 1
fi


