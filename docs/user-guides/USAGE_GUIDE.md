# 🚀 ATMS - Quick Usage Guide

**Your system is running with a 94.7% score - EXCELLENT!**

---

## 🎯 What You Can Do Right Now

### 1. **View Real-Time Dashboard**
```bash
open http://localhost:8006
```
- See live traffic metrics
- Monitor system performance
- View anomaly alerts
- Track vehicle counts

### 2. **Test AI Models**
```bash
# Check all models
curl http://localhost:8004/ | python3 -m json.tool

# Expected output: All 3 models loaded
{
  "multiview_fusion": true,
  "trajectory_tracking": true,
  "emission_calculation": true
}
```

### 3. **Query Analytics**
```bash
# Get traffic patterns
curl http://localhost:8005/api/traffic-patterns

# Get system statistics
curl http://localhost:8005/api/statistics
```

### 4. **Monitor Traffic Decisions**
```bash
# Check current phase
curl http://localhost:8007/phase/current

# Get decision statistics
curl http://localhost:8007/statistics
```

### 5. **View Infrastructure**
```bash
# Kafka UI
open http://localhost:8080

# PostgreSQL Admin
open http://localhost:5050
# Login: atms_user / atms_password
```

---

## 📹 To Test With Live Camera

### Option 1: iPhone Camera (Already Configured)
1. Install IP Webcam app or similar on iPhone
2. Start streaming at: `192.168.0.11:8081/video`
3. Sensor Fusion will automatically connect
4. Watch vehicles being detected in real-time!

### Option 2: Test Video File
```bash
# Process a video file
cd /Users/kappasutra/Traffic
python3 << EOF
import cv2
import requests

# Load video
video = cv2.VideoCapture('path/to/your/video.mp4')

while True:
    ret, frame = video.read()
    if not ret:
        break
    
    # Send to AI Perception
    # (Implementation depends on your needs)
    
video.release()
EOF
```

---

## 🧪 Quick Tests

### Test 1: AI Model Status
```bash
curl http://localhost:8004/
```

### Test 2: Dashboard Metrics
```bash
curl http://localhost:8006/api/metrics
```

### Test 3: Decision Engine Health
```bash
curl http://localhost:8007/health
```

### Test 4: All Services
```bash
for port in 8000 8003 8004 8005 8006 8007; do
  echo "Port $port:" && curl -s http://localhost:$port/health | python3 -m json.tool
done
```

---

## 📊 View System Status Anytime

```bash
# Run complete system test
cd /Users/kappasutra/Traffic
python3 scripts/test_complete_system.py

# Or quick verification
python3 scripts/verify_system_complete.py
```

---

## 🔧 System Control

### Start All Services
```bash
cd /Users/kappasutra/Traffic
./scripts/start_all_services.sh
```

### Stop All Services
```bash
./scripts/stop_all_services.sh
```

### View Logs
```bash
# All services
tail -f /tmp/atms_*.log

# Specific service
tail -f /tmp/atms_ai-perception.log
```

### Check Service Status
```bash
# Check processes
for service in sensor-fusion ai-perception analytics dashboard decision-engine api-gateway; do
  pid_file="/tmp/atms_${service}.pid"
  if [ -f "$pid_file" ]; then
    pid=$(cat "$pid_file")
    if ps -p "$pid" > /dev/null; then
      echo "✅ $service: RUNNING"
    else
      echo "❌ $service: STOPPED"
    fi
  fi
done
```

---

## 🎮 Demo Scenario

Here's a complete workflow:

```bash
# 1. View Dashboard
open http://localhost:8006

# 2. Check AI models
curl http://localhost:8004/ | python3 -m json.tool

# 3. Monitor decisions
watch -n 1 'curl -s http://localhost:8007/phase/current | python3 -m json.tool'

# 4. View metrics
watch -n 2 'curl -s http://localhost:8006/api/metrics | python3 -m json.tool'

# 5. Check Kafka topics
open http://localhost:8080
```

---

## 📈 Performance Monitoring

### System Metrics
```bash
# View system test results
cat system_test_results.json | python3 -m json.tool

# Check verification results
cat system_verification_results.json | python3 -m json.tool
```

### Service Logs
```bash
# AI Perception
tail -f /tmp/atms_ai-perception.log | grep -E '(INFO|ERROR|WARNING)'

# Decision Engine
tail -f /tmp/atms_decision-engine.log | grep -E '(decision|phase)'

# Dashboard
tail -f /tmp/atms_dashboard.log | grep -E '(metric|WebSocket)'
```

---

## 🐛 Troubleshooting

### Service Not Responding
```bash
# Check if running
ps aux | grep python | grep services

# Restart specific service
cd services/ai-perception
source venv/bin/activate
python src/integrated_perception_service.py &
```

### Check Infrastructure
```bash
# Docker containers
docker ps

# Kafka
docker logs atms-kafka --tail 50

# PostgreSQL
docker exec atms-postgres psql -U atms_user -d atms -c "\dt"

# Redis
docker exec atms-redis redis-cli ping
```

---

## 🎯 Next Steps

### For Testing:
1. ✅ System is ready - start with dashboard
2. ✅ All APIs accessible - test endpoints
3. ⏳ Add camera feed - see real-time detection

### For Production:
1. ⏳ Configure SSL/TLS
2. ⏳ Setup monitoring (Prometheus/Grafana)
3. ⏳ Configure backup strategies
4. ⏳ Deploy to production servers

### For Development:
1. ⏳ Add more AI models
2. ⏳ Enhance decision algorithms
3. ⏳ Improve UI/UX
4. ⏳ Add mobile app

---

## 📞 Quick Reference

| Service | Port | URL |
|---------|------|-----|
| Dashboard | 8006 | http://localhost:8006 |
| API Gateway | 8000 | http://localhost:8000 |
| AI Perception | 8004 | http://localhost:8004 |
| Analytics | 8005 | http://localhost:8005 |
| Decision Engine | 8007 | http://localhost:8007 |
| Sensor Fusion | 8003 | http://localhost:8003 |
| Kafka UI | 8080 | http://localhost:8080 |
| PgAdmin | 5050 | http://localhost:5050 |

---

**🎉 Your ATMS is fully operational! Start exploring! 🚦**

For detailed results, see: `COMPLETE_SYSTEM_TEST_RESULTS.md`

