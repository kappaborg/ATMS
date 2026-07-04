"""
Green-wave corridor benchmark — does coordination actually cut stops?

Simulates vehicles travelling a corridor of N signalised intersections and
compares three offset strategies on the SAME demand:

  * green-wave  — offset[i] = cumulative_distance[i] / design_speed (mod cycle)
  * simultaneous — every intersection green at the same time (offset 0): the
    naive "synchronised" corridor most cities start with
  * random       — each intersection independently timed (uncoordinated)

Metric: average STOPS per vehicle (and delay). A vehicle at the design speed
on a green-wave corridor should ride through with ~0 stops; the others don't.

Run:  python benchmarks/benchmark_corridor.py
"""
from __future__ import annotations

import random
import statistics

N = 6                 # intersections
SPACING_M = 400.0     # uniform spacing
SPEED_KMH = 50.0
CYCLE_S = 60.0
GREEN_S = 27.0        # through-direction green per cycle
N_VEHICLES = 400
HEADWAY_S = 6.0       # a vehicle enters the corridor every ~6 s
SPEED_VAR = 0.10      # ±10% speed spread (real drivers aren't identical)


def _cumulative():
    return [SPACING_M * i for i in range(N)]


def green_wave_offsets():
    mps = SPEED_KMH / 3.6
    return [(d / mps) % CYCLE_S for d in _cumulative()]


def simultaneous_offsets():
    return [0.0 for _ in range(N)]


def random_offsets(seed=7):
    rng = random.Random(seed)
    return [rng.uniform(0, CYCLE_S) for _ in range(N)]


def simulate(offsets, seed=42):
    rng = random.Random(seed)
    mps = SPEED_KMH / 3.6
    cum = _cumulative()
    stops_per, delay_per = [], []
    for v in range(N_VEHICLES):
        t0 = v * HEADWAY_S
        vspeed = mps * (1 + rng.uniform(-SPEED_VAR, SPEED_VAR))
        delay = 0.0
        stops = 0
        for i in range(N):
            arrival = t0 + cum[i] / vspeed + delay
            phase = (arrival - offsets[i]) % CYCLE_S
            if phase >= GREEN_S:  # red on arrival — wait for the next green
                delay += CYCLE_S - phase
                stops += 1
        stops_per.append(stops)
        delay_per.append(delay)
    return {
        "avg_stops": round(statistics.mean(stops_per), 2),
        "avg_delay_s": round(statistics.mean(delay_per), 1),
        "max_stops": max(stops_per),
    }


def main():
    runs = {
        "green-wave (ours)": simulate(green_wave_offsets()),
        "simultaneous": simulate(simultaneous_offsets()),
        "random": simulate(random_offsets()),
    }
    print(f"\nGreen-wave corridor — {N} intersections, {SPACING_M:.0f} m apart, "
          f"{SPEED_KMH:.0f} km/h design, {CYCLE_S:.0f}s cycle\n" + "=" * 66)
    print(f"{'strategy':<22}{'avg stops':>11}{'avg delay':>12}{'max stops':>11}")
    print(f"{'':<22}{'/vehicle':>11}{'(s)':>12}{'':>11}")
    print("-" * 66)
    for name, m in runs.items():
        print(f"{name:<22}{m['avg_stops']:>11}{m['avg_delay_s']:>12}{m['max_stops']:>11}")
    print("-" * 66)
    gw, sim = runs["green-wave (ours)"], runs["simultaneous"]
    if sim["avg_stops"]:
        cut = 100 * (sim["avg_stops"] - gw["avg_stops"]) / sim["avg_stops"]
        print(f"green-wave vs simultaneous: {cut:+.0f}% fewer stops "
              f"({gw['avg_stops']} vs {sim['avg_stops']} per vehicle)")
    print("A vehicle at the design speed rides the wave through with ~0 stops.")
    return 0 if gw["avg_stops"] <= min(sim["avg_stops"], runs["random"]["avg_stops"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
