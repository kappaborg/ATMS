# ATMS Operator Runbook

**Audience:** Demo presenter or pilot ops engineer. **Reading time:** 5 minutes.

## What you need running

| Service | Command | Port |
|---|---|---|
| Operator console (Streamlit) | `streamlit run services/operator-console/src/app.py` | 8501 |
| NTCIP controller emulator | `python3 scripts/ntcip_emulator.py --port 1611` | UDP 1611 |
| Demo pipeline (chamber + video) | `python3 -m simulation.demo --video <path> --site-config <yaml>` | 4444 (V2X), 9090 (Prometheus) |

Optional — only for the corresponding feature:

| Service | Command | When |
|---|---|---|
| GTFS-realtime synthetic feed | `python3 scripts/gtfs_synthetic_feed.py --port 5050 --delay 120` | Demo'ing transit signal priority |
| MQTT broker (Mosquitto) | `brew install mosquitto && mosquitto` (mac) | Demo'ing multi-intersection green wave |

## Five-minute live demo flow

### 1. Boot (30 s before audience arrives)

```bash
# Terminal 1
streamlit run services/operator-console/src/app.py
# → open http://localhost:8501 in browser, position on left half of screen

# Terminal 2
python3 scripts/ntcip_emulator.py --port 1611
# → position log on right half so audience sees real NTCIP packets arriving
```

### 2. Walkthrough script (4 min)

#### Step A — start the pipeline (30 s)

```bash
# Terminal 3
python3 -m simulation.demo \
    --video videos/youtube_MNn9qKG2UFI_full.mp4 \
    --site-config services/observability/example-intersection.yaml \
    --show \
    --save-video docs/demos/recordings/live.mp4
```

**Say:** "This is the chamber booting from a single YAML config. Every per-intersection knob — camera calibration, NTCIP target, MQTT broker, audit storage — comes from this file. Production deployment is just edit-config + restart."

#### Step B — point at the HUD + virtual signal heads on the live video window (45 s)

Top-left of the OpenCV preview shows:
```
NORTH_SOUTH  >>  GREEN
mode: adaptive  |  dominant: emission_cost
```

Top-right of the OpenCV preview shows two **virtual 3-light traffic signals** (N-S and E-W). The signal corresponding to the chamber's commanded direction shows GREEN; the other shows RED. Active lights have a soft glow.

**Say:** "The HUD tells you what the AI's decision is. The two signal heads show that same decision the way a driver would see it — red for blocked, green for served. Watch — when east-west's CO₂ rate gets high enough to outweigh the current direction, both the HUD label and the signal heads will switch simultaneously."

This makes the recording self-contained. A stakeholder can watch the mp4 standalone and immediately see what the AI is commanding — no operator console needed in parallel.

#### Step C — operator console panels (1 min)

Walk left-to-right through the console:

1. **Top banner** — `trained:dvm_car_v1` brand classifier, `adaptive` mode badge.
2. **Per-direction cards** — vehicle counts + brand mix + dual CO₂ (with and without brand multipliers).
3. **AI Decision Chamber panel** — 6-layer reasoning trace, priority bars (winner highlighted green), full justification text.
4. **Closed-loop NTCIP** — "Commanded: north_south | Actual: north_south | in sync ✓". *If you see "DIVERGE" — that's the chamber detecting the controller didn't honour the request.*
5. **Transit Signal Priority** — empty unless GTFS feed is on; if running, shows which routes are requesting priority.
6. **Detector + protocol coverage** — green chips for live sources (operator, visual lightbar, V2X SRM, audio siren, button ped, vision ped); grey for inactive.
7. **Operator controls** — three buttons for live demo actions.

#### Step D — interactive demo (2 min)

Do these IN ORDER, leaving a few seconds between each so the audience can watch the chamber react:

**1. Pedestrian request:**
- In console: pick "east_west" from "Direction needing crossing", click "Request pedestrian phase"
- **Watch:** within 2 sec the chamber's dominant factor changes to `pedestrian_demand`, phase switches to east_west, ped phase locks for ~19 s (MUTCD walk + clearance)
- **Say:** "Pedestrians are a hard constraint, not a soft signal. Once the demand is registered the chamber forces the phase change and won't release until MUTCD walk + clearance timers complete — even if a hundred vehicles queue on the other approach."

**2. V2X emergency vehicle:**
```bash
# Terminal 4
python3 scripts/v2x_srm_sender.py --phase 4 --type preempt --vehicle-id 911
```
- **Watch:** chamber mode flips to `preempt` (red badge in console), commanded phase locks to east_west, NTCIP emulator logs new SET-REQUEST packets
- **Say:** "That's a real J2735 SAE Signal Request Message — same wire format an ambulance's V2X transmitter would emit. The chamber treats V2X SRM as Layer 1 preemption, bypassing all optimization."

**3. Clear and continue:**
- In console: click "Clear all signals"
- Chamber returns to adaptive mode within 2 sec

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Console shows "Waiting for demo state" | Pipeline not running OR `/tmp/atms-demo-state.json` not being written | Verify Terminal 3 demo is alive + check `/tmp/atms-demo-state.json` is updating |
| Closed-loop shows "DIVERGE" persistently | NTCIP emulator not running OR firewall blocking UDP 1611 | Restart emulator; check `nc -u -l 1611` accepts connections |
| Audio siren badge stays grey | `sounddevice` not installed; mic-driven detector inactive | `pip install --break-system-packages sounddevice` |
| Operator console panels empty | State JSON was written before chamber was integrated (old format) | Stop & restart the pipeline |
| V2X SRM sender "address already in use" | Detector + sender both binding 4444 | Sender uses ephemeral port; detector listens. If error → restart pipeline |
| Mesh chip stays grey | No MQTT broker reachable at `mqtt.broker_host` in YAML | Either start broker OR leave `broker_host: ""` to disable mesh |

## File and port inventory

- **State JSON:** `/tmp/atms-demo-state.json` (chamber writes; console polls at 2 Hz)
- **Operator override file:** `/tmp/atms-operator-override.json` (operator console writes; chamber's `OperatorOverrideDetector` polls)
- **Pedestrian button file:** `/tmp/atms-ped-button.json` (same pattern)
- **Audit DB:** path from site config `audit.db_path`, default `/tmp/atms-chamber-audit.db`
- **Audit JSONL fallback:** `/tmp/atms-chamber-audit.jsonl` (only when `audit.db_path` is empty)
- **Annotated recordings:**
  - `docs/demos/recordings/final_youtube_demo_signals.mp4` (5 min, 1 GB) — HUD + virtual signal heads baked in, suitable for standalone stakeholder review
  - `docs/demos/recordings/test_with_chamber_hud.mp4` (28 s, 66 MB) — short version for quick previews

## Production deployment cheatsheet

```bash
# Per-intersection setup (operations engineer, once):
sudo mkdir -p /etc/atms /var/lib/atms /var/log/atms
sudo cp services/observability/example-intersection.yaml \
    /etc/atms/intersection-005.yaml
sudo vim /etc/atms/intersection-005.yaml
# Fill in:
#   intersection_id, description
#   camera.pixels_per_meter (from calibration survey)
#   camera.source (RTSP URL of the live camera)
#   crosswalk_zones (from site survey, pixel coords)
#   ntcip.controller_host + community (from controller config)
#   mqtt.broker_host (from city ops; leave empty for standalone)
#   transit_priority.feed_url + routes (from transit agency API + survey)
#   audit.db_path = /var/lib/atms/intersection-005-audit.db
#   prometheus.listen_port (default 9090)

# Run as a systemd unit:
sudo systemctl enable atms-chamber@intersection-005
sudo systemctl start atms-chamber@intersection-005
```

(`systemd` unit template not shipped here — pilot operations writes per their local conventions; the command is just `python3 -m simulation.demo --video <RTSP> --site-config /etc/atms/intersection-005.yaml`.)
