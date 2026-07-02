"""Unit tests for simulation/demo/events.py."""

from __future__ import annotations

import pytest

from simulation.demo.events import (
    DEMO_TIMELINE,
    DemoEvent,
    cues_only,
    events_due,
    side_effects,
)


class TestTimelineShape:
    def test_timeline_is_chronological(self):
        times = [e.at_sim_time_s for e in DEMO_TIMELINE]
        assert times == sorted(times)

    def test_timeline_fits_in_300s_scenario(self):
        # All events must fire before the demo scenario ends.
        for e in DEMO_TIMELINE:
            assert 0 <= e.at_sim_time_s < 300

    def test_kinds_are_known(self):
        known = {"cue", "v2x_inject", "ped_call", "force_mode", "recover"}
        for e in DEMO_TIMELINE:
            assert e.kind in known

    def test_force_mode_is_followed_by_recover(self):
        """An ALL_RED_FLASH demo must always show recovery; never leave the
        audience watching a stuck red-flash."""
        force_idx = next(
            (i for i, e in enumerate(DEMO_TIMELINE) if e.kind == "force_mode"),
            None,
        )
        if force_idx is not None:
            after = DEMO_TIMELINE[force_idx + 1 :]
            assert any(e.kind == "recover" for e in after), (
                "force_mode must be followed by a recover event in the timeline"
            )


class TestSplitHelpers:
    def test_cues_only_returns_only_cues(self):
        for e in cues_only():
            assert e.kind == "cue"

    def test_side_effects_returns_only_non_cues(self):
        for e in side_effects():
            assert e.kind != "cue"

    def test_cues_plus_side_effects_equals_timeline(self):
        assert len(cues_only()) + len(side_effects()) == len(DEMO_TIMELINE)


class TestEventsDue:
    @pytest.fixture
    def small_timeline(self):
        return (
            DemoEvent(at_sim_time_s=10.0, cue="a", kind="cue"),
            DemoEvent(at_sim_time_s=20.0, cue="b", kind="v2x_inject", payload={"x": 1}),
            DemoEvent(at_sim_time_s=30.0, cue="c", kind="cue"),
        )

    def test_returns_events_in_window(self, small_timeline):
        due = events_due(25.0, last_fired_at_s=15.0, timeline=small_timeline)
        assert [e.at_sim_time_s for e in due] == [20.0]

    def test_inclusive_on_upper_bound(self, small_timeline):
        # An event at exactly sim_time should fire.
        due = events_due(20.0, last_fired_at_s=15.0, timeline=small_timeline)
        assert [e.at_sim_time_s for e in due] == [20.0]

    def test_exclusive_on_lower_bound(self, small_timeline):
        # An event whose time equals last_fired_at_s should NOT fire again.
        due = events_due(25.0, last_fired_at_s=20.0, timeline=small_timeline)
        assert due == []

    def test_returns_empty_when_no_events_due(self, small_timeline):
        due = events_due(15.0, last_fired_at_s=10.0, timeline=small_timeline)
        assert due == []

    def test_handles_multiple_events_in_one_tick(self, small_timeline):
        # If the simulation jumps from 5s to 35s, all three fire.
        due = events_due(35.0, last_fired_at_s=5.0, timeline=small_timeline)
        assert len(due) == 3
        assert [e.at_sim_time_s for e in due] == [10.0, 20.0, 30.0]

    def test_negative_initial_last_time_fires_first_event(self, small_timeline):
        # The orchestrator starts with last_fired_at_s = -1.0.
        due = events_due(10.0, last_fired_at_s=-1.0, timeline=small_timeline)
        assert len(due) == 1
        assert due[0].at_sim_time_s == 10.0
