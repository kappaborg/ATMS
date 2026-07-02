# ADR-0018: Weather + lighting adaptation

**Status:** Accepted
**Date:** 2026-05-30
**Closes:** PRODUCTION_GAPS.md gap #22 (Phase C7)

## Context

Audit gap #22: detection accuracy and stopping-distance dynamics change significantly with weather and lighting. Concrete failure modes the prompt highlights:

- **Rain** reduces YOLO confidence and increases vehicle braking distances. Static detection thresholds let false-negatives through (vehicle missed) or trigger false-positives on glare.
- **Fog** does similar to confidence but the safety implication is worse — longer stopping distances mean min-green should be extended, intergreen should grow.
- **Dawn/dusk** introduces low-contrast scenes that the daytime-trained model handles poorly without a re-tune.
- **Night** needs a different model (or at least different post-processing thresholds).

Today nothing in the system reacts to these conditions.

## Decision

Introduce a `WeatherProvider` protocol that publishes a periodic `WeatherSnapshot` per intersection. Two consumers:

1. **`ai-perception`** — looks up the current snapshot and adjusts the `DetectionThresholds` from `atms_config.py` via a `DetectionThresholdAdjuster`. Concretely: vehicle confidence floor rises in fog/rain (we'd rather miss than misdetect on glare), pedestrian floor stays steady (we cannot afford to miss pedestrians), bbox-size thresholds shrink under low contrast.
2. **`services/traffic-controller`** — looks up the same snapshot and adjusts the `SafetyConfig` (`min_green_s`, `all_red_intergreen_s`). Concretely: heavy rain or snow extends `min_green_s` by 25%, `all_red_intergreen_s` by 50%, to account for longer braking distances.

### Update cadence

Snapshot refreshed every 5 minutes per intersection. Provider polls once and broadcasts. Per-intersection because adjacent intersections can have meaningfully different conditions (microclimate, shaded vs sunny side of a building).

### Data sources (provider implementations)

- **`OpenWeatherMapProvider`** — public API; one call per intersection (cached). Requires API key in SOPS-encrypted secret per A5.
- **`MunicipalDOTProvider`** — when the operator has a contract with their local DOT, use the DOT feed. Format varies; per-pilot adapter.
- **`StaticWeatherProvider`** — test double; lets developers force conditions during sim runs (C3).

### Schema

```python
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
    DUSK = "dusk"           # sun within 6° of horizon
    NIGHT = "night"

@dataclass(frozen=True)
class WeatherSnapshot:
    intersection_id: int
    observed_at: SyncedTimestamp        # C5 timestamp
    condition: WeatherCondition
    lighting: LightingLevel
    visibility_m: float                 # 10000 = "clear", under 200 = fog
    precipitation_mmh: float             # mm/hour
    wind_speed_mps: float
    temperature_c: float
    source: str                          # provider name, for audit
```

### Adjustment tables (defaults — operator overrides per-pilot)

#### Detection-threshold multipliers (applied to AtmsConfig.DetectionThresholds)

| Condition | vehicle_base_conf × | pedestrian_base_conf × |
|-----------|--------------------:|------------------------:|
| CLEAR / CLOUDS | 1.00 | 1.00 |
| RAIN_LIGHT | 1.05 | 1.00 |
| RAIN_HEAVY | 1.10 | 1.00 |
| FOG | 1.15 | 1.05 |
| SNOW | 1.10 | 1.00 |
| THUNDERSTORM | 1.10 | 1.00 |

We **never** raise pedestrian thresholds by more than 5% — false-negatives on pedestrians are unacceptable safety risks.

| Lighting | size_threshold × |
|----------|------------------:|
| DAY | 1.00 |
| DUSK | 0.90 |
| NIGHT | 0.85 |

(Lower size thresholds = accept smaller bounding boxes; low-light cameras have less sharp edges.)

#### Safety-config (SafetyConfig) multipliers — applied by traffic-controller

| Condition | min_green_s × | intergreen_s × |
|-----------|--------------:|---------------:|
| CLEAR / CLOUDS | 1.00 | 1.00 |
| RAIN_LIGHT | 1.10 | 1.20 |
| RAIN_HEAVY | 1.25 | 1.50 |
| FOG | 1.20 | 1.50 |
| SNOW | 1.30 | 1.75 |
| THUNDERSTORM | 1.25 | 1.50 |

Note: the failsafe's hard safety invariants still apply on top of these adjustments. min_green_s after adjustment is the floor, not the ceiling. ALL_RED_FLASH escalation timing is unchanged — it operates on hardware-fault detection, not weather.

### Operator override

Every adjustment is overridable per intersection via SOPS-encrypted YAML under `config/intersections/<id>/weather_overrides.yaml`. The override is read at service startup; live override requires a config-reload signal.

### Audit

Every adjustment emits a structured log event:

```
event=weather_adjustment, intersection_id=1, condition=fog, lighting=night,
vehicle_conf_multiplier=1.15, min_green_multiplier=1.20, source=openweathermap
```

Goes to Loki via the B3 pipeline. Operators query this when investigating "why was min-green 13.0 seconds today?"

## Out of scope for C7

- **Training a night-specific model** — Phase D3 retraining pipeline. C7 only adjusts thresholds; model swap is D1.
- **Real-time visibility sensors** at each intersection (vs API polling). Per-pilot hardware choice.
- **Hyperlocal microclimate modelling.** API granularity is "city sector" — sufficient for the urban pilot.

## Consequences

- New runtime dep: `httpx` (added in B4 follow-up was planned; lands here properly).
- New SOPS-encrypted secret: `OPENWEATHERMAP_API_KEY` (per-deployment).
- `ai-perception` and `traffic-controller` consume the snapshot via the shared provider; both services see consistent weather state.
- The adjustment is **additive on top of** the operator-configured per-intersection baseline; defaults to `1.00 ×` so a no-data scenario doesn't change behaviour.
- Tests force WeatherSnapshots into the system via `StaticWeatherProvider`; the C3 SUMO harness can replay rain / fog / night scenarios deterministically.
