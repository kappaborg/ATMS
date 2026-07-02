#!/bin/bash
# Stop ATMS Services
# Usage: ./scripts/stop_services.sh

set -e

echo "🛑 Stopping ATMS Services..."
echo ""

# Find and kill processes on ports 8014 and 8018
for port in 8014 8018; do
    PIDS=$(lsof -ti:$port 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "Stopping service on port $port (PIDs: $PIDS)..."
        echo "$PIDS" | xargs kill -9 2>/dev/null || true
        echo "✅ Port $port is now free"
    else
        echo "ℹ️  Port $port is already free"
    fi
done

echo ""
echo "✅ All services stopped!"

