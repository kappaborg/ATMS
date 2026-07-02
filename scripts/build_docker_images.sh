#!/bin/bash
# Build Docker Images for All Services
# Phase 3 - Week 9-10: Kubernetes Deployment

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "🐳 Building Docker Images for ATMS Services"
echo "=========================================="
echo ""

SERVICES=(
    "ai-perception:8004"
    "decision-engine:8007"
    "sensor-fusion:8008"
    "video-processor:8018"
    "api-gateway:8000"
    "dashboard:8006"
    "analytics:8005"
    "data-aggregator:8009"
    "traffic-controller:8010"
)

SUCCESS_COUNT=0
FAILED_COUNT=0
FAILED_SERVICES=()

for service_info in "${SERVICES[@]}"; do
    IFS=':' read -r service port <<< "$service_info"
    service_path="$PROJECT_ROOT/services/$service"
    
    if [ ! -f "$service_path/Dockerfile" ]; then
        echo -e "${YELLOW}⚠️  Skipping $service: Dockerfile not found${NC}"
        continue
    fi
    
    echo -e "${BLUE}📦 Building $service...${NC}"
    
           # Special handling for services that need shared package from root
           if [ "$service" = "sensor-fusion" ] || [ "$service" = "ai-perception" ]; then
               cd "$PROJECT_ROOT"
               if docker build --no-cache -f "$service_path/Dockerfile" -t "atms/$service:latest" . > /tmp/docker_build_${service}.log 2>&1; then
                   echo -e "${GREEN}✅ $service built successfully${NC}"
                   SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
               else
                   echo -e "${RED}❌ $service build failed${NC}"
                   echo -e "${YELLOW}   Check logs: /tmp/docker_build_${service}.log${NC}"
                   FAILED_COUNT=$((FAILED_COUNT + 1))
                   FAILED_SERVICES+=("$service")
               fi
           else
               cd "$service_path"
               if docker build --no-cache -t "atms/$service:latest" . > /tmp/docker_build_${service}.log 2>&1; then
                   echo -e "${GREEN}✅ $service built successfully${NC}"
                   SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
               else
                   echo -e "${RED}❌ $service build failed${NC}"
                   echo -e "${YELLOW}   Check logs: /tmp/docker_build_${service}.log${NC}"
                   FAILED_COUNT=$((FAILED_COUNT + 1))
                   FAILED_SERVICES+=("$service")
               fi
           fi
    
    echo ""
done

cd "$PROJECT_ROOT"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Build Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✅ Successful: $SUCCESS_COUNT${NC}"
echo -e "${RED}❌ Failed: $FAILED_COUNT${NC}"
echo ""

if [ $FAILED_COUNT -gt 0 ]; then
    echo -e "${RED}Failed Services:${NC}"
    for service in "${FAILED_SERVICES[@]}"; do
        echo -e "  - $service"
    done
    echo ""
    echo "View build logs:"
    for service in "${FAILED_SERVICES[@]}"; do
        echo "  cat /tmp/docker_build_${service}.log"
    done
    exit 1
else
    echo -e "${GREEN}🎉 All images built successfully!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Test images: docker run -p 8004:8004 atms/ai-perception:latest"
    echo "  2. Create docker-compose.services.yml"
    echo "  3. Create Kubernetes manifests"
fi

