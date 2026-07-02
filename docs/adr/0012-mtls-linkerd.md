# ADR-0012: mTLS via Linkerd + Kubernetes NetworkPolicies

**Status:** Accepted
**Date:** 2026-05-30
**Closes:** PRODUCTION_GAPS.md gap #11 (Phase B5)

## Context

Audit gap #11: service-to-service traffic inside the cluster is plaintext. Any pod can read any Kafka topic, hit any other service's HTTP API, and impersonate any caller because there is no identity. For an attacker who lands a foothold in any namespace, the rest of the cluster is wide open.

Phase A6 closed the *operator-to-service* HTTP path with JWT. B5 closes the *service-to-service* path with mutual TLS, plus a default-deny network policy.

## Decision

### Mesh: Linkerd

Linkerd over Istio for:

- **Operational simplicity.** Linkerd's control plane is ~3 deployments vs Istio's ~10. Smaller blast radius, easier upgrades.
- **mTLS by default.** No per-service config needed; identity is bound to the ServiceAccount.
- **Smaller proxy footprint.** linkerd2-proxy (Rust) is faster and uses less memory than Envoy at our request rate (<1 kQPS per service).
- **Predictable behavior.** Linkerd intentionally has fewer knobs. We don't need traffic-splitting / Wasm / circuit-breakers at the mesh layer (those are Phase B4's resilience primitives at the application layer).

Trade-off: Linkerd has fewer traffic-management features. We don't need them yet; Istio is the migration path if we later do.

### Trust anchor + issuer

Per Linkerd standard:

- **Trust anchor** (10-year, root): generated once during cluster bootstrap, stored offline (HSM-backed in prod), public cert in the Linkerd config.
- **Issuer certificate** (24h–8760h, intermediate): minted from the trust anchor. Auto-rotated by cert-manager on a configurable schedule. Pods get short-lived workload certs.

`cert-manager` (already common in our infra direction) issues the Linkerd identity certs via a `Certificate` resource targeting an `Issuer`. Rotation is automatic with zero pod restart.

### Sidecar injection

Namespace-level annotation `linkerd.io/inject: enabled` on the `atms` namespace. Every pod in the namespace gets the linkerd2-proxy sidecar automatically. No per-deployment config.

Opt-out: pods that legitimately can't accept a sidecar (privileged daemons; we don't expect any in ATMS) set `linkerd.io/inject: disabled` at the pod-template level.

### Network policies

Default-deny at the namespace boundary, explicit-allow per known edge. Manifests in `k8s/base/network-policies/`:

| Policy | Allows |
|--------|--------|
| `default-deny.yaml` | nothing inbound or outbound |
| `allow-dns.yaml` | egress to kube-system DNS |
| `allow-kafka.yaml` | every service → kafka.atms.svc on 9092 |
| `allow-postgres.yaml` | services that need DB → postgres.atms.svc on 5432 |
| `allow-redis.yaml` | services that need cache → redis.atms.svc on 6379 |
| `allow-decision-engine.yaml` | api-gateway, dashboard → decision-engine HTTP |
| `allow-traffic-controller.yaml` | api-gateway → traffic-controller HTTP |
| `allow-otel-collector.yaml` | every service → otel-collector on 4317 |
| `allow-probes.yaml` | kube-system → every pod on probe ports |

NetworkPolicies are **stacked** on mTLS — even if a policy was misconfigured, an attacker without a valid workload identity cannot establish a mesh-authenticated connection.

### Identity model

- Each ATMS Deployment has a dedicated `ServiceAccount` (e.g., `sa-traffic-controller`). The `ServiceAccount` is the identity inside the mesh.
- `linkerd-policy` resources scope per-route authorization: `traffic-controller` HTTP routes only accept connections from `sa-api-gateway` (operator-facing) and `sa-dashboard` (read paths). Operators connect via the API gateway, which enforces JWT (A6).
- Decision-engine → traffic-controller does **not** happen over HTTP — it happens via Kafka. Kafka itself runs outside the mesh in the initial deployment; Phase C2 may move it inside.

### What B5 does NOT do

- **Authorize Kafka topic access.** Kafka client-side ACLs are configured separately (Phase C2 or earlier). Linkerd cannot enforce per-topic ACLs.
- **Decrypt L7 protocol violations.** mTLS is at the transport layer; application-layer attacks (SQL injection, etc.) are still possible. JWT (A6), schema validation (A1), and resilience primitives (B4) defend at the application layer.
- **Replace JWT.** JWT remains the operator-side identity. mTLS is the service-to-service identity.

## Consequences

- New cluster-level dependency: Linkerd control plane + cert-manager.
- Per-pod CPU/memory: linkerd2-proxy adds ~5 m CPU and ~15 Mi memory per pod. Negligible at our scale.
- Per-request latency: linkerd2-proxy adds ~1-2 ms P50, ~5 ms P99. Within budget for both the operator API path and the Kafka non-path.
- Operator tooling: `linkerd viz` for traffic topology, `linkerd check` for control-plane health, `linkerd authz` for policy enforcement check.
- Future-cluster guarantees: any future PR that adds a service inherits mTLS automatically by deploying into the `atms` namespace. No per-PR mesh-config work.
- `network-policies/` directory ships with the manifests but **requires** a CNI that enforces NetworkPolicy (Calico, Cilium, etc.). Document this requirement in the cluster bootstrap.
