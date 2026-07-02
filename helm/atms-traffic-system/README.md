# ATMS Traffic System - Helm Chart

> ⚠️ **THIS CHART IS NOT FUNCTIONAL.** `templates/` is empty, so
> `helm install` creates **zero resources** — the commands below will
> "succeed" while deploying nothing. Until templates are authored
> (tracked in docs/PRODUCTION_GAPS.md), deploy with
> `kubectl apply -k k8s/overlays/<env>/` instead.

## Installation

```bash
# Install the chart
helm install atms-traffic-system ./helm/atms-traffic-system \
  --namespace atms-system \
  --create-namespace

# Upgrade
helm upgrade atms-traffic-system ./helm/atms-traffic-system \
  --namespace atms-system

# Uninstall
helm uninstall atms-traffic-system --namespace atms-system
```

## Configuration

See `values.yaml` for all configurable parameters.

## Dependencies

- Kafka (external or via Helm)
- Redis (external or via Helm)
- PostgreSQL (external or via Helm)
- Prometheus Operator (for ServiceMonitor)

