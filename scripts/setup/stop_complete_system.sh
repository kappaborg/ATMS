#!/bin/bash
# Stop Complete ATMS System
# Stops all services in reverse order

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║                                                                      ║"
echo "║       🛑 Stopping ATMS Complete System 🛑                           ║"
echo "║                                                                      ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

# =============================================================================
# STEP 1: Stop AI Perception
# =============================================================================

echo "1️⃣  Stopping AI Perception Service..."
pkill -f integrated_perception_service.py && echo "  ✅ Stopped" || echo "  ℹ️  Not running"
echo ""

# =============================================================================
# STEP 2: Stop Microservices
# =============================================================================

echo "2️⃣  Stopping Microservices..."
pkill -f "uvicorn.*8001" && echo "  ✅ Data Aggregator stopped" || echo "  ℹ️  Not running"
pkill -f "uvicorn.*8002" && echo "  ✅ Decision Engine stopped" || echo "  ℹ️  Not running"
pkill -f "uvicorn.*8003" && echo "  ✅ Traffic Controller stopped" || echo "  ℹ️  Not running"
echo ""

# =============================================================================
# STEP 3: Stop Kafka
# =============================================================================

echo "3️⃣  Stopping Kafka..."
if [ -f docker-compose.kafka.yml ]; then
    docker-compose -f docker-compose.kafka.yml down && echo "  ✅ Kafka stopped" || echo "  ⚠️  Error stopping Kafka"
else
    echo "  ℹ️  docker-compose.kafka.yml not found"
fi
echo ""

# =============================================================================
# STEP 4: Stop Database
# =============================================================================

echo "4️⃣  Stopping Database Infrastructure..."
if [ -f docker-compose.database.yml ]; then
    docker-compose -f docker-compose.database.yml down && echo "  ✅ Database stopped" || echo "  ⚠️  Error stopping database"
else
    echo "  ℹ️  docker-compose.database.yml not found"
fi
echo ""

# =============================================================================
# Verify all stopped
# =============================================================================

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║                                                                      ║"
echo "║              ✅ ALL SERVICES STOPPED! ✅                            ║"
echo "║                                                                      ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

echo "📊 Final Status:"
echo "═══════════════════════════════════════════════════════════════"
docker ps | grep -E "postgres|redis|kafka|zookeeper" || echo "  ✅ All Docker containers stopped"
lsof -i :8001 > /dev/null 2>&1 && echo "  ⚠️  Port 8001 still in use" || echo "  ✅ Port 8001 free"
lsof -i :8002 > /dev/null 2>&1 && echo "  ⚠️  Port 8002 still in use" || echo "  ✅ Port 8002 free"
lsof -i :8003 > /dev/null 2>&1 && echo "  ⚠️  Port 8003 still in use" || echo "  ✅ Port 8003 free"
lsof -i :8004 > /dev/null 2>&1 && echo "  ⚠️  Port 8004 still in use" || echo "  ✅ Port 8004 free"
echo ""

echo "ℹ️  To restart: ./start_complete_system.sh"

