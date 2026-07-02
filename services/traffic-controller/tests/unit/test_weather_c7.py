"""Tests for shared/atms_common/weather.py (Phase C7)."""

from __future__ import annotations

import asyncio

import pytest

from shared.atms_common.timekeeping import SyncedTimestamp
from shared.atms_common.weather import (
    DetectionThresholdAdjustment,
    LightingLevel,
    SafetyConfigAdjustment,
    StaticWeatherProvider,
    WeatherCondition,
    WeatherSnapshot,
    detection_adjustment_for,
    event_from_snapshot,
    safety_adjustment_for,
)


def _snapshot(
    *,
    intersection_id: int = 1,
    condition: WeatherCondition = WeatherCondition.CLEAR,
    lighting: LightingLevel = LightingLevel.DAY,
    source: str = "test",
) -> WeatherSnapshot:
    return WeatherSnapshot(
        intersection_id=intersection_id,
        observed_at=SyncedTimestamp.now(),
        condition=condition,
        lighting=lighting,
        source=source,
    )


# ---------------------------------------------------------------------------
# Detection adjustments
# ---------------------------------------------------------------------------


class TestDetectionAdjustment:
    def test_clear_day_is_neutral(self):
        adj = detection_adjustment_for(_snapshot())
        assert adj == DetectionThresholdAdjustment.neutral()

    def test_rain_raises_vehicle_floor(self):
        adj = detection_adjustment_for(_snapshot(condition=WeatherCondition.RAIN_HEAVY))
        assert adj.vehicle_conf_multiplier > 1.0

    def test_pedestrian_floor_capped_at_5pct(self):
        """ADR-0018: pedestrian thresholds never raised by > 5%."""
        for cond in WeatherCondition:
            adj = detection_adjustment_for(_snapshot(condition=cond))
            assert adj.pedestrian_conf_multiplier <= 1.05, cond

    def test_night_lowers_size_floor(self):
        day = detection_adjustment_for(_snapshot(lighting=LightingLevel.DAY))
        night = detection_adjustment_for(_snapshot(lighting=LightingLevel.NIGHT))
        assert night.size_multiplier < day.size_multiplier


# ---------------------------------------------------------------------------
# Safety adjustments
# ---------------------------------------------------------------------------


class TestSafetyAdjustment:
    def test_clear_is_neutral(self):
        adj = safety_adjustment_for(_snapshot())
        assert adj == SafetyConfigAdjustment.neutral()

    def test_snow_extends_min_green_and_intergreen(self):
        adj = safety_adjustment_for(_snapshot(condition=WeatherCondition.SNOW))
        assert adj.min_green_multiplier > 1.0
        assert adj.intergreen_multiplier > 1.0

    def test_intergreen_always_grows_at_least_as_much_as_min_green(self):
        """Intergreen accounts for longer braking — must adjust at least as
        much as min_green for any non-neutral condition."""
        for cond in WeatherCondition:
            if cond in (WeatherCondition.CLEAR, WeatherCondition.CLOUDS):
                continue
            adj = safety_adjustment_for(_snapshot(condition=cond))
            assert adj.intergreen_multiplier >= adj.min_green_multiplier, cond


# ---------------------------------------------------------------------------
# StaticWeatherProvider
# ---------------------------------------------------------------------------


class TestStaticProvider:
    def test_returns_configured_snapshot(self):
        snapshot = _snapshot(
            intersection_id=42, condition=WeatherCondition.FOG, lighting=LightingLevel.NIGHT
        )
        provider = StaticWeatherProvider(snapshot)
        result = asyncio.run(provider.get_snapshot(42))
        assert result.condition is WeatherCondition.FOG
        assert result.lighting is LightingLevel.NIGHT
        assert result.intersection_id == 42

    def test_rebinds_intersection_id(self):
        snapshot = _snapshot(intersection_id=1)
        provider = StaticWeatherProvider(snapshot)
        result = asyncio.run(provider.get_snapshot(7))
        assert result.intersection_id == 7


# ---------------------------------------------------------------------------
# Audit event
# ---------------------------------------------------------------------------


class TestEventEmission:
    def test_event_carries_all_multipliers(self):
        evt = event_from_snapshot(
            _snapshot(condition=WeatherCondition.FOG, lighting=LightingLevel.NIGHT)
        )
        d = evt.to_dict()
        assert d["event"] == "weather_adjustment"
        assert d["condition"] == "fog"
        assert d["lighting"] == "night"
        assert d["vehicle_conf_multiplier"] > 1.0
        assert d["min_green_multiplier"] > 1.0

    def test_event_source_propagates(self):
        evt = event_from_snapshot(_snapshot(source="openweathermap"))
        assert evt.to_dict()["source"] == "openweathermap"


# ---------------------------------------------------------------------------
# Combined invariants
# ---------------------------------------------------------------------------


class TestCombinedInvariants:
    def test_every_condition_has_multipliers(self):
        for cond in WeatherCondition:
            for light in LightingLevel:
                adj = detection_adjustment_for(_snapshot(condition=cond, lighting=light))
                # Sanity: multipliers are in plausible ranges.
                assert 0.5 <= adj.vehicle_conf_multiplier <= 1.5
                assert 0.9 <= adj.pedestrian_conf_multiplier <= 1.1
                assert 0.5 <= adj.size_multiplier <= 1.5

    def test_safety_multipliers_in_reasonable_range(self):
        for cond in WeatherCondition:
            adj = safety_adjustment_for(_snapshot(condition=cond))
            # No condition should adjust more than 2x — that's a per-pilot
            # operator override territory.
            assert 1.0 <= adj.min_green_multiplier <= 2.0, cond
            assert 1.0 <= adj.intergreen_multiplier <= 2.0, cond
