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

## Install as a desktop app (macOS)

Build a real `.app` and put it in Applications so you can open it from
Launchpad anytime:

```bash
cd panel && npm run tauri build
cp -R "src-tauri/target/release/bundle/macos/ATMS Panel.app" /Applications/
```

The app is just the UI — it needs the **gateway** running (it connects to
`http://127.0.0.1:8090`). Two ways to keep the gateway available:

- **On demand:** double-click `services/panel-gateway/launch.command`
  (leave the window open), then open *ATMS Panel*.
- **Always on:** install the LaunchAgent so the gateway starts at login —
  see `deploy/launchagents/com.atms.panel-gateway.plist`. The gateway idles
  at ~0% CPU when the app is closed, so this is cheap.

First launch may show a Gatekeeper prompt (unsigned local build): right-click
the app → **Open** once.

## Run it (development)

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

**Quick demo:** `./services/panel-gateway/demo.sh` starts the gateway and adds
a looping demo camera; then `cd panel && npm run tauri dev` opens the app.
(App connection is configured via `panel/.env` — see `.env.example`.)

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

Env: `PANEL_PORT`, `PANEL_HOST`, `PANEL_VIDEO_FPS`, `PANEL_CORS_ORIGINS`,
`PANEL_STATE_FILE`, `KAFKA_BOOTSTRAP_SERVERS`, `PANEL_CONTROLLER_URLS`,
`PANEL_CONTROLLER_POLL_S`, `PANEL_API_TOKEN`, `ATMS_ALLOWED_VIDEO_DIRS`,
`ATMS_ALLOW_LOOPBACK_SOURCES`, `PANEL_MAX_CAMERAS`, `PANEL_MAX_WS_CLIENTS`,
`PANEL_RATE_LIMIT` (see Security).
The app reads `VITE_GATEWAY` (default `http://127.0.0.1:8090`) and
`VITE_GATEWAY_TOKEN`.

## Connecting to a running ATMS

By default each camera computes a **local** decision estimate. Point the
gateway at your Kafka broker to also show the **real** controller output:

```bash
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 ./services/panel-gateway/run.sh
```

The gateway then consumes the `decisions` topic (the actual decision-engine
output) and the panel shows, per intersection, the **Controller** commanded
phase with a **live/stale** badge above the local panel estimate — so an
operator sees what the running system is commanding, and is warned when the
decision stream goes silent. Assign a camera to an intersection with
`intersection_id` when adding it. Without Kafka the panel works standalone on
local estimates.

**Failsafe mode** (the top-line safety signal). Point the gateway at the
traffic-controller(s) to show each intersection's failsafe mode —
**AI-ADAPTIVE** (normal), **FIXED-TIME** (AI degraded), or **ALL-RED FLASH**
(alarm, pulsing red) — plus a "controller unreachable" state:

```bash
PANEL_CONTROLLER_URLS="1=http://localhost:8010" ./services/panel-gateway/run.sh
```

The gateway polls each controller's (unauthenticated) `/health` endpoint every
`PANEL_CONTROLLER_POLL_S` seconds (default 2). Format is
`<intersection_id>=<base_url>`, comma-separated for multiple intersections.

Persistence: cameras and their calibration/zones are saved to
`PANEL_STATE_FILE` and restored on restart.

## Emissions (carbon dashboard)

When a camera is calibrated, the panel measures real CO2 from observed speed
(per-vehicle base g/km x a speed factor; idling is time-based) and shows total
CO2, rate, average intensity, and an **estimated** saving. The saved figure is
a transparent model — measured idle CO2 x an adaptive-control ratio (published
studies report ~10-30% idle/delay reduction) — never a raw measurement. Tune:
`PANEL_ADAPTIVE_SAVINGS_RATIO` (default 0.15), `PANEL_IDLE_CO2_G_S` (0.5),
`PANEL_IDLE_SPEED_KMH` (3.0).

## Security

- **Safe by default:** the gateway binds to `127.0.0.1` (local only). If you
  bind to a network interface (`PANEL_HOST=0.0.0.0`) without a token it logs a
  loud warning.
- **Token auth:** set `PANEL_API_TOKEN` to require a token on every mutating
  and streaming endpoint (`/cameras`, `/scene`, both WebSockets). REST uses
  `Authorization: Bearer <token>`; WebSockets use `?token=<token>` (browsers
  can't set WS headers). `/health` stays open for liveness probes. The app
  sends the token when built with `VITE_GATEWAY_TOKEN`.
- **Camera-source validation** (always on): `POST /cameras` rejects SSRF and
  local-file access. URLs to link-local/metadata (`169.254.169.254`),
  reserved, and — by default — loopback addresses are blocked; private LAN
  cameras are allowed. File sources are confined to `ATMS_ALLOWED_VIDEO_DIRS`
  (default `videos/` + `Processed_Videos/`); traversal is rejected. Set
  `ATMS_ALLOW_LOOPBACK_SOURCES=1` to allow `127.0.0.1` test streams.
- **Resource + rate limits** (DoS protection): at most `PANEL_MAX_CAMERAS`
  cameras (default 8) and `PANEL_MAX_WS_CLIENTS` WebSocket connections
  (default 32); mutating requests are rate-limited per client IP via
  `PANEL_RATE_LIMIT` (default `30/60` = 30 requests / 60 s). Over-limit
  returns `429` (REST) or closes the socket with `1013`.

## Driver-anomaly detection

Alongside stopped-vehicle incidents, the panel flags **speeding** (measured
speed over `PANEL_SPEED_LIMIT_KMH`, default 60 — needs calibration) and
**wrong-way** driving (a vehicle whose sustained motion opposes the learned
per-approach flow — needs approach zones, so it's disabled when uncalibrated to
avoid false positives). **Red-light running** flags a vehicle crossing a
**stop-line** while its approach is red (draw stop-lines in the Calibrate →
Stop-lines tab; works in image space, no ground-plane calibration needed). All three surface as one unified `violations` list in
`/ws/data`, are drawn on the frame (red STOPPED / orange SPEEDING / magenta
WRONG-WAY, most-severe wins), and roll up into the network overview.  **Reckless/erratic** driving flags repeated left-right heading reversals
(weaving) — distinguished from a normal turn, computed over a displacement step
so tracking jitter can't trigger it (advisory; tune `PANEL_ERRATIC_REVERSALS`). These are
operator alerts/analytics, not legal enforcement.

## Unattended monitoring

By default a camera idles at ~0% CPU when no operator is watching (video +
pipeline paused). For a government/24-7 deployment set `PANEL_ALWAYS_RECORD=1`:
the detection/decision/history pipeline keeps running even with no viewer —
throttled to `PANEL_RECORD_FPS` (default 5) and skipping video encoding — so
history, incidents and the network overview never have gaps. Cameras then
report status `recording`.

## Green-wave corridors

Coordinate a route of intersections into a green wave. `POST /corridors`
(operator) with `{corridor_id, direction, design_speed_kmh, cycle_s, green_s,
stops:[{intersection_id, distance_m}]}` computes the cumulative offset schedule
(offset[i] = cumulative_distance[i] / design_speed mod cycle) and pushes a
bounded coordination bias onto each intersection's engine — soft, so heavy
local demand still overrides it (an *adaptive* green wave). The Network view
shows a time-space diagram (green bands + the design-speed vehicle line riding
through them). Simulation: `python benchmarks/benchmark_corridor.py` (green-wave
~58% fewer stops than a naive simultaneous corridor).

## Long-horizon history (persisted)

The gateway persists per-interval metric deltas (vehicles, CO2, estimated
savings, incidents) to a local SQLite file, so totals survive restarts and you
can report "this month/year". `GET /history?hours=720&camera_id=X` returns
totals + a time-bucketed series; the report CSV includes last-24h/7d/30d
windows; the panel shows a 30-day strip. Config: `PANEL_HISTORY_DB` (default
next to PANEL_STATE_FILE), `PANEL_HISTORY_FLUSH_S` (default 60).

## Multi-operator access (RBAC)

For agency use, define named operators with roles instead of one shared token:

```bash
PANEL_USERS="alice:admin:sha256:<hex>,bob:operator:oppw,eve:viewer:viewpw" \
PANEL_AUTH_SECRET="<random-32+ chars>" ./services/panel-gateway/run.sh
```

Roles form a hierarchy: **viewer** (watch only) < **operator** (+ add/remove
cameras, calibrate) < **admin**. Passwords may be plaintext (dev) or
`sha256:<hex>` (recommended). Login (`POST /auth/login`) returns a signed
session token (8h TTL, `PANEL_TOKEN_TTL_S`); the app shows a sign-in screen,
the current user/role, and hides operator controls from viewers. Every login
and mutation is written to an append-only audit log (`panel.audit`). The
legacy `PANEL_API_TOKEN` still works and maps to admin. Set `PANEL_AUTH_SECRET`
so sessions survive a gateway restart.

## Real-data / strict live mode

For government/production use, set `ATMS_STRICT_LIVE=1`: it forbids recorded
file sources (only RTSP/HTTP streams and USB/Continuity cameras are accepted)
and forces mock detection off regardless of any other flag — so every number
comes from a real live stream. Each camera reports its `kind` (rtsp/http/usb/
file) and a `live` flag; the panel shows a green **● LIVE** badge for real
streams and **FILE** for recordings. `/health` reports `strict_live`.

## Notes for production

- Regenerate real app icons: `npm run tauri icon path/to/logo.png`.
- The gateway currently reuses the SimpleByteTracker and AIDecisionEngine via a
  `sys.path` insert (see `worker.py`); promoting those into `shared/` would
  decouple the gateway from the ai-perception layout.
- For >4 cameras or remote operators, front the video with WebRTC and add auth
  (the gateway is unauthenticated for local single-operator use today).
