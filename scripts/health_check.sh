#!/bin/bash

# ATMS System Health Check Script
# Verifies all components are running and healthy

set -e

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║                                                                       ║"
echo "║     🏥 ATMS SYSTEM HEALTH CHECK                                      ║"
echo "║                                                                       ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0

# Function to check if a process is running
check_process() {
    local name=$1
    local pattern=$2
    
    if pgrep -f "$pattern" > /dev/null; then
        echo -e "  ✅ ${GREEN}$name is running${NC}"
        return 0
    else
        echo -e "  ❌ ${RED}$name is NOT running${NC}"
        ERRORS=$((ERRORS + 1))
        return 1
    fi
}

# Function to check port
check_port() {
    local name=$1
    local port=$2
    
    if lsof -i :$port > /dev/null 2>&1; then
        echo -e "  ✅ ${GREEN}$name (port $port) is listening${NC}"
        return 0
    else
        echo -e "  ❌ ${RED}$name (port $port) is NOT listening${NC}"
        ERRORS=$((ERRORS + 1))
        return 1
    fi
}

# Function to check URL
check_url() {
    local name=$1
    local url=$2
    
    if curl -s -f "$url" > /dev/null; then
        echo -e "  ✅ ${GREEN}$name is responding${NC}"
        return 0
    else
        echo -e "  ❌ ${RED}$name is NOT responding${NC}"
        ERRORS=$((ERRORS + 1))
        return 1
    fi
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📡 INFRASTRUCTURE SERVICES"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check Docker
if command -v docker &> /dev/null && docker ps > /dev/null 2>&1; then
    echo -e "  ✅ ${GREEN}Docker is running${NC}"
    
    # Check Kafka
    if docker ps | grep -q kafka; then
        echo -e "  ✅ ${GREEN}Kafka container is running${NC}"
        check_port "Kafka" 9092
    else
        echo -e "  ❌ ${RED}Kafka container is NOT running${NC}"
        ERRORS=$((ERRORS + 1))
    fi
    
    # Check Zookeeper
    if docker ps | grep -q zookeeper; then
        echo -e "  ✅ ${GREEN}Zookeeper container is running${NC}"
    else
        echo -e "  ❌ ${RED}Zookeeper container is NOT running${NC}"
        ERRORS=$((ERRORS + 1))
    fi
    
    # Check Kafka UI
    if docker ps | grep -q kafka-ui; then
        echo -e "  ✅ ${GREEN}Kafka UI container is running${NC}"
        check_url "Kafka UI" "http://localhost:8080"
    else
        echo -e "  ⚠️  ${YELLOW}Kafka UI container is NOT running (optional)${NC}"
    fi
else
    echo -e "  ❌ ${RED}Docker is NOT running${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🤖 MICROSERVICES"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check Sensor Fusion Service
check_process "Sensor Fusion" "sensor-fusion/src/main.py"
check_port "Sensor Fusion API" 8000

# Check AI Perception Service
check_process "AI Perception" "ai-perception/src/main.py"
check_port "AI Perception API" 8001

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📷 CAMERA STATUS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check iPhone camera
CAMERA_URL="http://192.168.0.10:8081/video"
if curl -s -I --max-time 3 --user admin:kappa "$CAMERA_URL" | grep -q "200 OK"; then
    echo -e "  ✅ ${GREEN}iPhone camera is reachable${NC}"
else
    echo -e "  ❌ ${RED}iPhone camera is NOT reachable${NC}"
    echo -e "     URL: $CAMERA_URL"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 KAFKA TOPICS & MESSAGE FLOW"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check if kafkacat/kcat is available
if command -v kcat &> /dev/null; then
    KAFKA_CMD="kcat"
elif command -v kafkacat &> /dev/null; then
    KAFKA_CMD="kafkacat"
else
    echo -e "  ⚠️  ${YELLOW}kafkacat/kcat not installed - skipping topic check${NC}"
    echo -e "     Install with: brew install kcat"
    KAFKA_CMD=""
fi

if [ -n "$KAFKA_CMD" ]; then
    # List topics
    TOPICS=$($KAFKA_CMD -b localhost:9092 -L -J 2>/dev/null | jq -r '.topics[].topic' | grep -E 'camera-frames|detections' || echo "")
    
    if echo "$TOPICS" | grep -q "camera-frames"; then
        echo -e "  ✅ ${GREEN}Topic 'camera-frames' exists${NC}"
        
        # Check message count (last 1 second)
        COUNT=$($KAFKA_CMD -b localhost:9092 -C -t camera-frames -o -1 -c 1 -f '%T\n' 2>/dev/null | wc -l || echo "0")
        if [ "$COUNT" -gt 0 ]; then
            echo -e "     Messages flowing: ${GREEN}YES${NC}"
        else
            echo -e "     Messages flowing: ${YELLOW}NO (may be normal if just started)${NC}"
        fi
    else
        echo -e "  ❌ ${RED}Topic 'camera-frames' does NOT exist${NC}"
        ERRORS=$((ERRORS + 1))
    fi
    
    if echo "$TOPICS" | grep -q "detections"; then
        echo -e "  ✅ ${GREEN}Topic 'detections' exists${NC}"
        
        # Check message count
        COUNT=$($KAFKA_CMD -b localhost:9092 -C -t detections -o -1 -c 1 -f '%T\n' 2>/dev/null | wc -l || echo "0")
        if [ "$COUNT" -gt 0 ]; then
            echo -e "     Messages flowing: ${GREEN}YES${NC}"
        else
            echo -e "     Messages flowing: ${YELLOW}NO (check if objects detected)${NC}"
        fi
    else
        echo -e "  ❌ ${RED}Topic 'detections' does NOT exist${NC}"
        ERRORS=$((ERRORS + 1))
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "💻 SYSTEM RESOURCES"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# CPU usage
CPU_USAGE=$(top -l 1 | grep "CPU usage" | awk '{print $3}' | sed 's/%//')
echo "  CPU Usage: ${CPU_USAGE}%"

# Memory usage
MEMORY_PRESSURE=$(memory_pressure | grep "System-wide memory free percentage:" | awk '{print $5}' | sed 's/%//')
if [ -n "$MEMORY_PRESSURE" ]; then
    echo "  Memory Free: ${MEMORY_PRESSURE}%"
fi

# Disk space
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
echo "  Disk Usage: ${DISK_USAGE}%"

if [ "$DISK_USAGE" -gt 90 ]; then
    echo -e "  ⚠️  ${YELLOW}WARNING: Disk usage is high!${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $ERRORS -eq 0 ]; then
    echo -e "  ✅ ${GREEN}ALL SYSTEMS OPERATIONAL${NC}"
    echo ""
    echo "  System is ready for data collection! 🚀"
    exit 0
else
    echo -e "  ❌ ${RED}FOUND $ERRORS ERROR(S)${NC}"
    echo ""
    echo "  Please fix errors before starting data collection."
    exit 1
fi


