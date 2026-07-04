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


def _w(cam_id, iid, src="videos/x.mp4", sahi=False):
    return SimpleNamespace(
        cam_id=cam_id, intersection_id=iid, source=src, loop_file=True,
        status="running", error=None, fps=30.0, sahi_enabled=sahi,
        scene=SimpleNamespace(to_payload=lambda: {}, info=lambda: {}),
    )


def test_intersections_grouped_and_sorted():
    m = _manager_with({
        "a": _w("a", "1"), "b": _w("b", "1"), "c": _w("c", "2"),
    })
    got = m.intersections()
    assert got == [
        {"intersection_id": "1", "cameras": ["a", "b"]},
        {"intersection_id": "2", "cameras": ["c"]},
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
