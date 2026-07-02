# Demo runbook: 30-minute pilot pitch

**Audience:** Traffic authority / municipal stakeholder evaluating ATMS for a pilot intersection.
**Goal:** Prove the system is real, runs end-to-end, and degrades safely.
**Duration:** 30 minutes total (~25 demo + ~5 Q&A).
**Stack:** [`docker-compose.demo.yml`](../../docker-compose.demo.yml) + [`simulation/scenarios/demo/`](../../simulation/scenarios/demo/) + [`simulation/demo/`](../../simulation/demo/) orchestrator.

---

## 0. One-time machine setup

### macOS

```bash
# 1) SUMO Python bindings (use python3 -m pip, NOT bare pip)
python3 -m pip install --break-system-packages eclipse-sumo traci sumolib

# 2) X11 server — required for sumo-gui only. The eclipse-sumo wheel for
#    macOS builds sumo-gui against the FOX toolkit, which needs X11.
brew install --cask xquartz
# Log out + back in once so $DISPLAY gets set. Test with:
sumo-gui --help | head -1   # should print "Usage: sumo-gui ..."

# 3) Confirm both python3 and pip point at the same Python:
python3 -c "import sys; print(sys.executable)"
python3 -m pip --version   # the path should mention the same Python version
```

If you skip XQuartz, the headless mode (`python3 -m simulation.demo` with no flags) still runs the full scripted timeline — vehicles just don't render on screen. For most non-visual demos (executive Q&A, technical deep-dive) the headless cue stream + the live Grafana dashboard is sufficient.

### Linux

```bash
sudo apt-get install -y sumo sumo-tools sumo-doc
python3 -m pip install --break-system-packages eclipse-sumo traci sumolib
```

No X11 setup needed — most Linux desktop environments already have it.

---

## 0.4 Real video vs. SUMO simulation — choose your data source

The demo orchestrator has two modes:

| Mode | Vehicles are... | When to use |
|---|---|---|
| **SUMO** (default) — `python3 -m simulation.demo --gui` | spawned by a physics simulator | Scripted-event demos (failsafe drill, EV preempt, ped call). Repeatable. |
| **Real video** — `python3 -m simulation.demo --video videos/TEST.mp4` | **detected from actual traffic footage** by YOLOv8 | Showing "this works on real cameras." Emission numbers are derived from genuine detections. |

Both modes write the same `/tmp/atms-demo-state.json` and render identically in the Streamlit operator console. Switch between them by changing one command.

**Real-video mode requires** (already on most dev machines after the SE322 work):
- `ultralytics` (YOLOv8 — installed via `pip install --break-system-packages ultralytics`)
- `opencv-python` (frame I/O)
- A trained model at `models/yolov8n.pt` (in the repo)

Sample videos in the repo:
- `videos/TEST.mp4` — short test clip
- `videos/T1.mp4`, `videos/T2.mp4` — additional test footage
- `Processed_Videos/youtube_*.mp4` — YouTube intersection footage

Pass `--show` to also open an OpenCV preview window with per-vehicle bounding boxes + speed + emission overlay. Pass `--pixels-per-meter N` to tune speed estimation for the specific camera angle (default 8.0; increase for tighter shots, decrease for wide-angle).

**Brand identification — two model choices:**

```bash
# Default: small trained YOLO model. 13 brand classes (BMW, Toyota, Mercedes,
# Honda, Kia, MG, Mazda, Nissan, Skoda, fiat, BYD, hyundai, +generic). Fast
# per inference but narrow coverage.
python3 -m simulation.demo --video videos/TEST.mp4

# CLIP zero-shot. 65+ brand prompts (Tesla, Porsche, VW, Ford, Volvo,
# Polestar, Rivian, ...). Broader coverage, comparable wall-clock when
# throttled (cache hits more often because CLIP softmax confidences are
# higher than the trained model's). Downloads ~600 MB CLIP from HuggingFace
# on first use.
python3 -m simulation.demo --video videos/TEST.mp4 --brand-model clip

# Disable brand identification entirely (fastest)
python3 -m simulation.demo --video videos/TEST.mp4 --brand-weights ''
```

Speed knobs:
- `--frame-skip 5` (default 3): process every Nth frame; 3x speedup with no perceptible visual loss.
- `--brand-model clip` for broader coverage; trained for narrower-but-faster.
- `--runtime auto|onnx|pytorch` (default `auto`): ONNX with CoreML execution provider is ~1.5x faster than PyTorch on Apple Silicon. `auto` picks ONNX if a `.onnx` file exists alongside the `.pt`.

**Threshold tuning for wide-angle traffic footage.** The defaults (`--brand-conf 0.30 --brand-margin 0.05 --brand-vote-min-count 3`) follow ADR-0020's "right or absent" principle — strict commits, never confidently wrong. On a typical YouTube traffic clip (1080p, vehicles ~50-150 px wide), CLIP confidences sit around 0.15-0.25 per brand, which falls below those defaults. Two recipes for inspection runs:

```bash
# Inspection mode: see what CLIP would label every vehicle
python3 -m simulation.demo --video <path> --brand-model clip \
  --brand-conf 0.12 --brand-margin 0.0 \
  --brand-vote-min-count 1 --brand-vote-min-total 0.10

# Strict / production: only commit high-confidence brands
python3 -m simulation.demo --video <path> --brand-model clip
```

**Downloading test footage.** Use `scripts/download_test_video.sh <YouTube URL> [start_sec] [end_sec]` to grab a clip:

```bash
# Full video
./scripts/download_test_video.sh 'https://youtu.be/MNn9qKG2UFI'

# Trim to 60 seconds starting at 0:30
./scripts/download_test_video.sh 'https://youtu.be/MNn9qKG2UFI' 30 90
```

The script picks the best mp4 ≤1080p (4K is overkill — YOLOv8n downsamples to 640 internally) and trims via ffmpeg. Output goes to `videos/`.

---

## 0.5 The operator console (optional but recommended for non-technical audiences)

The new Streamlit operator console at `services/operator-console/` gives you a polished visual that's much friendlier to non-technical audiences than sumo-gui:

- Big colour-coded **failsafe mode tile** (green / amber / red)
- Per-direction cards showing **vehicles, speed, average CO₂ g/km, instantaneous CO₂ g/min**
- Total intersection CO₂ rate
- Scrolling recent-events feed
- Polls `/tmp/atms-demo-state.json` at 2 Hz — auto-updates as the demo progresses

**Run it:**

```bash
# Terminal 1: install once, then launch
python3 -m pip install --break-system-packages streamlit
streamlit run services/operator-console/src/app.py
# Opens http://localhost:8501

# Terminal 2: start the demo
python3 -m simulation.demo            # or --gui to also show SUMO
```

The console shows "waiting for demo" until the orchestrator writes its first state-tick. Once data appears, both panes update together — the orchestrator drives SUMO + emits state; the console renders it.

---

## 1. Pre-flight (do this 30 minutes before the demo)

1. **Cold start the stack.**
   ```bash
   docker compose \
     -f docker-compose.dev.yml \
     -f docker-compose.services.yml \
     -f docker-compose.keycloak.yml \
     -f docker-compose.demo.yml \
     up -d
   ```
2. **Wait ~60 s** for Kafka and Keycloak to settle (`docker compose ps` until everything is `healthy`).
3. **Smoke test each surface** the demo touches:
   ```bash
   curl -s http://localhost:8001/live   | jq .   # traffic-controller
   curl -s http://localhost:8007/live   | jq .   # decision-engine
   curl -s http://localhost:8009/live   | jq .   # v2x-interface
   curl -s http://localhost:3000/api/health      # Grafana
   curl -s http://localhost:3100/ready           # Loki
   ```
   All five should return 200. If any one is down, restart it (`docker compose restart <name>`) and re-test.
4. **Open three browser tabs**:
   - Grafana → "ATMS — Pilot Pitch Demo" dashboard (set refresh to **2s**)
   - Grafana → "ATMS — Failsafe Controller" dashboard (backup)
   - Loki Explore tab with query: `{service=~"traffic-controller|decision-engine|v2x-interface"} |~ "operator_action"`
5. **Open one terminal** with the orchestrator command ready to run (don't hit enter yet):
   ```bash
   DEMO_TOKEN="$(./scripts/mint-demo-token.sh engineer)" \
   python -m simulation.demo --gui --live
   ```
   (If the JWT minting script isn't on this machine, mint manually — see §3 below.)
6. **Pre-recorded fallback ready.** If wifi or Docker fails, switch to the screencast at `docs/demos/pilot-pitch-screencast.mp4`. Don't troubleshoot live.

---

## 2. The 30-minute flow

### 2.1 Architecture + safety posture (5 min)

**What you say:**
> "ATMS is a safety-first adaptive signal-control system. Before I show anything moving, three things to anchor on: first, an AI engine recommends signal phases. Second, a separate failsafe controller is the only thing that actually drives the signal — and it accepts the AI's recommendation only if a list of hard invariants holds. Third, when those invariants don't hold, the failsafe controller degrades to fixed-time or, if even that's unsafe, to all-red flash. The AI is **never** in the loop alone."

**What you show:** [STATUS_AND_PILOT_READINESS.md §2 (Safety Posture)](../STATUS_AND_PILOT_READINESS.md) — single page, on screen.

**Key talking points:**
- Conflict matrix encoded in code (`shared/atms_common/safety.py`); enforced by property-based tests.
- Min-green / min-yellow / max-red times come from RiLSA (EU) signal-timing standards, not invented locally.
- Time comparisons in the safety path use monotonic clocks only (ADR-0017) — wall-clock skew can't trip a min-green.

### 2.2 Live SUMO + Grafana (10 min)

**What you do:** Hit enter on the orchestrator. sumo-gui opens. The first audience cue prints at t=15s.

**What the audience sees:**
- A 4-way intersection with vehicles flowing on both axes (NS has ~50% more traffic).
- The signal head cycles dynamically as the AI balances directional pressure.
- The Grafana dashboard updates every 2s: mode tile, per-approach queue lengths, throughput, max-queue, **zero conflicts**.

**Key talking points (while the sim runs):**
- "The numbers you see on Grafana are computed from the same Kafka stream a real intersection would emit. There's no fake telemetry — the data path is identical to production."
- "The mode tile says `AI_ADAPTIVE`. That's the controller's authoritative view, not the AI's recommendation."
- "Every 2 seconds Grafana refreshes. If we change anything, you'll see it here."

### 2.3 EV preempt (5 min)

**Triggered at:** t=60s (auto-fired by the orchestrator timeline).

**Cue printed by the orchestrator:**
```
[ 1:00 ] V2X BSM injected. Controller arms preempt. Watch the EW signal
head — it gets green within the next intergreen window. Open Grafana panel
'Failsafe Mode' — show the audit-log line.
```

**What you say:**
> "A simulated emergency vehicle is approaching from the east. In a real deployment it would transmit a J2735 Basic Safety Message every 100 ms. Our v2x-interface validates it, extracts approach + vehicle class, and synthesises a PreemptRequest. The controller arms preempt, completes the current min-green, then transitions through yellow + all-red to give the EV's approach the green."

**What you show:**
- sumo-gui: the EV vehicle is the red one; it gets through the intersection without slowing.
- Grafana logs panel: the audit line `operator_action ... preempt_arm` appears.
- (Optional) Tempo: pull up the trace_id from the audit line and show the EV's request walking through v2x-interface → kafka → traffic-controller.

**Key talking points:**
- "The preempt is **arm-then-transition**, not instant. The controller refuses to skip the yellow phase. RiLSA rules apply even to EVs."
- "When pilot operators have V2X-equipped fleets, this becomes the dedicated EV channel. No vision-based siren detection is needed."

### 2.4 Pedestrian flow (3 min)

**Triggered at:** t=120s.

**What you say:**
> "A pedestrian button press. The controller registers the request — but doesn't immediately switch. It honours the current phase's min-green AND the minimum-walk time for the crossing direction. Safety is non-negotiable: a faster response would mean possibly stopping vehicles mid-block."

**What you show:** Grafana logs panel — the `ped_call` event arrives; the next phase transition includes the WALK indication; the WALK timer respects min-walk.

### 2.5 Failsafe drill (5 min) — the most important segment

**Triggered at:** t=180s.

**Cue printed by the orchestrator:**
```
[ 3:00 ] FAULT — controller will force ALL_RED_FLASH. This is the safety
floor. In production this fires on AI watchdog timeout, NTP loss, or a
hardware-fault read from NTCIP.
```

**What you say (slowly, this is the moment):**
> "In a moment the orchestrator will inject a simulated hardware fault. Watch three things: the Grafana mode tile, the signal head in sumo-gui, and the audit log."

**What happens:**
- Mode tile flips from green `AI_ADAPTIVE` to red `ALL_RED_FLASH`. Big visual change.
- All four signal heads in sumo-gui go flashing red.
- The audit log line `mode_transition reason=demo: simulated hardware fault` arrives.
- The vehicles stop. No one crosses the intersection until the fault clears.

**What you say (while it's red):**
> "This is the state where the AI is gone, the fixed-time fallback isn't trusted either, and the signal will not lift until a human commits to recover. There is no auto-recovery from this state. That's the safety floor — and it's the same code path whether the trigger is an AI watchdog timeout, an NTP-sync loss, or a real hardware fault read from NTCIP."

**Triggered at:** t=210s — orchestrator fires `recover`.
- Mode tile flips back to `AI_ADAPTIVE`.
- Traffic resumes; queues drain within ~30s.

**What you say:**
> "Operator acknowledged the fault, signed the recovery, intersection is back to normal. **Every step of this drill is in the audit log, signed by the operator's JWT principal.**"

### 2.6 Audit + privacy (2 min)

**What you show:**
- Loki search: `{service="traffic-controller"} |~ "operator_action"` — every action in the demo with `sub`, `jti`, `outcome`, `path`.
- One audit line, click the `trace_id` — Tempo opens the matching trace.
- `docs/runbooks/dsar.md` table of contents on screen (don't read it; just show it exists).

**What you say:**
> "Every operator action — preempt, ped-call, recover, mode-change — generates a JSON audit line. Every line correlates by trace_id to the underlying telemetry. License plates are never stored; they're HMAC-SHA256-hashed with a per-deployment salt so analytics queries work but the plate text can't be recovered. The full GDPR data-subject-access-request flow is wired and runbooked."

---

## 3. Minting a `DEMO_TOKEN`

For `--live` mode, the orchestrator needs an engineer-role JWT.

**Quick HS256 path (matches docker-compose.demo.yml defaults):**

```bash
python -c '
import jwt, time
secret = "demo-only-secret-32-chars-minimum-ok"
now = int(time.time())
for aud in ("atms-traffic-controller", "atms-decision-engine", "atms-v2x-interface"):
    tok = jwt.encode(
        {
            "iss": "atms-demo", "aud": aud, "sub": "demo-operator",
            "iat": now, "exp": now + 3600,
            "roles": ["engineer", "operator", "viewer"], "jti": f"demo-{aud}",
        }, secret, algorithm="HS256")
    print(f"export DEMO_TOKEN_{aud.replace(\"-\", \"_\").upper()}={tok}")
print(f"export DEMO_TOKEN={tok}")  # last one as default
'
```

Source the output in your shell, then run the orchestrator. The token is good for 1 hour.

**Keycloak path (when showcasing the OIDC flow):** see [`docs/runbooks/oidc-keycloak.md`](../runbooks/oidc-keycloak.md) §2.3.

---

## 4. Recovery — what to do if something fails mid-demo

| Symptom | Quick fix |
|---|---|
| sumo-gui won't start | Already running? `pkill -f sumo-gui` then retry. SUMO not installed? Switch to the screencast. |
| No vehicles in sumo-gui | The orchestrator is still in pre-loop. Wait ~3s; the sim window stays empty until the first vehicle departs at t=0. |
| Grafana shows no data | Prometheus / Loki is still bootstrapping. Wait 15s. If still empty, confirm the services are emitting: `docker logs atms-traffic-controller --tail 20`. |
| `(dry-run) would fire ...` in cue output | You forgot `--live`. Cancel (Ctrl-C), set `DEMO_TOKEN`, re-run with `--live`. |
| HTTP 401 from `--live` POSTs | Token expired or wrong audience. Re-mint per §3. |
| HTTP 403 from `--live` POSTs | Token has wrong roles. Demo expects `engineer`. |
| The ALL_RED_FLASH segment doesn't visibly stop traffic | Time-out, demo over. Hit Ctrl-C, talk through what *should* have happened, switch to the screencast for that segment. |

**Golden rule:** if the live demo stalls for >15 s, switch to the screencast. Don't troubleshoot in front of the audience.

---

## 5. After the demo

1. **Capture the run.** `docker compose logs > demo-run-$(date +%Y%m%d-%H%M).log` — useful for the follow-up email.
2. **Show the bench-readiness pack.** [STATUS_AND_PILOT_READINESS.md](../STATUS_AND_PILOT_READINESS.md) — open to the sign-off block. Walk the audience through what you need *from them* (open decisions from `docs/ROADMAP.md`).
3. **Hand off the artefacts.** A pre-built bundle to send:
   - This runbook
   - `docs/STATUS_AND_PILOT_READINESS.md`
   - `docs/ROADMAP.md`
   - The screencast (so they can re-watch and share internally)
   - List of the 19 ADRs in `docs/adr/` (the rationale package)

---

## 6. Variations

- **5-minute "wow"** — skip §2.1, §2.4, §2.6. Run only §2.2 (just enough to set context) → §2.5 (failsafe drill). The failsafe drill is the moment.
- **2-hour technical deep-dive** — run the full demo, then open `services/traffic-controller/tests/unit/test_safety_invariants.py` and step through the hypothesis property tests. Then open ADR-0005, ADR-0006, ADR-0017 and discuss each.
- **Pre-pilot dry run with operator's engineering team** — run the demo, then hand them the orchestrator and have *them* invent fault scenarios (`force_mode` with different reasons, alternative payloads). The orchestrator is data-driven; new scenarios are JSON edits.
