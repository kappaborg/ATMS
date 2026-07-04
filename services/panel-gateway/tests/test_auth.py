"""Multi-operator RBAC: login, token verification, role hierarchy."""
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import panel_auth
from panel_auth import (
    Principal,
    auth_enabled,
    authenticate,
    issue_token,
    principal_from_token,
)


def test_disabled_when_no_users_or_token(monkeypatch):
    monkeypatch.delenv("PANEL_USERS", raising=False)
    monkeypatch.delenv("PANEL_API_TOKEN", raising=False)
    assert auth_enabled() is False


def test_login_and_token_roundtrip(monkeypatch):
    monkeypatch.setenv("PANEL_USERS", "alice:admin:pw1,bob:operator:pw2,eve:viewer:pw3")
    monkeypatch.setenv("PANEL_AUTH_SECRET", "test-secret")
    assert auth_enabled() is True
    p = authenticate("bob", "pw2")
    assert p == Principal("bob", "operator")
    assert authenticate("bob", "wrong") is None
    assert authenticate("nobody", "x") is None
    token, _exp = issue_token(p)
    back = principal_from_token(token)
    assert back == Principal("bob", "operator")


def test_role_hierarchy():
    assert Principal("a", "admin").has_role("operator")
    assert Principal("a", "operator").has_role("viewer")
    assert not Principal("a", "viewer").has_role("operator")
    assert not Principal("a", "operator").has_role("admin")


def test_tampered_or_expired_token_rejected(monkeypatch):
    monkeypatch.setenv("PANEL_USERS", "alice:admin:pw1")
    monkeypatch.setenv("PANEL_AUTH_SECRET", "test-secret")
    token, _ = issue_token(Principal("alice", "admin"))
    body, sig = token.split(".", 1)
    assert principal_from_token(f"{body}.{sig}xx") is None  # bad signature
    assert principal_from_token("garbage") is None
    # expired
    expired, _ = issue_token(Principal("alice", "admin"), ttl_s=-10)
    assert principal_from_token(expired) is None


def test_sha256_password_hash(monkeypatch):
    h = hashlib.sha256(b"secretpw").hexdigest()
    monkeypatch.setenv("PANEL_USERS", f"carol:operator:sha256:{h}")
    assert authenticate("carol", "secretpw") == Principal("carol", "operator")
    assert authenticate("carol", "nope") is None


def test_legacy_api_token_maps_to_admin(monkeypatch):
    monkeypatch.delenv("PANEL_USERS", raising=False)
    monkeypatch.setenv("PANEL_API_TOKEN", "legacy123")
    assert principal_from_token("legacy123") == Principal("api-token", "admin")
    assert principal_from_token("wrong") is None


def test_malformed_users_ignored(monkeypatch):
    monkeypatch.setenv("PANEL_USERS", "bad-entry,x:notarole:pw,good:viewer:pw")
    assert authenticate("good", "pw") == Principal("good", "viewer")
    assert authenticate("x", "pw") is None
