#!/bin/bash
# Stop All ATMS Services
# =====================

echo "🛑 Stopping ATMS Services..."
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

SERVICES=("sensor-fusion" "ai-perception" "analytics" "dashboard" "decision-engine" "api-gateway")

for service in "${SERVICES[@]}"; do
    PID_FILE="/tmp/atms_${service}.pid"
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo -e "${GREEN}Stopping $service (PID: $PID)...${NC}"
            kill "$PID" 2>/dev/null || true
            rm -f "$PID_FILE"
        else
            echo -e "${RED}$service not running${NC}"
            rm -f "$PID_FILE"
        fi
    else
        echo -e "${RED}$service PID file not found${NC}"
    fi
done

# Clean up any remaining processes
pkill -f "integrated_perception_service.py" 2>/dev/null || true
pkill -f "services/.*/main.py" 2>/dev/null || true

echo ""
echo "✅ All services stopped!"

