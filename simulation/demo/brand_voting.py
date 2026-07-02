"""Multi-frame brand-vote aggregator.

The tracker sees each vehicle across many frames. Rather than overwriting
the track's `brand` on every classification (which lets a single
misidentification flip a stably-recognised vehicle), we collect every
observation and aggregate.

The aggregator is a **pure function** — no dependence on the tracker, the
estimator, or any I/O. This keeps it cheap to unit-test and easy to swap
out for a richer algorithm later (Bayesian, HMM, learned).

Decision rules:
1. **Single high-confidence shortcut.** If any observation has confidence
   >= `single_high_conf`, commit to that brand immediately.
2. **Majority-with-confidence vote.** Otherwise, sum each brand's
   confidence across all observations. The brand with the highest total
   wins, but only commits if:
   - Total winning confidence >= `min_total_confidence`
   - The winner appears in >= `min_count` separate observations
   - The winner's total beats the runner-up's total by >= `min_margin`
3. **Otherwise.** Return None (the explicit "unknown" outcome — the model
   has looked at this vehicle multiple times and never agreed on a brand).

The defaults are tuned so a track must be classified at least 3 times with
a consistent brand before we'll commit, OR see one strong signal. Adjustable
per pilot.
"""

from __future__ import annotations

from collections import defaultdict


def decide_brand(
    observations: list[tuple[str, float]],
    *,
    single_high_conf: float = 0.90,
    min_count: int = 3,
    min_total_confidence: float = 1.0,
    min_margin: float = 0.10,
) -> tuple[str, float] | None:
    """Aggregate per-track brand observations into a single decision.

    Args:
        observations: list of (brand, confidence) seen across frames for ONE
            track. `brand` is the canonical key, `confidence` is in [0, 1].
        single_high_conf: any observation at or above this confidence wins
            immediately. Default 0.90.
        min_count: a brand must appear in this many separate observations
            to be eligible (unless the high-conf shortcut fired). Default 3.
        min_total_confidence: the winning brand's total summed confidence
            must reach this threshold. Default 1.0.
        min_margin: winner's total must beat runner-up's by this much.
            Prevents a tied tie-breaker. Default 0.10.

    Returns:
        (brand, average_confidence) for the committed brand, or None.
    """
    if not observations:
        return None

    # Rule 1: single high-confidence shortcut
    for brand, conf in observations:
        if conf >= single_high_conf:
            return (brand, conf)

    # Rule 2: aggregate
    counts: dict[str, int] = defaultdict(int)
    totals: dict[str, float] = defaultdict(float)
    for brand, conf in observations:
        counts[brand] += 1
        totals[brand] += conf

    # Sort by total confidence descending
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return None

    winner_brand, winner_total = ranked[0]
    runner_up_total = ranked[1][1] if len(ranked) > 1 else 0.0

    if (
        counts[winner_brand] < min_count
        or winner_total < min_total_confidence
        or winner_total - runner_up_total < min_margin
    ):
        return None

    avg_conf = winner_total / counts[winner_brand]
    return (winner_brand, avg_conf)
