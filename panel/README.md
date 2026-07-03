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
| POST | `/cameras/{id}/scene` | set calibration + approach zones (below) |
| WS | `/ws/data` | JSON events: detections (with speed + approach), per-approach counts, decision, latency |
| WS | `/ws/video/{id}` | binary JPEG frames (latest-wins) |

## Calibration & approach zones

Without calibration the panel reports **no speed** and splits approaches by
frame centre (a stand-in). Calibrate a camera to get **real speed** (km/h) and
**real per-approach counts**.

**In the app:** select a camera and click **⚙ Calibrate**. On the frozen frame,
click ≥4 reference points and type each one's real-world position in metres
(pick a fixed origin, e.g. a lane corner with known spacing), then draw approach
zones and assign each a direction. **Apply to camera** shows the reprojection
error so you can see how good the fit is.

**Via the API** (what the UI calls under the hood):

```bash
curl -X POST http://127.0.0.1:8090/cameras/north/scene -H 'Content-Type: application/json' -d '{
  "calibration": {
    "image_points":  [[100,600],[1180,600],[400,250],[880,250]],
    "world_points_m":[[0,0],    [12,0],    [0,40],   [12,40]]
  },
  "zones": {
    "north": [[0,0],[640,0],[640,720],[0,720]],
    "south": [[640,0],[1280,0],[1280,720],[640,720]]
  },
  "zone_directions": {"north": "ns", "south": "ns"}
}'
```

- **calibration**: ≥4 image pixel points and their real-world ground-plane
  coordinates in metres (e.g. lane-marking corners with known spacing). A
  homography maps pixels → metres; speed is ground-plane displacement over
  time. The response includes `reprojection_error_m` — how well the homography
  fits its own points; lower is better (aim for < ~0.3 m).
- **zones**: named polygons (image pixels). A detection's centre is classified
  into a zone → its approach.
- **zone_directions**: maps each zone to `ns` or `ew` for the two decision-engine
  approaches.

Speed accuracy is only as good as the reference points; the ground-plane
homography is exact for objects on the road surface (verified to recover known
speeds within measurement noise in `services/panel-gateway` tests).

Env: `PANEL_PORT`, `PANEL_HOST`, `PANEL_VIDEO_FPS`, `PANEL_CORS_ORIGINS`.
The app reads `VITE_GATEWAY` (default `http://127.0.0.1:8090`).

## Notes for production

- Regenerate real app icons: `npm run tauri icon path/to/logo.png`.
- The gateway currently reuses the SimpleByteTracker and AIDecisionEngine via a
  `sys.path` insert (see `worker.py`); promoting those into `shared/` would
  decouple the gateway from the ai-perception layout.
- For >4 cameras or remote operators, front the video with WebRTC and add auth
  (the gateway is unauthenticated for local single-operator use today).
