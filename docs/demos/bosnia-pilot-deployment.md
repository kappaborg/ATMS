# ATMS — Bosnia (Sarajevo) Pilot Deployment Guide

**Audience:** KS Ministarstvo prometa technical lead + KJP "Park" operations engineer. **Reading time:** 8 min.

## Pilot scope

- **Location:** Marijin Dvor intersection (Hiseta × Trg BiH), Centar district, Sarajevo
- **Phase 1:** single intersection in adaptive mode with NTCIP-1202 closed-loop integration
- **Phase 2:** arterial corridor (4 intersections: Marijin Dvor → Hiseta → Pofalići → Skenderija) with MQTT green wave coordination
- **Phase 3:** GRAS transit signal priority integration when GTFS-realtime feed comes online (planned 2025 per Kanton Sarajevo Smart City roadmap)

## What's already done (Phase 1-5 system handoff)

| | |
|---|---|
| Decision chamber (16 modules, 3938 LoC) | All 6 layers production-grade |
| Real protocols at every boundary | NTCIP-1202, V2X J2735 SRM, MQTT, GTFS-RT, Prometheus, SQLite |
| Bosnia fleet emission overlay | `services/observability/bosnia-fleet-multipliers.yaml` |
| Sarajevo site config template | `services/observability/sarajevo-pilot.yaml` |
| Operator console Bosnian localization | `services/operator-console/src/locales.py` (bs locale) |
| Demo recordings with HUD + virtual signal heads | `docs/demos/recordings/*.mp4` |

## What pilot ops needs to do (site-specific configuration)

The Sarajevo template (`services/observability/sarajevo-pilot.yaml`) has TBD placeholders. Each TBD maps to a real operations task:

### 1. Camera survey (1 day, 1 surveyor)

- **`camera.pixels_per_meter`** — Mark two points in the intersection with known real-world distance (e.g., painted lane markings 3.5 m apart at the stop bar). Measure the pixel distance in the camera frame. `pixels_per_meter = pixel_distance / 3.5`.
- **`camera.source`** — The RTSP URL the installer publishes. Verify with `ffprobe rtsp://10.42.10.5:554/Streaming/Channels/101`.
- **`camera.width`, `camera.height`** — Match the camera's native resolution.
- **`crosswalk_zones`** — In the same frame, identify the pixel coords of each crosswalk's outer rectangle (where pedestrians wait + cross). Capture as `[x1, y1, x2, y2]` per direction.

### 2. NTCIP commissioning (2 days, KJP technician + installer)

- **`ntcip.controller_host`** — Static IP assigned to the Swarco/Yunex controller by KJP networks team.
- **`ntcip.community`** — SNMPv1 community string. KJP convention `sarajevo-pilot-readwrite` placeholder; replace per ops policy.
- **`ntcip.closed_loop_poll_seconds`** — Default 1.5 s is appropriate for adaptive control. KJP may prefer 3-5 s to reduce SNMP traffic on shared ops LAN.
- **Verify NTCIP-1202 compliance** — Swarco MX-PRO and Yunex Sitraffic sX confirmed compliant; older Marvell legacy boxes may need replacement.
- **Phase 2 swap to SNMPv3** — see Phase 6 backend (ATMS-CHAMBER ADR-0023, pending).

### 3. GRAS coordination for TSP (2 days, Kanton Sarajevo IT)

- **`transit_priority.feed_url`** — GRAS GTFS-realtime endpoint when published (planned `api.smartsarajevo.ba/gras/realtime/vehiclepositions`).
- **`transit_priority.routes`** — Map each GRAS route arriving at Marijin Dvor to its approach direction. Best source: GRAS dispatch + on-site observation. Initial estimate from public schedules:
  ```yaml
  routes:
    trolejbus-103: north_south    # Otoka — Vijećnica
    trolejbus-105: east_west      # Dobrinja — Vijećnica
    autobus-31E:   north_south    # Hrasno — Vijećnica
    autobus-32:    east_west      # Skenderija — Pofalići
  ```
- **`delay_threshold_s: 90`** — GRAS schedule precision is ~1 minute. Buses behind by 90 s warrant priority. Adjust per operations.

### 4. Audit + observability infrastructure (1 day, KJP networks)

- **`audit.db_path`** — Persistent volume on the edge node. Suggest `/var/lib/atms/sarajevo-marijindvor-001.db`. Mount must be ≥ 5 GB.
- **`audit.retention_days: 180`** — Twice the global default. KS Ministarstvo prometa may require longer for incident replay.
- **`prometheus.listen_port: 9090`** — Standard. Add corresponding scrape config to KJP central Prometheus.
- **Grafana dashboard import** — Use `services/observability/grafana-chamber-dashboard.json`. The `intersection` template variable will populate from the metrics labels.

### 5. Operator console deployment (0.5 day, ops engineer)

- Host the Streamlit app on an internal Kanton Sarajevo server reachable from the KJP operations centre.
- Locale defaults to Bosnian (`bs`) via the site config's `region.operator_locale: bs`. UI strings auto-translate: "AI Karar Odası", "Pješački zahtjev", "Hitno preuzimanje", "RASKORAK (3 otkucaja)", etc.
- Authentication: deploy behind Kanton Sarajevo SSO (Keycloak) using nginx auth_request gateway. Streamlit itself is unauthenticated.

## Bosnia-specific emission accounting

The fleet multiplier overlay (`bosnia-fleet-multipliers.yaml`) accounts for BiH's older imported fleet:

| Brand | Default (UK) | Bosnia | Δ% | Reason |
|---|---:|---:|---:|---|
| volkswagen | 1.00 | 1.10 | +10% | Older TDI import share |
| audi | 1.10 | 1.20 | +9% | Premium-old TDI imports |
| bmw | 1.10 | 1.20 | +9% | Older 3/5-series CDI imports |
| mercedes-benz | 1.10 | 1.20 | +9% | Same as BMW |
| fiat | 0.90 | 1.00 | +11% | Older diesels in fleet |
| citroen | 0.95 | 1.05 | +11% | Older HDi diesels |
| peugeot | 0.95 | 1.05 | +11% | Same as Citroen |
| dacia | 1.00 | 0.95 | -5% | Newer + efficient (Renault subsidiary) |
| **zastava** | (new) | **1.40** | n/a | Yugo-era 1980s-90s tech |
| **lada** | (new) | **1.35** | n/a | Russian imports, lower efficiency |
| **yugo** | (new) | **1.40** | n/a | Same as Zastava (telemetry distinction) |

Calibration source: EEA EU fleet emission reports + BiH Federation Statistical Office vehicle registrations. **Refresh annually** as fleet renewal progresses (BiH fleet average age was 16 years in 2024; expected to drop to ~13 years by 2027).

## Live demo commands (for technical evaluation)

```bash
# On a Sarajevo edge node — boots the chamber with all real protocols
# pointed at the per-intersection site config.
python3 -m simulation.demo \
    --video rtsp://10.42.10.5:554/Streaming/Channels/101 \
    --site-config /etc/atms/sarajevo-marijindvor-001.yaml \
    --show \
    --save-video /var/lib/atms/recordings/$(date +%Y%m%d-%H%M).mp4

# Boot output:
#   ✓ site config loaded: sarajevo-marijindvor-001
#     px/m=25.0  ntcip=10.42.10.10:161  mqtt=disabled
#     tsp=disabled  audit=sqlite  region=BA  locale=bs
```

Operator console at `http://atms-console.kjp.local:8501` displays:
- "AI Karar Odası" / "AI Komora Odluka" panel (locale-switched)
- "Sinhronizovano ✓" closed-loop badge when NTCIP read-back matches commanded phase
- "Pokrivenost detektora + protokola" coverage chips
- Three pilot operator buttons in Bosnian: "Zatraži pješačku fazu", "Pokreni hitno preuzimanje", "Obriši sve signale"

## Acceptance criteria for Phase 1 cutover

Before going live from shadow mode to enforcement:

- [ ] 30-day shadow run with chamber commands logged but not enforced — measure controller divergence count (target: <1% of ticks)
- [ ] Operator-labelled 500-vehicle ground truth set on Sarajevo footage — brand model precision ≥ 60% (current dvm_car_v1 baseline: 66.7% on UK ground truth; revalidate with BiH fleet distribution)
- [ ] NTCIP failover test — chamber process killed mid-cycle; controller falls back to fixed-time within 5 s
- [ ] MQTT broker failover test — broker offline; chamber continues standalone with no decision degradation
- [ ] Pedestrian phase MUTCD compliance audit — measured walk + clearance ≥ Vienna Convention minimums (typically 4 s + crossing_distance/1.0 m/s)
- [ ] Audit DB rotation + retention validated — fill DB to max_size, verify rotation, verify 180-day delete
- [ ] Grafana dashboard imported + Prometheus scrape verified at KJP NOC
- [ ] Bosnian-locale UI accepted by Kanton Sarajevo operators

## Phase 2-3 expansion (post-pilot success)

| Track | Trigger | Effort |
|---|---|---|
| Arterial coordination — Hiseta corridor | Marijin Dvor stable for 60 days | 2 weeks (MQTT broker + 3 more controllers + green wave offset calibration) |
| GRAS TSP integration | Kanton Sarajevo publishes GTFS-RT endpoint | 1 week (route-direction mapping + bonus tuning) |
| BiH-trained brand model | 5000-vehicle BiH ground truth collected | 3 weeks (data + training + A/B vs dvm_car_v1) |
| Banja Luka second-city pilot | Sarajevo cutover successful | 4 weeks (replicate stack per intersection) |

## Open items for KS Ministarstvo prometa

1. Confirm authority for NTCIP write-access on KJP's operational controllers (chamber sends advisory SET-REQUESTs — needs ministerial sign-off per BiH road safety code)
2. Confirm pedestrian phase parameters per BiH Vienna Convention interpretation (walking speed 1.0 m/s vs 1.2 m/s, minimum walk time)
3. Confirm GRAS schedule data sharing agreement for TSP — direct AVL feed acceptable as interim until GTFS-RT lands
4. Confirm Kanton Sarajevo Smart City roadmap timeline (relevant for Phase 2 arterial expansion + GRAS feed timing)
