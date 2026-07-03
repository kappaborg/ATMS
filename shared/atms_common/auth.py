"""
JWT authentication and RBAC for HTTP endpoints — gap #12 / Phase A6.

Design: docs/adr/0006-rbac-jwt-roles.md
OIDC integration: docs/runbooks/oidc-keycloak.md

The verifier is stateless: tokens are signed-and-claimed; the only mutable
state is the JWKS cache for RS256. This means a token issued by an external
IdP (Keycloak, etc.) validates the same way as a locally-issued dev token,
and replicas of the same service do not need to share state to accept the
same token — each replica holds its own JWKS cache.

Both HS256 (dev / test) and RS256 + JWKS (production OIDC) are supported by
the verifier interface. RS256 verification fetches the IdP's JWKS document
(typically `/protocol/openid-connect/certs` on Keycloak) and matches the
token's `kid` header against the published keys. The cache TTL defaults to
five minutes; key rotation triggers a force-refresh on the next unknown
`kid` (rate-limited so a stream of bogus tokens cannot DoS the IdP).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient, PyJWKClientError

# Public role names (order matters: index == hierarchy level).
ROLES: tuple[str, ...] = ("viewer", "operator", "engineer", "admin")
_ROLE_LEVEL: dict[str, int] = {r: i for i, r in enumerate(ROLES)}


def role_at_least(actual: str, minimum: str) -> bool:
    """True if `actual` is `minimum` or higher in the hierarchy."""
    a = _ROLE_LEVEL.get(actual)
    m = _ROLE_LEVEL.get(minimum)
    if a is None or m is None:
        return False
    return a >= m


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AuthError(Exception):
    """Auth failure with an HTTP status hint."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------------------
# Principal returned to handlers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    sub: str
    roles: frozenset[str]
    jti: str | None = None
    issued_at: int = 0
    expires_at: int = 0
    extras: dict[str, Any] = field(default_factory=dict)

    def has_role_at_least(self, minimum: str) -> bool:
        return any(role_at_least(r, minimum) for r in self.roles)


# ---------------------------------------------------------------------------
# Config + verifier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthConfig:
    issuer: str
    audience: str
    algorithm: str  # "HS256" or "RS256"
    hs256_secret: str | None = None
    rs256_jwks_uri: str | None = None
    clock_skew_s: int = 30
    jwks_cache_ttl_s: int = 300


class JWTVerifier:
    """
    Stateless JWT verifier.

    For HS256: pass the shared secret in `config.hs256_secret`.
    For RS256: pass the JWKS URI in `config.rs256_jwks_uri`. The verifier
    holds a `PyJWKClient` whose cache is refreshed every
    `config.jwks_cache_ttl_s` seconds, and forced-refreshed on the first
    encounter of an unknown `kid` (with rate-limiting via PyJWKClient).

    Tests may inject a pre-built `jwks_client` to bypass HTTP fetches.
    """

    def __init__(
        self,
        config: AuthConfig,
        *,
        jwks_client: PyJWKClient | None = None,
    ) -> None:
        self._cfg = config
        self._jwks_client: PyJWKClient | None = None
        if config.algorithm == "HS256":
            if not config.hs256_secret:
                raise ValueError("HS256 requires hs256_secret")
        elif config.algorithm == "RS256":
            if not config.rs256_jwks_uri:
                raise ValueError("RS256 requires rs256_jwks_uri")
            self._jwks_client = jwks_client or PyJWKClient(
                config.rs256_jwks_uri,
                cache_keys=True,
                lifespan=config.jwks_cache_ttl_s,
            )
        else:
            raise ValueError(f"unsupported algorithm: {config.algorithm}")

    def verify(self, token: str) -> Principal:
        if self._cfg.algorithm == "HS256":
            return self._verify_hs256(token)
        return self._verify_rs256(token)

    # ------------------------------------------------------------------

    def _verify_hs256(self, token: str) -> Principal:
        assert self._cfg.hs256_secret is not None  # checked in __init__
        try:
            payload = jwt.decode(
                token,
                self._cfg.hs256_secret,
                algorithms=["HS256"],
                audience=self._cfg.audience,
                issuer=self._cfg.issuer,
                leeway=self._cfg.clock_skew_s,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as e:
            raise AuthError(401, "token expired") from e
        except jwt.InvalidAudienceError as e:
            raise AuthError(401, "invalid audience") from e
        except jwt.InvalidIssuerError as e:
            raise AuthError(401, "invalid issuer") from e
        except jwt.MissingRequiredClaimError as e:
            raise AuthError(401, f"missing claim: {e.claim}") from e
        except jwt.InvalidTokenError as e:
            raise AuthError(401, f"invalid token: {e}") from e

        return _principal_from_payload(payload)

    def _verify_rs256(self, token: str) -> Principal:
        assert self._jwks_client is not None  # checked in __init__
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise AuthError(401, f"invalid token header: {e}") from e
        if not header.get("kid"):
            raise AuthError(401, "token missing 'kid' header")

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        except PyJWKClientError as e:
            # Covers JWKS fetch failures and `kid` not found after refresh.
            raise AuthError(401, f"JWKS resolution failed: {e}") from e

        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._cfg.audience,
                issuer=self._cfg.issuer,
                leeway=self._cfg.clock_skew_s,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as e:
            raise AuthError(401, "token expired") from e
        except jwt.InvalidAudienceError as e:
            raise AuthError(401, "invalid audience") from e
        except jwt.InvalidIssuerError as e:
            raise AuthError(401, "invalid issuer") from e
        except jwt.MissingRequiredClaimError as e:
            raise AuthError(401, f"missing claim: {e.claim}") from e
        except jwt.InvalidSignatureError as e:
            raise AuthError(401, "invalid signature") from e
        except jwt.InvalidTokenError as e:
            raise AuthError(401, f"invalid token: {e}") from e

        return _principal_from_payload(payload)


def _principal_from_payload(payload: dict[str, Any]) -> Principal:
    roles_raw = payload.get("roles", [])
    if isinstance(roles_raw, str):
        roles_raw = [roles_raw]
    roles = frozenset(str(r) for r in roles_raw)
    known = {"sub", "iss", "aud", "exp", "iat", "nbf", "jti", "roles"}
    extras = {k: v for k, v in payload.items() if k not in known}
    return Principal(
        sub=str(payload["sub"]),
        roles=roles,
        jti=str(payload["jti"]) if "jti" in payload else None,
        issued_at=int(payload.get("iat", 0)),
        expires_at=int(payload.get("exp", 0)),
        extras=extras,
    )


# ---------------------------------------------------------------------------
# Test helper — make a signed token in tests without standing up an IdP.
# Production code never imports this function path.
# ---------------------------------------------------------------------------


def issue_hs256_test_token(
    config: AuthConfig,
    *,
    sub: str,
    roles: Sequence[str],
    ttl_s: int = 60,
    jti: str | None = None,
    extra_claims: dict[str, Any] | None = None,
    now: int | None = None,
) -> str:
    """Issue a short-lived HS256 token signed with the config's secret."""
    import time as _time

    if config.algorithm != "HS256":
        raise ValueError("issue_hs256_test_token requires HS256 config")
    assert config.hs256_secret is not None
    iat = now if now is not None else int(_time.time())
    payload: dict[str, Any] = {
        "iss": config.issuer,
        "aud": config.audience,
        "sub": sub,
        "iat": iat,
        "exp": iat + ttl_s,
        "roles": list(roles),
    }
    if jti is not None:
        payload["jti"] = jti
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, config.hs256_secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# FastAPI integration — kept thin so unit tests can exercise the verifier
# without importing FastAPI at all.
# ---------------------------------------------------------------------------


def build_role_dependency(
    verifier: JWTVerifier,
    *,
    audit_logger: Callable[[dict[str, Any]], None] | None = None,
):
    """
    Return a FastAPI dependency factory.

    Usage in a service:

        verifier = JWTVerifier(...)
        require_role = build_role_dependency(verifier, audit_logger=app_logger)

        @app.post("/control/emergency", dependencies=[Depends(require_role("engineer"))])
        async def control_emergency(...): ...

    The dependency:
    - Extracts Bearer credentials.
    - Verifies the token (raises HTTP 401 on failure).
    - Checks the role (raises HTTP 403 on insufficient role).
    - Logs every accepted operator action and every denial via `audit_logger`.
    """
    bearer = HTTPBearer(auto_error=False)

    def require_role(minimum: str):
        if minimum not in _ROLE_LEVEL:
            raise ValueError(f"unknown role: {minimum}")

        # `Depends(bearer)` cannot live in a default-arg because ruff (B008) rightly
        # flags it as a call-in-default. FastAPI is fine with either; we use a
        # module-level alias on the dep function.
        _bearer_dep = Depends(bearer)

        async def dep(
            request: Request,
            creds: HTTPAuthorizationCredentials | None = _bearer_dep,
        ) -> Principal:
            client_host = request.client.host if request.client else None
            if creds is None or creds.scheme.lower() != "bearer":
                _audit(
                    audit_logger,
                    outcome="denied",
                    reason="no_bearer",
                    path=request.url.path,
                    client=client_host,
                )
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            try:
                principal = verifier.verify(creds.credentials)
            except AuthError as e:
                _audit(
                    audit_logger,
                    outcome="denied",
                    reason=e.detail,
                    path=request.url.path,
                    client=client_host,
                )
                raise HTTPException(
                    status_code=e.status_code,
                    detail=e.detail,
                    headers={"WWW-Authenticate": "Bearer"},
                ) from e
            if not principal.has_role_at_least(minimum):
                _audit(
                    audit_logger,
                    outcome="denied",
                    reason=f"role<{minimum}",
                    path=request.url.path,
                    client=client_host,
                    sub=principal.sub,
                    jti=principal.jti,
                    roles=sorted(principal.roles),
                )
                raise HTTPException(status_code=403, detail=f"insufficient role; need {minimum}")
            _audit(
                audit_logger,
                outcome="success",
                path=request.url.path,
                client=client_host,
                sub=principal.sub,
                jti=principal.jti,
                roles=sorted(principal.roles),
                minimum=minimum,
            )
            return principal

        return dep

    return require_role


def _audit(
    logger: Callable[[dict[str, Any]], None] | None,
    **event: Any,
) -> None:
    if logger is None:
        return
    event.setdefault("event", "operator_action")
    logger(event)
