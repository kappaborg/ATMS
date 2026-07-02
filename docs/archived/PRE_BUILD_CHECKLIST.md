# Pre-Build Checklist - Docker Images

**Last Updated**: December 2, 2025  
**Purpose**: Ensure all Docker images are built correctly with all dependencies before deployment

---

## 🔍 Pre-Build Verification

### 1. Check Dependencies

**Before building any image, verify:**

```bash
# Check if shared module exists
ls -la shared/
ls -la shared/utils/
ls -la shared/models/

# Check requirements.txt includes all dependencies
grep -E "prometheus-client|pydantic-settings" services/ai-perception/requirements.txt
```

**Required Dependencies:**
- ✅ `prometheus-client==0.19.0` (for metrics)
- ✅ `pydantic-settings==2.1.0` (for shared module)
- ✅ `shared` module (local package)

---

### 2. Verify Dockerfile Configuration

**For services using `shared` module (ai-perception, sensor-fusion):**

```bash
# Check Dockerfile copies shared module
grep -A 2 "COPY shared" services/ai-perception/Dockerfile
grep -A 2 "COPY shared" services/sensor-fusion/Dockerfile
```

**Required in Dockerfile:**
- ✅ Copy `shared` package in builder stage
- ✅ Install `shared` package with pip
- ✅ Copy `shared` to `/app/shared` in final stage
- ✅ Build from project root (not service directory)

---

### 3. Build Command Verification

**Services that need `shared` module MUST be built from project root:**

```bash
# ✅ CORRECT - Build from project root
cd /Users/kappasutra/Traffic
docker build --no-cache -f services/ai-perception/Dockerfile -t atms/ai-perception:latest .

# ❌ WRONG - Building from service directory
cd services/ai-perception
docker build -t atms/ai-perception:latest .
```

**Services requiring root build:**
- `ai-perception` (uses shared)
- `sensor-fusion` (uses shared)

**Services that can build from service directory:**
- `decision-engine`
- `video-processor`
- `api-gateway`
- `dashboard`
- `analytics`
- `data-aggregator`
- `traffic-controller`

---

## 📋 Complete Pre-Build Checklist

### Step 1: Verify Project Structure ✅

```bash
cd /Users/kappasutra/Traffic

# Check shared module exists
[ -d shared ] && echo "✅ Shared module exists" || echo "❌ Shared module missing"

# Check shared has required files
[ -f shared/utils/logger.py ] && echo "✅ logger.py exists" || echo "❌ logger.py missing"
[ -f shared/models/base.py ] && echo "✅ base.py exists" || echo "❌ base.py missing"
```

### Step 2: Verify Requirements Files ✅

```bash
# Check ai-perception requirements
grep -q "prometheus-client" services/ai-perception/requirements.txt && echo "✅ prometheus-client" || echo "❌ Missing prometheus-client"
grep -q "pydantic-settings" services/ai-perception/requirements.txt && echo "✅ pydantic-settings" || echo "❌ Missing pydantic-settings"
```

### Step 3: Verify Dockerfiles ✅

```bash
# Check ai-perception Dockerfile
grep -q "COPY shared" services/ai-perception/Dockerfile && echo "✅ Copies shared" || echo "❌ Missing shared copy"
grep -q "pip install.*shared" services/ai-perception/Dockerfile && echo "✅ Installs shared" || echo "❌ Missing shared install"
```

### Step 4: Test Build Locally ✅

```bash
# Test build ai-perception (from project root)
cd /Users/kappasutra/Traffic
docker build --no-cache -f services/ai-perception/Dockerfile -t atms/ai-perception:test .

# Test if shared module works
docker run --rm atms/ai-perception:test python -c "import sys; sys.path.insert(0, '/app'); from shared.utils.logger import setup_logger; print('✅ Shared works!')"

# Test if prometheus_client works
docker run --rm atms/ai-perception:test python -c "from prometheus_client import Counter; print('✅ prometheus_client works!')"
```

### Step 5: Clean Old Images ✅

```bash
# Remove old images to force rebuild
docker rmi atms/ai-perception:latest 2>/dev/null || true

# Or use build script with --no-cache
./scripts/build_docker_images.sh
```

---

## 🚨 Common Issues & Fixes

### Issue 1: `ModuleNotFoundError: No module named 'shared'`

**Cause**: Dockerfile doesn't copy shared module or build from wrong directory

**Fix**:
```bash
# 1. Verify Dockerfile copies shared
grep "COPY shared" services/ai-perception/Dockerfile

# 2. Rebuild from project root
cd /Users/kappasutra/Traffic
docker build --no-cache -f services/ai-perception/Dockerfile -t atms/ai-perception:latest .

# 3. Verify in image
docker run --rm atms/ai-perception:latest ls -la /app/shared
```

### Issue 2: `ModuleNotFoundError: No module named 'prometheus_client'`

**Cause**: Missing from requirements.txt or not installed

**Fix**:
```bash
# 1. Add to requirements.txt
echo "prometheus-client==0.19.0" >> services/ai-perception/requirements.txt

# 2. Rebuild image
docker build --no-cache -f services/ai-perception/Dockerfile -t atms/ai-perception:latest .
```

### Issue 3: `ModuleNotFoundError: No module named 'pydantic_settings'`

**Cause**: Missing dependency for shared module

**Fix**:
```bash
# 1. Add to requirements.txt
echo "pydantic-settings==2.1.0" >> services/ai-perception/requirements.txt

# 2. Rebuild image
docker build --no-cache -f services/ai-perception/Dockerfile -t atms/ai-perception:latest .
```

### Issue 4: Kubernetes using old image

**Cause**: ImagePullPolicy is `IfNotPresent` and old image cached

**Fix**:
```bash
# 1. Update imagePullPolicy to Always
kubectl patch deployment ai-perception -n atms-system -p '{"spec":{"template":{"spec":{"containers":[{"name":"ai-perception","imagePullPolicy":"Always"}]}}}}'

# 2. Or delete pods to force pull
kubectl delete pods -n atms-system -l app=ai-perception

# 3. Or tag new image with version
docker tag atms/ai-perception:latest atms/ai-perception:v1.0.1
# Update deployment to use v1.0.1
```

---

## ✅ Build Script Verification

**Use the build script which handles everything:**

```bash
./scripts/build_docker_images.sh
```

**The script:**
- ✅ Builds from correct directory for each service
- ✅ Uses `--no-cache` for fresh builds
- ✅ Handles `shared` module correctly
- ✅ Reports success/failure for each service

---

## 🎯 Recommended Build Order

1. **Build shared-dependent services first:**
   ```bash
   # ai-perception (needs shared)
   docker build --no-cache -f services/ai-perception/Dockerfile -t atms/ai-perception:latest .
   
   # sensor-fusion (needs shared)
   docker build --no-cache -f services/sensor-fusion/Dockerfile -t atms/sensor-fusion:latest .
   ```

2. **Build other services:**
   ```bash
   # Can build from service directory
   cd services/decision-engine
   docker build --no-cache -t atms/decision-engine:latest .
   ```

3. **Or use build script:**
   ```bash
   ./scripts/build_docker_images.sh
   ```

---

## 📊 Post-Build Verification

After building, verify each image:

```bash
# Test shared module
docker run --rm atms/ai-perception:latest python -c "import sys; sys.path.insert(0, '/app'); from shared.utils.logger import setup_logger; print('✅')"

# Test prometheus_client
docker run --rm atms/ai-perception:latest python -c "from prometheus_client import Counter; print('✅')"

# Test pydantic_settings
docker run --rm atms/ai-perception:latest python -c "from pydantic_settings import BaseSettings; print('✅')"
```

---

## 🚀 Next Steps After Building

1. **Tag images** (optional but recommended):
   ```bash
   docker tag atms/ai-perception:latest atms/ai-perception:v1.0.1
   ```

2. **Push to registry** (if using remote registry):
   ```bash
   docker push atms/ai-perception:v1.0.1
   ```

3. **Update Kubernetes deployments** (if using version tags):
   ```bash
   kubectl set image deployment/ai-perception ai-perception=atms/ai-perception:v1.0.1 -n atms-system
   ```

4. **Deploy to Kubernetes**:
   ```bash
   ./scripts/deploy_k8s.sh
   ```

---

## 📝 Quick Reference

**Build command for services with shared:**
```bash
cd /Users/kappasutra/Traffic
docker build --no-cache -f services/<service>/Dockerfile -t atms/<service>:latest .
```

**Build command for services without shared:**
```bash
cd services/<service>
docker build --no-cache -t atms/<service>:latest .
```

**Verify image:**
```bash
docker run --rm atms/<service>:latest <test-command>
```

