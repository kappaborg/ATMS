#!/bin/bash
# Deploy ATMS Traffic System to Kubernetes
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

echo "🚀 Deploying ATMS Traffic System to Kubernetes"
echo "=============================================="
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}❌ kubectl not found. Please install kubectl first.${NC}"
    exit 1
fi

# Check if cluster is accessible
if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}❌ Cannot connect to Kubernetes cluster.${NC}"
    echo -e "${YELLOW}   Please configure kubectl to connect to your cluster.${NC}"
    echo ""
    echo -e "${YELLOW}Options to set up a local cluster:${NC}"
    echo "  1. Minikube:  minikube start"
    echo "  2. Kind:      kind create cluster --name atms"
    echo "  3. Docker Desktop: Enable Kubernetes in settings"
    echo ""
    echo -e "${YELLOW}To build manifests without deploying (for testing):${NC}"
    echo "  kubectl kustomize k8s/base/ > manifests.yaml"
    echo ""
    exit 1
fi

echo -e "${BLUE}📦 Building and applying Kubernetes manifests using Kustomize...${NC}"
if kubectl apply -k k8s/base/; then
    echo ""
    echo -e "${YELLOW}⚠️  Note: Update secrets in k8s/base/secrets/atms-secrets.yaml before production!${NC}"
    echo ""
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✅ Deployment Complete!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    echo -e "${GREEN}📊 Check deployment status:${NC}"
    echo "  kubectl get pods -n atms-system"
    echo "  kubectl get services -n atms-system"
    echo "  kubectl get hpa -n atms-system"
    echo ""
    
    echo -e "${GREEN}📋 View logs:${NC}"
    echo "  kubectl logs -f deployment/ai-perception -n atms-system"
    echo "  kubectl logs -f deployment/decision-engine -n atms-system"
    echo ""
    
    echo -e "${GREEN}🔍 Troubleshooting:${NC}"
    echo "  kubectl describe pod <pod-name> -n atms-system"
    echo "  kubectl get events -n atms-system --sort-by='.lastTimestamp'"
    echo ""
else
    echo ""
    echo -e "${RED}❌ Deployment failed. Check the errors above.${NC}"
    echo ""
    echo -e "${YELLOW}To build manifests without deploying (for testing):${NC}"
    echo "  kubectl kustomize k8s/base/ > manifests.yaml"
    exit 1
fi

