# ADR-0002: Secrets management via SOPS + age

**Status:** Accepted
**Date:** 2026-05-29

## Context

Audit gap #10: `.env` was unignored at the repo root with empty placeholders for credentials; the first time someone fills it in and commits, secrets leak. Going forward we need a secrets-management approach that:

- Works on **on-prem Kubernetes** (decided in `docs/assumptions.md`) without a managed cloud KMS.
- Is GitOps-friendly: encrypted secrets can live in the same repo as the manifests they encrypt for.
- Is lightweight enough for a small ops team — no separate HA cluster to operate.
- Survives rotation: revoke a key without redeploying every service.

Alternatives considered:
- **HashiCorp Vault** — most powerful, but full HA Vault is non-trivial to operate; overkill for current size.
- **Sealed Secrets (Bitnami)** — encrypts only to a single cluster controller key; awkward for multi-cluster and disaster recovery.
- **SOPS + age** — file-level encryption, recipients are age keys (curve25519), files are diffable, decryption integrates with Helm / kustomize / direnv.

## Decision

Use **SOPS** (Mozilla) with **age** recipients.

- Production: encrypted YAML/JSON files under `deploy/secrets/<env>/`. Recipients = one age key per ops engineer + one cluster-bound age key (HSM-backed in production).
- Local dev: `.env` file (gitignored) holds dev values; never production values.
- Kubernetes: SOPS-decrypted at GitOps sync time (via [sops-operator](https://github.com/isindir/sops-secrets-operator) or `kustomize-sops` plugin in ArgoCD/Flux). Pods consume normal `Secret` objects.
- Key rotation: re-encrypt with new recipient list; commit; sync. Old recipient stays in history but cannot decrypt new files.

## Consequences

- New repo top-level dir: `deploy/secrets/` (template files only, real values come later).
- All services load secrets from environment variables. Per Phase B (B1) the Pydantic `Config` in `shared/atms_common/config.py` is the only place that reads from the environment.
- `.env` and `.env.*` are gitignored; `.env.example` is shipped.
- CI gate (Phase A4): a job greps the diff for high-entropy strings and known credential patterns and fails on match. Re-encrypt and resubmit.
- A separate ADR will be written if we later add Vault for dynamic credentials (DB short-lived creds, PKI for mTLS).
- This decision is for **on-prem** deployment only. A cloud deployment would re-open the question (cloud KMS-backed SOPS, or Vault Enterprise, or cloud-native secret store).
