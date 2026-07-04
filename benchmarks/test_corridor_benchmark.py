"""Regression: the green-wave corridor must beat the naive strategies."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import benchmark_corridor as bc


def test_green_wave_has_fewest_stops():
    gw = bc.simulate(bc.green_wave_offsets())
    sim = bc.simulate(bc.simultaneous_offsets())
    rnd = bc.simulate(bc.random_offsets())
    assert gw["avg_stops"] < sim["avg_stops"]
    assert gw["avg_stops"] <= rnd["avg_stops"]
    # and materially less delay than a simultaneous corridor
    assert gw["avg_delay_s"] < sim["avg_delay_s"] * 0.5
