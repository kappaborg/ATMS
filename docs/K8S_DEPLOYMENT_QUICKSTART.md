# Kubernetes Deployment Quick Start

## Prerequisites

1. **Kubernetes cluster** (minikube, kind, or cloud provider)
2. **kubectl** configured and connected to cluster
3. **Docker images built** (run `./scripts/build_docker_images.sh` first)

## Quick Deployment

### Option 1: Using Kustomize (Recommended)

```bash
# Deploy all resources
kubectl apply -k k8s/base/

# Verify deployment
kubectl get pods -n atms-system
kubectl get services -n atms-system
```

### Option 2: Using Deployment Script

```bash
# Run deployment script
./scripts/deploy_k8s.sh
```

### Option 3: Manual Step-by-Step

```bash
# 1. Create namespace
kubectl apply -f k8s/base/namespace.yaml

# 2. Create ConfigMaps and Secrets
kubectl apply -f k8s/base/configmaps/
kubectl apply -f k8s/base/secrets/

# 3. Create PersistentVolumes
kubectl apply -f k8s/base/persistent-volumes/

# 4. Deploy services
kubectl apply -f k8s/base/deployments/

# 5. Set up auto-scaling
kubectl apply -f k8s/base/hpa/

# 6. Configure monitoring
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

## Troubleshooting

### Pods Not Starting

```bash
# Check pod status
kubectl describe pod <pod-name> -n atms-system

# Check events
kubectl get events -n atms-system --sort-by='.lastTimestamp'
```

### Image Pull Errors

For local testing (minikube/kind):
```bash
# Load images into cluster
minikube image load atms/ai-perception:latest
# or
kind load docker-image atms/ai-perception:latest
```

### Service Not Accessible

```bash
# Port forward for testing
kubectl port-forward svc/ai-perception 8004:8004 -n atms-system
```

## Production Considerations

1. **Update Secrets**: Edit `k8s/base/secrets/atms-secrets.yaml` with production values
2. **Image Registry**: Push images to container registry and update image references
3. **Resource Limits**: Adjust based on actual usage
4. **Storage**: Configure appropriate storage classes
5. **Network Policies**: Implement for security
6. **Ingress**: Set up ingress controller for external access

