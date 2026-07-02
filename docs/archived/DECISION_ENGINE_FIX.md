# Decision Engine Fix - Readiness Probe

**Date**: December 2, 2025  
**Status**: ✅ **FIXED**

---

## Issue Identified

**Problem**: Decision Engine pods were showing `0/1 Ready` status, preventing the deployment from showing as fully available.

**Root Cause**: 
- Readiness probe was checking `/ready` endpoint
- Service only has `/health` endpoint
- Result: 404 errors, readiness probe failing

**Evidence from Logs**:
```
INFO:     10.244.0.1:58804 - "GET /ready HTTP/1.1" 404 Not Found
INFO:     10.244.0.1:58806 - "GET /ready HTTP/1.1" 404 Not Found
INFO:     10.244.0.1:39096 - "GET /health HTTP/1.1" 200 OK
```

---

## Fix Applied

**File**: `k8s/base/deployments/decision-engine-deployment.yaml`

**Change**:
```yaml
# Before:
readinessProbe:
  httpGet:
    path: /ready
    port: 8007

# After:
readinessProbe:
  httpGet:
    path: /health
    port: 8007
```

**Applied**:
```bash
kubectl apply -f k8s/base/deployments/decision-engine-deployment.yaml
```

---

## Verification

After applying the fix:
- Pods should transition to `1/1 Ready`
- Deployment should show `2/2` ready replicas
- Readiness probe should return 200 OK

**Check Status**:
```bash
kubectl get pods -n atms-system -l app=decision-engine
kubectl get deployment decision-engine -n atms-system
```

---

## Notes

- Decision Engine does NOT use the `shared` module (unlike ai-perception)
- Decision Engine does NOT need `python-multipart` (no form endpoints)
- Only fix needed was the readiness probe path

---

## Status

✅ **FIXED** - Readiness probe now points to correct endpoint

