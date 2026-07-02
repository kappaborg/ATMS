# Build Verification Checklist

**Last Updated**: December 2, 2025  
**Purpose**: Verify all components are ready before building Docker images

---

## ✅ Pre-Build Verification Steps

### 1. Port Conflicts ✅
```bash
# Check for port conflicts
lsof -i :8004
docker ps -a | grep 8004

# Clean up conflicting containers
docker stop $(docker ps -aq --filter "publish=8004")
docker rm $(docker ps -aq --filter "publish=8004")
```

**Status**: ✅ Port conflicts resolved

---

### 2. Code Syntax ✅
```bash
# Verify Python syntax
python3 -m py_compile services/ai-perception/src/calculations/speed_calculator.py
python3 -m py_compile services/ai-perception/src/main.py
```

**Status**: ✅ All syntax checks passed

---

### 3. Dependencies ✅
```bash
# Check requirements.txt
grep "prometheus-client" services/ai-perception/requirements.txt
grep "pydantic-settings" services/ai-perception/requirements.txt
```

**Required Dependencies:**
- ✅ `prometheus-client==0.19.0`
- ✅ `pydantic-settings==2.1.0`
- ✅ `scipy>=1.11.0`

**Status**: ✅ All dependencies present

---

### 4. Shared Module ✅
```bash
# Verify shared module exists
ls -la shared/
ls -la shared/utils/logger.py
ls -la shared/models/base.py
```

**Status**: ✅ Shared module verified

---

### 5. Dockerfile Configuration ✅
```bash
# Check Dockerfile
grep "COPY shared" services/ai-perception/Dockerfile
grep "PYTHONPATH" services/ai-perception/Dockerfile
```

**Required in Dockerfile:**
- ✅ `COPY shared /app/shared`
- ✅ `ENV PYTHONPATH=/app:/app/shared:$PYTHONPATH`

**Status**: ✅ Dockerfile configured correctly

---

### 6. Kubernetes Resources ✅
```bash
# Check resource requests
kubectl get deployment ai-perception -n atms-system -o jsonpath='{.spec.template.spec.containers[0].resources}'
kubectl get hpa ai-perception-hpa -n atms-system -o jsonpath='{.spec.minReplicas}-{.spec.maxReplicas}'
```

**Required Settings:**
- ✅ CPU request: 500m
- ✅ Memory request: 1Gi
- ✅ Replicas: 1
- ✅ HPA: min=1, max=5

**Status**: ✅ Resources configured

---

## 🚀 Build Command

**For services with shared module (build from project root):**
```bash
cd /Users/kappasutra/Traffic
docker build --no-cache -f services/ai-perception/Dockerfile -t atms/ai-perception:latest .
```

**For services without shared (build from service directory):**
```bash
cd services/decision-engine
docker build --no-cache -t atms/decision-engine:latest .
```

---

## ✅ Post-Build Verification

```bash
# Test shared module
docker run --rm atms/ai-perception:latest python -c "from shared.utils.logger import setup_logger; print('✅ Shared works!')"

# Test prometheus_client
docker run --rm atms/ai-perception:latest python -c "from prometheus_client import Counter; print('✅ prometheus_client works!')"

# Test speed_calculator
docker run --rm atms/ai-perception:latest python -c "import sys; sys.path.insert(0, '/app/src'); from calculations.speed_calculator import SpeedCalculator; print('✅ speed_calculator works!')"
```

---

## 📋 Integration Checklist

### Before Building:
- [x] Port conflicts resolved
- [x] Code syntax verified
- [x] Dependencies in requirements.txt
- [x] Shared module exists
- [x] Dockerfile configured
- [x] Kubernetes resources set

### After Building:
- [ ] Image builds successfully
- [ ] All modules import correctly
- [ ] No syntax errors
- [ ] Pods start successfully
- [ ] Health endpoint responds
- [ ] Metrics exposed

---

## 🔧 Troubleshooting

### Port Already Allocated
```bash
# Find and stop conflicting containers
docker ps -a | grep 8004
docker stop <container_id>
docker rm <container_id>
```

### Module Not Found
- Verify Dockerfile copies shared module
- Check PYTHONPATH is set
- Rebuild with --no-cache

### Syntax Errors
- Run `python3 -m py_compile` on all Python files
- Check indentation (use spaces, not tabs)
- Verify all imports are available

---

## ✅ Current Status

**All Pre-Build Checks**: ✅ PASSED  
**Ready to Build**: ✅ YES

