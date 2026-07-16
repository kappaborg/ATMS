"""Green-wave corridor: cumulative offsets, and the defining property — a
platoon at the design speed hits every downstream green."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from corridor import Corridor, Stop, build_corridor


def _corr(**kw):
    stops = [Stop("1", 0), Stop("2", 400), Stop("3", 400), Stop("4", 400)]
    return Corridor("c1", stops, design_speed_kmh=50.0, cycle_s=60.0, green_s=27.0, **kw)


def test_offsets_are_cumulative_not_pairwise():
    c = _corr()
    offs = c.offsets()
    mps = 50.0 / 3.6
    # intersection 3 is 800 m from the start -> offset = 800/mps mod 60
    assert offs["3"] == round((800 / mps) % 60.0, 2)
    # cumulative distances
    assert c.cumulative_distances() == [0.0, 400.0, 800.0, 1200.0]


def test_design_speed_platoon_hits_every_green():
    c = _corr()
    offs = c.offsets()
    mps = c.speed_mps
    cum = c.cumulative_distances()
    # a vehicle leaving stop 0 at t=0 at the design speed
    for s, d in zip(c.stops, cum):
        arrival = d / mps
        phase = (arrival - offs[s.intersection_id]) % c.cycle_s
        # Arrival lands at the green START (phase ~= 0); allow FP to wrap it to
        # just under a full cycle (== 0 modulo the cycle).
        assert phase < c.green_s or phase > c.cycle_s - 1e-6


def test_bands_and_trajectory_shape():
    c = _corr()
    bands = c.bands(num_cycles=2)
    assert len(bands) == 4
    assert all(len(b["windows"]) == 2 for b in bands)
    traj = c.trajectory()
    assert traj[0] == [0.0, 0.0] and traj[1][1] > 0


def test_validation():
    with pytest.raises(ValueError):
        Corridor("c", [Stop("1", 0)])  # need >= 2
    with pytest.raises(ValueError):
        Corridor("c", [Stop("1", 0), Stop("2", 400)], design_speed_kmh=0)


def test_build_from_payload_and_coordination_hint():
    c = build_corridor({
        "corridor_id": "main-st",
        "design_speed_kmh": 40.0,
        "cycle_s": 90.0,
        "stops": [{"intersection_id": "A", "distance_m": 0},
                  {"intersection_id": "B", "distance_m": 500}],
    })
    assert c.corridor_id == "main-st"
    hint = c.coordination_for("B", "north_south")
    assert hint["direction"] == "north_south"
    assert hint["cycle_s"] == 90.0
    assert c.coordination_for("nope", "ns") is None


def test_to_payload_round_trips_through_build_corridor():
    """to_dict() is the display shape and has no `stops`, so it cannot be fed
    back in — persistence must use to_payload()."""
    c = _corr(direction="east_west")
    back = build_corridor(c.to_payload())
    assert back.corridor_id == c.corridor_id
    assert back.direction == c.direction
    assert back.design_speed_kmh == c.design_speed_kmh
    assert back.cycle_s == c.cycle_s
    assert back.green_s == c.green_s
    assert [(s.intersection_id, s.distance_m) for s in back.stops] == [
        (s.intersection_id, s.distance_m) for s in c.stops
    ]
    assert back.offsets() == c.offsets()  # the thing that actually matters


def test_to_dict_cannot_round_trip():
    """Guards the mistake this replaced: to_dict() carries no stops."""
    with pytest.raises(KeyError):
        build_corridor(_corr().to_dict())
