"""Rate limiter + WebSocket connection limiter."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from limits import RateLimiter, WSLimiter, _parse_rate


def test_parse_rate():
    assert _parse_rate("30/60") == (30, 60.0)
    assert _parse_rate("garbage") == (30, 60.0)


def test_rate_limiter_blocks_over_limit():
    rl = RateLimiter("3/60")
    assert rl.allow("ip1")
    assert rl.allow("ip1")
    assert rl.allow("ip1")
    assert not rl.allow("ip1")  # 4th within window -> blocked


def test_rate_limiter_is_per_key():
    rl = RateLimiter("1/60")
    assert rl.allow("ip1")
    assert not rl.allow("ip1")
    assert rl.allow("ip2")  # different client unaffected


def test_rate_limiter_window_expiry():
    rl = RateLimiter("1/60")
    assert rl.allow("ip1")
    assert not rl.allow("ip1")
    # simulate the window passing by rewriting the recorded hit time
    rl._hits["ip1"][0] -= 61
    assert rl.allow("ip1")


def test_ws_limiter(monkeypatch):
    monkeypatch.setenv("PANEL_MAX_WS_CLIENTS", "2")
    wl = WSLimiter()
    assert wl.acquire()
    assert wl.acquire()
    assert not wl.acquire()  # cap reached
    wl.release()
    assert wl.acquire()  # slot freed
    assert wl.count == 2
