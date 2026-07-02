# Kubernetes Deployment Guide

## Prerequisites

- Kubernetes cluster (minikube, kind, or cloud provider)
- kubectl configured
- Helm 3.x installed
- Docker images built and pushed to registry

## Quick Start

### 1. Build Docker Images

```bash
./scripts/build_docker_images.sh
```

### 2. Deploy Using Kustomize

```bash
# Apply all base manifests
kubectl apply -k k8s/base/

# Verify deployment
kubectl get pods -n atms-system
kubectl get services -n atms-system
```

### 3. Deploy Using Helm

```bash
# Install chart
helm install atms-traffic-system ./helm/atms-traffic-system \
  --namespace atms-system \
  --create-namespace

# Upgrade
helm upgrade atms-traffic-system ./helm/atms-traffic-system \
  --namespace atms-system

# Check status
helm status atms-traffic-system -n atms-system
```

## Manual Deployment Steps

### 1. Create Namespace

```bash
kubectl apply -f k8s/base/namespace.yaml
```

### 2. Create ConfigMaps and Secrets

```bash
kubectl apply -f k8s/base/configmaps/
kubectl apply -f k8s/base/secrets/
```

**⚠️ Important**: Update secrets before applying in production!

### 3. Create Persistent Volumes

```bash
kubectl apply -f k8s/base/persistent-volumes/
```

### 4. Deploy Services

```bash
kubectl apply -f k8s/base/deployments/
```

### 5. Set Up Auto-Scaling

```bash
kubectl apply -f k8s/base/hpa/
```

### 6. Configure Monitoring

```bash
# Ensure Prometheus Operator is installed
kubectl apply -f k8s/base/monitoring/
```

## Verification

```bash
# Check all pods
kubectl get pods -n atms-system

# Check services
kubectl get svc -n atms-system

# Check HPA
kubectl get hpa -n atms-system

# View logs
kubectl logs -f deployment/ai-perception -n atms-system
```

## Monitoring Setup

### Prometheus Deployment

A standalone Prometheus instance is deployed to scrape metrics from services:

```bash
# Deploy Prometheus
kubectl apply -f k8s/base/monitoring/prometheus-standalone.yaml

# Check status
kubectl get pods -n atms-system -l app=prometheus

# Access Prometheus UI
kubectl port-forward svc/prometheus 9090:9090 -n atms-system
# Open http://localhost:9090
```

### ServiceMonitor

ServiceMonitor resources are used to configure metric scraping:

```bash
# Check ServiceMonitor
kubectl get servicemonitor -n atms-system

# View ServiceMonitor details
kubectl describe servicemonitor ai-perception -n atms-system
```

### Prometheus Targets

Verify Prometheus is scraping metrics:

```bash
# Port forward Prometheus
kubectl port-forward svc/prometheus 9090:9090 -n atms-system

# Check targets
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'
```

Expected targets:
- `ai-perception` - Should be UP
- `kubernetes-apiservers` - Should be UP
- `kubernetes-nodes` - Should be UP

## Testing Services

### Test All Services

Use the test script to verify all endpoints:

```bash
./scripts/test_all_services.sh
```

This will test:
- ai-perception `/health`, `/metrics`, `/`
- decision-engine `/health`, `/`
- Prometheus endpoints (if deployed)

### Manual Testing

```bash
# Test ai-perception
kubectl port-forward svc/ai-perception 8004:8004 -n atms-system
curl http://localhost:8004/health
curl http://localhost:8004/metrics

# Test decision-engine
kubectl port-forward svc/decision-engine 8007:8007 -n atms-system
curl http://localhost:8007/health

# Test Prometheus
kubectl port-forward svc/prometheus 9090:9090 -n atms-system
curl http://localhost:9090/api/v1/targets
```

## Troubleshooting

### Pods Not Starting

```bash
# Check pod status
kubectl describe pod <pod-name> -n atms-system

# Check events
kubectl get events -n atms-system --sort-by='.lastTimestamp'
```

### Image Pull Errors

```bash
# Ensure images are built and tagged correctly
docker images | grep atms

# For local testing with minikube/kind
# Load images into cluster
minikube image load atms/ai-perception:latest
# or
kind load docker-image atms/ai-perception:latest
```

### Service Not Accessible

```bash
# Check service endpoints
kubectl get endpoints -n atms-system

# Port forward for testing
kubectl port-forward svc/ai-perception 8004:8004 -n atms-system
```

## Production Considerations

1. **Secrets Management**: Use sealed-secrets or external secret management
2. **Image Registry**: Push images to container registry
3. **Resource Limits**: Adjust based on actual usage
4. **Storage**: Configure appropriate storage classes
5. **Network Policies**: Implement network policies for security
6. **Ingress**: Set up ingress controller for external access

