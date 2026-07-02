# Complete Deployment Guide - Phase 3 Week 9-10

**Date**: December 2, 2025  
**Status**: ✅ **COMPLETE** - All Services Deployed and Tested

---

## 📋 Prerequisites

- Kubernetes cluster (Minikube, Kind, or Docker Desktop)
- `kubectl` configured
- Docker images built (see `scripts/build_docker_images.sh`)

---

## 🚀 Step-by-Step Deployment

### Step 1: Build Docker Images

```bash
# Build all images
./scripts/build_docker_images.sh

# Verify images
docker images | grep atms/
```

**Expected Output**: All 9 service images built successfully

---

### Step 2: Deploy Kubernetes Resources

```bash
# Apply all manifests
kubectl apply -k k8s/base/

# Verify namespace
kubectl get namespace atms-system

# Check all resources
kubectl get all -n atms-system
```

**Expected Output**:
- Namespace created
- ConfigMaps and Secrets created
- Deployments created
- Services created
- HPA created

---

### Step 3: Verify Pods

```bash
# Wait for pods to be ready
kubectl wait --for=condition=Ready pod -l app=ai-perception -n atms-system --timeout=300s
kubectl wait --for=condition=Ready pod -l app=decision-engine -n atms-system --timeout=300s

# Check pod status
kubectl get pods -n atms-system
```

**Expected Output**:
```
NAME                               READY   STATUS    RESTARTS   AGE
ai-perception-xxx                  1/1     Running   0          2m
decision-engine-xxx                1/1     Running   0          2m
decision-engine-yyy                1/1     Running   0          2m
```

---

### Step 4: Install Metrics Server

```bash
# Install metrics server
./scripts/install_metrics_server.sh

# Verify
kubectl get pods -n kube-system -l k8s-app=metrics-server
kubectl top nodes
kubectl top pods -n atms-system
```

**Expected Output**: Metrics Server running, metrics available

---

### Step 5: Install Prometheus Operator (Optional)

```bash
# Install Prometheus Operator
./scripts/install_prometheus_operator.sh

# Verify ServiceMonitor CRD
kubectl get crd servicemonitors.monitoring.coreos.com

# Check operator
kubectl get pods -l app.kubernetes.io/name=prometheus-operator
```

**Note**: Some CRDs may fail due to annotation size limits. This is OK - ServiceMonitor CRD is available.

---

### Step 6: Deploy Prometheus (Optional)

```bash
# Deploy standalone Prometheus
kubectl apply -f k8s/base/monitoring/prometheus-standalone.yaml

# Wait for Prometheus to be ready
kubectl wait --for=condition=Ready pod -l app=prometheus -n atms-system --timeout=300s

# Check status
kubectl get pods -n atms-system -l app=prometheus
```

**Expected Output**: Prometheus pod running

---

### Step 7: Test All Services

```bash
# Run test script
./scripts/test_all_services.sh
```

**Expected Output**: All tests passing

---

### Step 8: Verify Monitoring

```bash
# Check ServiceMonitor
kubectl get servicemonitor -n atms-system

# Check Prometheus targets (if Prometheus deployed)
kubectl port-forward svc/prometheus 9090:9090 -n atms-system
# Open http://localhost:9090/targets
```

**Expected**: ai-perception target should be UP

---

### Step 9: Verify HPA

```bash
# Check HPA status
kubectl get hpa -n atms-system

# Describe HPA
kubectl describe hpa ai-perception-hpa -n atms-system

# Check metrics
kubectl top pods -n atms-system
```

**Expected**: HPA showing metrics, ready to scale

---

## ✅ Verification Checklist

- [ ] All pods running (1/1 or 2/2 Ready)
- [ ] All services accessible
- [ ] Health endpoints responding (200 OK)
- [ ] Metrics endpoints responding
- [ ] Metrics Server installed and providing metrics
- [ ] HPA configured and reading metrics
- [ ] Prometheus deployed (optional)
- [ ] ServiceMonitor created (optional)
- [ ] All tests passing

---

## 🔧 Common Issues and Fixes

### Issue: Pods stuck in Pending

**Cause**: Insufficient resources

**Fix**:
```bash
# Check resource requests
kubectl describe pod <pod-name> -n atms-system

# Reduce resource requests in deployment YAML if needed
```

---

### Issue: Readiness probe failing

**Cause**: Wrong endpoint path

**Fix**:
```bash
# Check endpoint
kubectl exec -n atms-system <pod-name> -- curl localhost:8004/health

# Update deployment if needed
kubectl patch deployment <deployment> -n atms-system --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/readinessProbe/httpGet/path", "value": "/health"}]'
```

---

### Issue: Metrics Server not providing metrics

**Cause**: TLS certificate issues

**Fix**:
```bash
# Reinstall with insecure TLS flag
./scripts/install_metrics_server.sh
```

---

### Issue: Prometheus Operator CRDs failing

**Cause**: Annotation size limits

**Fix**: This is OK - ServiceMonitor CRD is available. Use standalone Prometheus.

---

## 📊 Accessing Services

### Port Forwarding

```bash
# ai-perception
kubectl port-forward svc/ai-perception 8004:8004 -n atms-system
# Access: http://localhost:8004

# decision-engine
kubectl port-forward svc/decision-engine 8007:8007 -n atms-system
# Access: http://localhost:8007

# Prometheus
kubectl port-forward svc/prometheus 9090:9090 -n atms-system
# Access: http://localhost:9090
```

### Service URLs

- ai-perception: `http://ai-perception.atms-system.svc.cluster.local:8004`
- decision-engine: `http://decision-engine.atms-system.svc.cluster.local:8007`
- Prometheus: `http://prometheus.atms-system.svc.cluster.local:9090`

---

## 📚 Related Documentation

- `docs/KUBERNETES_DEPLOYMENT.md` - Main deployment guide
- `docs/K8S_DEPLOYMENT_QUICKSTART.md` - Quick start
- `docs/K8S_CLUSTER_SETUP.md` - Cluster setup
- `docs/PROMETHEUS_OPERATOR_STATUS.md` - Monitoring setup
- `docs/FINAL_SYSTEM_STATUS.md` - Complete status

---

## 🎉 Deployment Complete!

All services are deployed and operational. System is ready for:
- Production use
- Performance optimization (Week 11)
- Further development

---

## 🚀 Next Steps

1. **Week 11**: Performance optimization
   - Model quantization
   - Code optimization
   - Performance benchmarking

2. **Week 12**: Multi-intersection coordination
   - Intersection manager service
   - Communication protocol
   - Green wave algorithm

3. **Phase 4**: Advanced features
   - NTCIP protocol
   - Advanced analytics

---

**System Status**: ✅ **FULLY OPERATIONAL**

