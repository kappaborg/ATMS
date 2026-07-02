#!/bin/bash
# Setup Kubernetes Cluster Helper Script
# Checks available options and guides user through setup

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "🔍 Kubernetes Cluster Setup Helper"
echo "=================================="
echo ""

# Check kubectl
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}❌ kubectl not found${NC}"
    echo "   Install: brew install kubectl"
    exit 1
fi
echo -e "${GREEN}✅ kubectl is installed${NC}"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}⚠️  Docker not found${NC}"
    HAS_DOCKER=false
else
    if docker info &> /dev/null; then
        echo -e "${GREEN}✅ Docker is running${NC}"
        HAS_DOCKER=true
    else
        echo -e "${YELLOW}⚠️  Docker is installed but not running${NC}"
        HAS_DOCKER=false
    fi
fi

echo ""

# Check for existing cluster
if kubectl cluster-info &> /dev/null; then
    echo -e "${GREEN}✅ Kubernetes cluster is already running!${NC}"
    kubectl cluster-info
    echo ""
    echo "You can now deploy:"
    echo "  ./scripts/deploy_k8s.sh"
    exit 0
fi

echo -e "${YELLOW}⚠️  No Kubernetes cluster detected${NC}"
echo ""

# Check Docker Desktop Kubernetes
if [ "$HAS_DOCKER" = true ]; then
    echo -e "${BLUE}Option 1: Docker Desktop Kubernetes (Easiest)${NC}"
    echo "  1. Open Docker Desktop"
    echo "  2. Go to Settings → Kubernetes"
    echo "  3. Enable Kubernetes"
    echo "  4. Click 'Apply & Restart'"
    echo "  5. Wait for Kubernetes to start (green icon)"
    echo ""
fi

# Check for minikube
if command -v minikube &> /dev/null; then
    echo -e "${BLUE}Option 2: Minikube (Available)${NC}"
    echo "  Run: minikube start"
    echo ""
else
    echo -e "${YELLOW}Option 2: Minikube (Not installed)${NC}"
    echo "  Install: brew install minikube"
    echo "  Then run: minikube start"
    echo ""
fi

# Check for kind
if command -v kind &> /dev/null; then
    echo -e "${BLUE}Option 3: Kind (Available)${NC}"
    echo "  Run: kind create cluster --name atms"
    echo ""
else
    echo -e "${YELLOW}Option 3: Kind (Not installed)${NC}"
    echo "  Install: brew install kind"
    echo "  Then run: kind create cluster --name atms"
    echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}💡 Recommended: Docker Desktop Kubernetes (if available)${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "After setting up a cluster, verify with:"
echo "  kubectl cluster-info"
echo ""
echo "Then deploy:"
echo "  ./scripts/deploy_k8s.sh"

