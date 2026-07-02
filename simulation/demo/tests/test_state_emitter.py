"""Unit tests for simulation/demo/state_emitter.py."""

from __future__ import annotations

import json
from pathlib import Path

from simulation.demo.state_emitter import StateEmitter


def test_emit_writes_atomic_json(tmp_path: Path):
    path = tmp_path / "state.json"
    emitter = StateEmitter(path=path)
    emitter.emit({"sim_time_s": 12.0, "mode": "AI_ADAPTIVE"})

    data = json.loads(path.read_text())
    assert data["sim_time_s"] == 12.0
    assert data["mode"] == "AI_ADAPTIVE"
    assert data["recent_events"] == []


def test_events_buffer_is_cumulative(tmp_path: Path):
    path = tmp_path / "state.json"
    emitter = StateEmitter(path=path)
    emitter.append_event("cue", "first", sim_time_s=10.0)
    emitter.append_event("v2x_inject", "ev arrived", sim_time_s=60.0)
    emitter.emit({"sim_time_s": 60.0, "mode": "AI_ADAPTIVE"})

    data = json.loads(path.read_text())
    assert len(data["recent_events"]) == 2
    assert data["recent_events"][0]["kind"] == "cue"
    assert data["recent_events"][1]["kind"] == "v2x_inject"


def test_events_buffer_is_capped(tmp_path: Path):
    path = tmp_path / "state.json"
    emitter = StateEmitter(path=path)
    emitter._max_events = 5
    for i in range(20):
        emitter.append_event("cue", f"event {i}", sim_time_s=float(i))
    emitter.emit({"sim_time_s": 20.0, "mode": "AI_ADAPTIVE"})

    data = json.loads(path.read_text())
    assert len(data["recent_events"]) == 5
    # The newest events should be preserved.
    assert data["recent_events"][-1]["message"] == "event 19"


def test_emit_overwrites_previous(tmp_path: Path):
    path = tmp_path / "state.json"
    emitter = StateEmitter(path=path)
    emitter.emit({"sim_time_s": 1.0, "mode": "AI_ADAPTIVE"})
    emitter.emit({"sim_time_s": 2.0, "mode": "ALL_RED_FLASH"})

    data = json.loads(path.read_text())
    assert data["sim_time_s"] == 2.0
    assert data["mode"] == "ALL_RED_FLASH"


def test_emit_path_missing_dir_logs_but_does_not_raise(tmp_path: Path):
    # Force a path whose parent doesn't exist — the emitter should swallow.
    bad_path = tmp_path / "nonexistent" / "state.json"
    emitter = StateEmitter(path=bad_path)
    # Should NOT raise — production demo must never crash on a state-emit error.
    emitter.emit({"sim_time_s": 1.0})
    assert not bad_path.exists()
