# Runbook: Time synchronization (NTP + PTP)

**Audience:** SRE + edge-deployment team.
**Design:** [ADR-0017](../adr/0017-time-sync.md).
**Code:** [`shared/atms_common/timekeeping.py`](../../shared/atms_common/timekeeping.py).

---

## 1. Three-tier topology

| Tier | Scope | Source | Expected accuracy |
|------|-------|--------|-------------------|
| 1 | Cluster-wide | NTP (chrony) | ±5 ms |
| 2 | Edge subnet (camera ↔ edge ↔ controller) | PTP (linuxptp) | ±100 µs |
| 3 | In-process (safety path) | `time.monotonic_ns()` | guaranteed monotonic |

## 2. Cluster-wide NTP (Tier 1)

Every K8s node runs `chronyd` pointed at the operator's NTP servers.

### Install on a fresh node

```bash
sudo apt install -y chrony            # Debian/Ubuntu
sudo dnf install -y chrony            # RHEL family
```

`/etc/chrony/chrony.conf` (minimal):
```
pool ntp.atms-operator.example iburst maxsources 4
allow 10.0.0.0/8
driftfile /var/lib/chrony/chrony.drift
makestep 1.0 3
rtcsync
```

```bash
sudo systemctl enable --now chronyd
```

Verify:
```bash
chronyc tracking
# Look for: System time : <fraction> seconds [fast|slow] of NTP time
```

### Pod-side

The `ntp_sync_check` health check (see `shared/atms_common/timekeeping.py`) runs `chronyc tracking` inside the pod. K8s nodes inherit the host clock; the pod sees the same time. Failures here mean the **node**'s NTP is broken — log into the node, not the pod.

### Alerts

Prometheus rule (suggested):

```
- alert: HostNtpSkew
  expr: atms_ntp_skew_ms > 50
  for: 5m
  labels: {severity: warning, team: sre}
  annotations:
    summary: "Node NTP skew exceeds 50ms on {{ $labels.node }}"
```

## 3. PTP on the edge (Tier 2)

Required only for the C2 edge subnet. Requires hardware-stamped PTP NICs on the edge agent and cameras for sub-millisecond accuracy.

### Install linuxptp

```bash
sudo apt install -y linuxptp
```

### Boundary clock on the edge agent

`/etc/linuxptp/ptp4l.conf`:
```
[global]
twoStepFlag             1
slaveOnly               0
priority1               128
priority2               128
domainNumber            0
clockClass              248
clockAccuracy           0xFE
offsetScaledLogVariance 0xFFFF
free_running            0
freq_est_interval       1
delay_filter            moving_median
delay_filter_length     10
egressLatency           0
ingressLatency          0
boundary_clock_jbod     0
gmCapable               1
[eth0]
network_transport       UDPv4
delay_mechanism         E2E
```

Run:
```bash
sudo ptp4l -f /etc/linuxptp/ptp4l.conf -m
# In another shell, sync the system clock to the PHC:
sudo phc2sys -s eth0 -O 0 -m
```

Verify:
```bash
pmc -u -b 0 'GET CURRENT_DATA_SET'
# offsetFromMaster should be in single-digit µs once stabilised.
```

### Camera-side

Most IP cameras with PTP support enable it via web UI: Settings → Time → PTP → Slave. Set the same domain number as the boundary clock.

## 4. The in-process rule

Every comparison in the failsafe / decision-engine hot path uses `time.monotonic_ns()`. The wire schema (ADR-0005) uses `producer_timestamp_ns = monotonic_ns()`.

`time.time()` and `datetime.now()` are **forbidden** inside:

- `shared/atms_common/`
- `services/traffic-controller/src/`
- `services/decision-engine/src/`
- `services/sensor-fusion/src/`
- `services/ai-perception/src/`

A CI lint check enforces this (follow-up — script under `.github/workflows/ci.yml` `lint` job). The single exemption is `SyncedTimestamp.now()` internally; it's flagged with the comment `# safety-time-exempt`.

Allowed uses of wall-clock:
- Log formatting (handled by structlog timestamper outside the safety modules).
- `services/api-gateway/src/main.py` (operator-facing, not safety-critical).
- `services/dashboard/src/main.py` (presentation).
- `services/analytics/src/main.py` (post-hoc analysis).

## 5. Health checks

Every safety-critical service mounts `ntp_sync_check` on its `HealthRouter`. Edge services additionally mount `ptp_sync_check`. Skew above threshold → `/ready` returns 503 → K8s drains the pod.

Wire it up in a service's `main.py`:

```python
from shared.atms_common.timekeeping import (
    ntp_sync_check, ptp_sync_check, ntp_sync_probe, ptp_sync_probe, set_global_probe,
)

# Pick the probe matching the deployment tier.
if os.getenv("ATMS_EDGE_DEPLOYMENT", "0") == "1":
    set_global_probe(ptp_sync_probe)
    _health.add_check("ptp", ptp_sync_check(skew_threshold_us=500.0))
else:
    set_global_probe(ntp_sync_probe)
    _health.add_check("ntp", ntp_sync_check(skew_threshold_ms=50.0))
```

## 6. Multi-camera skew metric

`services/sensor-fusion/src/main.py` computes pairwise skew between cameras at the same intersection and emits `atms_camera_skew_ms{intersection_id,camera_a,camera_b}`. Alert when above 10 ms for > 1 minute.

## 7. Common incidents

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `/ready` returns 503, detail "ntp not synced" | chronyd not running on node | `systemctl restart chronyd` on the node |
| Skew jumps every 5–10 min | chrony makestep occurring; clock has been drifting | Reduce `makestep` interval or check upstream NTP reachability |
| All edge cameras show > 1 ms skew | PTP master not reaching cameras (firewall, VLAN) | Verify ptp4l can ping the cameras on PTP ports (319/320) |
| Decision-engine emits "future timestamp" rejections | Producer clock ahead of controller; NTP not synced on one side | Investigate per-node skew; restart chronyd |
| Sudden wholesale clock jump | Server crossed daylight-saving boundary | Convert all timestamps to UTC; the wire schema already uses UTC; this is a host config bug |
