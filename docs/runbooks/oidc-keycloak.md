# Runbook: OIDC integration via Keycloak (Phase A6 RS256 cutover)

**Audience:** Developer (dev mode), DevOps engineer (production cutover).
**Design:** [ADR-0006](../adr/0006-rbac-jwt-roles.md).
**Code:** [`shared/atms_common/auth.py`](../../shared/atms_common/auth.py).
**Tests:** [`services/traffic-controller/tests/unit/test_auth.py::TestVerifyRS256`](../../services/traffic-controller/tests/unit/test_auth.py).

---

## 1. What this gives you

`shared/atms_common/auth.py` supports both HS256 (dev / test) and RS256 + JWKS (production OIDC). Until this runbook landed, `_verify_rs256` raised `NotImplementedError`. It now uses PyJWT's `PyJWKClient` to fetch and cache JWKS from the IdP, with a five-minute TTL by default and automatic refresh on unknown `kid`.

The local Keycloak stack at [`docker-compose.keycloak.yml`](../../docker-compose.keycloak.yml) is **dev only** — admin passwords and client secrets are well-known. Production deployments point each service at the operator's existing IdP (Keycloak, Auth0, Okta, Azure AD, etc.) via the same `AUTH_*` env vars.

---

## 2. Dev mode (Keycloak via docker compose)

### 2.1 Spin up

```bash
docker compose -f docker-compose.keycloak.yml up -d
```

The realm `atms` is imported automatically on first boot from [`deploy/keycloak/atms-realm.json`](../../deploy/keycloak/atms-realm.json). It defines:

- Four realm roles: `viewer`, `operator`, `engineer`, `admin`.
- Four clients (one per FastAPI service): `atms-traffic-controller`, `atms-decision-engine`, `atms-v2x-interface`, `atms-api-gateway`. Each has an audience mapper so the token's `aud` claim equals the client id — this is what each service validates.
- Four dev users: `dev-viewer`, `dev-operator`, `dev-engineer`, `dev-admin` (passwords: `dev-<role>-password`).

### 2.2 Verify

```bash
curl -s http://localhost:8080/realms/atms/.well-known/openid-configuration | jq .issuer
# expect: "http://localhost:8080/realms/atms"

curl -s http://localhost:8080/realms/atms/protocol/openid-connect/certs | jq '.keys[0].kid'
# expect: a kid string (rotates on key rollover)
```

### 2.3 Get a token

```bash
TOKEN=$(curl -s -X POST 'http://localhost:8080/realms/atms/protocol/openid-connect/token' \
  -d 'grant_type=password' \
  -d 'client_id=atms-traffic-controller' \
  -d 'client_secret=dev-traffic-controller-secret' \
  -d 'username=dev-engineer' \
  -d 'password=dev-engineer-password' \
  -d 'scope=openid' | jq -r .access_token)

echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '{sub, aud, iss, roles, exp}'
```

Expected output:

```json
{
  "sub": "<uuid>",
  "aud": "atms-traffic-controller",
  "iss": "http://localhost:8080/realms/atms",
  "roles": ["engineer", "operator", "viewer"],
  "exp": 1735000000
}
```

### 2.4 Point a service at Keycloak

Set these env vars on the FastAPI service (traffic-controller, decision-engine, v2x-interface, api-gateway):

```bash
export AUTH_ALGORITHM=RS256
export AUTH_ISSUER='http://localhost:8080/realms/atms'
export AUTH_AUDIENCE='atms-traffic-controller'        # ← match per service
export AUTH_JWKS_URI='http://localhost:8080/realms/atms/protocol/openid-connect/certs'
export AUTH_CLOCK_SKEW_S=30
```

When the service is running inside the same Docker network as Keycloak, use the cluster-internal hostname `http://keycloak:8080/...` instead of `localhost:8080`.

### 2.5 Smoke-test the gated endpoint

```bash
curl -i -H "Authorization: Bearer $TOKEN" http://localhost:8001/preempt/arm \
     -H "Content-Type: application/json" \
     -d '{"approach": "north_south", "priority": "fire_rescue", "transponder_id": "EV-test"}'
```

Expected: `200 OK` with the preempt-arm response. The traffic-controller's audit log should show a `success` line referencing the principal's `sub` and `jti`.

---

## 3. Production cutover

### 3.1 Pre-flight

1. Choose an IdP. Options that are tested in similar deployments:
   - **Keycloak** (recommended OSS path): same image, same realm import format. Run it under your existing Kubernetes cluster.
   - **Auth0 / Okta / Azure AD**: enterprise-managed. Configure ATMS as an OIDC client with the same audience + roles mapping.
2. Define the realm/tenant equivalent to `deploy/keycloak/atms-realm.json` in the production IdP. **Never** import the dev realm file — its client secrets and user passwords are in the repo.
3. Issue four client credentials, one per service. Each client's `aud` claim must equal the client id (audience mapper, as in the dev realm).
4. Assign each operator a single ATMS role (`viewer`, `operator`, `engineer`, `admin`) according to the operator-side role mapping table — see your DPIA.
5. Validate the JWKS endpoint is reachable from inside the cluster.

### 3.2 Rollout sequence

ATMS supports both HS256 and RS256 via a single env-var flip. The recommended cutover is:

1. **Stage 1 (audit).** Bring up Keycloak in production. Run a parallel `audit-only` service replica that accepts the new tokens but does not enforce — log accepted+rejected separately. Run for one week to catch any per-operator misconfiguration.
2. **Stage 2 (mixed).** Each service runs **two** independent verifiers (one HS256, one RS256) — accept tokens validated by either. Operators carry both an HS256 dev token (for emergency fallback) and a Keycloak-issued RS256 token. Run for ~one week.
3. **Stage 3 (RS256-only).** Drop HS256 from every service. Audit logs should show 100% RS256 acceptance for the prior 48 hours before stage 3 lands.

Note: stage-2 dual-verifier support is **not** in the shared library today — each service would need a small wrapper around `JWTVerifier`. The wrapper is one of the C2-pilot follow-ups; if the operator's cutover is single-stage (HS256 → RS256 over a maintenance window), skip stage 2.

### 3.3 Env vars in production

Same as §2.4, but:

- `AUTH_ISSUER='https://idp.example.com/realms/atms'` (TLS required)
- `AUTH_JWKS_URI='https://idp.example.com/realms/atms/protocol/openid-connect/certs'` (TLS required)
- The JWKS URI **must** be HTTPS in production; PyJWKClient does not enforce this, but the Linkerd / NetworkPolicy layer should reject the connection if attempted over plaintext.

Pass these via the existing SOPS-encrypted secret bundles. The dev container reads them from environment; the K8s deployment reads them from a `Secret` mounted as env. Do not store the client secret in code or commit it.

### 3.4 Key rotation

Keycloak rotates its signing keys on the operator's schedule (default: never; recommended: every 90 days). When a key rotates:

1. The IdP publishes both old and new keys at the JWKS endpoint for a transition window.
2. Existing tokens signed by the old key continue to validate against the still-published old key.
3. New tokens carry the new `kid`. `PyJWKClient` force-refreshes the cache on the first unknown `kid`, fetches the new key, and resumes verification.
4. The five-minute cache TTL (`jwks_cache_ttl_s` on `AuthConfig`) puts an upper bound on the propagation lag without rotation events.

No service restart is required.

---

## 4. Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 — JWKS resolution failed` | JWKS URI unreachable, or non-JSON response | Verify network policy + JWKS URI; check Keycloak `/health/ready` |
| `401 — token missing 'kid' header` | Caller sent an HS256 token to an RS256-configured service | Caller must request RS256 tokens from the IdP |
| `401 — invalid issuer` | `AUTH_ISSUER` env mismatch with the `iss` claim | Issuer must be the IdP's full URL incl. realm path |
| `401 — invalid audience` | The IdP isn't emitting the per-client audience mapper | Re-check the realm's client → protocolMappers config |
| `401 — invalid signature` | Token was signed with a different key than the IdP publishes | Confirm the realm is correct; restart Keycloak if a key was manually rotated |
| `403 — insufficient role; need engineer` | User has the JWT but not the realm role | Assign the realm role in Keycloak's user admin |

---

## 5. Audit trail

Every gated endpoint logs a single JSON line per request via `audit_logger` (configured in each service's `_audit_log`). The line is shipped to Loki via Promtail. Fields:

- `event` = `operator_action`
- `outcome` = `success` or `denied`
- `reason` (denied only) = e.g. `role<engineer`, `token expired`, `invalid signature`
- `sub`, `jti`, `roles`, `path`, `client`

This is the source of truth for audit. The post-incident query is "show me every `operator_action` on `/preempt/arm` in the last hour grouped by `sub`."

---

## 6. Out of scope

- **Token revocation.** ATMS does not consult a revocation list — tokens are valid until expiry (15 min default). For emergency revocation, rotate the IdP signing key or shorten access-token lifespan in the realm config.
- **Refresh-token storage.** ATMS does not handle refresh tokens. The caller (operator console) is responsible for refreshing access tokens against the IdP directly.
- **Identity federation.** If the operator wants AD/SSO behind Keycloak, that's a Keycloak-side configuration; ATMS sees only the JWT issued by Keycloak.
- **mTLS for service-to-service.** Service-to-service auth uses Linkerd-managed mTLS (Phase B5, ADR-0012), not JWTs. JWTs cover human / operator-console traffic only.
