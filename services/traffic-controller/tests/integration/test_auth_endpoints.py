"""
End-to-end test of the JWT/RBAC gate on the traffic-controller HTTP API.

Uses FastAPI's TestClient — no Kafka, no real network. Asserts the gap-#12
acceptance criteria from SENIOR_ENGINEER_PROMPT:

- Unauthenticated request to a protected endpoint returns 401.
- Viewer role on a write endpoint returns 403.
- Engineer role on a write endpoint returns 200 (and the action takes effect).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# conftest.py at the service root sets AUTH_HS256_SECRET / AUTH_ISSUER /
# AUTH_AUDIENCE before main.py is imported. The values below MUST match.
_PROJECT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_PROJECT))
sys.path.insert(0, str(_PROJECT / "services/traffic-controller/src"))

from shared.atms_common.auth import AuthConfig, issue_hs256_test_token  # noqa: E402

import main as controller_main  # noqa: E402


@pytest.fixture
def auth_cfg() -> AuthConfig:
    return AuthConfig(
        issuer=os.environ["AUTH_ISSUER"],
        audience=os.environ["AUTH_AUDIENCE"],
        algorithm="HS256",
        hs256_secret=os.environ["AUTH_HS256_SECRET"],
        clock_skew_s=int(os.environ.get("AUTH_CLOCK_SKEW_S", "5")),
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(controller_main.app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Probes and public endpoints — no auth.
# ---------------------------------------------------------------------------


class TestPublicEndpoints:
    @pytest.mark.parametrize("path", ["/live", "/ready", "/startup", "/health", "/"])
    def test_no_auth_required(self, client, path):
        r = client.get(path)
        # /ready returns 503 when startup hasn't completed; that is itself a
        # "I responded without auth" outcome — anything other than 401/403 is fine.
        assert r.status_code not in (401, 403), (
            f"{path} should not require auth, got {r.status_code}"
        )


# ---------------------------------------------------------------------------
# Viewer endpoints
# ---------------------------------------------------------------------------


class TestViewerEndpoints:
    def test_status_unauthenticated_returns_401(self, client):
        assert client.get("/status").status_code == 401

    def test_status_viewer_returns_200(self, client, auth_cfg):
        token = issue_hs256_test_token(auth_cfg, sub="bob", roles=["viewer"])
        r = client.get("/status", headers=_bearer(token))
        assert r.status_code == 200
        assert r.json()["intersection_id"] == controller_main.service.intersection_id

    def test_status_engineer_can_also_view(self, client, auth_cfg):
        token = issue_hs256_test_token(auth_cfg, sub="alice", roles=["engineer"])
        assert client.get("/status", headers=_bearer(token)).status_code == 200

    def test_status_expired_token_returns_401(self, client, auth_cfg):
        import time as _time  # noqa: PLC0415

        token = issue_hs256_test_token(
            auth_cfg, sub="bob", roles=["viewer"], now=int(_time.time()) - 3600, ttl_s=60
        )
        assert client.get("/status", headers=_bearer(token)).status_code == 401

    def test_status_wrong_audience_returns_401(self, client):
        bad_cfg = AuthConfig(
            issuer=os.environ["AUTH_ISSUER"],
            audience="some-other-service",
            algorithm="HS256",
            hs256_secret=os.environ["AUTH_HS256_SECRET"],
        )
        token = issue_hs256_test_token(bad_cfg, sub="bob", roles=["viewer"])
        assert client.get("/status", headers=_bearer(token)).status_code == 401


# ---------------------------------------------------------------------------
# Engineer endpoints (write / mutate)
# ---------------------------------------------------------------------------


class TestEngineerEndpoints:
    def test_emergency_unauthenticated_returns_401(self, client):
        r = client.post("/control/emergency", json={"reason": "test"})
        assert r.status_code == 401
        assert r.headers.get("WWW-Authenticate", "").lower().startswith("bearer")

    def test_emergency_viewer_returns_403(self, client, auth_cfg):
        token = issue_hs256_test_token(auth_cfg, sub="bob", roles=["viewer"])
        r = client.post(
            "/control/emergency", json={"reason": "test"}, headers=_bearer(token)
        )
        assert r.status_code == 403

    def test_emergency_engineer_returns_200_and_acts(self, client, auth_cfg):
        from failsafe import Mode  # noqa: PLC0415

        # Reset failsafe mode before the test (it may be in ALL_RED_FLASH from a
        # previous test in this module).
        controller_main.service.failsafe.force_mode(
            Mode.FIXED_TIME, reason="test_reset"
        )

        token = issue_hs256_test_token(
            auth_cfg, sub="alice", roles=["engineer"], jti="jti-eng-1"
        )
        r = client.post(
            "/control/emergency",
            json={"reason": "smoke_test"},
            headers=_bearer(token),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "all_red_flash"
        assert body["principal_sub"] == "alice"
        assert (
            controller_main.service.failsafe.current_mode().value == "all_red_flash"
        )

    def test_recover_engineer_returns_200(self, client, auth_cfg):
        from failsafe import Mode  # noqa: PLC0415

        # Put it in ALL_RED_FLASH first via direct call.
        controller_main.service.failsafe.force_mode(
            Mode.ALL_RED_FLASH, reason="setup"
        )
        token = issue_hs256_test_token(auth_cfg, sub="alice", roles=["engineer"])
        r = client.post(
            "/control/recover",
            json={"target": "fixed_time", "reason": "post-walkthrough"},
            headers=_bearer(token),
        )
        assert r.status_code == 200
        assert r.json()["mode"] == "fixed_time"

    def test_recover_bad_target_returns_400(self, client, auth_cfg):
        token = issue_hs256_test_token(auth_cfg, sub="alice", roles=["engineer"])
        r = client.post(
            "/control/recover",
            json={"target": "not_a_mode", "reason": "x"},
            headers=_bearer(token),
        )
        # 400 = engineer authenticated AND authorized, but request body invalid.
        assert r.status_code == 400

    def test_manual_engineer_returns_410_not_403(self, client, auth_cfg):
        # /control/manual still requires engineer (so it can't be probed without
        # auth) but the engineer sees a 410 telling them to use the proper path.
        token = issue_hs256_test_token(auth_cfg, sub="alice", roles=["engineer"])
        r = client.post(
            "/control/manual",
            json={"direction": "north_south", "state": "green"},
            headers=_bearer(token),
        )
        assert r.status_code == 410

    def test_manual_viewer_returns_403(self, client, auth_cfg):
        token = issue_hs256_test_token(auth_cfg, sub="bob", roles=["viewer"])
        r = client.post(
            "/control/manual",
            json={"direction": "north_south", "state": "green"},
            headers=_bearer(token),
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Acceptance-criteria coverage in one explicit test (PROMPT gap #12).
# ---------------------------------------------------------------------------


def test_acceptance_unauth_401_viewer_on_write_403_engineer_200(client, auth_cfg):
    from failsafe import Mode  # noqa: PLC0415

    controller_main.service.failsafe.force_mode(Mode.FIXED_TIME, reason="ac_reset")

    # Unauthenticated request to a protected endpoint returns 401.
    assert client.post("/control/emergency", json={"reason": "x"}).status_code == 401

    # Viewer role on a write endpoint returns 403.
    viewer = issue_hs256_test_token(auth_cfg, sub="v", roles=["viewer"])
    r = client.post(
        "/control/emergency", json={"reason": "x"}, headers=_bearer(viewer)
    )
    assert r.status_code == 403

    # Engineer role on a write endpoint returns 200.
    eng = issue_hs256_test_token(auth_cfg, sub="e", roles=["engineer"])
    r = client.post("/control/emergency", json={"reason": "x"}, headers=_bearer(eng))
    assert r.status_code == 200
