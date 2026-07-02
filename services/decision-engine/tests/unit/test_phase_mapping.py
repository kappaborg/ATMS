"""
Tests for the priority-direction + phase-mapping helpers in
services/decision-engine/src/main.py.

Bug context (A3): the original A1 mapping `_PHASE_TO_COMMANDED` expected the
upstream `AIDecisionEngine` to emit `"north_south_green"`-style values, but it
actually emits direction-agnostic `GREEN/RED/YELLOW/ALL_RED`. Result was every
decision mapping to `all_red`. These tests verify the A3 fix: derive priority
direction locally and combine with the AI's phase.
"""

from __future__ import annotations

import pytest

from main import (
    _priority_direction,
    _score_direction,
    _wire_commanded_phase,
)


def _sample(
    *,
    vehicle_count: int = 0,
    average_emission: float = 0.0,
    average_waiting_time: float = 0.0,
    average_velocity: float = 5.0,
    environmental_impact_score: float = 0.0,
) -> dict:
    return {
        "vehicle_count": vehicle_count,
        "average_emission": average_emission,
        "average_waiting_time": average_waiting_time,
        "average_velocity": average_velocity,
        "environmental_impact_score": environmental_impact_score,
    }


# ---------------------------------------------------------------------------
# _score_direction — pure scoring function
# ---------------------------------------------------------------------------


class TestScoreDirection:
    def test_empty_returns_zero(self):
        assert _score_direction({}) == pytest.approx(0.0)

    def test_max_inputs_capped_at_one(self):
        s = _score_direction(_sample(
            vehicle_count=1000,
            average_emission=10_000,
            average_waiting_time=999,
            average_velocity=200,
        ))
        # Sum of weights = 1.0; each component capped at 1.0; no env boost
        # (environmental_impact_score=0) → max possible = 1.0.
        assert s == pytest.approx(1.0)

    def test_environmental_boost(self):
        without_boost = _score_direction(
            _sample(vehicle_count=10, environmental_impact_score=50)
        )
        with_boost = _score_direction(
            _sample(vehicle_count=10, environmental_impact_score=80)
        )
        assert with_boost == pytest.approx(without_boost * 1.2)

    def test_more_vehicles_means_higher_score(self):
        low = _score_direction(_sample(vehicle_count=2))
        high = _score_direction(_sample(vehicle_count=15))
        assert high > low

    def test_matches_ai_engine_scoring(self):
        """If this drifts, _score_direction needs to be updated to match
        ai_decision_system.AIDecisionEngine._calculate_direction_score."""
        from ai_decision_system import AIDecisionEngine  # noqa: PLC0415

        eng = AIDecisionEngine()
        for data in (
            _sample(vehicle_count=5, average_emission=80),
            _sample(vehicle_count=15, average_waiting_time=40, average_velocity=10),
            _sample(vehicle_count=20, environmental_impact_score=90),
            _sample(),
        ):
            ours = _score_direction(data)
            theirs = eng._calculate_direction_score(data)
            assert ours == pytest.approx(theirs), f"drift on {data}"


# ---------------------------------------------------------------------------
# _priority_direction — picks the higher-scoring side
# ---------------------------------------------------------------------------


class TestPriorityDirection:
    def test_ns_busier_returns_north_south(self):
        ns = _sample(vehicle_count=15, average_waiting_time=40)
        ew = _sample(vehicle_count=2)
        assert _priority_direction(ns, ew) == "north_south"

    def test_ew_busier_returns_east_west(self):
        ns = _sample(vehicle_count=2)
        ew = _sample(vehicle_count=15, average_waiting_time=40)
        assert _priority_direction(ns, ew) == "east_west"

    def test_tie_defaults_to_east_west(self):
        # Implementation: `ns > ew` is false on equality → returns east_west.
        # Tied conditions are a degenerate case; documenting the convention.
        ns = _sample(vehicle_count=5, average_emission=50)
        ew = _sample(vehicle_count=5, average_emission=50)
        assert _priority_direction(ns, ew) == "east_west"


# ---------------------------------------------------------------------------
# _wire_commanded_phase — phase + direction → wire enum string
# ---------------------------------------------------------------------------


class TestWireCommandedPhase:
    @pytest.mark.parametrize(
        ("phase", "direction", "expected"),
        [
            ("GREEN", "north_south", "ns_green"),
            ("GREEN", "east_west", "ew_green"),
            ("YELLOW", "north_south", "ns_yellow"),
            ("YELLOW", "east_west", "ew_yellow"),
            ("RED", "north_south", "all_red"),
            ("RED", "east_west", "all_red"),
            ("ALL_RED", "north_south", "all_red"),
            ("ALL_RED", "east_west", "all_red"),
        ],
    )
    def test_mapping(self, phase, direction, expected):
        assert _wire_commanded_phase(phase, direction) == expected

    def test_unknown_phase_defaults_to_all_red(self):
        # Defensive: any unknown enum value must produce a safe wire value.
        assert _wire_commanded_phase("FUCHSIA", "north_south") == "all_red"

    def test_output_is_valid_commandedphase(self):
        """Every output of _wire_commanded_phase MUST be a valid CommandedPhase."""
        from shared.atms_common.decision import CommandedPhase  # noqa: PLC0415

        phases = ["GREEN", "YELLOW", "RED", "ALL_RED", "BOGUS"]
        directions = ["north_south", "east_west"]
        for p in phases:
            for d in directions:
                wire = _wire_commanded_phase(p, d)
                # If this raises ValueError, the schema and the producer disagree.
                CommandedPhase(wire)
