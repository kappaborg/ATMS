#!/bin/bash
# Test All ATMS Services - Verify Endpoints and Connectivity
# Phase 3 - Week 9-10: Kubernetes Deployment

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "🧪 Testing All ATMS Services"
echo "=============================="
echo ""

NAMESPACE="atms-system"
FAILED_TESTS=0
PASSED_TESTS=0

# Function to test endpoint
test_endpoint() {
    local service=$1
    local port=$2
    local path=$3
    local description=$4
    
    echo -e "${BLUE}Testing: $description${NC}"
    
    # Port forward in background
    kubectl port-forward -n $NAMESPACE svc/$service $port:$port > /dev/null 2>&1 &
    PF_PID=$!
    sleep 2
    
    # Test endpoint
    if curl -s -f -m 5 http://localhost:$port$path > /dev/null 2>&1; then
        echo -e "${GREEN}  ✅ $description - OK${NC}"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        echo -e "${RED}  ❌ $description - FAILED${NC}"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    # Kill port forward
    kill $PF_PID 2>/dev/null || true
    sleep 1
}

# Test ai-perception
echo -e "${BLUE}📊 Testing ai-perception Service${NC}"
test_endpoint "ai-perception" "8004" "/health" "ai-perception /health"
test_endpoint "ai-perception" "8004" "/metrics" "ai-perception /metrics"
test_endpoint "ai-perception" "8004" "/" "ai-perception /"

echo ""

# Test decision-engine
echo -e "${BLUE}📊 Testing decision-engine Service${NC}"
test_endpoint "decision-engine" "8007" "/health" "decision-engine /health"
test_endpoint "decision-engine" "8007" "/" "decision-engine /"

echo ""

# Test Prometheus (if available)
if kubectl get svc prometheus -n $NAMESPACE &>/dev/null; then
    echo -e "${BLUE}📊 Testing Prometheus Service${NC}"
    test_endpoint "prometheus" "9090" "/api/v1/status/config" "Prometheus /api/v1/status/config"
    test_endpoint "prometheus" "9090" "/api/v1/targets" "Prometheus /api/v1/targets"
    echo ""
fi

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Test Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✅ Passed: $PASSED_TESTS${NC}"
echo -e "${RED}❌ Failed: $FAILED_TESTS${NC}"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}🎉 All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}⚠️  Some tests failed${NC}"
    exit 1
fi

