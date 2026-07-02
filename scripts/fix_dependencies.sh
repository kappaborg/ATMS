#!/bin/bash
# Fix Dependencies Script
# Installs all required dependencies for YouTube testing

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
echo "🔧 Fixing Dependencies"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Determine if we need --user flag (Python 3.14+)
PYTHON_VERSION=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
MAJOR_VERSION=$(echo $PYTHON_VERSION | cut -d. -f1)
MINOR_VERSION=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$MAJOR_VERSION" -ge 3 ] && [ "$MINOR_VERSION" -ge 12 ]; then
    PIP_FLAGS="--user"
    echo "📌 Using --user flag for Python $PYTHON_VERSION"
else
    PIP_FLAGS=""
fi

# Core dependencies
echo "📦 Installing Core Dependencies..."
pip3 install $PIP_FLAGS --upgrade pip setuptools wheel 2>&1 | grep -E "(Successfully|Requirement|ERROR|WARNING)" || true

echo ""
echo "📦 Installing OpenCV..."
pip3 install $PIP_FLAGS opencv-python 2>&1 | grep -E "(Successfully|Requirement|ERROR|WARNING)" || true

echo ""
echo "📦 Installing NumPy..."
pip3 install $PIP_FLAGS numpy 2>&1 | grep -E "(Successfully|Requirement|ERROR|WARNING)" || true

echo ""
echo "📦 Installing Ultralytics (YOLOv8)..."
pip3 install $PIP_FLAGS ultralytics 2>&1 | grep -E "(Successfully|Requirement|ERROR|WARNING)" || true

echo ""
echo "📦 Installing Kafka..."
pip3 install $PIP_FLAGS aiokafka 2>&1 | grep -E "(Successfully|Requirement|ERROR|WARNING)" || true

echo ""
echo "📦 Installing YouTube Downloader..."
pip3 install $PIP_FLAGS yt-dlp 2>&1 | grep -E "(Successfully|Requirement|ERROR|WARNING)" || true

echo ""
echo "📦 Installing Additional Dependencies..."
pip3 install $PIP_FLAGS fastapi uvicorn pydantic prometheus-client psutil 2>&1 | grep -E "(Successfully|Requirement|ERROR|WARNING)" || true

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "✅ Dependencies Installation Complete"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Verify installation
echo "🔍 Verifying Installation..."
python3 -c "
import sys
errors = []
try:
    import cv2
    print('✅ cv2 (OpenCV)')
except ImportError:
    errors.append('cv2')
    print('❌ cv2')

try:
    import numpy
    print('✅ numpy')
except ImportError:
    errors.append('numpy')
    print('❌ numpy')

try:
    import ultralytics
    print('✅ ultralytics')
except ImportError:
    errors.append('ultralytics')
    print('❌ ultralytics')

try:
    import aiokafka
    print('✅ aiokafka')
except ImportError:
    errors.append('aiokafka')
    print('❌ aiokafka')

try:
    import yt_dlp
    print('✅ yt-dlp')
except ImportError:
    errors.append('yt-dlp')
    print('❌ yt-dlp')

if errors:
    print(f'\n❌ Failed to install: {errors}')
    sys.exit(1)
else:
    print('\n✅ All dependencies installed successfully!')
"

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✅ All dependencies are ready!${NC}"
    echo ""
    echo "You can now test YouTube video:"
    echo "  ./scripts/quick_test_youtube.sh <youtube_url>"
else
    echo -e "${RED}❌ Some dependencies failed to install${NC}"
    echo "Try installing manually:"
    echo "  pip3 install opencv-python numpy ultralytics aiokafka yt-dlp"
fi

exit $EXIT_CODE

