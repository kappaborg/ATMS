# ADR-0006: RBAC roles + JWT authentication for HTTP endpoints

**Status:** Accepted
**Date:** 2026-05-29
**Closes:** PRODUCTION_GAPS.md gap #12 (Phase A6)

## Context

Phase A1 introduced operator endpoints (`/control/emergency`, `/control/recover`) on `services/traffic-controller` that can put a signalised intersection into all-red flash or take it out of one. Until A6, those endpoints are reachable without authentication; runbook §4.2 only said "should be reachable only from the operator subnet," which is not a guarantee.

The existing `security/jwt_handler.py` and `security/middleware.py` have several disqualifying issues for production:

1. **Auto-generated per-process secret.** A `JWTHandler()` with no `secret_key=` mints a random key on every start. Two replicas of the same service then cannot validate each other's tokens.
2. **In-memory token cache as a hard requirement.** `validate_token` returns `None` for any token not in `self.token_cache`, which means a token issued by an external IdP (or a peer replica) cannot validate.
3. **No `iss`/`aud` validation.** A leaked token from any other JWT issuer would validate.
4. **HS256-only.** Real OIDC IdPs (Keycloak, Auth0, Azure AD) sign with RS256 and publish a JWKS endpoint.
5. **Module-level ASGI middleware** rather than per-route `Depends()` — coarse-grained.

Service-to-service authentication is **out of scope** for this ADR: today services communicate via Kafka (no HTTP path), and Phase B5 will install Linkerd to handle service-to-service mTLS + identity. A6 is exclusively about **operator-facing HTTP**.

## Decision

Write `shared/atms_common/auth.py` from scratch. Remove `security/jwt_handler.py` and `security/middleware.py` once nothing imports them (follow-up cleanup PR — completed 2026-05-30).

### Role model

A flat, ordered set of four roles. Each higher role inherits permissions of lower roles.

| Role | Hierarchy | Typical user | Permissions |
|------|-----------|--------------|-------------|
| `viewer` | 0 | Dashboard read-only user | GET status / signals / metrics |
| `operator` | 1 | Traffic-ops shift staff | Acknowledge alerts; no state mutation |
| `engineer` | 2 | Traffic engineer / on-call | Force `ALL_RED_FLASH`; recover from it; change per-intersection config |
| `admin` | 3 | Platform admin | All of the above + manage roles, secrets, CI |

Endpoints declare their **minimum** required role; higher roles always pass.

### Endpoint matrix (traffic-controller)

| Path | Method | Min role | Rationale |
|------|--------|----------|-----------|
| `/live`, `/ready`, `/startup`, `/metrics` | GET | none | K8s probes / Prometheus scrape |
| `/` | GET | none | Service identity / discovery |
| `/health` | GET | none | Backward-compat; equivalent to `/ready` |
| `/status`, `/signals/*` | GET | `viewer` | Operational read |
| `/control/emergency` | POST | `engineer` | E-stops an intersection |
| `/control/recover` | POST | `engineer` | Recovers from E-stop |
| `/control/manual` | POST | `engineer` | (Currently returns 410; gate preserved for symmetry) |

### Token shape

Standard JWT (RFC 7519). Required claims:

- `iss` — the configured issuer URL (e.g. `https://idp.atms.example/realms/atms`).
- `aud` — `atms-traffic-controller` (the service this token is for; per-service audience prevents token reuse across services).
- `sub` — opaque operator id; logged in audit events.
- `exp`, `nbf`, `iat` — standard time bounds.
- `jti` — token id; logged on operator-mutation actions for traceability.
- `roles` — list of strings drawn from the role model above.

### Verification algorithm

- **Dev / test:** `HS256` with a shared secret loaded from env / SOPS (ADR-0002).
- **Production:** `RS256` with a JWKS URI (`AUTH_JWKS_URI`). Verifier fetches the JWKS, caches it for `AUTH_JWKS_CACHE_S` (default 300 s), and selects the key by `kid`.

A6 ships HS256 fully. **RS256 + JWKS is implemented (follow-up complete, 2026-05-30)** using PyJWT's `PyJWKClient` for JWKS fetching and caching. The `jwks_cache_ttl_s` field on `AuthConfig` (default 300 s) controls cache lifetime; unknown `kid` triggers an automatic refresh. Tests in `services/traffic-controller/tests/unit/test_auth.py::TestVerifyRS256` cover the verification, signature-tampering, key-mismatch, missing-kid, unknown-kid, expiry, and audience/issuer paths. Dev-mode Keycloak stack: [`docker-compose.keycloak.yml`](../../docker-compose.keycloak.yml) + [`deploy/keycloak/atms-realm.json`](../../deploy/keycloak/atms-realm.json). Operator runbook: [`docs/runbooks/oidc-keycloak.md`](../runbooks/oidc-keycloak.md).

### Audit logging

Every operator action that reaches a `require_role("engineer")`-gated handler emits a structured log line:

```
event=operator_action,intersection_id=...,principal_sub=...,principal_jti=...,action=...,reason=...,outcome=success|denied
```

Outcome `denied` is logged for both 401 (no/expired token) and 403 (insufficient role), with the IP address.

### Trust boundary clarifications

- **Kafka decisions** are **not** authenticated at the application layer in A6. Kafka client-side ACLs + (later) mTLS via Linkerd are the path. Decision producer/consumer JWTs are unnecessary churn and outside this ADR.
- **K8s probes** (`/live`, `/ready`, `/startup`) **never** require auth. Removing them from the public Service or NetworkPolicy is how non-cluster traffic is blocked.
- **Prometheus scraping** is bound to the cluster's Prometheus identity via NetworkPolicy (Phase B5), not JWT.

## Consequences

- A single new dependency: `pyjwt[crypto]` (the `crypto` extra pulls `cryptography`, which is also used by the RS256 JWK serialisation). PyJWT's bundled `PyJWKClient` uses stdlib `urllib` for JWKS fetches — no `httpx` dependency was needed in the end.
- `security/jwt_handler.py` and `security/middleware.py` are **REMOVED** (follow-up complete, 2026-05-30). No service imports them; `security/__init__.py` updated to reflect the removed modules.
- Every existing FastAPI endpoint must be reviewed for whether it needs a `require_role(...)` dependency. Phase A6 ships the traffic-controller subset; other services follow as their A6-equivalent PRs land.
- Local development needs a `dev-token` issuer or an env var with a pre-signed HS256 token, so devs can hit the operator endpoints from the dashboard. Documented in `CONTRIBUTING.md` follow-up.
- Tests use a generated HS256 secret per test, sign tokens themselves, and assert 401/403/200 on the gated endpoints.
