"""Network overview: cameras grouped by intersection, and intersection_id
surfaced in the camera list."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hub import CameraManager, Hub


def _manager_with(workers):
    m = CameraManager(Hub())
    m._workers = workers
    return m


def _w(cam_id, iid, src="videos/x.mp4", sahi=False, approach=None):
    return SimpleNamespace(
        cam_id=cam_id, intersection_id=iid, source=src, loop_file=True,
        status="running", error=None, fps=30.0, sahi_enabled=sahi, min_confidence=0.25,
        approach=approach,
        scene=SimpleNamespace(to_payload=lambda: {}, info=lambda: {}),
    )


def test_intersections_grouped_and_sorted():
    m = _manager_with({
        "a": _w("a", "1"), "b": _w("b", "1"), "c": _w("c", "2"),
    })
    got = m.intersections()
    assert got == [
        {"intersection_id": "1", "cameras": ["a", "b"], "name": None, "city": None},
        {"intersection_id": "2", "cameras": ["c"], "name": None, "city": None},
    ]


def test_camera_list_includes_intersection_id():
    m = _manager_with({"a": _w("a", "7")})
    assert m.list()[0]["intersection_id"] == "7"


def test_camera_list_includes_sahi_flag():
    m = _manager_with({"a": _w("a", "1", sahi=True), "b": _w("b", "1")})
    by_id = {c["camera_id"]: c["sahi"] for c in m.list()}
    assert by_id == {"a": True, "b": False}


def test_set_sahi_toggles_and_unknown_raises():
    import pytest

    m = _manager_with({"a": _w("a", "1")})
    m._persist = lambda: None  # no state file in unit test
    m.set_sahi("a", True)
    assert m._workers["a"].sahi_enabled is True
    with pytest.raises(KeyError):
        m.set_sahi("nope", True)


def test_empty_has_no_intersections():
    assert _manager_with({}).intersections() == []


def test_add_rejects_path_traversal_camera_id():
    import pytest

    m = _manager_with({})
    m._persist = lambda: None
    m._detector_lazy = lambda: None
    m.hub = type("H", (), {"_frames": {}})()
    for bad in ["../../etc/passwd", "a/b", "..", "x" * 65, "a b", ""]:
        with pytest.raises(ValueError):
            m.add(bad, "videos/x.mp4")


def test_add_rejects_bad_intersection_id():
    import pytest

    m = _manager_with({})
    m._persist = lambda: None
    m._detector_lazy = lambda: None
    with pytest.raises(ValueError):
        m.add("cam1", "videos/x.mp4", intersection_id="../../evil")


def test_camera_list_includes_min_confidence():
    m = _manager_with({"a": _w("a", "1")})
    assert "min_confidence" in m.list()[0]


def test_camera_list_includes_approach():
    m = _manager_with({"a": _w("a", "1", approach="north"), "b": _w("b", "1")})
    by_id = {c["camera_id"]: c["approach"] for c in m.list()}
    assert by_id == {"a": "north", "b": None}


def test_set_junction_names_and_surfaces_in_intersections():
    m = _manager_with({"a": _w("a", "1")})
    m._persist = lambda: None
    m.set_junction("1", "Marijin Dvor", "Sarajevo")
    got = m.intersections()[0]
    assert got["name"] == "Marijin Dvor"
    assert got["city"] == "Sarajevo"


def test_set_junction_clearing_falls_back_to_id():
    m = _manager_with({"a": _w("a", "1")})
    m._persist = lambda: None
    m.set_junction("1", "Marijin Dvor", "Sarajevo")
    m.set_junction("1", "  ", "")  # cleared
    got = m.intersections()[0]
    assert got["name"] is None and got["city"] is None


def test_named_junction_without_cameras_still_listed():
    """Naming a site then losing its camera must not erase the site."""
    m = _manager_with({})
    m._persist = lambda: None
    m.set_junction("9", "Skenderija", "Sarajevo")
    got = m.intersections()
    assert got == [{"intersection_id": "9", "cameras": [], "name": "Skenderija", "city": "Sarajevo"}]


def test_set_junction_rejects_path_traversal_id():
    import pytest

    m = _manager_with({})
    m._persist = lambda: None
    for bad in ["../../etc", "a/b", "x" * 65, ""]:
        with pytest.raises(ValueError):
            m.set_junction(bad, "n", "c")


def test_add_rejects_bad_approach():
    import pytest

    m = _manager_with({})
    m._persist = lambda: None
    m._detector_lazy = lambda: None
    with pytest.raises(ValueError):
        m.add("cam1", "videos/x.mp4", approach="northwest")


def test_set_min_confidence_clamps():
    import pytest

    m = _manager_with({"a": _w("a", "1")})
    m._persist = lambda: None
    m.set_min_confidence("a", 0.6)
    assert abs(m._workers["a"].min_confidence - 0.6) < 1e-6
    m.set_min_confidence("a", 5.0)  # out of range -> clamped
    assert m._workers["a"].min_confidence == 0.95
    with pytest.raises(KeyError):
        m.set_min_confidence("nope", 0.5)
