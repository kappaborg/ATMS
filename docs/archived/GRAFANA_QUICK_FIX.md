# 🔧 Grafana Quick Fix Guide

## Issue: Can't Access Grafana on localhost:3000

### Solution 1: Wait for Grafana to Fully Start

Grafana takes 10-30 seconds to fully start. Check status:

```bash
docker ps | grep grafana
# Should show: (healthy) not (health: starting)
```

### Solution 2: Check if Port is Actually Listening

```bash
# Check if port 3000 is listening
lsof -i :3000

# Or test connection
curl http://localhost:3000/api/health
```

### Solution 3: Restart Grafana Container

```bash
cd docker
docker-compose -f docker-compose.monitoring.yml restart grafana
sleep 15
# Then try http://localhost:3000 again
```

### Solution 4: Check for Database Lock Issues

If you see "database is locked" errors:

```bash
# Stop containers
cd docker
docker-compose -f docker-compose.monitoring.yml down

# Remove volumes (WARNING: This deletes Grafana data)
docker volume rm docker_grafana-data

# Restart
docker-compose -f docker-compose.monitoring.yml up -d
```

### Solution 5: Access from Container IP

If localhost doesn't work, try container IP:

```bash
# Get Grafana container IP
docker inspect atms-grafana | grep IPAddress

# Access via that IP (usually 172.x.x.x:3000)
```

### Solution 6: Check Browser/Network

- Try different browser
- Try incognito/private mode
- Clear browser cache
- Try: http://127.0.0.1:3000 instead of http://localhost:3000

### Quick Test Commands

```bash
# 1. Check container status
docker ps | grep grafana

# 2. Check logs
docker logs atms-grafana --tail 20

# 3. Test from inside container
docker exec atms-grafana wget -qO- http://localhost:3000/api/health

# 4. Test from host
curl -v http://localhost:3000/api/health
```

### Expected Output

When Grafana is ready:
- Container status: `(healthy)`
- Health endpoint: Returns `{"commit":"...","database":"ok","version":"..."}`
- Browser: Shows Grafana login page

---

**Most Common Issue**: Grafana needs 15-30 seconds to fully start. Just wait a bit longer!

