# Metrics Server Installation for HPA

## Overview

The Horizontal Pod Autoscaler (HPA) requires the Metrics Server to collect CPU and memory metrics from pods. Without it, HPA cannot scale based on resource utilization.

## Installation

### Option 1: Using kubectl (Recommended)

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

### Option 2: Using Helm

```bash
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm install metrics-server metrics-server/metrics-server --namespace kube-system
```

### Option 3: For Kind/Minikube (with insecure TLS)

If you get TLS errors, use this version:

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# If TLS errors occur, patch the deployment:
kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'
```

## Verification

```bash
# Check if metrics-server is running
kubectl get pods -n kube-system | grep metrics-server

# Test metrics API
kubectl top nodes
kubectl top pods -n atms-system

# Check HPA status
kubectl get hpa -n atms-system
kubectl describe hpa ai-perception-hpa -n atms-system
```

## Troubleshooting

### Metrics Server Not Starting

```bash
# Check logs
kubectl logs -n kube-system -l k8s-app=metrics-server

# Check if nodes are ready
kubectl get nodes

# For Kind, ensure node has enough resources
```

### HPA Shows "Unknown" Metrics

```bash
# Wait a few minutes after installing metrics-server
# HPA needs time to collect initial metrics

# Check HPA events
kubectl describe hpa ai-perception-hpa -n atms-system
```

## Notes

- Metrics Server collects metrics every 15-60 seconds
- HPA checks metrics every 15-30 seconds
- First metrics may take 1-2 minutes to appear
- For production, use proper TLS certificates

