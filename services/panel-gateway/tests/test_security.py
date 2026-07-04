"""Camera-source validation (SSRF + path traversal) and token auth."""
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "services" / "panel-gateway" / "src"))
import security
from security import SourceRejected, check_token, validate_source


def test_usb_index_ok():
    assert validate_source("0") == 0
    assert validate_source("2") == 2


def test_cloud_metadata_ip_blocked():
    # The classic SSRF target — link-local, must be rejected.
    with pytest.raises(SourceRejected):
        validate_source("http://169.254.169.254/latest/meta-data/")


def test_loopback_blocked_by_default(monkeypatch):
    monkeypatch.delenv("ATMS_ALLOW_LOOPBACK_SOURCES", raising=False)
    with pytest.raises(SourceRejected):
        validate_source("rtsp://127.0.0.1:554/stream")
    with pytest.raises(SourceRejected):
        validate_source("http://localhost:8090/")


def test_loopback_allowed_with_optin(monkeypatch):
    monkeypatch.setenv("ATMS_ALLOW_LOOPBACK_SOURCES", "1")
    assert validate_source("rtsp://127.0.0.1:554/stream").startswith("rtsp://")


def test_lan_and_public_urls_allowed():
    # RTSP cameras live on the LAN — private ranges must stay usable.
    assert validate_source("rtsp://192.168.1.20:554/h264") == "rtsp://192.168.1.20:554/h264"
    assert validate_source("http://8.8.8.8/stream") == "http://8.8.8.8/stream"


def test_unresolvable_host_rejected():
    with pytest.raises(SourceRejected):
        validate_source("rtsp://no.such.host.invalid/stream")


def test_file_traversal_blocked():
    with pytest.raises(SourceRejected):
        validate_source("/etc/passwd")
    with pytest.raises(SourceRejected):
        validate_source("../../../../etc/hosts")


def test_allowed_video_file_ok(tmp_path, monkeypatch):
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"x")
    monkeypatch.setenv("ATMS_ALLOWED_VIDEO_DIRS", str(tmp_path))
    assert validate_source(str(vid)) == str(vid.resolve())


def test_missing_file_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("ATMS_ALLOWED_VIDEO_DIRS", str(tmp_path))
    with pytest.raises(SourceRejected):
        validate_source(str(tmp_path / "nope.mp4"))


def test_empty_source_rejected():
    with pytest.raises(SourceRejected):
        validate_source("   ")


def test_strict_live_rejects_files_allows_streams(tmp_path, monkeypatch):
    from security import is_live_source, source_kind

    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"x")
    monkeypatch.setenv("ATMS_ALLOWED_VIDEO_DIRS", str(tmp_path))
    monkeypatch.setenv("ATMS_STRICT_LIVE", "1")
    # file rejected in strict live mode
    with pytest.raises(SourceRejected):
        validate_source(str(vid))
    # live sources still fine
    assert validate_source("0") == 0
    assert validate_source("rtsp://192.168.1.20:554/h264").startswith("rtsp://")
    # classification
    assert is_live_source("rtsp://x/y") and is_live_source("0") and not is_live_source("a.mp4")
    assert source_kind("http://x/y") == "http" and source_kind("a.mp4") == "file"


# --- token auth ---

def test_token_disabled_allows_all(monkeypatch):
    monkeypatch.delenv("PANEL_API_TOKEN", raising=False)
    check_token(None, None)  # no raise


def test_token_required_and_matched(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("PANEL_API_TOKEN", "s3cret")
    with pytest.raises(HTTPException):
        check_token(None, None)
    with pytest.raises(HTTPException):
        check_token("Bearer wrong", None)
    check_token("Bearer s3cret", None)  # header ok
    check_token(None, "s3cret")  # query ok (WebSocket path)
