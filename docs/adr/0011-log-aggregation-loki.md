# ADR-0011: Log aggregation — Loki + Promtail + Grafana

**Status:** Accepted
**Date:** 2026-05-30
**Closes:** PRODUCTION_GAPS.md gap #8 (Phase B3)

## Context

B1 added JSON via structlog. B2 added `trace_id` / `span_id` to every line. The remaining piece: ship those lines off the pod and make them queryable.

Per ADR-0003 we run on-prem Kubernetes with a small ops team. The senior-engineer prompt allows ELK if already in infra, otherwise Loki. There is no existing ELK; Loki is the simpler stack.

## Decision

### Pipeline

```
Service (stdout, JSON)
    └─ Container runtime captures stdout/stderr
       └─ Promtail DaemonSet scrapes /var/log/containers/*.log
          └─ Pipeline: parse JSON → extract labels → push to Loki
             └─ Loki TSDB
                └─ Grafana (explore, dashboards, alerts)
```

### Why this order

- **stdout-only emission.** Services never write to a file; the container runtime captures stdout into the standard K8s log path. This is the 12-factor convention and avoids volume management.
- **Promtail DaemonSet.** One pod per node, scraping the container log directory. Far cheaper than a sidecar per service.
- **JSON pipeline stage** parses each line and extracts `service`, `level`, `intersection_id`, `event`, `trace_id` as **labels** vs **structured fields**. Labels are indexed (low cardinality only); fields are queryable but not indexed.

### Label discipline

Loki performance is dominated by label cardinality. Strict per-label budget:

| Label | Source | Cardinality bound | Why |
|-------|--------|-------------------|-----|
| `service` | container annotation | ~12 (one per microservice) | High-value filter |
| `namespace` | pod metadata | 1 per env | Tenant isolation |
| `pod` | pod metadata | tens | Standard K8s convention |
| `level` | JSON `level` field | 5 (debug/info/warn/error/critical) | Severity filtering |
| `intersection_id` | JSON field | bounded by pilot size (~50 in pilot, ~1000 long-term) | Per-intersection slicing |

Everything else (`trace_id`, `span_id`, `decision_id`, `event`, `principal_sub`, etc.) lives **inside the structured payload** and is queryable via `| json` parsing in LogQL. They are **not** labels — extracting `trace_id` as a label would create a near-unbounded cardinality.

### Retention

| Env | Retention | Why |
|-----|-----------|-----|
| dev | 7 d | Cheap, debugging only |
| staging | 30 d | Pilot iteration window |
| prod | 90 d | Operational; aligns with incident-review SLA |

Beyond retention, traces (Tempo) retain for the same window so the trace-id click-through works.

### Cross-link with Tempo (B2)

Every JSON line already carries `trace_id`. Grafana's Loki datasource is configured with a "derived field" pattern that turns `trace_id` into a clickable link to the Tempo datasource. Operators click → trace explorer opens with the trace, span tree, and timing — without leaving the same browser tab.

### Service-side: `decision_id` binding (B3 new code)

Beyond the static fields B1/B2 already bind, services should attach `decision_id` to the logger context when processing a decision message. `shared/atms_common/logging.py` gains:

```python
@contextmanager
def bind_decision_id(decision_id: int):
    """Bind decision_id to every log line within the scope. Uses structlog
    contextvars so it's safe across async tasks."""
    structlog.contextvars.bind_contextvars(decision_id=str(decision_id))
    try:
        yield
    finally:
        structlog.contextvars.unbind_contextvars("decision_id")
```

The traffic-controller wraps each `submit_decision()` call in this context; the decision-engine wraps each `make_decision()` call. Result: every log line generated during decision processing carries the `decision_id` for correlation.

### Dashboards

Three Grafana dashboards ship with the cluster:

1. **ATMS Overview** — request rate per service, error rate, P95 latency.
2. **Failsafe Controller** — mode-transition timeline, AI-decision-age gauge, ped/preempt counters.
3. **Logs** — log volume per service/level, top error events, trace-id click-through.

JSON definitions live in `infrastructure/observability/grafana/dashboards/`. Loaded via the Grafana sidecar dashboard provisioner.

### Alerts (Phase B3 + B4 cross)

Loki alerting rules in `infrastructure/observability/loki/rules.yaml`:

- `LogErrorBurst`: `rate({service="traffic-controller", level="error"}[5m]) > 0.5` → page
- `ControllerStuckInAllRedFlash`: `count_over_time({service="traffic-controller", event="controller_mode_transition", to_mode="all_red_flash"}[5m]) > 0` → page
- `RepeatedFailsafeFlap`: `rate({service="traffic-controller", reason="flap_threshold"}[15m]) > 0` → page sev-2

## Consequences

- New runtime dep on Promtail + Loki + Grafana in the cluster. Helm charts maintained in `infrastructure/observability/`.
- No code change to services beyond the `bind_decision_id` helper — the JSON-to-stdout path is already correct from B1+B2.
- A2 (probes across remaining services) automatically inherits the logging pipeline once each service calls `configure_logging` — already documented as the pattern.
- Label cardinality is enforced by the Promtail pipeline; future labels go through ADR review before being added.
- Grafana dashboards ship as JSON in the repo; updates are reviewed via PR.
