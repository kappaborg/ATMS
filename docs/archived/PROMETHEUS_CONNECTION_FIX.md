# 🔧 Fixing Prometheus Connection Error

## Error Message
```
Error scraping target: Get "http://host.docker.internal:8004/metrics": 
dial tcp 192.168.65.254:8004: connect: connection refused
```

## Root Cause
The metrics server on port 8004 is not running. This happens when:
1. **YouTube processor is not running** - Metrics server only starts when processor runs
2. **Missing dependencies** - `prometheus-client` or `psutil` not installed
3. **Port conflict** - Another process is using port 8004

## Solutions

### Solution 1: Install Missing Dependencies (Most Common)
```bash
pip install prometheus-client psutil
```

Then restart your YouTube processor.

### Solution 2: Check if Processor is Running
The metrics server only runs when the YouTube processor is active.

```bash
# Check if processor is running
ps aux | grep youtube_decision_processor

# Check if port 8004 is listening
lsof -i :8004
```

If not running, start it:
```bash
python3 youtube_decision_processor.py <youtube_url>
```

### Solution 3: Check Port Availability
```bash
# Check what's using port 8004
lsof -i :8004

# If something else is using it, either:
# - Stop that process
# - Or change the port in monitoring/metrics.py
```

### Solution 4: Verify Metrics Endpoint
Once processor is running, test the endpoint:

```bash
# From host machine
curl http://localhost:8004/metrics

# Should return Prometheus metrics format
```

## Expected Behavior

### When Processor is Running:
- ✅ Port 8004 should be listening
- ✅ `curl http://localhost:8004/metrics` should return metrics
- ✅ Prometheus target should show "UP" (green)

### When Processor is NOT Running:
- ⚠️ Port 8004 is not listening
- ⚠️ Prometheus target shows "DOWN" (red) - **This is expected!**
- ⚠️ Connection refused error - **This is normal when processor is stopped**

## Quick Test

1. **Start processor:**
   ```bash
   python3 youtube_decision_processor.py https://www.youtube.com/watch?v=VIDEO_ID
   ```

2. **Wait 5 seconds** for metrics server to start

3. **Test endpoint:**
   ```bash
   curl http://localhost:8004/metrics | head -20
   ```

4. **Check Prometheus:**
   - Go to http://localhost:9090
   - Status → Targets
   - "traffic-system" should show "UP" ✅

## Troubleshooting

### If metrics endpoint doesn't respond:
1. Check processor logs for errors
2. Verify dependencies: `pip list | grep prometheus`
3. Check port: `lsof -i :8004`
4. Try different port if 8004 is blocked

### If Prometheus still can't connect:
1. **On Mac/Windows**: `host.docker.internal` should work
2. **On Linux**: May need to use Docker bridge IP:
   ```yaml
   # In docker/monitoring/prometheus/prometheus.yml
   - targets: ['172.17.0.1:8004']  # Docker bridge IP
   ```

---

**Note**: The "connection refused" error is **normal** when the processor is not running. 
The metrics server only exists while the processor is active.
