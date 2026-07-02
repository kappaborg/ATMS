# `infrastructure/observability/` — logs, traces, metrics

Phase B2 (tracing) and Phase B3 (logs) stack. Sits on top of Phase B1's structured logging + OTel propagation. See:

- [ADR-0010 — OpenTelemetry tracing](../../docs/adr/0010-opentelemetry-tracing.md)
- [ADR-0011 — Log aggregation](../../docs/adr/0011-log-aggregation-loki.md)

## Contents

```
infrastructure/observability/
├── README.md                              (this file)
├── loki/
│   ├── values.yaml                        Helm values for grafana/loki
│   └── alert-rules.yaml                   Loki alerting rules (LogQL)
├── promtail/
│   └── values.yaml                        Helm values for grafana/promtail
├── otel-collector/
│   └── values.yaml                        OTLP collector for traces
├── tempo/
│   └── values.yaml                        Tempo (trace TSDB)
└── grafana/
    └── dashboards/
        ├── atms-overview.json
        ├── failsafe-controller.json
        └── logs.json
```

## Install order (on-prem cluster)

```bash
# 1. Loki (the log TSDB).
helm upgrade --install loki grafana/loki -n observability \
    --create-namespace -f loki/values.yaml

# 2. Promtail (DaemonSet that scrapes pod stdout).
helm upgrade --install promtail grafana/promtail -n observability \
    -f promtail/values.yaml

# 3. Tempo (traces).
helm upgrade --install tempo grafana/tempo -n observability \
    -f tempo/values.yaml

# 4. OTel collector (receives OTLP from services, exports to Tempo).
helm upgrade --install otel-collector open-telemetry/opentelemetry-collector \
    -n observability -f otel-collector/values.yaml

# 5. Grafana (dashboards). Sidecar provisioner auto-loads JSON.
helm upgrade --install grafana grafana/grafana -n observability \
    --set sidecar.dashboards.enabled=true \
    --set-file 'sidecar.dashboards.label=grafana_dashboard'

# 6. Apply dashboards as ConfigMaps with the right label.
kubectl create configmap atms-grafana-dashboards \
    --from-file=grafana/dashboards/ \
    -n observability
kubectl label configmap atms-grafana-dashboards \
    grafana_dashboard=1 -n observability
```

## Verify the pipeline

```bash
# Tail logs landing in Loki for the controller (last 5 min).
kubectl exec -n observability deploy/loki -- \
    logcli query '{service="traffic-controller"}' --limit=50 --since=5m

# Open Grafana, switch to Explore → Loki:
#   {service="traffic-controller"} | json | line_format "{{.level}} {{.event}}"

# Click any line's `trace_id` link → Tempo opens the trace.
```

## Tuning per env

`values.yaml` in each subdir defaults to dev-friendly. Override per env via a
patch layered on top (Flux Kustomization), e.g. retention extension for prod.

## Outside this directory

- Service-side: log emission lives in `shared/atms_common/logging.py` and `shared/atms_common/tracing.py`. Don't add log forwarding inside services — Promtail handles it.
- Alert routing (PagerDuty, Slack): outside scope here; in `infrastructure/alertmanager/` once it ships.
