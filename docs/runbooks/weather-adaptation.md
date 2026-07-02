# Runbook: Weather + lighting adaptation (Phase C7)

**Audience:** Traffic engineer per-pilot, operator on-call.
**Design:** [ADR-0018](../adr/0018-weather-lighting-adaptation.md).
**Code:** [`shared/atms_common/weather.py`](../../shared/atms_common/weather.py).

---

## 1. How it works

Every 5 minutes the active `WeatherProvider` publishes a `WeatherSnapshot` per intersection. Two consumers react:

- `ai-perception` adjusts `DetectionThresholds` (confidence floors, bbox-size minimums).
- `traffic-controller` adjusts `SafetyConfig` (min_green_s, intergreen_s).

Adjustments are multipliers on top of the operator-configured baseline. Default is **1.00x** — no provider wired, nothing changes.

## 2. Provider configuration

Pick one provider per deployment:

- `OpenWeatherMapProvider` — public API. Requires `OPENWEATHERMAP_API_KEY` (SOPS-encrypted per A5).
- `MunicipalDOTProvider` — operator-specific feed.
- `StaticWeatherProvider` — test / sim only.

Wire in `services/ai-perception` and `services/traffic-controller`:

```python
from shared.atms_common.weather import StaticWeatherProvider, WeatherSnapshot, ...
from shared.atms_common.timekeeping import SyncedTimestamp

# example for a multi-intersection deployment:
provider = OpenWeatherMapProvider(api_key=settings.openweathermap_api_key)

async def refresh_loop() -> None:
    while True:
        snapshot = await provider.get_snapshot(settings.intersection_id)
        log.info("weather", **event_from_snapshot(snapshot).to_dict())
        await apply_adjustments(snapshot)
        await asyncio.sleep(300)  # 5 min
```

## 3. Operator overrides

Per-intersection YAML at `config/intersections/<id>/weather_overrides.yaml`:

```yaml
# Override the C7 defaults for intersection 7 (heavy industrial area; longer
# brake distance for trucks even in clear weather).
min_green_baseline_s: 12.0     # default 10
intergreen_baseline_s: 3.0     # default 2

# Optional: per-condition override of the multiplier table.
multipliers:
  fog:
    min_green: 1.50           # default 1.20
    intergreen: 2.00          # default 1.50
```

The override is read at service startup. Live reload requires a `SIGHUP` (controller restarts within a few seconds; failsafe transitions to FIXED_TIME during the gap — this is intentional, restart in low-traffic windows).

## 4. Audit + alerting

Every adjustment emits a Loki log line:

```
{service="traffic-controller", event="weather_adjustment"}
  | json
  | min_green_multiplier > 1.0
```

Alert: any intersection emitting `min_green_multiplier > 1.0` for > 2 hours straight → page traffic engineer (operator should know we're running adjusted timings).

Per-condition dwell metric:
- `atms_weather_condition_dwell_seconds{intersection_id, condition}`

## 5. Common questions

> "Why is min-green 13s today?"
The Grafana panel `weather_adjustment` shows the multiplier history. Look for `condition=rain_heavy` or similar.

> "Operator wants to disable adjustment for an intersection."
Set the override file's `multipliers.<condition>.min_green` to `1.0` for that condition. Or, in extremis, remove the WeatherProvider wiring from that service's startup.

> "Detector accuracy dropped today, but it was sunny."
The lighting tier may be wrong (sensor at dusk reading "day"). Inspect the `lighting` field on recent snapshots; it's emitted in the audit log.

## 6. Out of scope

- Real-time visibility sensors at the intersection (vs API polling).
- Hyperlocal microclimate forecasting (next 1h, hyperlocal). C7 only handles current conditions.
- Night-specific ML model (Phase D3 retraining pipeline). C7 only adjusts thresholds.
