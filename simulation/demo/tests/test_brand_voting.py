"""Unit tests for simulation/demo/brand_voting.py."""

from __future__ import annotations

import pytest

from simulation.demo.brand_voting import decide_brand


class TestDecideBrandShortcut:
    """Rule 1: single observation >= single_high_conf wins immediately."""

    def test_single_high_conf_wins(self):
        result = decide_brand([("tesla", 0.95)])
        assert result == ("tesla", 0.95)

    def test_high_conf_among_lower_observations_wins(self):
        obs = [
            ("toyota", 0.30),
            ("ford", 0.40),
            ("tesla", 0.95),  # this wins by shortcut
            ("toyota", 0.30),
        ]
        result = decide_brand(obs)
        assert result == ("tesla", 0.95)

    def test_just_below_shortcut_falls_through(self):
        # 0.89 < default 0.90 cutoff, only one observation → fails count gate
        result = decide_brand([("tesla", 0.89)])
        assert result is None

    def test_custom_shortcut_threshold(self):
        # With single_high_conf=0.50, a single 0.55 observation should commit.
        result = decide_brand([("tesla", 0.55)], single_high_conf=0.50)
        assert result == ("tesla", 0.55)


class TestDecideBrandMajority:
    """Rule 2: aggregate by total confidence + count + margin gates."""

    def test_three_same_brand_with_decent_total_wins(self):
        obs = [("toyota", 0.40), ("toyota", 0.45), ("toyota", 0.50)]
        result = decide_brand(obs)
        # Total = 1.35, count = 3, runner-up = 0 — clears all gates
        assert result is not None
        assert result[0] == "toyota"

    def test_two_observations_fail_count_gate(self):
        # Only 2 observations of toyota, default min_count=3
        obs = [("toyota", 0.50), ("toyota", 0.50)]
        result = decide_brand(obs)
        assert result is None

    def test_low_total_confidence_fails_total_gate(self):
        # 3 observations of toyota but each only 0.20 → total 0.60 < 1.0
        obs = [("toyota", 0.20), ("toyota", 0.20), ("toyota", 0.20)]
        result = decide_brand(obs)
        assert result is None

    def test_tight_margin_fails(self):
        # toyota gets total 1.0, ford gets total 0.95 → margin 0.05 < default 0.10
        obs = [
            ("toyota", 0.40),
            ("toyota", 0.30),
            ("toyota", 0.30),
            ("ford", 0.40),
            ("ford", 0.30),
            ("ford", 0.25),
        ]
        result = decide_brand(obs)
        assert result is None  # no clear winner

    def test_clear_winner_with_margin(self):
        # toyota wins clearly even with some ford noise
        obs = [
            ("toyota", 0.50),
            ("toyota", 0.50),
            ("toyota", 0.50),
            ("ford", 0.20),
        ]
        result = decide_brand(obs)
        assert result is not None
        assert result[0] == "toyota"

    def test_single_misclassification_does_not_flip(self):
        # 4 toyota + 1 spurious tesla — toyota wins
        obs = [
            ("toyota", 0.40),
            ("toyota", 0.40),
            ("toyota", 0.40),
            ("toyota", 0.40),
            ("tesla", 0.45),
        ]
        result = decide_brand(obs)
        assert result is not None
        assert result[0] == "toyota"

    def test_returned_confidence_is_average(self):
        # 3 toyota observations: 0.40, 0.50, 0.60 -> avg = 0.50
        obs = [("toyota", 0.40), ("toyota", 0.50), ("toyota", 0.60)]
        result = decide_brand(obs)
        assert result is not None
        assert result[0] == "toyota"
        assert result[1] == pytest.approx(0.50)


class TestDecideBrandEdge:
    def test_empty_returns_none(self):
        assert decide_brand([]) is None

    def test_single_low_conf_returns_none(self):
        # Not high enough for shortcut + only 1 observation
        assert decide_brand([("toyota", 0.30)]) is None

    def test_all_different_brands_returns_none(self):
        # 5 brands, each once — no majority
        obs = [
            ("toyota", 0.30),
            ("ford", 0.30),
            ("tesla", 0.30),
            ("bmw", 0.30),
            ("honda", 0.30),
        ]
        result = decide_brand(obs)
        assert result is None


class TestCustomThresholds:
    def test_lower_min_count_allows_two_observations(self):
        obs = [("toyota", 0.55), ("toyota", 0.55)]
        # min_count=2 + total 1.10 > 1.0 + no runner-up
        result = decide_brand(obs, min_count=2)
        assert result is not None
        assert result[0] == "toyota"

    def test_lower_min_total_allows_weaker_observations(self):
        obs = [("toyota", 0.20), ("toyota", 0.20), ("toyota", 0.20)]
        # min_total_confidence=0.5 instead of 1.0
        result = decide_brand(obs, min_total_confidence=0.5)
        assert result is not None
        assert result[0] == "toyota"

    def test_lower_min_margin_allows_close_winners(self):
        # margin = 0.04, normally fails (default min_margin=0.10)
        obs = [
            ("toyota", 0.50),
            ("toyota", 0.50),
            ("toyota", 0.50),  # total 1.50
            ("ford", 0.50),
            ("ford", 0.50),
            ("ford", 0.46),  # total 1.46, margin = 0.04
        ]
        result = decide_brand(obs, min_margin=0.02)
        assert result is not None
        assert result[0] == "toyota"
