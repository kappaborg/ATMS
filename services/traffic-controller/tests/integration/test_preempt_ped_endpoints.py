"""
HTTP endpoint tests for /control/preempt, /control/preempt/clear,
and /control/ped-call (Phase A7).

Verifies auth gates (engineer for preempt, operator for ped-call) and end-to-end
behaviour through the FastAPI TestClient.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from shared.atms_common.auth import AuthConfig, issue_hs256_test_token

import main as controller_main
from failsafe import Mode


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
    return TestClient(controller_main.app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _preempt_body(approach: str = "north_south", priority: str = "fire_rescue") -> dict:
    return {
        "approach": approach,
        "priority": priority,
        "valid_until_ns": time.monotonic_ns() + 30 * 1_000_000_000,
        "transponder_id": "TX-001",
    }


def _ped_call_body(approach: str = "north_south", accessibility: bool = False) -> dict:
    return {
        "approach": approach,
        "valid_until_ns": time.monotonic_ns() + 30 * 1_000_000_000,
        "accessibility": accessibility,
    }


@pytest.fixture(autouse=True)
def reset_failsafe():
    """Each test starts with the controller in FIXED_TIME and no preempt/ped state."""
    # Clear any state from prior tests.
    controller_main.service.failsafe.force_mode(Mode.FIXED_TIME, reason="test_reset")
    controller_main.service.failsafe._active_preempt = None
    controller_main.service.failsafe._preempt_armed_at_ns = 0
    controller_main.service.failsafe._ped_queue.clear()
    yield


class TestPreemptArm:
    def test_unauthenticated_401(self, client):
        assert client.post("/control/preempt", json=_preempt_body()).status_code == 401

    def test_viewer_403(self, client, auth_cfg):
        tok = issue_hs256_test_token(auth_cfg, sub="v", roles=["viewer"])
        assert (
            client.post(
                "/control/preempt", json=_preempt_body(), headers=_bearer(tok)
            ).status_code
            == 403
        )

    def test_engineer_200_arms_preempt(self, client, auth_cfg):
        tok = issue_hs256_test_token(auth_cfg, sub="alice", roles=["engineer"])
        r = client.post("/control/preempt", json=_preempt_body(), headers=_bearer(tok))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["armed"] is True
        assert body["approach"] == "north_south"
        assert body["principal_sub"] == "alice"
        assert controller_main.service.failsafe.has_active_preempt()

    def test_invalid_approach_400(self, client, auth_cfg):
        tok = issue_hs256_test_token(auth_cfg, sub="e", roles=["engineer"])
        bad = _preempt_body()
        bad["approach"] = "diagonal"
        r = client.post("/control/preempt", json=bad, headers=_bearer(tok))
        assert r.status_code == 400


class TestPreemptClear:
    def test_clear_after_min_dwell(self, client, auth_cfg):
        tok = issue_hs256_test_token(auth_cfg, sub="e", roles=["engineer"])
        client.post("/control/preempt", json=_preempt_body(), headers=_bearer(tok))
        # Simulate dwell by advancing the failsafe's view of time.
        controller_main.service.failsafe._preempt_armed_at_ns -= int(
            (controller_main.service.failsafe._cfg.preempt_min_dwell_s + 1) * 1e9
        )
        r = client.post(
            "/control/preempt/clear",
            json={"approach": "north_south", "reason": "test_clear"},
            headers=_bearer(tok),
        )
        assert r.status_code == 200
        assert r.json()["cleared"] is True


class TestPedCall:
    def test_unauthenticated_401(self, client):
        assert client.post("/control/ped-call", json=_ped_call_body()).status_code == 401

    def test_viewer_403(self, client, auth_cfg):
        tok = issue_hs256_test_token(auth_cfg, sub="v", roles=["viewer"])
        r = client.post(
            "/control/ped-call", json=_ped_call_body(), headers=_bearer(tok)
        )
        assert r.status_code == 403

    def test_operator_200_queues_call(self, client, auth_cfg):
        tok = issue_hs256_test_token(auth_cfg, sub="op", roles=["operator"])
        r = client.post(
            "/control/ped-call", json=_ped_call_body(), headers=_bearer(tok)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["queued"] is True
        assert body["accessibility"] is False
        assert body["principal_sub"] == "op"

    def test_accessibility_call_propagates(self, client, auth_cfg):
        tok = issue_hs256_test_token(auth_cfg, sub="op", roles=["operator"])
        r = client.post(
            "/control/ped-call",
            json=_ped_call_body(accessibility=True),
            headers=_bearer(tok),
        )
        assert r.status_code == 200
        assert r.json()["accessibility"] is True

    def test_invalid_approach_400(self, client, auth_cfg):
        tok = issue_hs256_test_token(auth_cfg, sub="op", roles=["operator"])
        bad = _ped_call_body()
        bad["approach"] = "up"
        r = client.post("/control/ped-call", json=bad, headers=_bearer(tok))
        assert r.status_code == 400
