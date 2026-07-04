"""
Carbon / emissions accounting for the panel.

Measures real CO2 from observed speed using the same model as the rest of
ATMS (per-type base g/km at optimal speed x a speed factor), split into:
  * moving emissions  — distance-based (speed x dt),
  * idle emissions    — time-based (a stationary car still emits), which is
    where adaptive signal control actually saves carbon.

The measured totals are honest data. The "estimated saved vs fixed-time"
figure is explicitly a MODEL: measured idle CO2 x an adaptive-control savings
ratio (published adaptive-signal studies report ~10-30% delay/idle reduction;
default 0.15, adjustable and shown in the UI). It is never presented as a raw
measurement.

Emissions require a real speed, so they only accrue once the camera is
calibrated.
"""
from __future__ import annotations

import os

# g CO2 per km at optimal speed (50-80 km/h), by our detector's class labels.
# Mirrors services/ai-perception/src/emission/emission_calculator.py.
_CO2_BASE_G_PER_KM: dict[str, float] = {
    "car": 120.0,
    "motorcycle": 80.0,
    "bus": 800.0,
    "truck": 350.0,
    "bicycle": 0.0,
    "person": 0.0,
}
_DEFAULT_BASE = 140.0


def co2_g_per_km(label: str, speed_kmh: float) -> float:
    base = _CO2_BASE_G_PER_KM.get(label, _DEFAULT_BASE)
    if speed_kmh < 20:      # stop-and-go
        factor = 1.4
    elif speed_kmh < 40:    # slow
        factor = 1.2
    elif speed_kmh <= 80:   # optimal
        factor = 1.0
    elif speed_kmh <= 100:  # fast
        factor = 1.1
    else:                   # excessive
        factor = 1.3
    return base * factor


class EmissionAccumulator:
    def __init__(self) -> None:
        self.idle_g_per_s = float(os.getenv("PANEL_IDLE_CO2_G_S", "0.5"))
        self.idle_speed_kmh = float(os.getenv("PANEL_IDLE_SPEED_KMH", "3.0"))
        self.savings_ratio = float(os.getenv("PANEL_ADAPTIVE_SAVINGS_RATIO", "0.15"))
        self.total_co2_g = 0.0
        self.idle_co2_g = 0.0
        self.vehicle_km = 0.0
        self._seen: set[int] = set()
        self._start: float | None = None

    def add(self, track_id: int, label: str, speed_kmh: float, dt_s: float, t: float) -> None:
        if dt_s <= 0 or dt_s > 5:  # ignore first-frame / stall gaps
            return
        if self._start is None:
            self._start = t
        # Cap the unique-vehicle set so a multi-day session can't leak memory.
        # Past the cap the vehicle COUNT saturates; the CO2 totals (the metric
        # that matters) keep accumulating exactly regardless.
        if len(self._seen) < 500_000:
            self._seen.add(int(track_id))
        if speed_kmh <= self.idle_speed_kmh:
            g = self.idle_g_per_s * dt_s  # idling: emits over time, ~0 distance
            self.idle_co2_g += g
            self.total_co2_g += g
        else:
            dist_km = speed_kmh * (dt_s / 3600.0)
            g = co2_g_per_km(label, speed_kmh) * dist_km
            self.total_co2_g += g
            self.vehicle_km += dist_km

    def cumulative(self) -> dict:
        """Raw cumulative counters (grams, unique vehicles) since session start
        — used to compute per-interval deltas for the history store."""
        return {
            "co2_g": self.total_co2_g,
            "saved_g": self.idle_co2_g * self.savings_ratio,
            "vehicles": len(self._seen),
        }

    def stats(self, now: float) -> dict | None:
        if self._start is None:
            return None  # nothing measured yet (uncalibrated / no vehicles)
        elapsed_h = max((now - self._start) / 3600.0, 1e-9)
        avg = self.total_co2_g / self.vehicle_km if self.vehicle_km > 0 else 0.0
        return {
            "total_co2_kg": round(self.total_co2_g / 1000.0, 4),
            "idle_co2_kg": round(self.idle_co2_g / 1000.0, 4),
            "vehicles": len(self._seen),
            "avg_g_per_km": round(avg, 1),
            "rate_kg_h": round((self.total_co2_g / 1000.0) / elapsed_h, 3),
            # Model estimate — labelled as such in the UI.
            "est_saved_kg": round((self.idle_co2_g * self.savings_ratio) / 1000.0, 4),
            "savings_ratio": self.savings_ratio,
        }
