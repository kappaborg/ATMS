# KJP "Park" Sarajevo — ATMS Pilot Handoff Package

**Audience:** KJP operations engineering team (commissioning + sustaining ops).
**Scope:** Everything needed to take the ATMS pilot from "code complete" to "running in production at Marijin Dvor".
**Status:** Handoff-ready as of Phase 11.

## 1. Systemd unit templates

The chamber + supporting services run as systemd units. Templates below; KJP ops should drop into `/etc/systemd/system/` and `systemctl enable + start` each.

### 1.1 — atms-chamber@.service (per-intersection)

```ini
[Unit]
Description=ATMS Decision Chamber — %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=atms
Group=atms
WorkingDirectory=/opt/atms/current
EnvironmentFile=/etc/atms/secrets.env
ExecStart=/usr/bin/python3 -m simulation.demo \
    --site-config /etc/atms/%i.yaml \
    --video ${ATMS_CAMERA_RTSP_%i}
Restart=on-failure
RestartSec=10
StandardOutput=append:/var/log/atms/chamber-%i.log
StandardError=append:/var/log/atms/chamber-%i.err
# Resource limits — prevent runaway memory consumption
MemoryMax=4G
CPUQuota=200%
# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/atms /var/log/atms /tmp

[Install]
WantedBy=multi-user.target
```

Enable + start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable atms-chamber@sarajevo-marijindvor-001.service
sudo systemctl start  atms-chamber@sarajevo-marijindvor-001.service
sudo systemctl status atms-chamber@sarajevo-marijindvor-001.service
```

### 1.2 — atms-operator-console.service

```ini
[Unit]
Description=ATMS Operator Console (Streamlit)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=atms
Group=atms
WorkingDirectory=/opt/atms/current
ExecStart=/usr/bin/streamlit run services/operator-console/src/app.py \
    --server.address 127.0.0.1 \
    --server.port 8501 \
    --server.headless true
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/atms/console.log

[Install]
WantedBy=multi-user.target
```

### 1.3 — atms-overview-console.service (corridor view)

```ini
[Unit]
Description=ATMS Multi-Intersection Overview
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=atms
Group=atms
WorkingDirectory=/opt/atms/current
Environment="ATMS_OVERVIEW_BROKER=mqtt.atms.kjp.local"
Environment="ATMS_OVERVIEW_INTERSECTIONS=sarajevo-marijindvor-001,sarajevo-hiseta-002,sarajevo-pofalici-003,sarajevo-skenderija-004"
ExecStart=/usr/bin/streamlit run services/operator-console/src/overview_app.py \
    --server.address 127.0.0.1 \
    --server.port 8502 \
    --server.headless true
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/atms/overview.log

[Install]
WantedBy=multi-user.target
```

### 1.4 — atms-audit-forwarder.timer + service (periodic)

```ini
# /etc/systemd/system/atms-audit-forwarder.timer
[Unit]
Description=Forward audit DB rotations to TimescaleDB every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/atms-audit-forwarder.service
[Unit]
Description=ATMS audit forwarder
After=network-online.target

[Service]
Type=oneshot
User=atms
Group=atms
WorkingDirectory=/opt/atms/current
EnvironmentFile=/etc/atms/secrets.env
ExecStart=/usr/bin/python3 -m simulation.decision_chamber.audit_forwarder \
    --intersection-id sarajevo-marijindvor-001 \
    --dsn ${ATMS_TIMESCALE_DSN} \
    --rotated-dir /var/lib/atms \
    --cold-tier-bucket s3://atms-archive-sarajevo/ \
    --local-quota-bytes 10737418240
StandardOutput=append:/var/log/atms/forwarder.log
```

## 2. Secrets file template

`/etc/atms/secrets.env` (mode 0600, owned by atms:atms):

```bash
# NTCIP-1202 SNMPv3 credentials — from KJP secrets manager
ATMS_NTCIP_AUTH_KEY=<32+ char passphrase>
ATMS_NTCIP_PRIV_KEY=<32+ char passphrase>

# MQTT broker auth (when enabled)
ATMS_MQTT_USERNAME=atms-chamber-sarajevo
ATMS_MQTT_PASSWORD=<broker secret>

# TimescaleDB DSN for audit archive
ATMS_TIMESCALE_DSN=postgresql://atms_writer:<pwd>@timescale.kjp.local:5432/atms_audit

# AWS S3 cold tier (if used) — KJP ops decides
AWS_ACCESS_KEY_ID=<...>
AWS_SECRET_ACCESS_KEY=<...>
AWS_DEFAULT_REGION=eu-central-1

# Per-intersection RTSP URLs — assigned at install time
ATMS_CAMERA_RTSP_sarajevo-marijindvor-001=rtsp://10.42.10.5:554/Streaming/Channels/101
ATMS_CAMERA_RTSP_sarajevo-hiseta-002=rtsp://10.42.20.5:554/Streaming/Channels/101
```

## 3. Operations runbook quick-reference

| What | Command |
|---|---|
| Check chamber status | `sudo systemctl status atms-chamber@sarajevo-marijindvor-001` |
| View live chamber log | `journalctl -fu atms-chamber@sarajevo-marijindvor-001` |
| Restart chamber | `sudo systemctl restart atms-chamber@sarajevo-marijindvor-001` |
| Stop for maintenance | `sudo systemctl stop atms-chamber@sarajevo-marijindvor-001` (controller falls back to fixed-time) |
| Verify NTCIP closed-loop | `curl http://localhost:9090/metrics | grep controller_divergence` |
| Force pedestrian phase | Operator console → "Request pedestrian phase" |
| Force emergency preempt | Operator console → "Force emergency preempt" OR `python3 scripts/v2x_srm_sender.py --phase 4 --type preempt` |
| Replay decision | `python3 scripts/audit_replay.py --db /var/lib/atms/sarajevo-marijindvor-001.db --decision-id <id>` |
| Run acceptance tests | `python3 scripts/pilot_acceptance_tests.py --site-config /etc/atms/sarajevo-marijindvor-001.yaml` |
| Run failover tests | `python3 scripts/failover_tests.py --output-report /var/log/atms/failover-$(date +%F).md` |

## 4. Monitoring + alerting

### Prometheus alerts (drop into `/etc/prometheus/atms-alerts.yml`)

```yaml
groups:
- name: atms-pilot
  rules:
  - alert: ATMSChamberControllerDivergent
    expr: increase(atms_chamber_controller_divergence_total[5m]) > 0
    for: 1m
    labels:
      severity: page
    annotations:
      summary: "Chamber {{ $labels.intersection }} commanded != controller actual phase"
      description: "Possible controller fallback. Check NTCIP connectivity."

  - alert: ATMSSceneChange
    expr: atms_scene_change_alert_active > 0
    for: 5m
    labels:
      severity: ticket
    annotations:
      summary: "Camera scene shifted at {{ $labels.intersection }}"
      description: "Homography may be invalid. Re-run scripts/calibrate_camera_homography.py"

  - alert: ATMSAuditForwardLag
    expr: atms_audit_forward_lag_seconds > 3600
    for: 30m
    labels:
      severity: page
    annotations:
      summary: "Audit forwarding behind by >1h at {{ $labels.intersection }}"
      description: "TimescaleDB likely down. Local archive growing — check disk."

  - alert: ATMSChamberDown
    expr: up{job="atms-chamber"} == 0
    for: 1m
    labels:
      severity: page
    annotations:
      summary: "Chamber process down at {{ $labels.intersection }}"
      description: "Controller has fallen back to fixed-time. Restart chamber + investigate logs."
```

### Grafana

Import `services/observability/grafana-chamber-dashboard.json` and add the
intersection list as the dashboard's `$intersection` template values.

## 5. Emergency contacts

| Role | Responsibility |
|---|---|
| KJP Engineering Duty | Chamber crash, controller divergence — page via ops on-call |
| KS Ministarstvo prometa Tech Lead | Pilot scope changes, regulatory escalations |
| GRAS Dispatch | TSP integration issues |
| KJP Networks | NTCIP / MQTT / TimescaleDB connectivity |

## 6. Cutover criteria

Before flipping chamber from shadow → enforcing mode:

- [ ] All 7 failover scenarios pass (`scripts/failover_tests.py`)
- [ ] All 11 pilot acceptance tests pass (`scripts/pilot_acceptance_tests.py`)
- [ ] 30-day shadow run with controller divergence < 1% of ticks
- [ ] Bosnian-locale operator UI accepted by Kanton Sarajevo
- [ ] KS Ministarstvo prometa signed authority for NTCIP write
- [ ] KJP Networks confirmed sustained MQTT + Timescale connectivity
- [ ] On-call rotation established
- [ ] Operations runbook (this document) reviewed by KJP duty engineers
- [ ] Rollback procedure tested in lab
- [ ] Insurance / liability framework confirmed by KS legal

## 7. Out-of-scope (Phase 12+ work — not blocking pilot)

- CI/CD pipeline for ongoing updates (KJP ops team typically owns this with their existing tooling)
- Banja Luka second-city replication
- BiH-specific brand model (`dvm_car_v2_bih`) — runs after 5000+ ground-truth labels collected
- TSP integration once GRAS GTFS-RT feed comes online (planned 2025)
- Multi-intersection green wave activation along Hiseta corridor (after Marijin Dvor stable for 60 days)
