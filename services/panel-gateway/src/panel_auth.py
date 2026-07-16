"""
Multi-operator RBAC for the panel gateway.

Named operators with roles instead of one shared secret — what a public
agency needs (accountability + least privilege). Roles form a hierarchy:

    viewer  < operator < admin

  * viewer   — watch cameras, video, data, reports
  * operator — + add/remove cameras, calibrate scenes
  * admin    — + everything (reserved for future settings/user mgmt)

Users come from PANEL_USERS: "user:role:password[,user:role:password...]".
The password may be plaintext (dev) or "sha256:<hex>" (recommended). Login
issues a compact HMAC-signed session token (stdlib only — no JWT dependency).

Backward compatible: if PANEL_API_TOKEN is set it still works and maps to the
admin role. If neither PANEL_USERS nor PANEL_API_TOKEN is set, auth is off
(local dev on 127.0.0.1).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass

log = logging.getLogger("panel.auth")

_ROLE_LEVEL = {"viewer": 1, "operator": 2, "admin": 3}
_TOKEN_TTL_S = int(os.getenv("PANEL_TOKEN_TTL_S", str(8 * 3600)))


@dataclass(frozen=True)
class Principal:
    sub: str
    role: str

    def has_role(self, minimum: str) -> bool:
        return _ROLE_LEVEL.get(self.role, 0) >= _ROLE_LEVEL.get(minimum, 99)


# --- config ---

def _users() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for entry in filter(None, (e.strip() for e in os.getenv("PANEL_USERS", "").split(","))):
        parts = entry.split(":", 2)
        if len(parts) != 3 or parts[1] not in _ROLE_LEVEL:
            log.warning("ignoring malformed PANEL_USERS entry (need user:role:password)")
            continue
        out[parts[0]] = {"role": parts[1], "password": parts[2]}
    return out


def _api_token() -> str:
    return os.getenv("PANEL_API_TOKEN", "")


def auth_enabled() -> bool:
    return bool(_users()) or bool(_api_token())


_SHORT_SECRET_WARNED = False


def _secret() -> bytes:
    s = os.getenv("PANEL_AUTH_SECRET", "")
    if s:
        if len(s.encode()) < 32:
            global _SHORT_SECRET_WARNED
            if not _SHORT_SECRET_WARNED:
                _SHORT_SECRET_WARNED = True
                log.warning(
                    "PANEL_AUTH_SECRET is only %d bytes; use >= 32 bytes of entropy "
                    "for a strong session-token HMAC key.", len(s.encode()),
                )
        return s.encode()
    # Ephemeral per-process secret: sessions won't survive a restart. Fine for
    # a single desktop instance; set PANEL_AUTH_SECRET for stable sessions.
    global _EPHEMERAL
    try:
        return _EPHEMERAL
    except NameError:
        _EPHEMERAL = secrets.token_bytes(32)
        return _EPHEMERAL


# --- password check ---

_PBKDF2_ITERS = 200_000
_WEAK_HASH_WARNED = False


def hash_password(password: str, *, iterations: int = _PBKDF2_ITERS) -> str:
    """Produce a salted PBKDF2-HMAC-SHA256 credential for PANEL_USERS:
    ``pbkdf2:<iterations>:<salt_hex>:<hash_hex>``. Run as a CLI:
    ``python -m panel_auth <password>``."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2:{iterations}:{salt.hex()}:{dk.hex()}"


def _password_ok(supplied: str, stored: str) -> bool:
    if stored.startswith("pbkdf2:"):
        try:
            _, iters, salt_hex, hash_hex = stored.split(":", 3)
            dk = hashlib.pbkdf2_hmac("sha256", supplied.encode(), bytes.fromhex(salt_hex), int(iters))
            return hmac.compare_digest(dk.hex(), hash_hex)
        except (ValueError, TypeError):
            return False
    if stored.startswith("sha256:"):
        _warn_weak_hash("sha256 (unsalted)")
        digest = hashlib.sha256(supplied.encode()).hexdigest()
        return hmac.compare_digest(digest, stored[len("sha256:"):])
    _warn_weak_hash("plaintext")
    return hmac.compare_digest(supplied, stored)


def _warn_weak_hash(kind: str) -> None:
    global _WEAK_HASH_WARNED
    if not _WEAK_HASH_WARNED:
        _WEAK_HASH_WARNED = True
        log.warning(
            "PANEL_USERS contains a %s password — prefer salted 'pbkdf2:...' "
            "credentials (generate with: python -m panel_auth <password>).", kind,
        )


def authenticate(username: str, password: str) -> Principal | None:
    user = _users().get(username)
    if user and _password_ok(password, user["password"]):
        return Principal(sub=username, role=user["role"])
    return None


# --- tokens ---

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(p: Principal, ttl_s: int = _TOKEN_TTL_S) -> tuple[str, int]:
    exp = int(time.time()) + ttl_s
    body = _b64(json.dumps({"sub": p.sub, "role": p.role, "exp": exp}).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}", exp


def principal_from_token(token: str | None) -> Principal | None:
    """Resolve a bearer token to a Principal, or None. Also accepts the legacy
    PANEL_API_TOKEN (mapped to admin)."""
    if not token:
        return None
    api = _api_token()
    if api and hmac.compare_digest(token, api):
        return Principal(sub="api-token", role="admin")
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_unb64(body))
        if payload.get("exp", 0) < time.time():
            return None
        return Principal(sub=str(payload["sub"]), role=str(payload["role"]))
    except Exception:  # noqa: BLE001
        return None


if __name__ == "__main__":
    # Credential helper: `python -m panel_auth <password>` prints a salted
    # pbkdf2 hash to paste into a PANEL_USERS entry (user:role:<hash>).
    import getpass
    import sys

    pw = sys.argv[1] if len(sys.argv) > 1 else getpass.getpass("password: ")
    print(hash_password(pw))
