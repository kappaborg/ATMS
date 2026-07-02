# Monitoring Stack - Prometheus & Grafana

This directory contains all monitoring-related Docker configurations.

## Structure

```
monitoring/
├── docker-compose.yml          # Main compose file for monitoring stack
├── prometheus/
│   └── prometheus.yml          # Prometheus configuration
└── grafana/
    ├── dashboards/
    │   ├── dashboard.yml       # Dashboard provisioning config
    │   └── traffic-system-dashboard.json  # Dashboard definition
    └── datasources/
        └── prometheus.yml      # Prometheus datasource config
```

## Quick Start

```bash
# From docker/monitoring directory
cd docker/monitoring
docker-compose up -d

# Or from project root
cd docker/monitoring && docker-compose up -d
```

## Access

- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090

## Stop

```bash
cd docker/monitoring
docker-compose down
```

## Notes

- Prometheus scrapes metrics from `host.docker.internal:8004` (YouTube processor)
- For Linux, you may need to update `prometheus.yml` to use Docker bridge IP
- All configurations are automatically provisioned on startup
