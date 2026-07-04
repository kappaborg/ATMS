# ATMS Panel Gateway — Deployment

The panel gateway is the self-contained backend that ingests cameras (RTSP /
USB / files / YouTube-live pages), runs the full detection→decision→evidence
pipeline, and serves the desktop panel (and any HTTP/WS client). This guide
covers running it **anywhere** — not just the development Mac.

## Option A — Docker (recommended for servers / edge boxes)

```bash
# from the repo root
docker compose -f deploy/docker-compose.panel.yml up -d --build
# or plain docker:
docker build -f services/panel-gateway/Dockerfile -t atms-panel-gateway .
docker run -d -p 8090:8090 -v atms-panel-data:/data atms-panel-gateway
```

- Weights (YOLO + plate detector) are **baked into the image** — works offline.
  The ReID backbone downloads once on first use (or pre-mount a torch cache).
- Durable state (cameras, calibrations, history, violation evidence) lives in
  the `/data` volume and survives container upgrades.
- **The container binds 0.0.0.0 — configure access control** (see Security).

Add cameras exactly as on the desktop:

```bash
curl -X POST http://<host>:8090/cameras -H 'Content-Type: application/json' \
  -d '{"camera_id":"sarajevo","source":"https://www.youtube.com/watch?v=ud6OgjE6duo"}'
```

Point the desktop app at the server by building it with
`VITE_GATEWAY=http://<host>:8090` in `panel/.env`.

## Option B — bare metal (macOS / Linux)

```bash
./services/panel-gateway/setup.sh          # creates its own .venv (py3.11/3.12)
./services/panel-gateway/launch.command    # starts on http://127.0.0.1:8090
```

Auto-start at login (macOS): `deploy/launchagents/com.atms.panel-gateway.plist`.

## Security checklist for any network-reachable deployment

| Setting | Why |
|---|---|
| `PANEL_USERS="name:role:sha256:<hex>,…"` | named operators, RBAC (viewer/operator/admin) |
| `PANEL_AUTH_SECRET` | sessions survive restarts |
| `PANEL_VIOLATION_RETENTION_DAYS` (default 30 in Docker) | evidence (plates/photos = PII) auto-expires |
| `ATMS_STRICT_LIVE=1` | production: forbid file sources, live streams only |
| `PANEL_CORS_ORIGINS` | pin allowed web origins |
| TLS | terminate HTTPS/WSS at a reverse proxy (nginx/caddy) in front of :8090 |

## Feature flags (all optional)

`PANEL_ALWAYS_RECORD` / `PANEL_RECORD_FPS` — unattended detection & evidence;
`PANEL_READ_PLATES` + `PANEL_PLATE_COUNTRY` — plate capture & validation;
`PANEL_USE_SAHI` or per-camera via API/app — small-object slicing;
`PANEL_MODEL` (yolov8n/s/m — bigger = better small/night detection, slower); `PANEL_CONFIDENCE` (detection floor, default 0.35; lower for dim/small objects); `PANEL_TRACK_NEW` (new-track confidence, default 0.35; lower so faint night objects get counted); `PANEL_MIN_CONFIDENCE` (per-camera detection floor — raise to drop wrong boxes on noisy scenes); `PANEL_INFER_WAIT_MS` (max wait for the shared detector before a camera reuses its last result — bounds multi-stream latency, default 150); `PANEL_DETECT_INTERVAL_MS` (cap detection rate per camera, default 0=off); `PANEL_REID` — appearance identity recovery; `PANEL_SPEED_LIMIT_KMH`,
`PANEL_DRIFT_LAT_G`, `PANEL_SPEEDING_FRAMES`, `PANEL_ERRATIC_REVERSALS` —
violation tuning; `KAFKA_BOOTSTRAP_SERVERS`, `PANEL_CONTROLLER_URLS` —
full-ATMS integration. Full reference: `panel/README.md`.

## Sizing (measured, CPU-only)

| Scenario | Guidance |
|---|---|
| 1–4 cameras, whole-frame | any modern 4-core box, ~2 GB RAM for the process |
| SAHI cameras (aerial) | budget ~1 fps per SAHI camera per 4 cores — enable per camera, only where needed |
| Plates ON | easyocr adds ~1.5 GB RAM once loaded; OCR runs only on flagged violators |

The pipeline degrades gracefully: detection/decisions stay real-time; video
fps shares whatever CPU remains.
