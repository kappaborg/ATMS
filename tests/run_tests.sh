#!/bin/bash
# Test Runner Script
# Uses the AI Perception service venv for testing

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🧪 Running Tests..."
echo "Project Root: $PROJECT_ROOT"
echo ""

# Check if AI Perception venv exists
VENV_PATH="$PROJECT_ROOT/services/ai-perception/venv"
if [ ! -d "$VENV_PATH" ]; then
    echo "❌ Virtual environment not found at: $VENV_PATH"
    echo "Please run: cd services/ai-perception && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Activate venv
echo "📦 Activating virtual environment..."
source "$VENV_PATH/bin/activate"

# Install test dependencies if needed
echo "📥 Installing test dependencies..."
pip install -q pytest pytest-asyncio pytest-cov httpx numpy opencv-python || true

# Set PYTHONPATH
export PYTHONPATH="$PROJECT_ROOT:$PROJECT_ROOT/services/ai-perception/src:$PROJECT_ROOT/services/video-processor/src:$PYTHONPATH"

# Run tests
echo ""
echo "🚀 Running benchmark tests..."
python3 "$SCRIPT_DIR/benchmark_performance_tests.py" || echo "⚠️  Benchmark tests failed (may need models)"

echo ""
echo "🚀 Running white box unit tests..."
python3 -m pytest "$SCRIPT_DIR/white_box_unit_tests.py" -v || echo "⚠️  White box tests failed"

echo ""
echo "🚀 Running black box integration tests..."
python3 -m pytest "$SCRIPT_DIR/black_box_integration_tests.py" -v || echo "⚠️  Black box tests failed"

echo ""
echo "✅ Tests complete!"

