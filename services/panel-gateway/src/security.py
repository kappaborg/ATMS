"""
Gateway security: camera-source validation (SSRF + path traversal) and an
optional bearer-token guard.

Camera sources are attacker-influenced input (POST /cameras). Without checks a
`source` can be an internal/metadata URL (SSRF, e.g. http://169.254.169.254/…)
or an arbitrary local file path. This module confines both:

  * URLs (rtsp/http/https): the host is resolved and link-local (cloud
    metadata), reserved, multicast, unspecified, and — by default — loopback
    addresses are rejected. Private LAN ranges are allowed because RTSP
    cameras live there; set ATMS_ALLOW_LOOPBACK_SOURCES=1 to also allow
    127.0.0.1 for local test streams.
  * File paths: confined to ATMS_ALLOWED_VIDEO_DIRS (default the repo's
    videos/ and Processed_Videos/); traversal outside is rejected.
  * A bare integer is a USB device index.

Auth: if PANEL_API_TOKEN is set, mutating and streaming endpoints require it
(Authorization: Bearer <token>, or ?token=<token> for WebSockets). Comparison
is constant-time.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

_ROOT = Path(__file__).resolve().parents[3]


class SourceRejected(ValueError):
    """Raised when a camera source fails validation."""


def _allowed_dirs() -> list[Path]:
    env = os.getenv("ATMS_ALLOWED_VIDEO_DIRS")
    if env:
        return [Path(p).expanduser().resolve() for p in env.split(os.pathsep) if p]
    return [(_ROOT / "videos").resolve(), (_ROOT / "Processed_Videos").resolve()]


def _allow_loopback() -> bool:
    return os.getenv("ATMS_ALLOW_LOOPBACK_SOURCES", "").lower() in ("1", "true", "yes")


def _allow_private_http() -> bool:
    # RTSP cameras legitimately live on private LAN ranges, but an http(s)
    # source pointed at a private address is an SSRF vector (an operator — or
    # anyone, if auth is off — can probe internal web services / metadata).
    # Blocked by default; opt in for genuine LAN HTTP(S) streams.
    return os.getenv("ATMS_ALLOW_PRIVATE_HTTP", "").lower() in ("1", "true", "yes")


def _strict_live() -> bool:
    return os.getenv("ATMS_STRICT_LIVE", "").lower() in ("1", "true", "yes")


def source_kind(source) -> str:
    """Classify a (validated) source: 'rtsp' | 'http' | 'usb' | 'file'."""
    s = str(source).strip().lower()
    if str(source).strip().isdigit():
        return "usb"
    if s.startswith("rtsp://"):
        return "rtsp"
    if s.startswith(("http://", "https://")):
        return "http"
    return "file"


def is_live_source(source) -> bool:
    """Live = a real-time device or network stream (not a recorded file)."""
    return source_kind(source) in ("rtsp", "http", "usb")


def validate_source(source: str) -> str | int:
    """Return a safe source (int USB index or a vetted URL / absolute file
    path) or raise SourceRejected."""
    s = str(source).strip()
    if not s:
        raise SourceRejected("empty source")
    if s.isdigit():
        return int(s)  # USB device index
    if s.lower().startswith(("rtsp://", "http://", "https://")):
        return _validate_url(s)
    # File source — forbidden in strict live mode (no recorded/backup video).
    if _strict_live():
        raise SourceRejected(
            "strict live mode (ATMS_STRICT_LIVE) forbids file sources — "
            "use an RTSP/HTTP stream or a USB/Continuity camera"
        )
    return _validate_file(s)


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise SourceRejected("URL has no host")
    is_http = parsed.scheme in ("http", "https")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise SourceRejected(f"cannot resolve host '{host}'") from e
    # NOTE: this validates the addresses the host resolves to *now*; FFmpeg/
    # yt-dlp re-resolve at connect time, so a DNS-rebinding attacker can still
    # move a name to an internal IP after this check. Pinning the vetted IP at
    # connect time is the remaining hardening (tracked separately).
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise SourceRejected(f"blocked address {ip} (link-local/reserved/metadata)")
        if ip.is_loopback and not _allow_loopback():
            raise SourceRejected(
                f"loopback source {ip} blocked "
                "(set ATMS_ALLOW_LOOPBACK_SOURCES=1 for local test streams)"
            )
        if is_http and ip.is_private and not (ip.is_loopback and _allow_loopback()) and not _allow_private_http():
            raise SourceRejected(
                f"private-range HTTP source {ip} blocked (SSRF guard) — "
                "set ATMS_ALLOW_PRIVATE_HTTP=1 to allow LAN HTTP(S) streams"
            )
    return url


def _validate_file(path: str) -> str:
    if "\x00" in path:
        raise SourceRejected("null byte in path")
    p = Path(path).expanduser()
    resolved = (Path.cwd() / p).resolve() if not p.is_absolute() else p.resolve()
    dirs = _allowed_dirs()
    if not any(resolved == d or d in resolved.parents for d in dirs):
        allowed = ", ".join(str(d) for d in dirs)
        raise SourceRejected(f"file source must be within: {allowed}")
    if not resolved.is_file():
        raise SourceRejected("file not found")
    return str(resolved)


# --------------------------------------------------------------------------- #
# Token auth
# --------------------------------------------------------------------------- #

def api_token() -> str:
    return os.getenv("PANEL_API_TOKEN", "")


def check_token(authorization: str | None, token_query: str | None) -> None:
    """Raise 401 if a token is configured and the supplied one is wrong/missing."""
    from fastapi import HTTPException, status

    expected = api_token()
    if not expected:
        return  # auth disabled
    supplied = None
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    elif token_query:
        supplied = token_query
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing API token"
        )
