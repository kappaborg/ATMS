#!/bin/bash
# Install Prometheus Operator for Kubernetes Monitoring
# Phase 3 - Week 9-10: Kubernetes Deployment

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "📊 Installing Prometheus Operator"
echo "=================================="
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}❌ kubectl not found. Please install kubectl first.${NC}"
    exit 1
fi

# Check if cluster is accessible
if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}❌ Cannot connect to Kubernetes cluster.${NC}"
    echo -e "${YELLOW}   Please ensure your Kubernetes cluster is running and kubectl is configured.${NC}"
    exit 1
fi

echo -e "${BLUE}📦 Installing Prometheus Operator CRDs...${NC}"
# Install Prometheus Operator bundle (includes CRDs and operator)
# Note: Some CRDs may fail due to annotation size limits in older Kubernetes versions
# This is OK - we only need ServiceMonitor for basic monitoring
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/bundle.yaml 2>&1 | grep -v "Too long" || true

echo -e "${YELLOW}⏳ Waiting for CRDs to be established...${NC}"
# Wait for ServiceMonitor CRD to be ready
if kubectl wait --for condition=established --timeout=120s crd/servicemonitors.monitoring.coreos.com 2>/dev/null; then
    echo -e "${GREEN}✅ ServiceMonitor CRD established${NC}"
else
    echo -e "${YELLOW}⚠️  ServiceMonitor CRD may take longer. Check with:${NC}"
    echo "  kubectl get crd servicemonitors.monitoring.coreos.com"
fi

# Wait for Prometheus CRD
if kubectl wait --for condition=established --timeout=120s crd/prometheuses.monitoring.coreos.com 2>/dev/null; then
    echo -e "${GREEN}✅ Prometheus CRD established${NC}"
else
    echo -e "${YELLOW}⚠️  Prometheus CRD may take longer${NC}"
fi

echo ""
echo -e "${BLUE}🔄 Waiting for Prometheus Operator to be ready...${NC}"
# Wait for operator pod to be ready
if kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=prometheus-operator -n default --timeout=300s 2>/dev/null; then
    echo -e "${GREEN}✅ Prometheus Operator is ready${NC}"
else
    echo -e "${YELLOW}⚠️  Prometheus Operator may take longer to start. Check status with:${NC}"
    echo "  kubectl get pods -l app.kubernetes.io/name=prometheus-operator"
fi

echo ""
# Check if ServiceMonitor CRD was created (this is the critical one)
if kubectl get crd servicemonitors.monitoring.coreos.com &>/dev/null; then
    echo -e "${GREEN}✅ ServiceMonitor CRD is available (required for monitoring)${NC}"
    SERVICE_MONITOR_READY=true
else
    echo -e "${RED}❌ ServiceMonitor CRD not found${NC}"
    SERVICE_MONITOR_READY=false
fi

# Check if Prometheus CRD was created (optional, for full Prometheus setup)
if kubectl get crd prometheuses.monitoring.coreos.com &>/dev/null; then
    echo -e "${GREEN}✅ Prometheus CRD is available (optional, for full Prometheus)${NC}"
else
    echo -e "${YELLOW}⚠️  Prometheus CRD not available (optional - can use standalone Prometheus)${NC}"
fi

if [ "$SERVICE_MONITOR_READY" = true ]; then
    echo ""
    echo -e "${GREEN}✅ Prometheus Operator Installation Complete!${NC}"
    echo -e "${YELLOW}   Note: Some optional CRDs failed due to annotation size limits.${NC}"
    echo -e "${YELLOW}   This is OK - ServiceMonitor (required) is available.${NC}"
else
    echo ""
    echo -e "${YELLOW}⚠️  Prometheus Operator partially installed${NC}"
    echo -e "${YELLOW}   ServiceMonitor CRD not available. You may need to install manually.${NC}"
fi

echo ""
echo -e "${BLUE}🔍 Verify installation:${NC}"
echo "  kubectl get crd | grep monitoring"
echo "  kubectl get pods -l app.kubernetes.io/name=prometheus-operator"
echo ""

if [ "$SERVICE_MONITOR_READY" = true ]; then
    echo -e "${BLUE}📋 Next Steps:${NC}"
    echo "  1. Enable ServiceMonitor in k8s/base/kustomization.yaml"
    echo "  2. Apply updated manifests: kubectl apply -k k8s/base/"
    echo "  3. Create Prometheus instance (optional - can use standalone Prometheus)"
    echo "  4. Configure Grafana datasource (optional)"
else
    echo -e "${YELLOW}📋 Alternative: Use standalone Prometheus (without Operator)${NC}"
    echo "  Prometheus can scrape metrics directly from /metrics endpoints"
    echo "  No ServiceMonitor CRD required"
fi
echo ""

