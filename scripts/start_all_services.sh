#!/bin/bash
# Start All ATMS Services
# ======================

set -e

echo "🚀 Starting ATMS Services..."
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Check if virtual environments exist
check_venv() {
    local service=$1
    if [ ! -d "services/$service/venv" ]; then
        echo -e "${YELLOW}⚠️  Virtual environment not found for $service${NC}"
        echo "   Creating virtual environment..."
        python3 -m venv "services/$service/venv"
        source "services/$service/venv/bin/activate"
        pip install -q --upgrade pip setuptools wheel
        if [ -f "services/$service/requirements.txt" ]; then
            pip install -q -r "services/$service/requirements.txt"
        else
            echo -e "${YELLOW}   No requirements.txt found for $service${NC}"
        fi
        deactivate
    else
        # Even if venv exists, ensure setuptools is installed
        source "services/$service/venv/bin/activate"
        pip install -q --upgrade pip setuptools wheel > /dev/null 2>&1 || true
        deactivate
    fi
}

# Start service function
start_service() {
    local service=$1
    local port=$2
    local script_path=$3
    
    echo -e "${GREEN}Starting $service on port $port...${NC}"
    
    check_venv "$service"
    
    # Check if script exists
    if [ ! -f "services/$service/$script_path" ]; then
        echo -e "${YELLOW}  ⚠️  Script not found: services/$service/$script_path${NC}"
        echo "  Skipping $service..."
        return
    fi
    
    (
        cd "services/$service"
        source venv/bin/activate
        # Ensure setuptools is available
        pip install -q --upgrade setuptools wheel > /dev/null 2>&1 || true
        python "$script_path" > "/tmp/atms_${service}.log" 2>&1 &
        echo $! > "/tmp/atms_${service}.pid"
        echo "  ✅ $service started (PID: $(cat /tmp/atms_${service}.pid))"
    )
    
    # Wait a bit for service to start
    sleep 2
}

# Start services
echo "Starting services..."

# 1. Sensor Fusion Service (port 8003)
start_service "sensor-fusion" "8003" "src/main.py"

# 2. AI Perception Service (port 8004)
start_service "ai-perception" "8004" "src/main.py"

# 3. Analytics Service (port 8005)
start_service "analytics" "8005" "src/main.py"

# 4. Dashboard Service (port 8006)
start_service "dashboard" "8006" "src/main.py"

# 5. Decision Engine Service (port 8007)
start_service "decision-engine" "8007" "src/main.py"

# 6. API Gateway (port 8000)
start_service "api-gateway" "8000" "src/main.py"

echo ""
echo "✅ All services started!"
echo ""
echo "Service URLs:"
echo "  - API Gateway:      http://localhost:8000"
echo "  - Sensor Fusion:    http://localhost:8003"
echo "  - AI Perception:    http://localhost:8004"
echo "  - Analytics:        http://localhost:8005"
echo "  - Dashboard:        http://localhost:8006"
echo "  - Decision Engine:  http://localhost:8007"
echo ""
echo "Logs:"
echo "  - Check /tmp/atms_*.log for service logs"
echo ""
echo "To stop all services:"
echo "  ./scripts/stop_all_services.sh"

