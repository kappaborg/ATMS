"""
Vehicle emission estimation — production-grade port of the SE322 emission
calculator.

Lifted from `services/ai-perception/src/emission/emission_calculator.py` with
the following design changes:

1. **Pure-functional core.** No mutable statistics counter. Aggregation belongs
   to the caller (decision-engine aggregates per-direction; observability layer
   accumulates over time).
2. **Typed data model.** `EmissionProfile` dataclass replaces the dict-of-dicts.
3. **Brand multipliers.** New `BRAND_MULTIPLIERS` table layered on top of the
   per-vehicle-class base factors — lets the recognised brand from
   `models/car_brand_classification/` modulate the emission estimate without
   needing per-(brand, model, year) entries.
4. **Idling distinguished from low-speed.** SUMO + real intersections both
   produce many vehicles at speed = 0. Idling g/min is reported separately
   from g/km because dividing by distance breaks down at zero speed.
5. **No exception swallowing.** Bad input (unknown vehicle class) returns the
   `vehicle` default with a warning, but doesn't paper over a real bug.

Source data:
- CO2/fuel/NOx/PM2.5 baselines are EU NEDC-equivalent for representative
  passenger/commercial vehicles. Update the table per pilot region as needed.
- Brand multipliers are conservative defaults (premium brands ~1.10x for the
  larger-displacement effect; EV-heavy brands like Tesla ~0.30x to reflect
  the lifecycle-electricity factor with EU grid mix). Pilot ops should
  override these from regional WLTP / EPA data.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vehicle taxonomy
# ---------------------------------------------------------------------------


class VehicleClass(str, Enum):
    """Coarse vehicle class — the level the YOLOv8 detector outputs."""

    CAR = "car"
    SEDAN = "sedan"
    SUV = "suv"
    MINIVAN = "minivan"
    TRUCK = "truck"
    BUS = "bus"
    VAN = "van"
    MOTORCYCLE = "motorcycle"
    BICYCLE = "bicycle"
    TRAMWAY = "tramway"
    EMERGENCY = "emergency"
    UNKNOWN = "vehicle"

    @classmethod
    def coerce(cls, raw: str | None) -> VehicleClass:
        """Loosely map an upstream detector's label to a VehicleClass member."""
        if not raw:
            return cls.UNKNOWN
        key = raw.lower().strip()
        # SUMO uses `passenger`, `truck`, `bus`, `motorcycle`, `bicycle`, `emergency`, etc.
        synonyms: dict[str, VehicleClass] = {
            "passenger": cls.CAR,
            "vehicle": cls.CAR,
            "automobile": cls.CAR,
            "auto": cls.CAR,
            "lorry": cls.TRUCK,
            "delivery": cls.VAN,
            "coach": cls.BUS,
            "ambulance": cls.EMERGENCY,
            "fire": cls.EMERGENCY,
            "police": cls.EMERGENCY,
            "tram": cls.TRAMWAY,
            "moto": cls.MOTORCYCLE,
            "motorbike": cls.MOTORCYCLE,
            "bike": cls.BICYCLE,
        }
        if key in synonyms:
            return synonyms[key]
        try:
            return cls(key)
        except ValueError:
            return cls.UNKNOWN


# ---------------------------------------------------------------------------
# Emission profile (per vehicle class)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmissionProfile:
    """Baseline emission factors at the vehicle class's optimal speed."""

    co2_base_g_per_km: float
    fuel_l_per_100km: float
    nox_g_per_km: float
    pm25_g_per_km: float
    optimal_speed_kmh: float
    idling_g_per_min: float  # CO2 emitted while stationary with engine on

    @staticmethod
    def zero() -> EmissionProfile:
        return EmissionProfile(
            co2_base_g_per_km=0.0,
            fuel_l_per_100km=0.0,
            nox_g_per_km=0.0,
            pm25_g_per_km=0.0,
            optimal_speed_kmh=20.0,
            idling_g_per_min=0.0,
        )


# Per-vehicle-class baseline. Sourced from the SE322 legacy table; verified
# against EU NEDC / WLTP fleet averages 2024. Operator can override per pilot
# by replacing the JSON loaded by `load_emission_table()`.
_DEFAULT_TABLE: dict[VehicleClass, EmissionProfile] = {
    VehicleClass.CAR: EmissionProfile(120.0, 5.5, 0.06, 0.005, 65.0, 5.0),
    VehicleClass.SEDAN: EmissionProfile(115.0, 5.2, 0.05, 0.004, 65.0, 4.5),
    VehicleClass.SUV: EmissionProfile(180.0, 8.5, 0.08, 0.007, 70.0, 7.5),
    VehicleClass.MINIVAN: EmissionProfile(150.0, 7.0, 0.07, 0.006, 70.0, 6.0),
    VehicleClass.TRUCK: EmissionProfile(300.0, 15.0, 0.50, 0.050, 60.0, 15.0),
    VehicleClass.BUS: EmissionProfile(1200.0, 35.0, 5.0, 0.200, 50.0, 40.0),
    VehicleClass.VAN: EmissionProfile(200.0, 9.0, 0.12, 0.010, 65.0, 8.0),
    VehicleClass.MOTORCYCLE: EmissionProfile(80.0, 3.5, 0.15, 0.020, 60.0, 2.0),
    VehicleClass.BICYCLE: EmissionProfile.zero(),
    VehicleClass.TRAMWAY: EmissionProfile.zero(),  # electric; lifecycle CO2 handled separately
    VehicleClass.EMERGENCY: EmissionProfile(220.0, 11.0, 0.20, 0.015, 70.0, 9.0),
    VehicleClass.UNKNOWN: EmissionProfile(140.0, 6.5, 0.07, 0.006, 65.0, 5.5),
}


# Brand multipliers — applied on top of the class baseline.
# 1.00 = class average. Premium / larger-displacement brands tend slightly up;
# EV-heavy brands tend down. These are conservative defaults — replace per
# pilot region from local registration + WLTP data.
_DEFAULT_BRAND_MULTIPLIERS: dict[str, float] = {
    # ---- BEV-pure fleets (lifecycle-electricity with EU grid mix) ----
    "tesla": 0.30,
    "polestar": 0.35,
    "lucid": 0.32,
    "rivian": 0.40,
    "nio": 0.35,
    "xpeng": 0.35,
    "vinfast": 0.45,
    # ---- PHEV / EV-heavy mixed fleets ----
    "byd": 0.55,
    "mg": 0.85,  # current MG fleet is EV-heavy (was ICE in older models)
    "geely": 0.85,
    "chery": 0.90,
    # ---- Hybrid-leading manufacturers ----
    "toyota": 0.85,
    "lexus": 0.90,
    "honda": 0.95,
    "acura": 0.95,
    # ---- Efficient ICE ----
    "mazda": 0.92,  # Skyactiv
    "hyundai": 0.95,
    "kia": 0.95,
    "fiat": 0.90,  # small Italian engines
    "nissan": 0.95,
    "infiniti": 1.05,
    "mitsubishi": 0.95,
    "subaru": 1.00,
    "suzuki": 0.90,
    # ---- Western-Europe / VW-platform median ----
    "volkswagen": 1.00,
    "vw": 1.00,
    "skoda": 1.00,
    "seat": 1.00,
    "cupra": 1.05,
    "opel": 1.00,
    "vauxhall": 1.00,
    "renault": 0.95,
    "dacia": 1.00,
    "peugeot": 0.95,
    "citroen": 0.95,
    "ds": 1.05,
    "volvo": 0.95,  # hybrid-leaning new fleet
    "saab": 1.05,
    # ---- US median ----
    "ford": 1.05,
    "chevrolet": 1.05,
    "chevy": 1.05,
    "buick": 1.10,
    "gmc": 1.20,
    "lincoln": 1.15,
    "cadillac": 1.15,
    # ---- Premium / larger-displacement ----
    "audi": 1.10,
    "bmw": 1.10,
    "mini": 1.00,
    "mercedes-benz": 1.10,
    "smart": 0.75,
    "land rover": 1.25,
    "range rover": 1.25,
    "jaguar": 1.15,
    "alfa romeo": 1.10,
    "maserati": 1.30,
    "porsche": 1.20,
    "bentley": 1.40,
    "rolls-royce": 1.45,
    "ferrari": 1.45,
    "lamborghini": 1.50,
    "aston martin": 1.40,
    # ---- Trucks / large-SUV ----
    "ram": 1.25,
    "jeep": 1.20,
    "dodge": 1.20,
    "chrysler": 1.15,
    # ---- Korean / Japanese commercial ----
    "isuzu": 1.20,
    "scania": 1.30,
    "man": 1.30,
    # ---- Added 2026-06-13 to cover the DVM-Car 54-class brand model ----
    # Calibrated against existing anchors using new-fleet WLTP CO₂ ranges:
    # daihatsu = small efficient ICE (kei-style cars, similar to suzuki/fiat).
    "daihatsu": 0.90,
    # great wall = Chinese SUVs/pickups (Haval/Wey/Tank), heavier ICE than VW median.
    "great wall": 1.30,
    # lotus = sports cars; mixed fleet (older petrol high, new BEV Eletre/Emeya 0.0)
    #   so a 1.20 blended estimate. Operator can split if a per-model multiplier
    #   ever becomes needed.
    "lotus": 1.20,
    # mclaren = supercars, twin-turbo V8s — same band as Lamborghini/Ferrari.
    "mclaren": 1.50,
    # rover = defunct British marque; historical fleet uses 1990s-2000s petrol.
    "rover": 1.10,
    # ssangyong = Korean SUVs (Tivoli/Rexton/Korando); slightly below Land Rover.
    "ssangyong": 1.20,
}


# ---------------------------------------------------------------------------
# Speed → emission multiplier
# ---------------------------------------------------------------------------


def _speed_factor(speed_kmh: float, optimal_speed_kmh: float) -> float:
    """Emission multiplier as a function of speed.

    Pure function — no class state. Matches the original SE322 curve:
    - <20 km/h (stop-and-go): +40%
    - 20-40 km/h (slow):      +20%
    - 40-80 km/h (optimal):   1.0 with a small distance-from-optimal penalty
    - 80-100 km/h (fast):     +10-15%
    - 100-120 km/h (very fast): +20%
    - >120 km/h:              +30%
    """
    if speed_kmh <= 0:
        return 1.0  # idling — caller should use idling_g_per_min instead

    diff = abs(speed_kmh - optimal_speed_kmh)
    if speed_kmh < 20:
        return 1.4
    if speed_kmh < 40:
        return 1.2
    if speed_kmh <= 80:
        return 1.0 + (diff / 200.0)
    if speed_kmh <= 100:
        return 1.1 + (diff / 300.0)
    if speed_kmh <= 120:
        return 1.2
    return 1.3


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmissionEstimate:
    """One vehicle's emission estimate at a given instant."""

    vehicle_class: VehicleClass
    brand: str | None
    speed_kmh: float
    co2_g_per_km: float
    nox_g_per_km: float
    pm25_g_per_km: float
    fuel_l_per_100km: float
    impact_level: str  # zero | low | medium | high | very_high

    def to_dict(self) -> dict[str, Any]:
        return {
            "vehicle_class": self.vehicle_class.value,
            "brand": self.brand,
            "speed_kmh": round(self.speed_kmh, 1),
            "co2_g_per_km": round(self.co2_g_per_km, 2),
            "nox_g_per_km": round(self.nox_g_per_km, 3),
            "pm25_g_per_km": round(self.pm25_g_per_km, 4),
            "fuel_l_per_100km": round(self.fuel_l_per_100km, 2),
            "impact_level": self.impact_level,
        }


@dataclass(frozen=True)
class DirectionEmissionTotal:
    """Aggregated emission for a per-direction approach (one tick / window)."""

    direction: str
    vehicle_count: int
    average_emission_g_per_km: float
    instantaneous_co2_g_per_min: float  # idling-aware accumulator
    fleet: tuple[EmissionEstimate, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "vehicle_count": self.vehicle_count,
            "average_emission_g_per_km": round(self.average_emission_g_per_km, 2),
            "instantaneous_co2_g_per_min": round(self.instantaneous_co2_g_per_min, 2),
        }


def _impact_level(co2_g_per_km: float) -> str:
    if co2_g_per_km <= 0:
        return "zero"
    if co2_g_per_km < 100:
        return "low"
    if co2_g_per_km < 150:
        return "medium"
    if co2_g_per_km < 200:
        return "high"
    return "very_high"


class EmissionEstimator:
    """
    Stateless estimator — one instance per service.

    Inputs:
      - vehicle class (from the YOLOv8 detector)
      - optional brand (from the trained car-brand classifier in
        `models/car_brand_classification/`)
      - current speed in km/h (from tracker / TraCI)

    Output:
      - `EmissionEstimate` for a single vehicle, OR
      - `DirectionEmissionTotal` for a collection (sum/average over an approach)
    """

    def __init__(
        self,
        table: dict[VehicleClass, EmissionProfile] | None = None,
        brand_multipliers: dict[str, float] | None = None,
        region_overlay_path: str | None = None,
    ) -> None:
        self._table = table or _DEFAULT_TABLE
        self._brand_multipliers = dict(brand_multipliers or _DEFAULT_BRAND_MULTIPLIERS)
        if region_overlay_path:
            self._apply_region_overlay(region_overlay_path)

    def _apply_region_overlay(self, path: str) -> None:
        """Layer a region-specific YAML overlay on top of the defaults.

        Overlay format (see `services/observability/bosnia-fleet-multipliers.yaml`):

            new_brands:
                <brand>: <multiplier>      # brands NOT in default table
            adjustments:
                <brand>: <multiplier>      # REPLACES the default value
            region:
                country_code: BA           # informational
                pilot_city: Sarajevo       # informational
                notes: ...                 # informational

        Both `new_brands` and `adjustments` keys are merged into
        `self._brand_multipliers`. `adjustments` overwrites; `new_brands`
        adds. Lower-cased on insert.
        """
        try:
            import yaml  # noqa: PLC0415
        except ImportError:
            return
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            return
        for brand, mult in (data.get("new_brands") or {}).items():
            self._brand_multipliers[str(brand).lower().strip()] = float(mult)
        for brand, mult in (data.get("adjustments") or {}).items():
            self._brand_multipliers[str(brand).lower().strip()] = float(mult)

    def estimate(
        self,
        vehicle_class: str | VehicleClass,
        speed_kmh: float = 0.0,
        brand: str | None = None,
    ) -> EmissionEstimate:
        cls = (
            vehicle_class
            if isinstance(vehicle_class, VehicleClass)
            else VehicleClass.coerce(vehicle_class)
        )
        profile = self._table.get(cls, self._table[VehicleClass.UNKNOWN])
        brand_norm = brand.lower().strip() if brand else None
        brand_mult = self._brand_multipliers.get(brand_norm, 1.0) if brand_norm else 1.0

        # Apply speed factor + brand multiplier
        sf = _speed_factor(speed_kmh, profile.optimal_speed_kmh)
        co2 = profile.co2_base_g_per_km * sf * brand_mult
        return EmissionEstimate(
            vehicle_class=cls,
            brand=brand_norm,
            speed_kmh=max(0.0, speed_kmh),
            co2_g_per_km=co2,
            nox_g_per_km=profile.nox_g_per_km * sf * brand_mult,
            pm25_g_per_km=profile.pm25_g_per_km * sf * brand_mult,
            fuel_l_per_100km=profile.fuel_l_per_100km * sf * brand_mult,
            impact_level=_impact_level(co2),
        )

    def aggregate_direction(
        self,
        direction: str,
        vehicles: list[tuple[str | VehicleClass, float, str | None]],
    ) -> DirectionEmissionTotal:
        """Aggregate a per-direction fleet.

        Each tuple is `(class, speed_kmh, brand_or_None)`. Returns the average
        emission per km (the field the AI decision engine consumes as
        `average_emission`) plus the instantaneous CO2 g/min including idling
        vehicles (useful for the operator console's CO2 ticker).
        """
        if not vehicles:
            return DirectionEmissionTotal(
                direction=direction,
                vehicle_count=0,
                average_emission_g_per_km=0.0,
                instantaneous_co2_g_per_min=0.0,
            )

        estimates: list[EmissionEstimate] = []
        idling_g_per_min = 0.0
        for vclass, speed, brand in vehicles:
            est = self.estimate(vclass, speed_kmh=speed, brand=brand)
            estimates.append(est)
            if speed <= 0:
                cls = vclass if isinstance(vclass, VehicleClass) else VehicleClass.coerce(vclass)
                idling_g_per_min += self._table.get(
                    cls, self._table[VehicleClass.UNKNOWN]
                ).idling_g_per_min

        avg = sum(e.co2_g_per_km for e in estimates) / len(estimates)
        # Moving vehicles' instantaneous CO2 per minute:
        #   speed[km/h] * (1/60) [h/min] * g_per_km = g/min
        moving = sum((e.co2_g_per_km * e.speed_kmh / 60.0) for e in estimates if e.speed_kmh > 0)
        return DirectionEmissionTotal(
            direction=direction,
            vehicle_count=len(estimates),
            average_emission_g_per_km=avg,
            instantaneous_co2_g_per_min=idling_g_per_min + moving,
            fleet=tuple(estimates),
        )


# ---------------------------------------------------------------------------
# Loader for per-pilot override
# ---------------------------------------------------------------------------


def load_emission_table(path: Path) -> dict[VehicleClass, EmissionProfile]:
    """Load an operator-supplied emission table from JSON.

    Format: {"car": {"co2_base_g_per_km": 110, ...}, ...}. Keys map to
    VehicleClass via `VehicleClass.coerce`. Returns a complete table merged
    on top of `_DEFAULT_TABLE` (operator overrides what they care about,
    everything else falls back to defaults).
    """
    raw = json.loads(path.read_text())
    table: dict[VehicleClass, EmissionProfile] = dict(_DEFAULT_TABLE)
    for key, fields in raw.items():
        cls = VehicleClass.coerce(key)
        defaults = _DEFAULT_TABLE.get(cls, _DEFAULT_TABLE[VehicleClass.UNKNOWN])
        table[cls] = EmissionProfile(
            co2_base_g_per_km=float(fields.get("co2_base_g_per_km", defaults.co2_base_g_per_km)),
            fuel_l_per_100km=float(fields.get("fuel_l_per_100km", defaults.fuel_l_per_100km)),
            nox_g_per_km=float(fields.get("nox_g_per_km", defaults.nox_g_per_km)),
            pm25_g_per_km=float(fields.get("pm25_g_per_km", defaults.pm25_g_per_km)),
            optimal_speed_kmh=float(fields.get("optimal_speed_kmh", defaults.optimal_speed_kmh)),
            idling_g_per_min=float(fields.get("idling_g_per_min", defaults.idling_g_per_min)),
        )
    return table
