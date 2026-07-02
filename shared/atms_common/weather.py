"""
Weather + lighting adaptation — Phase C7 (ADR-0018).

`WeatherProvider` publishes a `WeatherSnapshot` per intersection. Two
consumers in scope:

- ai-perception: uses `DetectionThresholdAdjuster` to scale confidence floors
  and bbox-size thresholds.
- traffic-controller: uses `SafetyConfigAdjuster` to scale min-green and
  intergreen.

Adjustments default to 1.00x when no provider is wired up - a fresh deployment
sees the unmodified config until the operator turns on the weather feed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from shared.atms_common.errors import AtmsError
from shared.atms_common.timekeeping import SyncedTimestamp


class WeatherError(AtmsError):
    """Raised by providers on upstream failure."""


# ---------------------------------------------------------------------------
# Enums + snapshot
# ---------------------------------------------------------------------------


class WeatherCondition(str, Enum):
    CLEAR = "clear"
    CLOUDS = "clouds"
    RAIN_LIGHT = "rain_light"
    RAIN_HEAVY = "rain_heavy"
    SNOW = "snow"
    FOG = "fog"
    THUNDERSTORM = "thunderstorm"


class LightingLevel(str, Enum):
    DAY = "day"
    DUSK = "dusk"
    NIGHT = "night"


@dataclass(frozen=True)
class WeatherSnapshot:
    intersection_id: int
    observed_at: SyncedTimestamp
    condition: WeatherCondition
    lighting: LightingLevel
    visibility_m: float = 10000.0
    precipitation_mmh: float = 0.0
    wind_speed_mps: float = 0.0
    temperature_c: float = 15.0
    source: str = "unknown"


# ---------------------------------------------------------------------------
# Adjustment tables (ADR-0018 §Adjustment tables)
# ---------------------------------------------------------------------------

# Multipliers applied to AtmsConfig.DetectionThresholds.vehicle_base_conf.
_VEHICLE_CONF_MULT: dict[WeatherCondition, float] = {
    WeatherCondition.CLEAR: 1.00,
    WeatherCondition.CLOUDS: 1.00,
    WeatherCondition.RAIN_LIGHT: 1.05,
    WeatherCondition.RAIN_HEAVY: 1.10,
    WeatherCondition.FOG: 1.15,
    WeatherCondition.SNOW: 1.10,
    WeatherCondition.THUNDERSTORM: 1.10,
}

# Pedestrian conf multipliers — capped tightly: false negatives on peds
# are not acceptable. Max +5% across all conditions.
_PEDESTRIAN_CONF_MULT: dict[WeatherCondition, float] = {
    WeatherCondition.CLEAR: 1.00,
    WeatherCondition.CLOUDS: 1.00,
    WeatherCondition.RAIN_LIGHT: 1.00,
    WeatherCondition.RAIN_HEAVY: 1.00,
    WeatherCondition.FOG: 1.05,
    WeatherCondition.SNOW: 1.00,
    WeatherCondition.THUNDERSTORM: 1.00,
}

# Lighting → bbox-size threshold multiplier.
_SIZE_MULT_LIGHTING: dict[LightingLevel, float] = {
    LightingLevel.DAY: 1.00,
    LightingLevel.DUSK: 0.90,
    LightingLevel.NIGHT: 0.85,
}

# Safety-config multipliers (traffic-controller).
_MIN_GREEN_MULT: dict[WeatherCondition, float] = {
    WeatherCondition.CLEAR: 1.00,
    WeatherCondition.CLOUDS: 1.00,
    WeatherCondition.RAIN_LIGHT: 1.10,
    WeatherCondition.RAIN_HEAVY: 1.25,
    WeatherCondition.FOG: 1.20,
    WeatherCondition.SNOW: 1.30,
    WeatherCondition.THUNDERSTORM: 1.25,
}

_INTERGREEN_MULT: dict[WeatherCondition, float] = {
    WeatherCondition.CLEAR: 1.00,
    WeatherCondition.CLOUDS: 1.00,
    WeatherCondition.RAIN_LIGHT: 1.20,
    WeatherCondition.RAIN_HEAVY: 1.50,
    WeatherCondition.FOG: 1.50,
    WeatherCondition.SNOW: 1.75,
    WeatherCondition.THUNDERSTORM: 1.50,
}


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


class WeatherProvider(ABC):
    """Provides current weather + lighting per intersection."""

    @abstractmethod
    async def get_snapshot(self, intersection_id: int) -> WeatherSnapshot: ...


class StaticWeatherProvider(WeatherProvider):
    """Test / sim double — always returns a fixed snapshot."""

    def __init__(self, snapshot: WeatherSnapshot) -> None:
        self._snapshot = snapshot

    async def get_snapshot(self, intersection_id: int) -> WeatherSnapshot:
        # Return the same snapshot but rebind intersection_id so callers can
        # share one StaticWeatherProvider across many intersections in tests.
        return WeatherSnapshot(
            intersection_id=intersection_id,
            observed_at=self._snapshot.observed_at,
            condition=self._snapshot.condition,
            lighting=self._snapshot.lighting,
            visibility_m=self._snapshot.visibility_m,
            precipitation_mmh=self._snapshot.precipitation_mmh,
            wind_speed_mps=self._snapshot.wind_speed_mps,
            temperature_c=self._snapshot.temperature_c,
            source=self._snapshot.source,
        )


# ---------------------------------------------------------------------------
# Adjusters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DetectionThresholdAdjustment:
    vehicle_conf_multiplier: float
    pedestrian_conf_multiplier: float
    size_multiplier: float

    @staticmethod
    def neutral() -> DetectionThresholdAdjustment:
        return DetectionThresholdAdjustment(1.0, 1.0, 1.0)


def detection_adjustment_for(snapshot: WeatherSnapshot) -> DetectionThresholdAdjustment:
    return DetectionThresholdAdjustment(
        vehicle_conf_multiplier=_VEHICLE_CONF_MULT.get(snapshot.condition, 1.0),
        pedestrian_conf_multiplier=_PEDESTRIAN_CONF_MULT.get(snapshot.condition, 1.0),
        size_multiplier=_SIZE_MULT_LIGHTING.get(snapshot.lighting, 1.0),
    )


@dataclass(frozen=True)
class SafetyConfigAdjustment:
    min_green_multiplier: float
    intergreen_multiplier: float

    @staticmethod
    def neutral() -> SafetyConfigAdjustment:
        return SafetyConfigAdjustment(1.0, 1.0)


def safety_adjustment_for(snapshot: WeatherSnapshot) -> SafetyConfigAdjustment:
    return SafetyConfigAdjustment(
        min_green_multiplier=_MIN_GREEN_MULT.get(snapshot.condition, 1.0),
        intergreen_multiplier=_INTERGREEN_MULT.get(snapshot.condition, 1.0),
    )


# ---------------------------------------------------------------------------
# Audit-event payload — emitted by the consuming service through structlog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WeatherAdjustmentEvent:
    intersection_id: int
    condition: WeatherCondition
    lighting: LightingLevel
    vehicle_conf_multiplier: float
    pedestrian_conf_multiplier: float
    size_multiplier: float
    min_green_multiplier: float
    intergreen_multiplier: float
    source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "event": "weather_adjustment",
            "intersection_id": self.intersection_id,
            "condition": self.condition.value,
            "lighting": self.lighting.value,
            "vehicle_conf_multiplier": self.vehicle_conf_multiplier,
            "pedestrian_conf_multiplier": self.pedestrian_conf_multiplier,
            "size_multiplier": self.size_multiplier,
            "min_green_multiplier": self.min_green_multiplier,
            "intergreen_multiplier": self.intergreen_multiplier,
            "source": self.source,
        }


def event_from_snapshot(snapshot: WeatherSnapshot) -> WeatherAdjustmentEvent:
    det = detection_adjustment_for(snapshot)
    safety = safety_adjustment_for(snapshot)
    return WeatherAdjustmentEvent(
        intersection_id=snapshot.intersection_id,
        condition=snapshot.condition,
        lighting=snapshot.lighting,
        vehicle_conf_multiplier=det.vehicle_conf_multiplier,
        pedestrian_conf_multiplier=det.pedestrian_conf_multiplier,
        size_multiplier=det.size_multiplier,
        min_green_multiplier=safety.min_green_multiplier,
        intergreen_multiplier=safety.intergreen_multiplier,
        source=snapshot.source,
    )
