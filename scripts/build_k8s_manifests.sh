#!/bin/bash
# Build Kubernetes manifests using Kustomize (no cluster required)
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

echo "🔨 Building Kubernetes Manifests"
echo "=================================="
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}❌ kubectl not found. Please install kubectl first.${NC}"
    exit 1
fi

OUTPUT_FILE="${1:-manifests.yaml}"

echo -e "${BLUE}📦 Building manifests from k8s/base/...${NC}"
if kubectl kustomize k8s/base/ > "$OUTPUT_FILE" 2>&1; then
    echo -e "${GREEN}✅ Manifests built successfully!${NC}"
    echo ""
    echo -e "${GREEN}📄 Output file: ${OUTPUT_FILE}${NC}"
    echo ""
    echo -e "${GREEN}📊 Manifest summary:${NC}"
    echo "  Namespaces: $(grep -c '^kind: Namespace' "$OUTPUT_FILE" || echo 0)"
    echo "  ConfigMaps: $(grep -c '^kind: ConfigMap' "$OUTPUT_FILE" || echo 0)"
    echo "  Secrets: $(grep -c '^kind: Secret' "$OUTPUT_FILE" || echo 0)"
    echo "  Deployments: $(grep -c '^kind: Deployment' "$OUTPUT_FILE" || echo 0)"
    echo "  Services: $(grep -c '^kind: Service' "$OUTPUT_FILE" || echo 0)"
    echo "  HPA: $(grep -c '^kind: HorizontalPodAutoscaler' "$OUTPUT_FILE" || echo 0)"
    echo ""
    echo -e "${GREEN}🚀 To deploy these manifests:${NC}"
    echo "  kubectl apply -f $OUTPUT_FILE"
    echo ""
    echo -e "${YELLOW}⚠️  Note: Requires a running Kubernetes cluster${NC}"
    echo "  Set up a local cluster with:"
    echo "    • Minikube:  minikube start"
    echo "    • Kind:      kind create cluster"
    echo "    • Docker Desktop: Enable Kubernetes in settings"
else
    echo -e "${RED}❌ Failed to build manifests. Check errors above.${NC}"
    exit 1
fi

