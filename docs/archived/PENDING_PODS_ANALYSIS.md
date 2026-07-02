# Pending Pods Analysis - ai-perception

## Issue Summary

**Problem**: `ai-perception` pods are stuck in `Pending` state, preventing containers from running.

**Impact**: 
- Deployment shows "Progressing" with 0/3 pods ready
- Cannot run containers due to resource constraints
- System cannot scale properly

---

## Root Cause Analysis

### 1. Resource Constraints

**Likely Cause**: Insufficient memory/CPU on the Kubernetes node.

**Evidence**:
- Multiple pods requesting resources simultaneously
- HPA configured for 2-10 replicas
- Each pod requests: 1 CPU, 2Gi memory
- Node has limited resources (single-node cluster)

### 2. Deployment Configuration

**Current Settings**:
- **Replicas**: 2 (minimum from HPA)
- **Resource Requests**: 
  - CPU: 1000m (1 core)
  - Memory: 2Gi
- **Resource Limits**:
  - CPU: 2000m (2 cores)
  - Memory: 4Gi

**HPA Configuration**:
- Min replicas: 2
- Max replicas: 10
- Target CPU: 70%
- Target Memory: 80%

### 3. Node Capacity

**Single-Node Cluster** (kind/minikube):
- Limited total resources
- All pods compete for same resources
- No node scaling capability

---

## Solutions

### Solution 1: Reduce Resource Requests (Quick Fix) ⚡

**Action**: Lower memory and CPU requests to fit more pods on the node.

**Changes**:
```yaml
resources:
  requests:
    cpu: "500m"      # Reduced from 1000m
    memory: "1Gi"    # Reduced from 2Gi
  limits:
    cpu: "1000m"     # Reduced from 2000m
    memory: "2Gi"    # Reduced from 4Gi
```

**Pros**: 
- Quick fix
- Allows more pods to schedule
- Works with current cluster

**Cons**:
- May impact performance
- Pods may be throttled

---

### Solution 2: Reduce Replica Count (Immediate Fix) ⚡

**Action**: Lower minimum replicas to 1.

**Changes**:
```yaml
# In HPA
minReplicas: 1  # Changed from 2
```

**Pros**:
- Immediate relief
- Fewer pods competing for resources
- Still allows scaling up when needed

**Cons**:
- Less redundancy
- Single point of failure

---

### Solution 3: Increase Node Resources (Best Long-term) 🎯

**Action**: Allocate more resources to the Kubernetes node.

**For Kind**:
```bash
# Create cluster with more resources
cat <<EOF | kind create cluster --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraArgs:
    - --system-reserved=cpu=500m,memory=1Gi
    - --kube-reserved=cpu=500m,memory=1Gi
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        system-reserved: "cpu=500m,memory=1Gi"
        kube-reserved: "cpu=500m,memory=1Gi"
EOF
```

**For Minikube**:
```bash
minikube start --memory=8192 --cpus=4
```

**For Docker Desktop**:
- Increase memory/CPU in Docker Desktop settings
- Restart Kubernetes

**Pros**:
- Best performance
- Allows proper scaling
- Production-ready

**Cons**:
- Requires cluster restart
- Needs more host resources

---

### Solution 4: Optimize Resource Allocation (Recommended) 🎯

**Action**: Combine reduced requests with smart limits.

**Changes**:
1. Reduce initial replicas to 1
2. Lower resource requests
3. Keep reasonable limits
4. Enable HPA for scaling

**Implementation**:
```yaml
# Deployment
spec:
  replicas: 1  # Start with 1
  template:
    spec:
      containers:
      - name: ai-perception
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
          limits:
            cpu: "2000m"
            memory: "4Gi"

# HPA
spec:
  minReplicas: 1  # Start with 1
  maxReplicas: 5  # Lower max for single node
```

---

## Recommended Action Plan

### Immediate (Now):
1. ✅ Reduce HPA minReplicas to 1
2. ✅ Reduce resource requests (CPU: 500m, Memory: 1Gi)
3. ✅ Restart deployment

### Short-term (Today):
1. Monitor pod scheduling
2. Verify all pods start
3. Test container functionality

### Long-term (This Week):
1. Increase node resources
2. Optimize resource allocation
3. Set up proper monitoring

---

## Verification Steps

After applying fixes:

```bash
# Check pod status
kubectl get pods -n atms-system

# Check resource usage
kubectl top nodes
kubectl top pods -n atms-system

# Check events
kubectl get events -n atms-system --sort-by='.lastTimestamp'

# Verify deployment
kubectl get deployment ai-perception -n atms-system
kubectl get hpa -n atms-system
```

---

## Expected Results

After fixes:
- ✅ All pods should be Running (not Pending)
- ✅ Deployment should show X/X pods ready
- ✅ Containers should be accessible
- ✅ HPA should be able to scale when needed

---

## Additional Notes

### Why This Happens:
1. **Single-node cluster**: Limited resources
2. **Multiple services**: All competing for resources
3. **HPA minimum**: Forces 2+ replicas
4. **Resource requests**: Too high for available capacity

### Prevention:
- Monitor node capacity
- Set appropriate resource requests
- Use resource quotas
- Consider multi-node cluster for production

