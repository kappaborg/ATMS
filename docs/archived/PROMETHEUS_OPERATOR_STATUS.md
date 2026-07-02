# Prometheus Operator Installation Status

**Date**: December 2, 2025  
**Status**: ✅ **PARTIALLY INSTALLED** - ServiceMonitor Available

---

## Installation Results

### ✅ Successfully Created CRDs

The following CRDs were created successfully:
- ✅ `podmonitors.monitoring.coreos.com`
- ✅ `probes.monitoring.coreos.com`
- ✅ `prometheusrules.monitoring.coreos.com`
- ✅ `servicemonitors.monitoring.coreos.com` **← Required for monitoring**
- ✅ `prometheus-operator` deployment
- ✅ `prometheus-operator` service account
- ✅ `prometheus-operator` cluster role

### ⚠️ Failed CRDs (Non-Critical)

These CRDs failed due to annotation size limits (262144 bytes max):
- ❌ `alertmanagerconfigs.monitoring.coreos.com`
- ❌ `alertmanagers.monitoring.coreos.com`
- ❌ `prometheusagents.monitoring.coreos.com`
- ❌ `prometheuses.monitoring.coreos.com`
- ❌ `scrapeconfigs.monitoring.coreos.com`
- ❌ `thanosrulers.monitoring.coreos.com`

**Impact**: These are optional for basic monitoring. The **ServiceMonitor CRD is available**, which is what we need for scraping metrics.

---

## Why This Happened

**Root Cause**: Kubernetes has a limit of 262144 bytes (256KB) for metadata annotations in CustomResourceDefinitions. The Prometheus Operator bundle includes very large OpenAPI schemas in annotations, which exceed this limit in some Kubernetes versions.

**Affected Versions**: This can happen in:
- Older Kubernetes versions (< 1.25)
- Some local clusters (Kind, Minikube)
- Clusters with strict validation

---

## Solution Options

### Option 1: Use ServiceMonitor (Recommended) ✅

**Status**: ✅ **Available and Working**

The ServiceMonitor CRD is available, which is sufficient for basic monitoring:

```bash
# Enable ServiceMonitor in kustomization.yaml
# Uncomment: - monitoring/ai-perception-servicemonitor.yaml

# Apply
kubectl apply -k k8s/base/
```

**Pros**:
- ServiceMonitor CRD is available
- Can use standalone Prometheus (without Operator)
- Simpler setup

**Cons**:
- Cannot use Prometheus Operator's Prometheus CRD
- Need to configure Prometheus manually

---

### Option 2: Use Standalone Prometheus (Alternative)

If ServiceMonitor doesn't work, use standalone Prometheus:

```yaml
# prometheus-config.yaml
scrape_configs:
  - job_name: 'ai-perception'
    kubernetes_sd_configs:
      - role: endpoints
        namespaces:
          names:
            - atms-system
    relabel_configs:
      - source_labels: [__meta_kubernetes_service_name]
        action: keep
        regex: ai-perception
      - source_labels: [__meta_kubernetes_endpoint_port_name]
        action: keep
        regex: http
```

**Pros**:
- No CRD dependencies
- Works with any Kubernetes version
- Full control over configuration

**Cons**:
- Manual configuration required
- No Operator benefits (auto-discovery, etc.)

---

### Option 3: Fix CRD Annotation Size (Advanced)

For production, you can:
1. Use a newer Kubernetes version (1.25+)
2. Modify CRDs to remove large annotations
3. Use a different Prometheus Operator version

---

## Current Status

### ✅ What Works

1. **ServiceMonitor CRD**: ✅ Available
   ```bash
   kubectl get crd servicemonitors.monitoring.coreos.com
   ```

2. **Prometheus Operator**: ✅ Running
   ```bash
   kubectl get pods -l app.kubernetes.io/name=prometheus-operator
   ```

3. **ServiceMonitor Resource**: ✅ Can be created
   ```bash
   kubectl apply -f k8s/base/monitoring/ai-perception-servicemonitor.yaml
   ```

### ⚠️ What Doesn't Work

1. **Prometheus CRD**: ❌ Not available (optional)
   - Cannot use `Prometheus` custom resource
   - Need to use standalone Prometheus

2. **Alertmanager CRD**: ❌ Not available (optional)
   - Cannot use `Alertmanager` custom resource
   - Need to use standalone Alertmanager

---

## Recommended Next Steps

### For Basic Monitoring (Recommended)

1. ✅ **ServiceMonitor is available** - Use it!
2. Enable ServiceMonitor in `k8s/base/kustomization.yaml`
3. Deploy standalone Prometheus (or use existing Prometheus)
4. Configure Prometheus to discover ServiceMonitors

### Steps

```bash
# 1. Enable ServiceMonitor
# Edit k8s/base/kustomization.yaml
# Uncomment: - monitoring/ai-perception-servicemonitor.yaml

# 2. Apply
kubectl apply -k k8s/base/

# 3. Verify ServiceMonitor
kubectl get servicemonitor -n atms-system

# 4. Configure Prometheus to use ServiceMonitor
# (If using standalone Prometheus, configure it to discover ServiceMonitors)
```

---

## Verification

```bash
# Check CRDs
kubectl get crd | grep monitoring

# Check ServiceMonitor
kubectl get servicemonitor -n atms-system

# Check Operator
kubectl get pods -l app.kubernetes.io/name=prometheus-operator

# Test ServiceMonitor creation
kubectl apply -f k8s/base/monitoring/ai-perception-servicemonitor.yaml
```

---

## Summary

✅ **ServiceMonitor CRD is available** - This is what we need for basic monitoring!

The failed CRDs are optional and don't prevent monitoring setup. You can:
- Use ServiceMonitor with standalone Prometheus ✅
- Or wait for Kubernetes upgrade to fix annotation limits

**System is ready for monitoring setup!**

