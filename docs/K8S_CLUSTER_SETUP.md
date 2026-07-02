# Kubernetes Cluster Setup Guide

## Quick Setup Options

### Option 1: Docker Desktop Kubernetes (Recommended - Easiest) ✅

Since you have Docker Desktop running, this is the **easiest option**:

1. **Open Docker Desktop**
2. **Go to Settings** (gear icon)
3. **Click on "Kubernetes"** in the left sidebar
4. **Check "Enable Kubernetes"**
5. **Click "Apply & Restart"**
6. **Wait for Kubernetes to start** (you'll see a green Kubernetes icon in the status bar)

**Verify it's working:**
```bash
kubectl cluster-info
kubectl get nodes
```

**Then deploy:**
```bash
./scripts/deploy_k8s.sh
```

---

### Option 2: Install Minikube

**Install:**
```bash
brew install minikube
```

**Start cluster:**
```bash
minikube start
```

**Verify:**
```bash
kubectl cluster-info
```

**Deploy:**
```bash
./scripts/deploy_k8s.sh
```

---

### Option 3: Install Kind

**Install:**
```bash
brew install kind
```

**Create cluster:**
```bash
kind create cluster --name atms
```

**Verify:**
```bash
kubectl cluster-info
```

**Deploy:**
```bash
./scripts/deploy_k8s.sh
```

---

## Helper Script

Run the setup helper to check what's available:
```bash
./scripts/setup_k8s_cluster.sh
```

This will:
- Check what tools you have installed
- Guide you to the best option
- Provide step-by-step instructions

---

## Troubleshooting

### Check if cluster is running:
```bash
kubectl cluster-info
```

### Check kubectl context:
```bash
kubectl config get-contexts
```

### Switch context (if needed):
```bash
kubectl config use-context docker-desktop  # For Docker Desktop
kubectl config use-context minikube        # For Minikube
kubectl config use-context kind-atms       # For Kind
```

---

## After Cluster is Running

1. **Verify cluster:**
   ```bash
   kubectl get nodes
   ```

2. **Deploy ATMS:**
   ```bash
   ./scripts/deploy_k8s.sh
   ```

3. **Check deployment:**
   ```bash
   kubectl get pods -n atms-system
   kubectl get services -n atms-system
   ```

---

## Notes

- **Docker Desktop Kubernetes** is the easiest if you already have Docker Desktop
- **Minikube** is good for development and testing
- **Kind** is lightweight and fast for local development

All three options work with our deployment scripts!

