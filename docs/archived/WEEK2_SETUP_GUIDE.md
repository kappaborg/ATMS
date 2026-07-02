# 📊 Week 2 Setup Guide - Grafana & Python Dashboard

**Date**: November 30, 2025  
**Status**: Week 2 Complete ✅

---

## ✅ What's Been Implemented

### 1. Grafana Dashboard Setup ✅
- Docker Compose configuration for Prometheus + Grafana
- Prometheus configuration file
- Pre-configured Grafana dashboard with 10 panels
- Automatic datasource provisioning

### 2. Python Interface Dashboard ✅
- Real-time dashboard using matplotlib and tkinter
- Updates every 1 second (non-blocking)
- Shows FPS, detections, processing times
- System resource monitoring

---

## 🚀 Quick Start

### Option 1: Grafana Dashboard (Web-based)

1. **Start Monitoring Stack**:
   ```bash
   # Make sure Kafka network exists
   docker network create atms-network 2>/dev/null || true
   
   # Start Prometheus and Grafana
   cd docker
   docker-compose -f docker-compose.monitoring.yml up -d
   ```

2. **Access Dashboards**:
   - **Grafana**: http://localhost:3000
     - Username: `admin`
     - Password: `admin`
   - **Prometheus**: http://localhost:9090

3. **Run YouTube Processor**:
   ```bash
   python3 youtube_decision_processor.py https://www.youtube.com/watch?v=VIDEO_ID
   ```

4. **View Metrics**:
   - Prometheus metrics: http://localhost:8004/metrics
   - Grafana dashboard: http://localhost:3000 (auto-imported)

### Option 2: Python Dashboard (Local GUI)

1. **Install Dependencies**:
   ```bash
   pip install matplotlib
   ```

2. **Run with Dashboard**:
   ```bash
   python3 youtube_decision_processor.py --dashboard https://www.youtube.com/watch?v=VIDEO_ID
   ```

3. **Dashboard Features**:
   - Real-time FPS chart
   - Detection count chart
   - Processing time chart
   - System resource display
   - Updates every 1 second

---

## 📊 Grafana Dashboard Panels

The dashboard includes 10 panels:

1. **FPS - Current** - Real-time FPS display
2. **FPS - Average** - Average FPS over time
3. **Vehicles Detected** - Current vehicle count
4. **Pedestrians Detected** - Current pedestrian count
5. **Frame Processing Time** - Processing time histogram
6. **Detection Time** - Detection processing time
7. **Total Detections** - Detection rate over time
8. **System Resources** - Memory and CPU usage
9. **Decision Confidence** - Decision confidence scores
10. **Traffic Metrics** - Vehicle counts and emissions by direction

---

## 🔧 Configuration

### Prometheus Configuration

Edit `docker/prometheus/prometheus.yml`:

```yaml
# If running on same machine, change:
- targets: ['host.docker.internal:8004']
# To:
- targets: ['localhost:8004']
```

### Grafana Configuration

- Default credentials: `admin` / `admin`
- Change in `docker/docker-compose.monitoring.yml` if needed

### Python Dashboard

- Update interval: 1 second (configurable in code)
- Window size: 1200x800 (configurable)
- Data history: Last 100 points

---

## 📈 Performance Impact

**Grafana**: 0% (separate service)  
**Python Dashboard**: <1% (separate thread, infrequent updates)

---

## 🐛 Troubleshooting

### Grafana Not Showing Data

1. **Check Prometheus**:
   ```bash
   curl http://localhost:9090/api/v1/targets
   ```
   Should show `traffic-system` target as UP

2. **Check Metrics Endpoint**:
   ```bash
   curl http://localhost:8004/metrics
   ```
   Should return Prometheus metrics

3. **Check Network**:
   ```bash
   docker network inspect atms-network
   ```
   Prometheus and Grafana should be on same network

### Python Dashboard Not Showing

1. **Check Dependencies**:
   ```bash
   pip install matplotlib
   ```

2. **Check Logs**:
   Look for dashboard-related messages in console

3. **Try Manual Start**:
   ```python
   from monitoring.dashboard import create_dashboard
   from monitoring import PerformanceCollector
   
   collector = PerformanceCollector()
   collector.start()
   dashboard = create_dashboard(collector)
   dashboard.show()
   ```

---

## 📝 Files Created

```
docker/
├── docker-compose.monitoring.yml    # Docker Compose for monitoring
└── prometheus/
    └── prometheus.yml               # Prometheus configuration

grafana/
├── datasources/
│   └── prometheus.yml              # Grafana datasource config
└── dashboards/
    ├── dashboard.yml               # Dashboard provisioning
    └── traffic-system-dashboard.json # Dashboard definition

monitoring/
└── dashboard.py                    # Python dashboard

docs/
└── WEEK2_SETUP_GUIDE.md            # This file
```

---

## ✅ Success Criteria

- [x] Grafana dashboard working
- [x] Prometheus scraping metrics
- [x] Python dashboard functional
- [x] No performance degradation
- [x] Backward compatible (optional features)

---

## 🎉 Summary

**Week 2 Complete!** ✅

Both Grafana and Python dashboards are now available:
- **Grafana**: Professional web-based monitoring
- **Python Dashboard**: Lightweight local GUI

**Next**: Week 3 - Security implementation!

---

**Last Updated**: November 30, 2025

