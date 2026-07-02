#!/bin/bash
# Install Metrics Server for Kubernetes HPA
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

echo "📊 Installing Metrics Server for HPA"
echo "======================================"
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}❌ kubectl not found. Please install kubectl first.${NC}"
    exit 1
fi

# Check if cluster is accessible
if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}❌ Cannot connect to Kubernetes cluster.${NC}"
    exit 1
fi

echo -e "${BLUE}📦 Installing Metrics Server...${NC}"

# Detect cluster type
CLUSTER_TYPE="standard"
if kubectl get nodes -o jsonpath='{.items[0].metadata.labels}' | grep -q "kind"; then
    CLUSTER_TYPE="kind"
elif kubectl get nodes -o jsonpath='{.items[0].metadata.labels}' | grep -q "minikube"; then
    CLUSTER_TYPE="minikube"
fi

if [ "$CLUSTER_TYPE" = "kind" ] || [ "$CLUSTER_TYPE" = "minikube" ]; then
    echo -e "${YELLOW}⚠️  Detected $CLUSTER_TYPE cluster - using insecure TLS${NC}"
    
    # Install with insecure TLS flag
    kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
    
    # Wait for deployment
    sleep 5
    
    # Patch to allow insecure TLS
    kubectl patch deployment metrics-server -n kube-system --type='json' \
      -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]' 2>/dev/null || \
    kubectl patch deployment metrics-server -n kube-system --type='json' \
      -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/args", "value": ["--kubelet-insecure-tls"]}]' 2>/dev/null || \
    echo -e "${YELLOW}⚠️  Could not patch deployment (may already be configured)${NC}"
    
    # Restart deployment
    kubectl rollout restart deployment/metrics-server -n kube-system
else
    # Standard installation
    kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
fi

echo ""
echo -e "${BLUE}⏳ Waiting for Metrics Server to be ready...${NC}"
kubectl wait --for=condition=available --timeout=120s deployment/metrics-server -n kube-system || {
    echo -e "${YELLOW}⚠️  Metrics Server may take longer to start. Check status with:${NC}"
    echo "  kubectl get pods -n kube-system | grep metrics-server"
}

echo ""
echo -e "${GREEN}✅ Metrics Server Installation Complete!${NC}"
echo ""

# Verify installation
echo -e "${BLUE}🔍 Verifying installation...${NC}"
sleep 5

if kubectl get pods -n kube-system | grep -q "metrics-server.*Running"; then
    echo -e "${GREEN}✅ Metrics Server is running${NC}"
else
    echo -e "${YELLOW}⚠️  Metrics Server may still be starting. Check with:${NC}"
    echo "  kubectl get pods -n kube-system | grep metrics-server"
fi

echo ""
echo -e "${GREEN}📊 Test Metrics API:${NC}"
echo "  kubectl top nodes"
echo "  kubectl top pods -n atms-system"
echo ""
echo -e "${GREEN}📋 Check HPA Status:${NC}"
echo "  kubectl get hpa -n atms-system"
echo "  kubectl describe hpa ai-perception-hpa -n atms-system"
echo ""

