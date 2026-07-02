# Contributing to ATMS

This document describes how to develop, test, and submit changes to the ATMS codebase. Before contributing, read [`docs/SENIOR_ENGINEER_PROMPT.md`](docs/SENIOR_ENGINEER_PROMPT.md) for the project's operating principles and phase plan.

---

## Quick start

```bash
# 1. Get the deps for the service you're working on (example: traffic-controller).
cd services/traffic-controller
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt

# 2. Run the tests.
pytest tests/ -v

# 3. Run the linters.
cd ../..
pip install ruff mypy
ruff check shared/atms_common services/traffic-controller/src
ruff format --check shared/atms_common services/traffic-controller/src
mypy shared/atms_common services/traffic-controller/src
```

## Required status checks (branch protection on `main`)

Every PR must pass the `CI required` check before it can merge to `main`. That check aggregates every job in [`.github/workflows/ci.yml`](.github/workflows/ci.yml):

| Job | What it verifies |
|-----|------------------|
| `lint` | `ruff check` clean + `ruff format --check` clean on Phase A code |
| `typecheck` | `mypy` strict-mode clean on Phase A code |
| `test` | Unit + in-process integration tests pass on Python 3.11 and 3.12, ≥80% line coverage |
| `secrets-scan` | `gitleaks` finds no committed secrets |
| `build` | Every service Dockerfile builds successfully |
| `image-scan` | `trivy` finds no fixable HIGH/CRITICAL CVEs |
| `sbom` | `syft` produces a SPDX-JSON SBOM per image |
| `ci-required` | Aggregator — set this as the **only** required check; it tracks the others |

PRs are blocked when any of the above fails. To bypass a check you must:

1. File an issue documenting why the gate is wrong (don't make CI noisier — fix the root cause).
2. Update the gate (e.g., a `ruff` rule, a Trivy ignore) in the same PR that needs the bypass, with a rationale comment.
3. Get approval from a `@OWNER-sre` listed in [CODEOWNERS](.github/CODEOWNERS).

Never use `--no-verify` to bypass pre-commit hooks. If a hook fails, fix the issue.

## CI architecture (one-line summary per workflow)

- [`ci.yml`](.github/workflows/ci.yml) — runs on PR and on push to `main`. Linting, typecheck, tests, secrets scan, image build, vulnerability scan, SBOM generation.
- [`release.yml`](.github/workflows/release.yml) — runs on push to `main` and on `v*` tags. Pushes images to the registry, signs them with **cosign keyless OIDC**, attaches SBOM attestations.
- [`nightly.yml`](.github/workflows/nightly.yml) — daily 03:17 UTC. Full Testcontainers-Kafka chaos test, repository-wide CVE scan. Opens a digest issue on failure.

## Operating principles (from the senior engineer prompt)

These are non-negotiable — read them whenever you open a PR:

1. **Safety bias.** When in doubt, fail to fixed-time signal plans, not to "best guess." Never invent fallbacks that touch actuators without explicit safety review.
2. **Small, reversible PRs.** No PR larger than ~500 lines of net change. Every PR must be revertable cleanly.
3. **Tests before merge.** Every new behavior ships with tests. Bug fixes ship with a regression test that fails on the unfixed code.
4. **No mocked DB / Kafka in integration tests.** Use Testcontainers.
5. **No new abstractions without two existing call sites.**
6. **Write ADRs.** Architecturally significant decisions go in [`docs/adr/`](docs/adr/) **before** the code.
7. **Update the audit.** Close gaps in [`docs/PRODUCTION_GAPS.md`](docs/PRODUCTION_GAPS.md) when the work merges.
8. **Verify documented claims.** If you touch a subsystem whose docs make a quantitative claim, re-measure it.
9. **No `--no-verify`, no destructive git ops, no force-push to `main`.**
10. **Conventional commits, signed, with co-author trailer.**

## What goes in a PR

- One logical change. Not a bug fix bundled with a refactor.
- Tests in the same PR.
- ADR in the same PR if you took an architecturally significant decision.
- A runbook update if you changed operational behavior.
- A line moved from `[TODO]` to `[DONE]` in `docs/PRODUCTION_GAPS.md` if you closed a gap.

## Local auth (dev tokens)

The traffic-controller's operator endpoints (`/status`, `/signals/*`, `/control/*`) are gated by JWT + RBAC (see [`docs/adr/0006-rbac-jwt-roles.md`](docs/adr/0006-rbac-jwt-roles.md)). Locally, mint an HS256 token with the helper in `shared/atms_common/auth.py`:

```python
from shared.atms_common.auth import AuthConfig, issue_hs256_test_token

cfg = AuthConfig(
    issuer="atms-dev",
    audience="atms-traffic-controller",
    algorithm="HS256",
    hs256_secret="<the same value you set in AUTH_HS256_SECRET>",
)
print(issue_hs256_test_token(cfg, sub="me", roles=["engineer"], ttl_s=3600))
```

Then call the API:

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8003/status
```

Production tokens come from the operator IdP (Keycloak); the controller switches to RS256 + JWKS by setting `AUTH_ALGORITHM=RS256` and `AUTH_JWKS_URI=...`. The RS256 verifier is currently stubbed; it lights up alongside the IdP integration work.

## Operator endpoints (Phase A7)

The traffic-controller exposes operator-facing HTTP endpoints. Required roles:

| Endpoint | Method | Min role | Use |
|----------|--------|----------|-----|
| `/control/emergency` | POST | `engineer` | Force `ALL_RED_FLASH` |
| `/control/recover` | POST | `engineer` | Recover out of `ALL_RED_FLASH` |
| `/control/preempt` | POST | `engineer` | Arm EV preempt (NTCIP / transponder writer in prod) |
| `/control/preempt/clear` | POST | `engineer` | Clear active preempt |
| `/control/ped-call` | POST | `operator` | Queue pedestrian call (push-button / NTCIP) |
| `/status`, `/signals/*` | GET | `viewer` | Read-only operational view |

See [`docs/runbooks/failsafe.md`](docs/runbooks/failsafe.md) for the operational procedures and audit trail.

## Service skeleton (Phase B1/B2/B3)

A new ATMS service starts from this five-line bootstrap:

```python
from shared.atms_common.logging import configure_logging
from shared.atms_common.tracing import configure_tracing, instrument_fastapi
from shared.atms_common.health import HealthRouter
from shared.atms_common.config import AtmsBaseSettings

settings = AtmsBaseSettings()
configure_logging(service="my-service", version="1.0", intersection_id=settings.intersection_id)
configure_tracing(service="my-service", version="1.0", development=True)
app = FastAPI(); instrument_fastapi(app)
HealthRouter(service_name="my-service").attach(app)
```

That gives you: JSON logs, OTel traces, K8s probes, env-validated config — uniform across every service.

Full migration guide: [`docs/migration/a2-shared-lib-bootstrap.md`](docs/migration/a2-shared-lib-bootstrap.md).

## Secrets (Phase A5)

Production secrets are SOPS-encrypted under `deploy/secrets/<env>/` and decrypted by Flux at GitOps sync time. Local dev workflow:

```bash
# One-time bootstrap (see docs/runbooks/secrets.md §1).
brew install sops age
age-keygen -o ~/.config/sops/age/keys.txt
# Share your public key with the project owner, who adds it to .sops.yaml.

# Decrypt for local dev (after your key is in .sops.yaml):
make secrets-decrypt ENV=dev
# → produces .env (gitignored)
```

Common tasks:

| Task | Command |
|------|---------|
| Add a new secret | edit `.env` → `cp` to `deploy/secrets/dev/atms.env` → `make secrets-encrypt ENV=dev FILE=atms.env` |
| Edit an encrypted file in `$EDITOR` | `make secrets-edit ENV=dev FILE=atms.env.sops` |
| Re-encrypt after `.sops.yaml` change | `make secrets-rotate-recipients` |

CI gates: `gitleaks` blocks plaintext secrets in PRs, `secrets-check` confirms committed `*.sops*` files look encrypted. Both are in `.github/workflows/ci.yml`. See [`docs/runbooks/secrets.md`](docs/runbooks/secrets.md) for the full procedure including key rotation and incident response.

## Reporting a security issue

Do **not** open a public GitHub issue. Email `security@<your-domain>` (Phase A6 sets up the mailbox; until then route through `@OWNER-security`).
