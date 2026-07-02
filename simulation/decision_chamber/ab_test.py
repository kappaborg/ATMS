"""A/B test framework — shadow chamber for safe weight tuning.

Production problem: when you want to change `w_emission` from 0.40 to 0.50
to see if it reduces total corridor CO₂, you can't just deploy the
change because if it makes throughput worse the city sues you. You
need to run the change in shadow mode against the same input stream and
COMPARE.

Solution: run TWO `DecisionChamber` instances per tick — the PRIMARY
(whose decisions actually go to the controller) and one or more
SHADOWS (whose decisions are computed but discarded, except for
metrics). The shadow's `commanded_phase`, `priority_scores`,
`dominant_factor` are emitted alongside the primary's so an analyst can
compare them in Prometheus / Grafana / SQLite.

Use cases:
- Weight tuning: shadow uses higher w_emission; if shadow consistently
  picks emission-priority direction when primary picks queue-priority,
  the analyst gets data on the trade-off.
- Algorithm changes: shadow runs new L3 scoring formula; primary keeps
  current. Roll out by promoting shadow → primary once metrics support
  the change.
- Pre-pilot validation: shadow tracks what a future SNMPv3 + multi-
  intersection setup would have decided.

The shadow incurs minimal cost: it shares all sensor inputs (no extra
detector polls), runs its own scoring + hysteresis (pure compute,
sub-millisecond), and writes its decision to a separate Prometheus
label so dashboards filter naturally.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from simulation.decision_chamber.chamber import DecisionChamber
from simulation.decision_chamber.state import (
    ChamberConfig,
    ChamberOutput,
    DirectionState,
)

log = logging.getLogger("atms.chamber.ab")


class ShadowChamber:
    """Wraps a secondary DecisionChamber that computes decisions
    alongside the primary but never sends to the controller. Useful for
    weight tuning, formula experiments, pre-promotion validation.

    Operator pattern:

        primary = DecisionChamber(prod_config)
        shadow  = ShadowChamber(
            label="emission_heavy",
            config=ChamberConfig(w_queue=0.20, w_emission=0.60, w_fairness=0.20),
        )

        for tick:
            primary_out = primary.tick(...)
            shadow_out  = shadow.observe(primary_input, primary_out)
            # shadow_out.commanded_phase may differ from primary_out — the
            # delta gets recorded for offline analysis
    """

    def __init__(
        self,
        label: str,
        config: ChamberConfig | None = None,
        intersection_id: str = "demo",
    ):
        # Shadow has its own state but no detectors / bridge / mesh / TSP
        # — it consumes the inputs the primary already gathered. This
        # keeps shadow purely a "what would I have decided" experiment.
        self.label = label
        self._chamber = DecisionChamber(
            config=config or ChamberConfig(audit_log_path=None),
            intersection_id=f"{intersection_id}.shadow.{label}",
        )
        self.divergence_count = 0
        self.observation_count = 0

    def observe(
        self,
        tick_time: datetime,
        directions: list[DirectionState],
        primary_output: ChamberOutput,
        detector_context: dict[str, Any] | None = None,
    ) -> ChamberOutput:
        """Run shadow scoring on the same inputs. Returns the shadow's
        ChamberOutput. Caller is responsible for emitting metrics
        comparing primary vs shadow.
        """
        shadow_out = self._chamber.tick(
            tick_time=tick_time,
            directions=directions,
            detector_context=detector_context,
        )
        self.observation_count += 1
        if shadow_out.commanded_phase != primary_output.commanded_phase:
            self.divergence_count += 1
        return shadow_out

    def stats(self) -> dict:
        """Summary stats for the operator console / metrics scrape."""
        return {
            "label": self.label,
            "observations": self.observation_count,
            "divergences": self.divergence_count,
            "divergence_rate": (
                self.divergence_count / max(self.observation_count, 1)
            ),
        }


class ABTestHarness:
    """Multi-shadow harness — one primary chamber + N labelled shadows.

    Usage in production pilot:

        harness = ABTestHarness(primary=primary_chamber)
        harness.add_shadow("emission_heavy", ChamberConfig(w_emission=0.60))
        harness.add_shadow("fairness_heavy", ChamberConfig(w_fairness=0.50))

        # Each tick:
        out = harness.tick(tick_time, directions, detector_context)
        # primary's decision goes through bridge automatically;
        # shadows record their alternative decisions into metrics
    """

    def __init__(self, primary: DecisionChamber):
        self.primary = primary
        self._shadows: list[ShadowChamber] = []
        self._metrics_hook = getattr(primary, "_metrics", None)

    def add_shadow(
        self, label: str, config: ChamberConfig
    ) -> ShadowChamber:
        shadow = ShadowChamber(
            label=label, config=config,
            intersection_id=self.primary._intersection_id,
        )
        self._shadows.append(shadow)
        log.info("A/B harness: added shadow '%s'", label)
        return shadow

    def tick(
        self,
        tick_time: datetime,
        directions: list[DirectionState],
        detector_context: dict[str, Any] | None = None,
    ) -> ChamberOutput:
        primary_out = self.primary.tick(
            tick_time=tick_time,
            directions=directions,
            detector_context=detector_context,
        )

        for shadow in self._shadows:
            shadow_out = shadow.observe(
                tick_time=tick_time,
                directions=directions,
                primary_output=primary_out,
                detector_context=detector_context,
            )
            # Record divergence to Prometheus if the primary has metrics
            if self._metrics_hook is not None:
                self._metrics_hook.increment(
                    "atms_ab_observations_total",
                    shadow_label=shadow.label,
                )
                if shadow_out.commanded_phase != primary_out.commanded_phase:
                    self._metrics_hook.increment(
                        "atms_ab_divergences_total",
                        shadow_label=shadow.label,
                        primary_phase=primary_out.commanded_phase,
                        shadow_phase=shadow_out.commanded_phase,
                    )

        return primary_out

    def summary(self) -> list[dict]:
        return [s.stats() for s in self._shadows]
