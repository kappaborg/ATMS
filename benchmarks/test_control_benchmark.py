"""Regression guard: the adaptive engine must beat fixed-time under the demand
where adaptive control is supposed to help (imbalanced / heavy), and stay
real-time. Runs a short simulation so it's fast enough for CI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_control import Adaptive, FixedTime, Greedy, gen_arrivals, simulate


def test_adaptive_beats_fixed_time_under_imbalance():
    ns, ew = gen_arrivals(1200, base_ns=0.30, base_ew=0.05, seed=1)
    fixed = simulate(FixedTime(30), ns, ew)
    ours = simulate(Adaptive(), ns, ew)
    # Big win expected when one approach is starved by a rigid 50/50 split.
    assert ours["avg_delay_s"] < fixed["avg_delay_s"] * 0.8
    assert ours["served"] >= fixed["served"]


def test_adaptive_wins_under_heavy_imbalanced_demand():
    # Oversaturated AND imbalanced (0.55 > 0.5 sat flow) — adaptive should win.
    ns, ew = gen_arrivals(1200, base_ns=0.35, base_ew=0.20, seed=2)
    fixed = simulate(FixedTime(30), ns, ew)
    ours = simulate(Adaptive(), ns, ew)
    assert ours["avg_delay_s"] < fixed["avg_delay_s"]
    assert ours["served"] >= fixed["served"]


def test_adaptive_competitive_under_balanced_heavy():
    # Near-balanced heavy: adaptive isn't expected to WIN, but must not lose
    # meaningfully (the honest finding — fixed-time is fine when balanced).
    ns, ew = gen_arrivals(1200, base_ns=0.24, base_ew=0.20, seed=2)
    fixed = simulate(FixedTime(30), ns, ew)
    ours = simulate(Adaptive(), ns, ew)
    assert ours["avg_delay_s"] <= fixed["avg_delay_s"] * 1.05


def test_decision_is_real_time():
    ns, ew = gen_arrivals(300, 0.2, 0.15, seed=3)
    ours = simulate(Adaptive(), ns, ew)
    assert ours["latency_us"] < 50_000  # < 50 ms/decision = real-time


def test_naive_greedy_is_unstable():
    # Documents WHY our engine needs hysteresis: naive longer-queue switching
    # thrashes and does far worse than fixed-time under load.
    ns, ew = gen_arrivals(1200, 0.24, 0.20, seed=4)
    fixed = simulate(FixedTime(30), ns, ew)
    greedy = simulate(Greedy(), ns, ew)
    assert greedy["avg_delay_s"] > fixed["avg_delay_s"]
