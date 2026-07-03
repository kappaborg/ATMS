"""CO2 emission model + accumulator."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from emissions import EmissionAccumulator, co2_g_per_km


def test_co2_curve_is_u_shaped():
    # Stop-and-go and excessive speed emit more per km than the optimal range.
    optimal = co2_g_per_km("car", 60)
    assert co2_g_per_km("car", 5) > optimal  # congestion penalty
    assert co2_g_per_km("car", 130) > optimal  # excessive-speed penalty
    assert co2_g_per_km("bus", 60) > co2_g_per_km("car", 60)  # heavier vehicle


def test_moving_vehicle_accumulates_distance_based():
    acc = EmissionAccumulator()
    # a car at 60 km/h for 3600 s covers 60 km -> ~120 g/km * 60 = ~7.2 kg
    for i in range(3600):
        acc.add(1, "car", 60.0, 1.0, float(i))
    s = acc.stats(3600.0)
    assert 6.5 < s["total_co2_kg"] < 8.0
    assert s["vehicles"] == 1
    assert 110 < s["avg_g_per_km"] < 130


def test_idle_vehicle_accumulates_time_based_and_is_savable():
    acc = EmissionAccumulator()
    # a stationary car idles for 100 s -> idle CO2 accrues even with ~0 distance
    for i in range(100):
        acc.add(1, "car", 0.0, 1.0, float(i))
    s = acc.stats(100.0)
    assert s["idle_co2_kg"] > 0
    # est saved = idle CO2 * ratio
    assert abs(s["est_saved_kg"] - s["idle_co2_kg"] * s["savings_ratio"]) < 1e-6


def test_no_data_returns_none():
    acc = EmissionAccumulator()
    assert acc.stats(10.0) is None


def test_ignores_bad_dt():
    acc = EmissionAccumulator()
    acc.add(1, "car", 60.0, 0.0, 0.0)   # zero dt
    acc.add(1, "car", 60.0, 99.0, 1.0)  # huge gap
    assert acc.stats(2.0) is None  # nothing counted
