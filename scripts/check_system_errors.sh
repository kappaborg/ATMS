#!/bin/bash
# System Error Check Script
# Checks for common errors in the system

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "═══════════════════════════════════════════════════════════════"
echo "🔍 System Error Check"
echo "═══════════════════════════════════════════════════════════════"
echo ""

ERRORS_FOUND=0

# Check 1: Python dependencies
echo "1. Checking Python Dependencies..."
MISSING=()

check_python_dep() {
    if python3 -c "import $1" 2>/dev/null; then
        echo -e "${GREEN}  ✅ $1${NC}"
    else
        echo -e "${RED}  ❌ $1 (MISSING)${NC}"
        MISSING+=("$1")
        ERRORS_FOUND=$((ERRORS_FOUND + 1))
    fi
}

check_python_dep "cv2"
check_python_dep "numpy"
check_python_dep "ultralytics"
check_python_dep "aiokafka"
check_python_dep "yt_dlp"

if [ ${#MISSING[@]} -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}  Fix: pip3 install ${MISSING[*]}${NC}"
fi

echo ""

# Check 2: Service logs
echo "2. Checking Service Logs for Errors..."
LOG_FILES=$(find /tmp -name "atms_*.log" -type f 2>/dev/null | head -5)

if [ -z "$LOG_FILES" ]; then
    echo -e "${YELLOW}  ⚠️  No service logs found${NC}"
else
    for log in $LOG_FILES; do
        SERVICE=$(basename "$log" .log | sed 's/atms_//')
        ERROR_COUNT=$(grep -i "error\|exception\|fail" "$log" 2>/dev/null | wc -l | tr -d ' ')
        
        if [ "$ERROR_COUNT" -gt 0 ]; then
            echo -e "${RED}  ❌ $SERVICE: $ERROR_COUNT errors found${NC}"
            echo -e "${YELLOW}    Recent errors:${NC}"
            grep -i "error\|exception\|fail" "$log" 2>/dev/null | tail -3 | sed 's/^/      /'
            ERRORS_FOUND=$((ERRORS_FOUND + 1))
        else
            echo -e "${GREEN}  ✅ $SERVICE: No errors${NC}"
        fi
    done
fi

echo ""

# Check 3: Port conflicts
echo "3. Checking Port Conflicts..."
PORTS=(8004 8007 8008 8009 8010)

for port in "${PORTS[@]}"; do
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        PROCESS=$(lsof -Pi :$port -sTCP:LISTEN | tail -1 | awk '{print $1, $2}')
        echo -e "${GREEN}  ✅ Port $port: In use by $PROCESS${NC}"
    else
        echo -e "${YELLOW}  ⚠️  Port $port: Not in use${NC}"
    fi
done

echo ""

# Check 4: File existence
echo "4. Checking Critical Files..."
FILES=(
    "youtube_decision_processor.py"
    "services/ai-perception/src/main.py"
    "services/decision-engine/src/main.py"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}  ✅ $file${NC}"
    else
        echo -e "${RED}  ❌ $file (MISSING)${NC}"
        ERRORS_FOUND=$((ERRORS_FOUND + 1))
    fi
done

echo ""

# Check 5: Import test
echo "5. Testing Python Imports..."
if python3 -c "
import sys
sys.path.insert(0, '.')
try:
    import cv2
    import numpy as np
    print('  ✅ Basic imports OK')
except ImportError as e:
    print(f'  ❌ Import error: {e}')
    sys.exit(1)
" 2>&1; then
    echo -e "${GREEN}  ✅ Python imports working${NC}"
else
    echo -e "${RED}  ❌ Python imports failed${NC}"
    ERRORS_FOUND=$((ERRORS_FOUND + 1))
fi

echo ""

# Summary
echo "═══════════════════════════════════════════════════════════════"
if [ $ERRORS_FOUND -eq 0 ]; then
    echo -e "${GREEN}✅ No errors found! System is ready.${NC}"
else
    echo -e "${RED}❌ Found $ERRORS_FOUND error(s)${NC}"
    echo ""
    echo "Fix suggestions:"
    echo "  1. Install missing dependencies: pip3 install opencv-python numpy ultralytics aiokafka yt-dlp"
    echo "  2. Check service logs: tail -f /tmp/atms_*.log"
    echo "  3. Restart services if needed"
fi
echo "═══════════════════════════════════════════════════════════════"
echo ""

exit $ERRORS_FOUND

