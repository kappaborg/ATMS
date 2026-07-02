# ATMS Traffic System - Helm Chart

The chart renders a Deployment + Service (and HPA where autoscaling is
enabled) for each of the 9 services in `values.yaml`. Secrets are NOT
templated: pods read `postgres.password` / `jwt.secret` from the
SOPS-materialised `atms-secrets` Secret (ADR-0002) — apply the
environment overlay (`kubectl apply -k k8s/overlays/<env>/`) or create
the Secret before installing, or pods start without credentials.

Validate locally with `helm lint helm/atms-traffic-system` and
`helm template atms helm/atms-traffic-system`.

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

