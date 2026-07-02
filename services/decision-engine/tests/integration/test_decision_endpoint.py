"""
End-to-end test of the /decision/make endpoint.

Verifies the A1+A3 contract: a successful POST emits a wire schema that the
failsafe controller's validator (shared.atms_common.decision) accepts.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from shared.atms_common.auth import AuthConfig, issue_hs256_test_token
from shared.atms_common.decision import CommandedPhase, DecisionMessage

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


@pytest.fixture
def engineer_headers(auth_cfg) -> dict[str, str]:
    tok = issue_hs256_test_token(auth_cfg, sub="alice", roles=["engineer"])
    return {"Authorization": f"Bearer {tok}"}


def _sample_request(*, ns_busy: bool = True) -> dict:
    """Return a request body biased toward the given direction."""
    busy = {
        "vehicle_count": 18,
        "average_emission": 150.0,
        "average_waiting_time": 45.0,
        "average_velocity": 6.0,
        "total_emission": 150.0,
        "environmental_impact_score": 60.0,
    }
    quiet = {
        "vehicle_count": 2,
        "average_emission": 30.0,
        "average_waiting_time": 5.0,
        "average_velocity": 25.0,
        "total_emission": 30.0,
        "environmental_impact_score": 10.0,
    }
    return {
        "north_south": busy if ns_busy else quiet,
        "east_west": quiet if ns_busy else busy,
    }


class TestDecisionEndpointSchema:
    def test_response_has_required_wire_fields(self, client, engineer_headers):
        r = client.post(
            "/decision/make", json=_sample_request(), headers=engineer_headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        for f in (
            "decision_id",
            "intersection_id",
            "producer_timestamp_ns",
            "valid_until_ns",
            "commanded_phase",
            "priority",
            "confidence",
            "reason",
        ):
            assert f in body, f"missing wire field: {f}"

    def test_response_validates_against_decisionmessage(self, client, engineer_headers):
        r = client.post(
            "/decision/make", json=_sample_request(), headers=engineer_headers
        )
        body = r.json()
        parsed = DecisionMessage.from_dict(body)
        assert isinstance(parsed, DecisionMessage), (
            f"failed to parse wire body as DecisionMessage: {parsed}"
        )
        # And the controller's validation gate (intersection match, monotonic,
        # not expired, not future-dated) accepts it.
        now_ns = time.monotonic_ns()
        result = parsed.validate_for_controller(
            controller_intersection_id=parsed.intersection_id,
            last_accepted_decision_id=None,
            now_ns=now_ns,
        )
        assert result.ok, f"controller rejected wire decision: {result.status}"

    def test_commanded_phase_reflects_priority_direction_ns(
        self, client, engineer_headers
    ):
        r = client.post(
            "/decision/make",
            json=_sample_request(ns_busy=True),
            headers=engineer_headers,
        )
        wire = CommandedPhase(r.json()["commanded_phase"])
        # NS is busy → either ns_green (priority gets green) or all_red
        # (initial phase / transition). Critical: NEVER ew_green when NS is busy.
        assert wire in (
            CommandedPhase.NS_GREEN,
            CommandedPhase.NS_YELLOW,
            CommandedPhase.ALL_RED,
        ), f"NS busy yielded {wire}"

    def test_commanded_phase_reflects_priority_direction_ew(
        self, client, engineer_headers
    ):
        r = client.post(
            "/decision/make",
            json=_sample_request(ns_busy=False),
            headers=engineer_headers,
        )
        wire = CommandedPhase(r.json()["commanded_phase"])
        assert wire in (
            CommandedPhase.EW_GREEN,
            CommandedPhase.EW_YELLOW,
            CommandedPhase.ALL_RED,
        ), f"EW busy yielded {wire}"


class TestMonotonicAcrossRequests:
    def test_two_calls_emit_strictly_increasing_decision_id(
        self, client, engineer_headers
    ):
        a = client.post(
            "/decision/make", json=_sample_request(), headers=engineer_headers
        ).json()
        b = client.post(
            "/decision/make", json=_sample_request(), headers=engineer_headers
        ).json()
        assert b["decision_id"] > a["decision_id"]

    def test_consecutive_emit_valid_ttls(self, client, engineer_headers):
        r = client.post(
            "/decision/make", json=_sample_request(), headers=engineer_headers
        )
        body = r.json()
        # valid_until must be strictly after producer_timestamp
        assert body["valid_until_ns"] > body["producer_timestamp_ns"]
        # TTL is configured at DECISION_TTL_MS (default 2500). Sanity-check it's
        # in [1s, 30s].
        ttl_ns = body["valid_until_ns"] - body["producer_timestamp_ns"]
        assert 1_000_000_000 <= ttl_ns <= 30_000_000_000


class TestRegressionBugA3:
    def test_busy_direction_does_not_always_collapse_to_all_red(
        self, client, engineer_headers
    ):
        """
        Regression for the A1-era bug fixed in A3: prior to the fix, every
        decision mapped to `all_red` because `_to_commanded_phase` expected a
        directional input the AI engine never produced.
        """
        seen = set()
        for _ in range(5):
            r = client.post(
                "/decision/make",
                json=_sample_request(ns_busy=True),
                headers=engineer_headers,
            )
            seen.add(r.json()["commanded_phase"])
        assert seen - {"all_red"}, (
            "all responses were `all_red` — A1-era bug is back"
        )
