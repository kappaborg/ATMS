# ATMS Panel

A desktop operator panel (Tauri + Svelte) for live monitoring of the ATMS
traffic system: camera video with detection overlays, signal decisions, and
metrics — updating in real time.

It has two parts:

| Part | Path | What it does |
|------|------|--------------|
| **Gateway** | `services/panel-gateway/` | Python service. Ingests cameras (RTSP / USB / HTTP-MJPEG / file), runs the ATMS detection + decision pipeline, serves data + video over WebSockets. |
| **App** | `panel/` | Tauri desktop app. Connects to the gateway and renders the panel. |

The panel is a **monitoring surface only** — it is never in the safety-critical
control loop. The traffic-controller failsafe owns signal safety.

## Latency

- **Data** (detections, decisions, counts): ~30–50 ms from capture to on-screen —
  feels instant. This is what the panel optimises for.
- **Video**: annotated JPEG over WebSocket, ~150–300 ms glass-to-glass, throttled
  to ~20 fps for smoothness. (Video latency is bounded by the camera/codec, not
  the app — a hard physical floor of ~100 ms+ for RTSP.)

## Run it

**1. Start the gateway** (needs Python 3.11/3.12):

```bash
python3.12 -m venv services/panel-gateway/.venv
services/panel-gateway/.venv/bin/pip install -r services/panel-gateway/requirements.txt
./services/panel-gateway/run.sh            # serves on http://127.0.0.1:8090
```

**2. Start the desktop app** (needs Node ≥ 18 and the Rust toolchain):

```bash
cd panel
npm install
npm run tauri dev                          # first run compiles the Rust shell (slow)
```

Add a camera from the app's **Add camera** panel, or via the API:

```bash
# RTSP
curl -X POST http://127.0.0.1:8090/cameras -H 'Content-Type: application/json' \
  -d '{"camera_id":"north","source":"rtsp://user:pass@192.168.1.10:554/stream"}'
# USB device index
curl -X POST http://127.0.0.1:8090/cameras -H 'Content-Type: application/json' \
  -d '{"camera_id":"usb0","source":"0"}'
# Local video file (loops)
curl -X POST http://127.0.0.1:8090/cameras -H 'Content-Type: application/json' \
  -d '{"camera_id":"demo","source":"videos/T1.mp4","loop_file":true}'
```

## Gateway API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | liveness |
| GET | `/cameras` | list cameras + status/fps |
| POST | `/cameras` | add `{camera_id, source, loop_file?}` |
| DELETE | `/cameras/{id}` | remove a camera |
| WS | `/ws/data` | JSON events: detections, decision, counts, latency |
| WS | `/ws/video/{id}` | binary JPEG frames (latest-wins) |

Env: `PANEL_PORT`, `PANEL_HOST`, `PANEL_VIDEO_FPS`, `PANEL_CORS_ORIGINS`.
The app reads `VITE_GATEWAY` (default `http://127.0.0.1:8090`).

## Notes for production

- Regenerate real app icons: `npm run tauri icon path/to/logo.png`.
- The gateway currently reuses the SimpleByteTracker and AIDecisionEngine via a
  `sys.path` insert (see `worker.py`); promoting those into `shared/` would
  decouple the gateway from the ai-perception layout.
- For >4 cameras or remote operators, front the video with WebRTC and add auth
  (the gateway is unauthenticated for local single-operator use today).
