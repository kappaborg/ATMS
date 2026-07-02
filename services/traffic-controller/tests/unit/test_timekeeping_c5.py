"""Tests for shared/atms_common/timekeeping.py (Phase C5)."""

from __future__ import annotations

import pytest

from shared.atms_common.timekeeping import (
    SyncedTimestamp,
    TimeSyncSource,
    _parse_chrony_offset_ms,
    _parse_ptp_offset_us,
    ntp_sync_check,
    ntp_sync_probe,
    ptp_sync_check,
    set_global_probe,
)


class TestSyncedTimestamp:
    def test_now_returns_both_clocks(self):
        ts = SyncedTimestamp.now()
        assert ts.monotonic_ns > 0
        assert ts.wall_clock_ns > 0
        assert isinstance(ts.source, TimeSyncSource)

    def test_default_is_system_clock(self):
        # Reset to default probe.
        set_global_probe(lambda: (TimeSyncSource.SYSTEM_CLOCK, 0.0))
        ts = SyncedTimestamp.now()
        assert ts.source is TimeSyncSource.SYSTEM_CLOCK
        assert not ts.is_synced()

    def test_global_probe_override(self):
        set_global_probe(lambda: (TimeSyncSource.NTP, 12.5))
        ts = SyncedTimestamp.now()
        assert ts.source is TimeSyncSource.NTP
        assert ts.skew_estimate_ms == 12.5
        assert ts.is_synced()
        # Reset.
        set_global_probe(lambda: (TimeSyncSource.SYSTEM_CLOCK, 0.0))

    def test_monotonic_strictly_non_decreasing(self):
        a = SyncedTimestamp.now()
        b = SyncedTimestamp.now()
        assert b.monotonic_ns >= a.monotonic_ns


class TestChronyParsing:
    def test_normal_output(self):
        sample = """
Reference ID    : C0A80001 (gateway)
Stratum         : 3
Ref time (UTC)  : Thu May 30 10:00:00 2026
System time     : 0.000123456 seconds fast of NTP time
Last offset     : +0.000001234 seconds
RMS offset      : 0.000005678 seconds
"""
        ms = _parse_chrony_offset_ms(sample)
        assert ms is not None
        assert ms == pytest.approx(0.123456, abs=1e-4)

    def test_missing_system_time_returns_none(self):
        assert _parse_chrony_offset_ms("garbage\nother stuff\n") is None


class TestPtpParsing:
    def test_normal_output(self):
        sample = """
sending: GET CURRENT_DATA_SET
        \tstepsRemoved       1
        \toffsetFromMaster   -250
        \tmeanPathDelay       5000
"""
        us = _parse_ptp_offset_us(sample)
        assert us is not None
        assert us == pytest.approx(0.25, abs=1e-3)

    def test_missing_offset_returns_none(self):
        assert _parse_ptp_offset_us("nothing here") is None


class TestNtpProbe:
    def test_missing_binary_falls_back(self):
        source, skew = ntp_sync_probe(chronyc_path="/nonexistent/chronyc-binary-xyz")
        assert source is TimeSyncSource.SYSTEM_CLOCK
        assert skew == 0.0


class TestHealthChecks:
    async def test_ntp_check_fails_when_not_synced(self):
        check = ntp_sync_check(
            probe=lambda: (TimeSyncSource.SYSTEM_CLOCK, 0.0)
        )
        r = await check()
        assert not r.ok
        assert "not synced" in r.detail

    async def test_ntp_check_fails_when_skew_too_high(self):
        check = ntp_sync_check(
            skew_threshold_ms=10.0,
            probe=lambda: (TimeSyncSource.NTP, 25.0),
        )
        r = await check()
        assert not r.ok
        assert "skew" in r.detail

    async def test_ntp_check_ok_when_in_range(self):
        check = ntp_sync_check(
            skew_threshold_ms=50.0,
            probe=lambda: (TimeSyncSource.NTP, 5.5),
        )
        r = await check()
        assert r.ok

    async def test_ptp_check_microsecond_threshold(self):
        # 0.5 ms = 500 us → above the 1000 us default but within a 750 us threshold.
        check = ptp_sync_check(
            skew_threshold_us=750.0,
            probe=lambda: (TimeSyncSource.PTP, 0.5),
        )
        r = await check()
        assert r.ok

    async def test_ptp_check_fails_above_threshold(self):
        check = ptp_sync_check(
            skew_threshold_us=200.0,
            probe=lambda: (TimeSyncSource.PTP, 0.5),  # 500 us
        )
        r = await check()
        assert not r.ok
