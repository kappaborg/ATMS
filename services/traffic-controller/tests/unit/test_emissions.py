"""Unit tests for shared/atms_common/emissions.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from shared.atms_common.emissions import (
    EmissionEstimator,
    EmissionProfile,
    VehicleClass,
    _impact_level,
    _speed_factor,
    load_emission_table,
)

# ---------------------------------------------------------------------------
# VehicleClass.coerce — synonym mapping
# ---------------------------------------------------------------------------


class TestVehicleClassCoerce:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("car", VehicleClass.CAR),
            ("SUV", VehicleClass.SUV),
            ("  truck  ", VehicleClass.TRUCK),
            ("passenger", VehicleClass.CAR),
            ("ambulance", VehicleClass.EMERGENCY),
            ("fire", VehicleClass.EMERGENCY),
            ("motorbike", VehicleClass.MOTORCYCLE),
            ("tram", VehicleClass.TRAMWAY),
            ("bike", VehicleClass.BICYCLE),
        ],
    )
    def test_known_synonyms(self, raw: str, expected: VehicleClass):
        assert VehicleClass.coerce(raw) is expected

    def test_unknown_maps_to_default(self):
        assert VehicleClass.coerce("zeppelin") is VehicleClass.UNKNOWN

    def test_none_maps_to_default(self):
        assert VehicleClass.coerce(None) is VehicleClass.UNKNOWN

    def test_empty_string_maps_to_default(self):
        assert VehicleClass.coerce("") is VehicleClass.UNKNOWN


# ---------------------------------------------------------------------------
# Speed factor curve
# ---------------------------------------------------------------------------


class TestSpeedFactor:
    def test_idling_is_1(self):
        assert _speed_factor(0.0, 65.0) == 1.0

    def test_negative_speed_is_1(self):
        assert _speed_factor(-5.0, 65.0) == 1.0

    def test_stop_and_go_penalty(self):
        assert _speed_factor(10.0, 65.0) == 1.4

    def test_slow_penalty(self):
        assert _speed_factor(30.0, 65.0) == 1.2

    def test_optimal_speed_is_baseline(self):
        # At exactly the optimal speed, the factor is 1.0 (diff=0).
        assert _speed_factor(65.0, 65.0) == 1.0

    def test_off_optimal_in_range_small_penalty(self):
        # 75 km/h vs optimal 65 → diff=10 → 1.0 + 10/200 = 1.05
        assert _speed_factor(75.0, 65.0) == pytest.approx(1.05)

    def test_fast_penalty(self):
        # 95 vs optimal 65 → diff=30 → 1.1 + 30/300 = 1.20
        assert _speed_factor(95.0, 65.0) == pytest.approx(1.20)

    def test_very_fast_penalty(self):
        assert _speed_factor(110.0, 65.0) == 1.2

    def test_excessive_speed_penalty(self):
        assert _speed_factor(140.0, 65.0) == 1.3


# ---------------------------------------------------------------------------
# Impact level buckets
# ---------------------------------------------------------------------------


class TestImpactLevel:
    @pytest.mark.parametrize(
        ("co2", "expected"),
        [
            (0.0, "zero"),
            (50.0, "low"),
            (99.9, "low"),
            (100.0, "medium"),
            (149.9, "medium"),
            (150.0, "high"),
            (199.9, "high"),
            (200.0, "very_high"),
            (500.0, "very_high"),
        ],
    )
    def test_bucket(self, co2: float, expected: str):
        assert _impact_level(co2) == expected


# ---------------------------------------------------------------------------
# EmissionEstimator
# ---------------------------------------------------------------------------


class TestEmissionEstimator:
    @pytest.fixture
    def est(self) -> EmissionEstimator:
        return EmissionEstimator()

    def test_idling_car_uses_baseline(self, est: EmissionEstimator):
        e = est.estimate("car", speed_kmh=0.0)
        # Baseline 120 g/km, speed_factor 1.0
        assert e.co2_g_per_km == pytest.approx(120.0)
        assert e.impact_level == "medium"

    def test_bus_is_much_higher_than_car(self, est: EmissionEstimator):
        car = est.estimate("car", speed_kmh=50.0)
        bus = est.estimate("bus", speed_kmh=50.0)
        assert bus.co2_g_per_km > 5 * car.co2_g_per_km  # buses are ~10x

    def test_bicycle_is_zero(self, est: EmissionEstimator):
        e = est.estimate("bicycle", speed_kmh=15.0)
        assert e.co2_g_per_km == 0.0
        assert e.impact_level == "zero"

    def test_tramway_is_zero(self, est: EmissionEstimator):
        e = est.estimate("tramway", speed_kmh=40.0)
        assert e.co2_g_per_km == 0.0

    def test_emergency_uses_emergency_profile(self, est: EmissionEstimator):
        e = est.estimate("emergency", speed_kmh=80.0)
        # Emergency baseline 220 with speed factor for 80 vs optimal 70:
        # diff=10, sf = 1.0 + 10/200 = 1.05 → 220*1.05 = 231
        assert e.co2_g_per_km == pytest.approx(231.0)

    def test_brand_multiplier_reduces_emission(self, est: EmissionEstimator):
        # Tesla multiplier is 0.30 — should be far below the class average.
        baseline = est.estimate("sedan", speed_kmh=50.0)
        tesla = est.estimate("sedan", speed_kmh=50.0, brand="Tesla")
        assert tesla.co2_g_per_km < baseline.co2_g_per_km * 0.4

    def test_brand_multiplier_increases_emission(self, est: EmissionEstimator):
        # Porsche multiplier is 1.20.
        baseline = est.estimate("car", speed_kmh=50.0)
        porsche = est.estimate("car", speed_kmh=50.0, brand="porsche")
        assert porsche.co2_g_per_km > baseline.co2_g_per_km

    def test_unknown_brand_is_neutral(self, est: EmissionEstimator):
        baseline = est.estimate("car", speed_kmh=50.0)
        weird = est.estimate("car", speed_kmh=50.0, brand="MysteryMakeIneverHeardOf")
        assert weird.co2_g_per_km == baseline.co2_g_per_km

    def test_unknown_vehicle_class_falls_back_to_default(self, est: EmissionEstimator):
        e = est.estimate("hovercraft", speed_kmh=50.0)
        assert e.vehicle_class is VehicleClass.UNKNOWN
        assert e.co2_g_per_km > 0  # baseline 140 applied

    def test_estimate_to_dict_is_json_serializable(self, est: EmissionEstimator):
        e = est.estimate("car", speed_kmh=50.0, brand="Tesla")
        assert json.dumps(e.to_dict())


# ---------------------------------------------------------------------------
# Aggregate-direction (per-approach fleet roll-up)
# ---------------------------------------------------------------------------


class TestAggregateDirection:
    def test_empty_direction_returns_zeros(self):
        est = EmissionEstimator()
        agg = est.aggregate_direction("north_south", vehicles=[])
        assert agg.vehicle_count == 0
        assert agg.average_emission_g_per_km == 0.0
        assert agg.instantaneous_co2_g_per_min == 0.0

    def test_single_vehicle(self):
        est = EmissionEstimator()
        agg = est.aggregate_direction("ns", vehicles=[("car", 50.0, None)])
        assert agg.vehicle_count == 1
        assert agg.average_emission_g_per_km > 0

    def test_mixed_fleet_average(self):
        est = EmissionEstimator()
        agg = est.aggregate_direction(
            "ns",
            vehicles=[
                ("car", 60.0, None),
                ("truck", 60.0, None),
                ("bus", 60.0, None),
            ],
        )
        assert agg.vehicle_count == 3
        # Average should sit between the car (low) and bus (very high).
        car = est.estimate("car", speed_kmh=60.0).co2_g_per_km
        bus = est.estimate("bus", speed_kmh=60.0).co2_g_per_km
        assert car < agg.average_emission_g_per_km < bus

    def test_idling_vehicles_contribute_to_g_per_min_only(self):
        est = EmissionEstimator()
        agg = est.aggregate_direction(
            "ns",
            vehicles=[
                ("car", 0.0, None),
                ("car", 0.0, None),
            ],
        )
        # average_emission is the per-km baseline, NOT zero, because we report
        # what the AI engine consumes (it's a heuristic, not a stoichiometric
        # calculation). instantaneous_co2_g_per_min IS zero for moving but
        # adds idling contribution.
        assert agg.instantaneous_co2_g_per_min > 0  # cars idling

    def test_brand_aware_aggregation_lowers_average(self):
        est = EmissionEstimator()
        gas_fleet = est.aggregate_direction(
            "ns",
            vehicles=[("car", 60.0, "porsche"), ("car", 60.0, "porsche")],
        )
        ev_fleet = est.aggregate_direction(
            "ns",
            vehicles=[("car", 60.0, "tesla"), ("car", 60.0, "tesla")],
        )
        assert ev_fleet.average_emission_g_per_km < gas_fleet.average_emission_g_per_km / 2


# ---------------------------------------------------------------------------
# Pilot-override JSON loader
# ---------------------------------------------------------------------------


class TestLoadEmissionTable:
    def test_override_updates_named_classes_only(self, tmp_path: Path):
        override = tmp_path / "override.json"
        override.write_text(json.dumps({"car": {"co2_base_g_per_km": 80.0}}))
        table = load_emission_table(override)
        assert table[VehicleClass.CAR].co2_base_g_per_km == 80.0
        # Truck stays at the default
        assert table[VehicleClass.TRUCK].co2_base_g_per_km == 300.0

    def test_partial_field_override_keeps_other_fields(self, tmp_path: Path):
        override = tmp_path / "override.json"
        override.write_text(json.dumps({"car": {"co2_base_g_per_km": 80.0}}))
        table = load_emission_table(override)
        # The other fields of `car` should retain defaults
        assert table[VehicleClass.CAR].fuel_l_per_100km == 5.5
        assert table[VehicleClass.CAR].optimal_speed_kmh == 65.0

    def test_unknown_key_is_ignored_via_coerce_fallback(self, tmp_path: Path):
        override = tmp_path / "override.json"
        # "spaceship" maps to UNKNOWN under coerce, so this overrides
        # the UNKNOWN profile rather than silently dropping the entry.
        override.write_text(json.dumps({"spaceship": {"co2_base_g_per_km": 999.0}}))
        table = load_emission_table(override)
        assert table[VehicleClass.UNKNOWN].co2_base_g_per_km == 999.0


# ---------------------------------------------------------------------------
# Custom-table constructor
# ---------------------------------------------------------------------------


class TestCustomTable:
    def test_custom_table_overrides_defaults(self):
        custom = {
            VehicleClass.CAR: EmissionProfile(50.0, 3.0, 0.03, 0.002, 65.0, 2.0),
            VehicleClass.UNKNOWN: EmissionProfile(60.0, 3.5, 0.04, 0.003, 65.0, 2.5),
        }
        est = EmissionEstimator(table=custom)
        e = est.estimate("car", speed_kmh=65.0)
        assert e.co2_g_per_km == pytest.approx(50.0)

    def test_custom_brand_multipliers(self):
        est = EmissionEstimator(brand_multipliers={"acme": 0.10})
        baseline = est.estimate("car", speed_kmh=65.0)
        with_brand = est.estimate("car", speed_kmh=65.0, brand="Acme")
        assert with_brand.co2_g_per_km == pytest.approx(baseline.co2_g_per_km * 0.10)


# ---------------------------------------------------------------------------
# Defensive: shape of EmissionEstimate
# ---------------------------------------------------------------------------


def test_emission_estimate_is_frozen():
    est = EmissionEstimator()
    e = est.estimate("car", speed_kmh=50.0)
    with pytest.raises(Exception):
        e.co2_g_per_km = 999.0  # type: ignore[misc]


def test_emission_estimate_round_trip():
    est = EmissionEstimator()
    e = est.estimate("suv", speed_kmh=40.0, brand="Toyota")
    d = e.to_dict()
    assert d["vehicle_class"] == "suv"
    assert d["brand"] == "toyota"
    assert d["impact_level"] in {"low", "medium", "high", "very_high", "zero"}
