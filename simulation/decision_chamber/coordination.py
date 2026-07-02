"""Layer 4 enhancement — multi-intersection coordination.

For Phase 3 we implement **Pattern A (green wave)** from the dossier:
arterial coordination along a corridor of consecutive intersections.

How a green wave works:
- Upstream intersection serves a through-movement green
- When that green ends, the upstream chamber publishes a `wave_pulse`
  event over MQTT, including the estimated arrival time at downstream
  intersections (= upstream_green_end_time + offset_seconds)
- This (downstream) chamber listens for those pulses
- When this chamber is currently green in the same through direction AND
  a pulse is "in flight" (arrival within ±wave_window_seconds), the L4
  coordinator scores higher to KEEP the green — extending it just long
  enough to let the wave packet pass

Pattern B (mesh) and Pattern C (central optimizer) are Phase 4+ work.
The coordinator interface is designed so adding them is additive: the
same `wave_pulses` channel can carry mesh state, the same L4 hook can
incorporate central-optimizer suggestions.

Real production: this requires per-link `offset_seconds` calibration
during site survey — distance / speed_limit. Defaults below assume
~250 m between intersections at 50 km/h ≈ 18 s offset.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

log = logging.getLogger("atms.chamber.coordination")


@dataclass(frozen=True)
class WaveNeighbor:
    """One upstream neighbor in the green-wave configuration.

    `intersection_id` matches the neighbor's MQTT topic prefix.
    `offset_seconds` = expected travel time from neighbor → this intersection
    `through_direction` = which of OUR directions receives the wave
                          (typically same as neighbor's through direction
                          on an arterial corridor).
    """

    intersection_id: str
    offset_seconds: float
    through_direction: str


@dataclass(frozen=True)
class CoordinationConfig:
    upstream_neighbors: tuple[WaveNeighbor, ...] = field(default_factory=tuple)
    # How wide of a window (seconds) around the expected arrival counts
    # as "the wave is passing through me right now"
    wave_window_seconds: float = 6.0
    # Bonus score added to the green direction when in the wave window
    wave_hold_bonus: float = 0.15


class GreenWaveCoordinator:
    """Decides whether the current green should be extended to maintain
    the corridor's green wave. Stateless across ticks — all input comes
    from the mesh's wave_pulse cache + the chamber's current state.
    """

    def __init__(self, config: CoordinationConfig | None = None):
        self._config = config or CoordinationConfig()

    @property
    def neighbors(self) -> tuple[WaveNeighbor, ...]:
        return self._config.upstream_neighbors

    def evaluate(
        self,
        tick_time: datetime,
        current_direction: str,
        neighbor_pulses: dict[str, dict],
    ) -> tuple[float, str]:
        """Return (bonus_for_current_direction, reason).

        Bonus is added to the L4 scoring stage when computing the
        challenge margin. Positive bonus = "hold the current green".
        The reason string explains the calculation for the audit log.
        """
        if not self._config.upstream_neighbors:
            return 0.0, "no upstream neighbors configured"
        if not neighbor_pulses:
            return 0.0, "no recent wave pulses from neighbors"

        for nb in self._config.upstream_neighbors:
            if nb.through_direction != current_direction:
                continue
            pulse = neighbor_pulses.get(nb.intersection_id)
            if pulse is None:
                continue
            # pulse should carry an iso-formatted `wave_pulse_at` timestamp
            try:
                pulse_at = datetime.fromisoformat(
                    pulse.get("wave_pulse_at", "").replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                continue
            expected_arrival = pulse_at + timedelta(seconds=nb.offset_seconds)
            delta = (tick_time - expected_arrival).total_seconds()
            # If we're within ±wave_window_seconds of the expected arrival,
            # we're in the wave window — extend green.
            if abs(delta) <= self._config.wave_window_seconds:
                return (
                    self._config.wave_hold_bonus,
                    (
                        f"green wave from {nb.intersection_id}: "
                        f"expected ±{self._config.wave_window_seconds:.0f}s of arrival "
                        f"(delta {delta:+.1f}s)"
                    ),
                )

        return 0.0, "no active wave window for current direction"
