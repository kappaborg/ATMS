#!/bin/bash
# Quick setup script for test environment

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🔧 Setting up test environment..."
echo ""

# Check for AI Perception venv
VENV_PATH="$PROJECT_ROOT/services/ai-perception/venv"
if [ -d "$VENV_PATH" ]; then
    echo "✅ Found AI Perception venv"
    echo "   Activate it with: source $VENV_PATH/bin/activate"
    echo ""
    echo "   Then install test deps: pip install pytest pytest-asyncio pytest-cov httpx"
    echo "   And run tests: ./tests/run_tests.sh"
else
    echo "❌ AI Perception venv not found"
    echo "   Creating test venv..."
    
    cd "$PROJECT_ROOT"
    python3 -m venv tests/venv
    source tests/venv/bin/activate
    
    echo "📦 Installing test dependencies..."
    pip install --upgrade pip
    pip install -r tests/requirements.txt
    
    echo ""
    echo "✅ Test environment ready!"
    echo "   Activate with: source tests/venv/bin/activate"
fi

