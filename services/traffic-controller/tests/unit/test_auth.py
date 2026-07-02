"""Unit tests for shared/atms_common/auth.py."""

from __future__ import annotations

import time

import pytest
from shared.atms_common.auth import (
    AuthConfig,
    AuthError,
    JWTVerifier,
    Principal,
    issue_hs256_test_token,
    role_at_least,
)


@pytest.fixture
def cfg() -> AuthConfig:
    return AuthConfig(
        issuer="atms-test",
        audience="atms-traffic-controller",
        algorithm="HS256",
        hs256_secret="unit-secret",
        clock_skew_s=5,
    )


@pytest.fixture
def verifier(cfg) -> JWTVerifier:
    return JWTVerifier(cfg)


# ---------------------------------------------------------------------------
# Role hierarchy
# ---------------------------------------------------------------------------


class TestRoleHierarchy:
    def test_self_is_at_least_self(self):
        for r in ("viewer", "operator", "engineer", "admin"):
            assert role_at_least(r, r)

    def test_admin_dominates_all(self):
        for r in ("viewer", "operator", "engineer", "admin"):
            assert role_at_least("admin", r)

    def test_viewer_below_engineer(self):
        assert not role_at_least("viewer", "engineer")

    def test_unknown_role_returns_false(self):
        assert not role_at_least("ghost", "viewer")
        assert not role_at_least("viewer", "ghost")


class TestPrincipal:
    def test_has_role_at_least(self):
        p = Principal(sub="u1", roles=frozenset({"engineer"}))
        assert p.has_role_at_least("viewer")
        assert p.has_role_at_least("engineer")
        assert not p.has_role_at_least("admin")

    def test_multi_role_picks_highest(self):
        p = Principal(sub="u1", roles=frozenset({"viewer", "engineer"}))
        assert p.has_role_at_least("engineer")


# ---------------------------------------------------------------------------
# JWTVerifier (HS256)
# ---------------------------------------------------------------------------


class TestVerifyHS256:
    def test_happy_path(self, verifier, cfg):
        token = issue_hs256_test_token(cfg, sub="alice", roles=["engineer"], jti="jti-1")
        p = verifier.verify(token)
        assert p.sub == "alice"
        assert "engineer" in p.roles
        assert p.jti == "jti-1"

    def test_expired(self, verifier, cfg):
        token = issue_hs256_test_token(
            cfg,
            sub="alice",
            roles=["engineer"],
            now=int(time.time()) - 3600,
            ttl_s=60,
        )
        with pytest.raises(AuthError) as exc:
            verifier.verify(token)
        assert exc.value.status_code == 401
        assert "expired" in exc.value.detail

    def test_wrong_issuer(self, cfg):
        bad_iss_cfg = AuthConfig(
            issuer="wrong-issuer",
            audience=cfg.audience,
            algorithm="HS256",
            hs256_secret=cfg.hs256_secret,
        )
        # Token issued under the wrong issuer
        token = issue_hs256_test_token(bad_iss_cfg, sub="x", roles=["viewer"])
        v = JWTVerifier(cfg)
        with pytest.raises(AuthError) as exc:
            v.verify(token)
        assert "issuer" in exc.value.detail

    def test_wrong_audience(self, cfg):
        bad_aud_cfg = AuthConfig(
            issuer=cfg.issuer,
            audience="not-this-service",
            algorithm="HS256",
            hs256_secret=cfg.hs256_secret,
        )
        token = issue_hs256_test_token(bad_aud_cfg, sub="x", roles=["viewer"])
        v = JWTVerifier(cfg)
        with pytest.raises(AuthError) as exc:
            v.verify(token)
        assert "audience" in exc.value.detail

    def test_tampered(self, verifier, cfg):
        token = issue_hs256_test_token(cfg, sub="alice", roles=["engineer"])
        # Flip a byte in the signature segment (last segment of the JWT).
        head, payload, sig = token.split(".")
        tampered_sig = "AAAA" + sig[4:]
        bad = ".".join([head, payload, tampered_sig])
        with pytest.raises(AuthError) as exc:
            verifier.verify(bad)
        assert exc.value.status_code == 401

    def test_missing_required_claim(self, verifier, cfg):
        # Sign a token without "sub". issue_hs256_test_token always sets sub,
        # so go through PyJWT directly here.
        import jwt as _jwt  # noqa: PLC0415

        payload = {
            "iss": cfg.issuer,
            "aud": cfg.audience,
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
            "roles": ["viewer"],
        }
        token = _jwt.encode(payload, cfg.hs256_secret, algorithm="HS256")
        with pytest.raises(AuthError) as exc:
            verifier.verify(token)
        assert "sub" in exc.value.detail or "claim" in exc.value.detail

    def test_wrong_secret(self, verifier, cfg):
        evil_cfg = AuthConfig(
            issuer=cfg.issuer,
            audience=cfg.audience,
            algorithm="HS256",
            hs256_secret="not-the-real-secret",
        )
        token = issue_hs256_test_token(evil_cfg, sub="x", roles=["engineer"])
        with pytest.raises(AuthError):
            verifier.verify(token)


class TestVerifierConfig:
    def test_hs256_requires_secret(self):
        with pytest.raises(ValueError, match="HS256 requires hs256_secret"):
            JWTVerifier(AuthConfig(issuer="x", audience="y", algorithm="HS256", hs256_secret=None))

    def test_rs256_requires_jwks_uri(self):
        with pytest.raises(ValueError, match="RS256 requires rs256_jwks_uri"):
            JWTVerifier(
                AuthConfig(
                    issuer="x",
                    audience="y",
                    algorithm="RS256",
                    rs256_jwks_uri=None,
                )
            )

    def test_unsupported_algorithm(self):
        with pytest.raises(ValueError, match="unsupported algorithm"):
            JWTVerifier(
                AuthConfig(
                    issuer="x",
                    audience="y",
                    algorithm="none",
                    hs256_secret="s",
                )
            )


# ---------------------------------------------------------------------------
# JWTVerifier (RS256 / JWKS)
# ---------------------------------------------------------------------------

import json  # noqa: E402

import jwt as _jwt  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from jwt import PyJWKClient  # noqa: E402


class _FakeJWKSClient(PyJWKClient):
    """Test double — returns a pre-built JWKS dict without HTTP I/O.

    Overrides `fetch_data` so `get_signing_key_from_jwt` resolves keys from
    the canned dict. Calls to `fetch_data` are counted so tests can assert
    refresh behaviour.
    """

    def __init__(self, jwks: dict) -> None:
        super().__init__(uri="http://fake-jwks/never-fetched", cache_keys=True, lifespan=300)
        self._jwks = jwks
        self.fetch_calls = 0

    def fetch_data(self) -> dict:
        self.fetch_calls += 1
        return self._jwks


def _make_rsa_keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


def _to_jwk(public_key, *, kid: str) -> dict:
    jwk_str = _jwt.algorithms.RSAAlgorithm.to_jwk(public_key)
    jwk = json.loads(jwk_str)
    jwk["kid"] = kid
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return jwk


def _pem(private_key) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _sign_rs256(
    private_key,
    *,
    iss: str,
    aud: str,
    sub: str,
    roles: list[str],
    kid: str,
    ttl_s: int = 60,
    issued_offset: int = 0,
    jti: str | None = None,
) -> str:
    now = int(time.time()) + issued_offset
    payload: dict = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "iat": now,
        "exp": now + ttl_s,
        "roles": roles,
    }
    if jti is not None:
        payload["jti"] = jti
    return _jwt.encode(payload, _pem(private_key), algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def rsa_keys():
    return _make_rsa_keypair()


@pytest.fixture
def rs256_cfg() -> AuthConfig:
    return AuthConfig(
        issuer="atms-test-idp",
        audience="atms-traffic-controller",
        algorithm="RS256",
        rs256_jwks_uri="http://jwks-not-fetched-in-tests",
        clock_skew_s=5,
    )


@pytest.fixture
def jwks(rsa_keys) -> dict:
    _, public = rsa_keys
    return {"keys": [_to_jwk(public, kid="atms-key-1")]}


@pytest.fixture
def rs256_verifier(rs256_cfg, jwks) -> JWTVerifier:
    return JWTVerifier(rs256_cfg, jwks_client=_FakeJWKSClient(jwks))


class TestVerifyRS256:
    def test_happy_path(self, rs256_verifier, rsa_keys, rs256_cfg):
        private, _ = rsa_keys
        token = _sign_rs256(
            private,
            iss=rs256_cfg.issuer,
            aud=rs256_cfg.audience,
            sub="alice",
            roles=["engineer"],
            kid="atms-key-1",
            jti="rs-jti-1",
        )
        p = rs256_verifier.verify(token)
        assert p.sub == "alice"
        assert "engineer" in p.roles
        assert p.jti == "rs-jti-1"

    def test_expired(self, rs256_verifier, rsa_keys, rs256_cfg):
        private, _ = rsa_keys
        token = _sign_rs256(
            private,
            iss=rs256_cfg.issuer,
            aud=rs256_cfg.audience,
            sub="alice",
            roles=["engineer"],
            kid="atms-key-1",
            issued_offset=-3600,
        )
        with pytest.raises(AuthError) as exc:
            rs256_verifier.verify(token)
        assert exc.value.status_code == 401
        assert "expired" in exc.value.detail

    def test_wrong_issuer(self, rs256_verifier, rsa_keys, rs256_cfg):
        private, _ = rsa_keys
        token = _sign_rs256(
            private,
            iss="wrong-idp",
            aud=rs256_cfg.audience,
            sub="x",
            roles=["viewer"],
            kid="atms-key-1",
        )
        with pytest.raises(AuthError) as exc:
            rs256_verifier.verify(token)
        assert "issuer" in exc.value.detail

    def test_wrong_audience(self, rs256_verifier, rsa_keys, rs256_cfg):
        private, _ = rsa_keys
        token = _sign_rs256(
            private,
            iss=rs256_cfg.issuer,
            aud="not-this-service",
            sub="x",
            roles=["viewer"],
            kid="atms-key-1",
        )
        with pytest.raises(AuthError) as exc:
            rs256_verifier.verify(token)
        assert "audience" in exc.value.detail

    def test_missing_kid_header(self, rs256_verifier, rsa_keys, rs256_cfg):
        # Forge a token without 'kid' in the header.
        private, _ = rsa_keys
        now = int(time.time())
        payload = {
            "iss": rs256_cfg.issuer,
            "aud": rs256_cfg.audience,
            "sub": "x",
            "iat": now,
            "exp": now + 60,
            "roles": ["viewer"],
        }
        token = _jwt.encode(payload, _pem(private), algorithm="RS256")  # no kid
        with pytest.raises(AuthError) as exc:
            rs256_verifier.verify(token)
        assert "kid" in exc.value.detail

    def test_unknown_kid(self, rs256_verifier, rsa_keys, rs256_cfg):
        # Sign with a kid the JWKS doesn't publish.
        private, _ = rsa_keys
        token = _sign_rs256(
            private,
            iss=rs256_cfg.issuer,
            aud=rs256_cfg.audience,
            sub="x",
            roles=["viewer"],
            kid="rotated-out-key",
        )
        with pytest.raises(AuthError) as exc:
            rs256_verifier.verify(token)
        assert exc.value.status_code == 401
        assert "JWKS" in exc.value.detail or "key" in exc.value.detail.lower()

    def test_tampered_signature(self, rs256_verifier, rsa_keys, rs256_cfg):
        private, _ = rsa_keys
        token = _sign_rs256(
            private,
            iss=rs256_cfg.issuer,
            aud=rs256_cfg.audience,
            sub="x",
            roles=["viewer"],
            kid="atms-key-1",
        )
        head, payload, sig = token.split(".")
        tampered = ".".join([head, payload, "AAAA" + sig[4:]])
        with pytest.raises(AuthError) as exc:
            rs256_verifier.verify(tampered)
        assert exc.value.status_code == 401

    def test_signed_by_different_key(self, rs256_verifier, rs256_cfg):
        # Adversary signs with a different RSA key — the JWKS will publish
        # a key under 'atms-key-1' but the signature won't verify against it.
        evil_private, _ = _make_rsa_keypair()
        token = _sign_rs256(
            evil_private,
            iss=rs256_cfg.issuer,
            aud=rs256_cfg.audience,
            sub="x",
            roles=["viewer"],
            kid="atms-key-1",  # claims the legitimate kid
        )
        with pytest.raises(AuthError) as exc:
            rs256_verifier.verify(token)
        assert exc.value.status_code == 401

    def test_jwks_caches_across_verifications(self, rs256_verifier, rsa_keys, rs256_cfg):
        private, _ = rsa_keys
        client = rs256_verifier._jwks_client
        assert isinstance(client, _FakeJWKSClient)
        client.fetch_calls = 0  # reset; constructor may have called

        for i in range(3):
            token = _sign_rs256(
                private,
                iss=rs256_cfg.issuer,
                aud=rs256_cfg.audience,
                sub=f"u{i}",
                roles=["viewer"],
                kid="atms-key-1",
            )
            rs256_verifier.verify(token)

        # Three verifications should not trigger three JWKS fetches — at most one.
        assert client.fetch_calls <= 1
