"""
JWT/RBAC enforcement on the decision-engine HTTP API.

Mirrors the Phase A6 traffic-controller auth tests for the decision-engine.
Decision-mutating endpoints require `engineer+`; read-only return `viewer+`;
mode-toggle requires `admin`.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from shared.atms_common.auth import AuthConfig, issue_hs256_test_token

import main as engine_main


@pytest.fixture
def auth_cfg() -> AuthConfig:
    return AuthConfig(
        issuer=os.environ["AUTH_ISSUER"],
        audience=os.environ["AUTH_AUDIENCE"],
        algorithm="HS256",
        hs256_secret=os.environ["AUTH_HS256_SECRET"],
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(engine_main.app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sample_body() -> dict:
    side = {
        "vehicle_count": 5,
        "average_emission": 100.0,
        "average_waiting_time": 20.0,
        "average_velocity": 15.0,
        "total_emission": 100.0,
        "environmental_impact_score": 40.0,
    }
    return {"north_south": side, "east_west": side}


class TestPublicEndpoints:
    @pytest.mark.parametrize("path", ["/", "/health", "/live", "/startup", "/ready"])
    def test_no_auth_required(self, client, path):
        r = client.get(path)
        assert r.status_code not in (401, 403), (
            f"{path} unexpectedly requires auth, got {r.status_code}"
        )


class TestHealthRouter:
    """Phase B1 health probes."""

    def test_live_returns_200(self, client):
        r = client.get("/live")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "live"
        assert body["service"] == "decision-engine"

    def test_startup_returns_200(self, client):
        # The startup_event hook isn't fired by TestClient unless we use the
        # lifespan context. Without it, /startup reports "starting". Either
        # state is fine here — we just assert the endpoint is reachable and
        # returns one of the documented states.
        r = client.get("/startup")
        assert r.status_code == 200
        assert r.json()["status"] in ("starting", "started")
        assert r.json()["service"] == "decision-engine"


class TestViewerEndpoints:
    @pytest.mark.parametrize("path", ["/phase/current", "/statistics", "/mode"])
    def test_unauthenticated_returns_401(self, client, path):
        assert client.get(path).status_code == 401

    @pytest.mark.parametrize("path", ["/phase/current", "/statistics", "/mode"])
    def test_viewer_returns_200(self, client, auth_cfg, path):
        token = issue_hs256_test_token(auth_cfg, sub="v", roles=["viewer"])
        assert client.get(path, headers=_bearer(token)).status_code == 200


class TestEngineerEndpoint:
    def test_decision_unauthenticated_returns_401(self, client):
        assert (
            client.post("/decision/make", json=_sample_body()).status_code == 401
        )

    def test_decision_viewer_returns_403(self, client, auth_cfg):
        token = issue_hs256_test_token(auth_cfg, sub="v", roles=["viewer"])
        r = client.post("/decision/make", json=_sample_body(), headers=_bearer(token))
        assert r.status_code == 403

    def test_decision_engineer_returns_200_with_principal(self, client, auth_cfg):
        token = issue_hs256_test_token(
            auth_cfg, sub="alice", roles=["engineer"], jti="jti-eng-de-1"
        )
        r = client.post(
            "/decision/make", json=_sample_body(), headers=_bearer(token)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["audit_principal_sub"] == "alice"
        assert body["audit_principal_jti"] == "jti-eng-de-1"


class TestAdminEndpoint:
    def test_set_auto_mode_engineer_403(self, client, auth_cfg):
        token = issue_hs256_test_token(auth_cfg, sub="e", roles=["engineer"])
        r = client.post("/mode/auto?enabled=true", headers=_bearer(token))
        assert r.status_code == 403

    def test_set_auto_mode_admin_200(self, client, auth_cfg):
        token = issue_hs256_test_token(auth_cfg, sub="a", roles=["admin"])
        r = client.post("/mode/auto?enabled=true", headers=_bearer(token))
        assert r.status_code == 200, r.text


class TestAuthFailureModes:
    def test_expired_token_401(self, client, auth_cfg):
        token = issue_hs256_test_token(
            auth_cfg,
            sub="v",
            roles=["viewer"],
            now=int(time.time()) - 3600,
            ttl_s=60,
        )
        assert (
            client.get("/statistics", headers=_bearer(token)).status_code == 401
        )

    def test_wrong_audience_401(self, client):
        bad_cfg = AuthConfig(
            issuer=os.environ["AUTH_ISSUER"],
            audience="atms-some-other-service",
            algorithm="HS256",
            hs256_secret=os.environ["AUTH_HS256_SECRET"],
        )
        token = issue_hs256_test_token(bad_cfg, sub="v", roles=["viewer"])
        assert (
            client.get("/statistics", headers=_bearer(token)).status_code == 401
        )


def test_acceptance_unauth_401_viewer_on_write_403_engineer_200(client, auth_cfg):
    """Mirrors the Phase A6 acceptance assertion for the decision-engine."""
    # Unauthenticated.
    assert (
        client.post("/decision/make", json=_sample_body()).status_code == 401
    )
    # Viewer on a write endpoint.
    viewer = issue_hs256_test_token(auth_cfg, sub="v", roles=["viewer"])
    assert (
        client.post(
            "/decision/make", json=_sample_body(), headers=_bearer(viewer)
        ).status_code
        == 403
    )
    # Engineer on a write endpoint.
    eng = issue_hs256_test_token(auth_cfg, sub="e", roles=["engineer"])
    assert (
        client.post(
            "/decision/make", json=_sample_body(), headers=_bearer(eng)
        ).status_code
        == 200
    )
