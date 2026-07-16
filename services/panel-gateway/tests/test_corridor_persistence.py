"""Corridors must survive a gateway restart — and bring their coordination
with them. Before this, `_corridors` was in-memory only: a restart silently
dropped the corridor AND the green-wave offsets pushed onto each engine, with
no error and no empty state to notice."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import store
from hub import CameraManager, Hub

PAYLOAD = {
    "corridor_id": "main-st",
    "direction": "north_south",
    "design_speed_kmh": 50.0,
    "cycle_s": 60.0,
    "green_s": 27.0,
    "stops": [
        {"intersection_id": "1", "distance_m": 0},
        {"intersection_id": "2", "distance_m": 400},
    ],
}


class _Engine:
    """Records what the corridor pushed onto it."""

    def __init__(self):
        self.coord = None

    def set_coordination(self, offset_s, cycle_s, green_s, direction):
        self.coord = {"offset_s": offset_s, "cycle_s": cycle_s, "green_s": green_s, "direction": direction}

    def clear_coordination(self):
        self.coord = None


def _w(cam_id, iid):
    return SimpleNamespace(
        cam_id=cam_id, intersection_id=iid, source="videos/x.mp4", loop_file=True,
        status="running", error=None, fps=30.0, sahi_enabled=False, min_confidence=0.25,
        approach=None, engine=_Engine(),
        scene=SimpleNamespace(to_payload=lambda: {}, info=lambda: {}),
    )


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    monkeypatch.setenv("PANEL_STATE_FILE", str(p))
    return p


def _manager(workers):
    m = CameraManager(Hub())
    m._workers = workers
    return m


def test_corridor_survives_restart_and_recoordinates(state_file, monkeypatch):
    m1 = _manager({"a": _w("a", "1"), "b": _w("b", "2")})
    m1.add_corridor(PAYLOAD)
    assert m1._workers["b"].engine.coord is not None  # coordinated before restart

    # A fresh manager reading the same state file == a gateway restart. Cameras
    # are stubbed in (restore() would need a real detector), so drive the
    # corridor half of restore() directly against the saved state.
    m2 = _manager({"a": _w("a", "1"), "b": _w("b", "2")})
    saved = store.load()
    assert "corridors" in saved, "corridors were not persisted at all"
    for entry in saved["corridors"]:
        from corridor import build_corridor
        corr = build_corridor(entry)
        m2._corridors[corr.corridor_id] = corr
        m2._apply_coordination(corr)

    assert [c["corridor_id"] for c in m2.list_corridors()] == ["main-st"]
    # The list coming back is not enough — the engines must be coordinating again.
    assert m2._workers["b"].engine.coord == m1._workers["b"].engine.coord


def test_removing_a_corridor_persists_the_removal(state_file):
    m = _manager({"a": _w("a", "1"), "b": _w("b", "2")})
    m.add_corridor(PAYLOAD)
    m.remove_corridor("main-st")
    assert store.load()["corridors"] == []
    assert m._workers["b"].engine.coord is None  # and the engine was cleared


def test_restore_tolerates_state_without_corridors_key(state_file):
    """Old state files predate this field."""
    store.save({"cameras": []})
    m = _manager({})
    m._detector_lazy = lambda: None
    assert m.restore() == 0
    assert m.list_corridors() == []


def test_restore_skips_a_bad_corridor_without_blocking_the_rest(state_file):
    store.save({
        "cameras": [],
        "junctions": {},
        "corridors": [
            {"corridor_id": "bad", "stops": [{"intersection_id": "1", "distance_m": 0}]},  # <2 stops
            PAYLOAD,
        ],
    })
    m = _manager({"a": _w("a", "1"), "b": _w("b", "2")})
    m._detector_lazy = lambda: None
    m.restore()
    assert [c["corridor_id"] for c in m.list_corridors()] == ["main-st"]
