# Runbook: mTLS via Linkerd (Phase B5)

**Audience:** Platform / SRE operating the on-prem K8s cluster.
**Design:** [ADR-0012](../adr/0012-mtls-linkerd.md).
**Owning manifests:** [`infrastructure/linkerd/`](../../infrastructure/linkerd/), [`k8s/base/network-policies/`](../../k8s/base/network-policies/).

This runbook covers the install, verification, rotation, and incident response for Linkerd mesh + Kubernetes NetworkPolicies in the `atms` namespace.

---

## 1. Install (one-time)

Follow [`infrastructure/linkerd/README.md`](../../infrastructure/linkerd/README.md). Summary:

1. Install cert-manager.
2. Apply `cert-manager-issuer.yaml` — creates the trust anchor + identity issuer.
3. Install `linkerd-crds` and `linkerd-control-plane` Helm charts.
4. Install `linkerd-viz` for the dashboard.
5. Annotate the `atms` namespace: `linkerd.io/inject=enabled`.
6. Restart all ATMS deployments to pick up the sidecar: `kubectl -n atms rollout restart deployment`.
7. Apply NetworkPolicies: `kubectl apply -k k8s/base/network-policies/`.

**Pre-flight check:** the cluster CNI must enforce NetworkPolicy. Calico, Cilium, Antrea, and Weave do; some default cloud CNIs do not. Verify with `kubectl get nodes -o jsonpath='{.items[0].status.nodeInfo}'` and consult your distro docs.

## 2. Verify

After install, every check should be green.

```bash
# Mesh control-plane health.
linkerd check

# Every pod in atms is meshed.
linkerd -n atms viz stat deployment
# Expect: each deployment shows TLS=100%.

# Edges all carry mTLS.
linkerd -n atms viz edges deployment
# Expect: every row has TLS=true. Any "no" is a misconfigured sidecar.

# Per-service authorization.
linkerd -n atms viz authz deploy/traffic-controller
# Expect: explicit allow rows for sa-api-gateway; default deny otherwise.

# NetworkPolicy is enforced.
kubectl run -n atms pol-test --image=busybox --rm -it -- \
  wget -T 2 -qO- http://decision-engine:8007/health
# Expect: timeout — `pol-test` has no allow rule, so the policy blocks.
```

## 3. Operator tasks

### 3.1 Add a new service

1. Deploy into the `atms` namespace with a unique `ServiceAccount` (e.g. `sa-<service>`).
2. The namespace annotation auto-injects the sidecar — no per-pod config.
3. Add a NetworkPolicy under `k8s/base/network-policies/` for any service-to-service or out-of-namespace flow it needs.
4. Update the Linkerd `Server` + `ServerAuthorization` resources to scope which ServiceAccounts may call the new service.
5. `kubectl apply -k k8s/base/network-policies/` and verify with `linkerd viz authz`.

### 3.2 Rotate the identity issuer

cert-manager renews the issuer automatically per `renewBefore` (default 30 days). Manual rotation:

```bash
# Force renewal of the issuer cert.
kubectl -n linkerd cmctl renew linkerd-identity-issuer

# Watch the new cert come up.
kubectl -n linkerd get certificate linkerd-identity-issuer -w

# Rolling-restart the linkerd-identity deployment to pick up the new cert.
kubectl -n linkerd rollout restart deployment/linkerd-identity

# Verify the proxies got the new issuer.
linkerd identity -n atms deploy/traffic-controller
# Expect: NotBefore/NotAfter dates match the new cert.
```

Pods do **not** need a restart — linkerd2-proxy reloads workload certs hot.

### 3.3 Rotate the trust anchor (annual)

Higher-risk because old workload certs become invalid. Follow the [Linkerd anchor-rotation procedure](https://linkerd.io/2/tasks/rotate-trust-roots/) — there is no shortcut.

Out-of-band: notify the team 1 week in advance; schedule during a low-traffic window.

## 4. Incident response

### 4.1 "Service A cannot reach Service B"

Likely causes in order of frequency:

1. **NetworkPolicy missing.** `kubectl -n atms describe networkpolicy` and verify there's an allow rule for the edge. Add one.
2. **Sidecar not injected.** `kubectl -n atms get pod <pod> -o jsonpath='{.spec.containers[*].name}'` should include `linkerd-proxy`. If not: namespace annotation missing, or pod has `linkerd.io/inject: disabled`.
3. **Linkerd authz denied.** Check `linkerd -n atms viz authz deploy/<target>` — the source ServiceAccount must be allowed.
4. **Identity-issuer expired.** `linkerd check` will flag this.

### 4.2 "mesh is down"

```bash
# Check the control plane.
linkerd check
kubectl -n linkerd get pod

# Common: cert-manager hasn't renewed. Check Certificate status.
kubectl -n linkerd get certificate

# Worst case: roll back to before the most recent control-plane upgrade.
helm rollback linkerd-control-plane -n linkerd
```

### 4.3 Compromised workload private key

Workload private keys live only in linkerd2-proxy memory and are never written to disk. To rotate after suspected compromise:

1. Delete the affected pod (`kubectl delete pod <pod>`). The new proxy will mint a fresh keypair.
2. If the identity-issuer key itself is suspected compromised, rotate it (§3.2) — that invalidates every workload cert and forces every pod to mint a new one.

## 5. NetworkPolicy reference

Manifests in [`k8s/base/network-policies/`](../../k8s/base/network-policies/):

| File | What it allows |
|------|----------------|
| `00-default-deny.yaml` | Nothing. Baseline. |
| `10-allow-dns.yaml` | kube-system DNS |
| `20-allow-kafka.yaml` | every pod → Kafka |
| `30-allow-otel-collector.yaml` | every pod → OTel collector (B2) |
| `40-allow-decision-engine.yaml` | api-gateway, dashboard → decision-engine |
| `41-allow-traffic-controller.yaml` | api-gateway → traffic-controller |

When you add a new edge, add a NetworkPolicy in the same PR.

## 6. What this does NOT cover

- Kafka topic-level ACLs — out of scope; tracked separately.
- L7 attacks (SQL injection, JWT forgery) — defended at the application layer by A6 + B4.
- Operator-to-service auth — JWT (A6); the mesh authenticates *services*, not human operators.
- Inter-cluster connectivity — single-cluster only for the pilot.
