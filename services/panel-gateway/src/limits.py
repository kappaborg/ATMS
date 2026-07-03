"""
Resource + rate limits — the third leg of gateway hardening (after auth and
source validation). Without these, a client can exhaust the host by spamming
camera-adds, registering thousands of cameras, or opening unbounded
WebSocket connections.

Config (env):
  PANEL_MAX_CAMERAS      max concurrent cameras          (default 8)
  PANEL_MAX_WS_CLIENTS   max concurrent WS connections   (default 32)
  PANEL_RATE_LIMIT       mutating requests per window    (default "30/60"
                         = 30 requests / 60 s per client IP)
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque


def max_cameras() -> int:
    return int(os.getenv("PANEL_MAX_CAMERAS", "8"))


def max_ws_clients() -> int:
    return int(os.getenv("PANEL_MAX_WS_CLIENTS", "32"))


def _parse_rate(spec: str) -> tuple[int, float]:
    try:
        n, w = spec.split("/")
        return int(n), float(w)
    except (ValueError, AttributeError):
        return 30, 60.0


class RateLimiter:
    """Sliding-window limiter keyed by an arbitrary client id."""

    def __init__(self, spec: str | None = None) -> None:
        self.max, self.window = _parse_rate(spec or os.getenv("PANEL_RATE_LIMIT", "30/60"))
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            dq = self._hits[key]
            while dq and now - dq[0] > self.window:
                dq.popleft()
            if len(dq) >= self.max:
                return False
            dq.append(now)
            return True


class WSLimiter:
    """Counts concurrent WebSocket connections against a cap."""

    def __init__(self) -> None:
        self._n = 0
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            if self._n >= max_ws_clients():
                return False
            self._n += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._n = max(0, self._n - 1)

    @property
    def count(self) -> int:
        return self._n
