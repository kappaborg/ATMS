# Linkerd — mTLS + network policy stack (Phase B5)

Service-to-service mTLS via [Linkerd](https://linkerd.io). See [ADR-0012](../../docs/adr/0012-mtls-linkerd.md).

## Install order

```bash
# 1. cert-manager (issues the Linkerd trust anchor + identity issuer).
helm upgrade --install cert-manager jetstack/cert-manager \
  -n cert-manager --create-namespace \
  --set crds.enabled=true

# 2. The Linkerd trust anchor + identity issuer.
kubectl apply -f cert-manager-issuer.yaml

# 3. Linkerd CRDs and control plane.
helm upgrade --install linkerd-crds linkerd/linkerd-crds \
  -n linkerd --create-namespace
helm upgrade --install linkerd-control-plane linkerd/linkerd-control-plane \
  -n linkerd -f control-plane-values.yaml

# 4. Linkerd viz (dashboard + Prometheus integration).
helm upgrade --install linkerd-viz linkerd/linkerd-viz -n linkerd-viz \
  --create-namespace -f viz-values.yaml

# 5. Annotate the ATMS namespace for auto-injection.
kubectl annotate namespace atms linkerd.io/inject=enabled --overwrite

# 6. Roll the services to pick up the sidecar.
kubectl -n atms rollout restart deployment

# 7. Apply NetworkPolicies (in k8s/base/network-policies/).
kubectl apply -k ../../k8s/base/network-policies
```

## Verify

```bash
# Check mesh health.
linkerd check

# View mTLS topology — every edge should be tls=true.
linkerd -n atms viz edges deployment

# Authorization check — confirm only sa-api-gateway can reach traffic-controller.
linkerd -n atms viz authz deploy/traffic-controller
```

Expected: every edge in `atms` namespace is `tls=true`; unauthorized service-account attempts get rejected at the proxy.

## Rotation

cert-manager rotates the Linkerd identity issuer automatically per the `Certificate` resource's `renewBefore` setting (default 30 days). The trust anchor itself is rotated manually (~yearly) and is stored offline.

See [docs/runbooks/mtls.md](../../docs/runbooks/mtls.md) for the rotation playbook.
