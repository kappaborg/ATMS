"""Layer 3 — multi-objective scoring.

Pure functions, no I/O, deterministic. Easy to unit-test and reason
about: given the same inputs you get the same scores. The chamber
combines the scoring output with hysteresis (Layer 4) to make the
final phase decision.

Three signals contribute to each direction's score:

1. **Queue pressure** — how many vehicles are waiting on this approach.
   Normalised by the maximum across directions so absolute counts don't
   bias the comparison.

2. **Emission cost** — the smart objective. For each waiting vehicle:
   `idling_g_per_min × seconds_already_waiting / 60` accumulates the
   extra CO₂ produced by NOT serving this direction. Prioritising the
   queue with the highest accumulated emission cost minimises TOTAL
   system emissions per unit time. This is the climate-aware objective
   the project's mission demands.

3. **Fairness pressure** — `seconds_since_green / max_starvation`. A
   small soft signal compared to the hard `max_starvation` constraint
   enforced in Layer 2; this just nudges the optimizer toward equity
   before the hard limit triggers.

We deliberately do NOT include `avg_speed` as its own dimension — slow
average speed already manifests as high queue + idling emission, and
including it explicitly would double-count.
"""

from __future__ import annotations

from simulation.decision_chamber.state import ChamberConfig, DirectionState, LayerTrace


def emission_cost_g(d: DirectionState, max_starvation_seconds: float) -> float:
    """Accumulated CO₂ cost of keeping this direction red so far.

    Reasoning: a direction's `instantaneous_co2_g_per_min` × time spent
    queuing × idling-correction. We approximate the "extra" emission
    caused by waiting as the idling-vehicle portion of the current
    g/min times the seconds-since-green normalised to the starvation
    horizon. The result is in grams of CO₂ "already paid" by waiting.
    """
    if d.vehicle_count == 0:
        return 0.0
    # Idling-share of the instantaneous rate. If we have no idling info,
    # assume the whole queue contributes (conservative — biases toward
    # serving anyone who's been waiting).
    idling_fraction = (
        d.idling_vehicle_count / d.vehicle_count if d.vehicle_count > 0 else 1.0
    )
    # Cap the wait at the starvation horizon; beyond that the L2 hard
    # constraint takes over and the optimizer's contribution is irrelevant.
    capped_wait_seconds = min(d.seconds_since_green, max_starvation_seconds)
    return d.instantaneous_co2_g_per_min * idling_fraction * (capped_wait_seconds / 60.0)


def _normalise(values: dict[str, float]) -> dict[str, float]:
    """Min-max normalisation to [0,1]. If all values are 0 returns 0s;
    if max equals min returns 0.5 for everyone (no signal to discriminate).
    """
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    if hi == lo:
        # No signal — return mid-range so nothing dominates the weighted sum.
        return {k: 0.5 if hi > 0 else 0.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def score_directions(
    directions: list[DirectionState],
    config: ChamberConfig,
    tsp_bonus: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, dict[str, float]], LayerTrace]:
    """Compute final priority scores per direction.

    Returns:
        scores               — final weighted score per direction
        per_signal_normalised — debug-friendly per-input normalised scores
        trace                — LayerTrace recording the calculation

    `per_signal_normalised` lets the operator console show the per-input
    progress bars (queue, emission, fairness) so the operator sees WHICH
    factor pushed which direction up.
    """
    if not directions:
        return (
            {},
            {},
            LayerTrace(
                layer="L3_optimization",
                result="skipped",
                notes="no directions provided",
            ),
        )

    raw_queue = {d.name: float(d.vehicle_count) for d in directions}
    raw_emission = {
        d.name: emission_cost_g(d, config.max_starvation_seconds) for d in directions
    }
    raw_fairness = {
        d.name: min(d.seconds_since_green / config.max_starvation_seconds, 1.0)
        for d in directions
    }

    n_queue = _normalise(raw_queue)
    n_emission = _normalise(raw_emission)
    # Fairness is already in [0,1] by construction (already capped at 1.0)
    n_fairness = raw_fairness

    scores: dict[str, float] = {}
    tsp_bonus = tsp_bonus or {}
    for d in directions:
        scores[d.name] = (
            config.w_queue * n_queue.get(d.name, 0.0)
            + config.w_emission * n_emission.get(d.name, 0.0)
            + config.w_fairness * n_fairness.get(d.name, 0.0)
        )
        # Pedestrian demand on this direction is a STRONG bias — peds
        # have been waiting and a real intersection cannot keep ignoring
        # them. +0.40 reliably outranks normal traffic scoring (which
        # tops out around 0.7-0.9 with all factors saturated) so the
        # next phase change will serve the ped direction.
        if d.has_pedestrian_demand:
            scores[d.name] += 0.40
        # Transit Signal Priority bonus — soft bias, smaller than ped.
        # Multiple late buses on the same direction stack additively.
        scores[d.name] += tsp_bonus.get(d.name, 0.0)

    per_signal = {
        d.name: {
            "queue": n_queue.get(d.name, 0.0),
            "emission": n_emission.get(d.name, 0.0),
            "fairness": n_fairness.get(d.name, 0.0),
            "pedestrian": 1.0 if d.has_pedestrian_demand else 0.0,
            "tsp_bonus": tsp_bonus.get(d.name, 0.0),
            "raw_queue_count": raw_queue[d.name],
            "raw_emission_g": round(raw_emission[d.name], 1),
            "raw_seconds_since_green": directions[
                [d.name for d in directions].index(d.name)
            ].seconds_since_green,
        }
        for d in directions
    }

    trace = LayerTrace(
        layer="L3_optimization",
        result="passed",
        notes=(
            f"weights queue={config.w_queue} emission={config.w_emission} "
            f"fairness={config.w_fairness}"
        ),
        detail={"per_signal": per_signal, "scores": scores},
    )
    return scores, per_signal, trace


def identify_dominant_factor(
    per_signal: dict[str, dict[str, float]], winner: str, config: ChamberConfig
) -> str:
    """Which input factor contributed most to the winner's score?
    Returns a short string suitable for the operator console.
    """
    if winner not in per_signal:
        return "unknown"
    sig = per_signal[winner]
    weighted = {
        "queue": config.w_queue * sig["queue"],
        "emission_cost": config.w_emission * sig["emission"],
        "fairness": config.w_fairness * sig["fairness"],
        # Pedestrian bias is large and unweighted; if present, it
        # almost always dominates.
        "pedestrian_demand": 0.40 if sig.get("pedestrian", 0) > 0.5 else 0.0,
        # Transit Signal Priority bonus — direct raw contribution
        # (already in [0, 1] range from get_tsp_bonus_per_direction).
        "transit_priority": sig.get("tsp_bonus", 0.0),
    }
    return max(weighted.items(), key=lambda kv: kv[1])[0]
