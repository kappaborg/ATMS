"""Deep ReID: identity recovery is CONSERVATIVE — recover clear matches,
never merge ambiguous ones."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import reid as reid_mod
from reid import DeepReID


def _vec(seed, d=64):
    rng = np.random.RandomState(seed)
    v = rng.randn(d)
    return v / np.linalg.norm(v)


def _mk(monkeypatch, emb_by_key):
    """DeepReID whose embed() returns a canned vector keyed by bbox x1."""
    r = DeepReID(ttl_s=10.0, sim_thresh=0.90, margin=0.05, update_every=1)
    monkeypatch.setattr(r, "embed", lambda frame, bbox: emb_by_key.get(int(bbox[0])))
    return r


FRAME = np.zeros((100, 100, 3), dtype=np.uint8)


def test_recovers_clear_match(monkeypatch):
    a = _vec(1)
    r = _mk(monkeypatch, {10: a, 11: a})  # same appearance at both times
    for _ in range(3):
        r.note_seen(42, FRAME, (10, 0, 50, 40), (30, 20))
    r.note_lost(42, t=100.0)
    got = r.recover(FRAME, (11, 0, 51, 40), (32, 22), t=103.0, frame_diag=141.0)
    assert got == 42
    assert 42 not in r._gallery  # consumed


def test_ambiguous_candidates_not_merged(monkeypatch):
    a = _vec(1)
    r = _mk(monkeypatch, {10: a, 20: a, 11: a})  # two lost vehicles look identical
    for _ in range(3):
        r.note_seen(1, FRAME, (10, 0, 50, 40), (30, 20))
    r.note_lost(1, 100.0)
    for _ in range(3):
        r.note_seen(2, FRAME, (20, 0, 60, 40), (40, 20))
    r.note_lost(2, 100.0)
    # margin gate: best and runner-up are equal -> cannot be sure -> no merge
    assert r.recover(FRAME, (11, 0, 51, 40), (31, 20), 101.0, 141.0) is None


def test_low_similarity_not_merged(monkeypatch):
    r = _mk(monkeypatch, {10: _vec(1), 11: _vec(2)})  # different appearance
    for _ in range(3):
        r.note_seen(7, FRAME, (10, 0, 50, 40), (30, 20))
    r.note_lost(7, 100.0)
    assert r.recover(FRAME, (11, 0, 51, 40), (30, 20), 101.0, 141.0) is None


def test_spatially_distant_not_merged(monkeypatch):
    a = _vec(1)
    r = _mk(monkeypatch, {10: a, 11: a})
    for _ in range(3):
        r.note_seen(9, FRAME, (10, 0, 50, 40), (5, 5))
    r.note_lost(9, 100.0)
    # reappears across the frame (> 0.25 * diag) -> not the same parked/occluded car
    assert r.recover(FRAME, (11, 0, 51, 40), (95, 95), 101.0, 141.0) is None


def test_gallery_expires(monkeypatch):
    a = _vec(1)
    r = _mk(monkeypatch, {10: a, 11: a})
    for _ in range(3):
        r.note_seen(5, FRAME, (10, 0, 50, 40), (30, 20))
    r.note_lost(5, 100.0)
    assert r.recover(FRAME, (11, 0, 51, 40), (30, 20), 100.0 + r.ttl_s + 1, 141.0) is None


def test_enabled_env(monkeypatch):
    monkeypatch.delenv("PANEL_REID", raising=False)
    assert reid_mod.enabled() is True  # on by default
    monkeypatch.setenv("PANEL_REID", "0")
    assert reid_mod.enabled() is False
