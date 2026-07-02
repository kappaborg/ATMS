"""
Time synchronization helpers — Phase C5 (ADR-0017).

The canonical timestamp shape across ATMS is `SyncedTimestamp`: it carries
both the monotonic clock (used for safety-critical comparisons) and the
wall-clock (used only for human-readable display), plus the sync source and
an estimated skew vs ground truth.

Code rule: anywhere safety-critical, prefer `SyncedTimestamp.now()` and
compare the `monotonic_ns` field. `time.time()` / `datetime.now()` are
**forbidden** in `shared/atms_common/`, the controller, the decision engine,
sensor-fusion, and ai-perception. The lint check at .github/workflows/ci.yml
enforces this.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from shared.atms_common.errors import AtmsError
from shared.atms_common.health import CheckResult


class TimeSyncError(AtmsError):
    """Raised by the sync probes when an external tool fails or is missing."""


class TimeSyncSource(str, Enum):
    SYSTEM_CLOCK = "system_clock"  # not synced — dev / fallback only
    NTP = "ntp"  # cluster-wide via chrony / systemd-timesyncd
    PTP = "ptp"  # edge subnet via linuxptp (ptp4l + phc2sys)


# Default probe — caller can override with a real probe attached to the
# service. The default returns SYSTEM_CLOCK with 0 skew so `SyncedTimestamp.now()`
# always returns *something* in unit tests.
def _default_probe() -> tuple[TimeSyncSource, float]:
    return (TimeSyncSource.SYSTEM_CLOCK, 0.0)


_global_probe: Callable[[], tuple[TimeSyncSource, float]] = _default_probe


def set_global_probe(probe: Callable[[], tuple[TimeSyncSource, float]]) -> None:
    """Register the active sync probe (called once at service startup)."""
    global _global_probe  # noqa: PLW0603 — singleton pattern
    _global_probe = probe


@dataclass(frozen=True)
class SyncedTimestamp:
    """
    The canonical timestamp shape. Use `monotonic_ns` for safety comparisons,
    `wall_clock_ns` only for display.
    """

    monotonic_ns: int
    wall_clock_ns: int
    source: TimeSyncSource
    skew_estimate_ms: float

    @staticmethod
    def now() -> SyncedTimestamp:
        source, skew_ms = _global_probe()
        return SyncedTimestamp(
            monotonic_ns=time.monotonic_ns(),
            # `time.time_ns()` is allowed here — it is the *one* place where
            # wall-clock is read. The `# noqa: ATMS-CLOCK` marker below is
            # matched by tools/lint_safety_clock.py per ADR-0017.
            wall_clock_ns=time.time_ns(),  # noqa: ATMS-CLOCK  the canonical wall-clock anchor
            source=source,
            skew_estimate_ms=skew_ms,
        )

    def is_synced(self) -> bool:
        return self.source is not TimeSyncSource.SYSTEM_CLOCK


# ---------------------------------------------------------------------------
# NTP probe — chrony's `chronyc tracking` output
# ---------------------------------------------------------------------------


def _parse_chrony_offset_ms(output: str) -> float | None:
    """Extract `System time` offset from `chronyc tracking` output."""
    for line in output.splitlines():
        if line.startswith("System time"):
            # "System time     : 0.000000123 seconds slow of NTP time"
            parts = line.split(":", 1)[1].strip().split()
            if not parts:
                continue
            try:
                seconds = float(parts[0])
            except ValueError:
                continue
            return abs(seconds) * 1000.0
    return None


def ntp_sync_probe(*, chronyc_path: str = "chronyc") -> tuple[TimeSyncSource, float]:
    """Probe NTP sync via chronyc. Falls back to SYSTEM_CLOCK on failure."""
    try:
        result = subprocess.run(
            [chronyc_path, "tracking"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (TimeSyncSource.SYSTEM_CLOCK, 0.0)
    if result.returncode != 0:
        return (TimeSyncSource.SYSTEM_CLOCK, 0.0)
    skew_ms = _parse_chrony_offset_ms(result.stdout)
    if skew_ms is None:
        return (TimeSyncSource.SYSTEM_CLOCK, 0.0)
    return (TimeSyncSource.NTP, skew_ms)


# ---------------------------------------------------------------------------
# PTP probe — linuxptp `pmc -u -b 0` GET CURRENT_DATA_SET
# ---------------------------------------------------------------------------


def _parse_ptp_offset_us(output: str) -> float | None:
    """Extract `offsetFromMaster` (nanoseconds) from pmc output."""
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("offsetFromMaster"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    ns = int(parts[1])
                except ValueError:
                    continue
                return abs(ns) / 1000.0
    return None


def ptp_sync_probe(*, pmc_path: str = "pmc") -> tuple[TimeSyncSource, float]:
    """Probe PTP sync via linuxptp's pmc tool."""
    try:
        result = subprocess.run(
            [pmc_path, "-u", "-b", "0", "GET CURRENT_DATA_SET"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (TimeSyncSource.SYSTEM_CLOCK, 0.0)
    if result.returncode != 0:
        return (TimeSyncSource.SYSTEM_CLOCK, 0.0)
    offset_us = _parse_ptp_offset_us(result.stdout)
    if offset_us is None:
        return (TimeSyncSource.SYSTEM_CLOCK, 0.0)
    return (TimeSyncSource.PTP, offset_us / 1000.0)


# ---------------------------------------------------------------------------
# HealthCheck integration
# ---------------------------------------------------------------------------


def ntp_sync_check(
    *,
    skew_threshold_ms: float = 50.0,
    probe: Callable[[], tuple[TimeSyncSource, float]] | None = None,
) -> Callable[[], Any]:
    """
    Returns a HealthCheck-compatible callable. Fails when:
    - the probe reports SYSTEM_CLOCK (no NTP sync)
    - skew > threshold
    """
    probe_fn = probe or ntp_sync_probe

    async def _check() -> CheckResult:
        source, skew_ms = probe_fn()
        if source is TimeSyncSource.SYSTEM_CLOCK:
            return CheckResult(ok=False, detail="ntp not synced")
        if skew_ms > skew_threshold_ms:
            return CheckResult(
                ok=False,
                detail=f"ntp skew {skew_ms:.1f}ms > threshold {skew_threshold_ms:.1f}ms",
            )
        return CheckResult(ok=True, detail=f"ntp synced, skew {skew_ms:.1f}ms")

    return _check


def ptp_sync_check(
    *,
    skew_threshold_us: float = 1000.0,
    probe: Callable[[], tuple[TimeSyncSource, float]] | None = None,
) -> Callable[[], Any]:
    """Edge-only health check. Threshold in microseconds (PTP is sub-millisecond)."""
    probe_fn = probe or ptp_sync_probe

    async def _check() -> CheckResult:
        source, skew_ms = probe_fn()
        skew_us = skew_ms * 1000.0
        if source is TimeSyncSource.SYSTEM_CLOCK:
            return CheckResult(ok=False, detail="ptp not synced")
        if skew_us > skew_threshold_us:
            return CheckResult(
                ok=False,
                detail=f"ptp skew {skew_us:.0f}µs > threshold {skew_threshold_us:.0f}µs",
            )
        return CheckResult(ok=True, detail=f"ptp synced, skew {skew_us:.0f}µs")

    return _check
