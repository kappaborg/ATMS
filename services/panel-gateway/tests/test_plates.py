"""Plate reader — the caching/budget/gating logic (model-free so it's fast)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import plates


def test_enabled_reads_env(monkeypatch):
    monkeypatch.delenv("PANEL_READ_PLATES", raising=False)
    assert plates.enabled() is False
    monkeypatch.setenv("PANEL_READ_PLATES", "1")
    assert plates.enabled() is True


def test_cache_returned_without_reload():
    r = plates.PlateReader()
    r._cache[7] = "ABC123"
    assert r.cached(7) == "ABC123"
    # a cached plate short-circuits read() (no model load needed)
    assert r.read(None, (0, 0, 10, 10), 7) == "ABC123"


def test_per_frame_budget(monkeypatch):
    r = plates.PlateReader(max_per_frame=1)
    calls = []
    monkeypatch.setattr(r, "_lazy", lambda: (calls.append(1), False)[1])  # models unavailable
    r.begin_frame()
    r.read(None, (0, 0, 10, 10), 1)  # consumes the frame's budget
    r.read(None, (0, 0, 10, 10), 2)  # budget exhausted -> no attempt
    assert len(calls) == 1


def test_attempts_bounded_by_max_tries(monkeypatch):
    r = plates.PlateReader(max_per_frame=10, max_tries=3)
    calls = []
    monkeypatch.setattr(r, "_lazy", lambda: (calls.append(1), False)[1])
    for _ in range(10):  # same track over 10 frames
        r.begin_frame()
        r.read(None, (0, 0, 10, 10), 1)
    assert len(calls) == 3  # retried, but capped at max_tries


def test_remove_clears_state():
    r = plates.PlateReader()
    r._cache[3] = "XYZ"
    r._attempts[3] = 2
    r.remove(3)
    assert r.cached(3) is None and 3 not in r._attempts
