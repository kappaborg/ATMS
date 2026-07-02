# ADR-0003: Deployment target is on-prem Kubernetes

**Status:** Accepted
**Date:** 2026-05-29

## Context

ATMS controls safety-critical municipal infrastructure (signalized intersections). The pilot operator has chosen **on-prem / self-hosted Kubernetes** (`docs/assumptions.md` #1) over a managed public cloud.

Drivers:
- Data residency (camera video, license plates) under GDPR — keep within the operator's data centre.
- Latency from cloud to intersection adds variability that is unacceptable for the actuation path.
- Hybrid architecture (Phase C2 edge agent) keeps the actuation path local; cloud-or-on-prem only matters for the control plane.
- Operator already runs on-prem K8s for other services; we inherit the same Ops practices.

Alternatives:
- Public cloud K8s (EKS / GKE / AKS) — was rejected for the reasons above.
- Bare metal without K8s — rejected; we want declarative deploys, rolling updates, K8s-native observability.

## Decision

- Target K8s distribution: **upstream Kubernetes** (vanilla) at the operator's chosen version, no proprietary distro.
- Manifests structured as base + overlays under `k8s/` (already in place).
- Helm chart kept in `helm/atms-traffic-system/` for parametrized installs.
- Deployment orchestration: **GitOps via ArgoCD or Flux** (final choice in a future ADR; defaults to Flux for simpler reconciler).
- Service mesh: **Linkerd** (chosen separately; see future ADR-0006). Lightweight, mTLS-by-default, easier to operate than Istio.
- Container registry: on-prem (Harbor or similar); images signed via cosign (Phase A4 CI gate).

## Consequences

- No managed-cloud-only assumptions in code (no AWS SDK, no GCP-specific APIs).
- Secrets via SOPS + age (ADR-0002), not cloud KMS.
- Storage: PV/PVC using the operator's storage class. TimescaleDB (Phase C4) deployed via its operator chart.
- GPU scheduling: NVIDIA device plugin. Inference workloads request GPU explicitly.
- A future "deploy to cloud" decision re-opens A5 (secrets), B5 (mesh CA), and C2 (edge vs cloud control plane split).
