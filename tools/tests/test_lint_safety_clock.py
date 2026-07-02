"""Unit tests for tools/lint_safety_clock.py (ADR-0017 §rule)."""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

_TOOLS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_TOOLS))

import lint_safety_clock as lint  # noqa: E402

# ---------------------------------------------------------------------------
# _dotted_call
# ---------------------------------------------------------------------------


def _first_call(src: str) -> ast.Call:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            return node
    raise AssertionError("no Call node found")


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("time.time()", "time.time"),
        ("time.time_ns()", "time.time_ns"),
        ("datetime.now()", "datetime.now"),
        ("datetime.utcnow()", "datetime.utcnow"),
        ("datetime.datetime.now()", "datetime.datetime.now"),
        ("datetime.datetime.utcnow()", "datetime.datetime.utcnow"),
        ("obj.method()", "obj.method"),  # not banned, but parsed
        ("bare()", "bare"),
    ],
)
def test_dotted_call_extracts_module_path(src: str, expected: str) -> None:
    assert lint._dotted_call(_first_call(src)) == expected


def test_dotted_call_returns_none_for_subscript_call() -> None:
    """e.g. `funcs[0]()` — not a plain module.attr call."""
    src = "funcs[0]()"
    assert lint._dotted_call(_first_call(src)) is None


# ---------------------------------------------------------------------------
# _scan_file — banned vs exempt vs allowed
# ---------------------------------------------------------------------------


def _write(tmp_path: pathlib.Path, source: str) -> pathlib.Path:
    f = tmp_path / "sample.py"
    f.write_text(source, encoding="utf-8")
    return f


def test_scan_flags_time_time(tmp_path: pathlib.Path) -> None:
    f = _write(tmp_path, "import time\nx = time.time()\n")
    violations = lint._scan_file(f)
    assert violations == [(2, "time.time")]


def test_scan_flags_datetime_now_with_tz(tmp_path: pathlib.Path) -> None:
    f = _write(tmp_path, "from datetime import UTC, datetime\nx = datetime.now(UTC)\n")
    violations = lint._scan_file(f)
    assert violations == [(2, "datetime.now")]


def test_scan_flags_datetime_utcnow(tmp_path: pathlib.Path) -> None:
    f = _write(tmp_path, "from datetime import datetime\nx = datetime.utcnow()\n")
    violations = lint._scan_file(f)
    assert violations == [(2, "datetime.utcnow")]


def test_scan_flags_dotted_datetime_datetime_now(tmp_path: pathlib.Path) -> None:
    f = _write(tmp_path, "import datetime\nx = datetime.datetime.now()\n")
    violations = lint._scan_file(f)
    assert violations == [(2, "datetime.datetime.now")]


def test_scan_respects_per_line_noqa(tmp_path: pathlib.Path) -> None:
    f = _write(
        tmp_path,
        "import time\nx = time.time()  # noqa: ATMS-CLOCK  legitimate display\n",
    )
    assert lint._scan_file(f) == []


def test_scan_passes_monotonic_calls(tmp_path: pathlib.Path) -> None:
    f = _write(tmp_path, "import time\nx = time.monotonic_ns()\n")
    assert lint._scan_file(f) == []


def test_scan_does_not_flag_unrelated_dotted_calls(tmp_path: pathlib.Path) -> None:
    f = _write(tmp_path, "import obj\nx = obj.time()\n")  # not the `time` module
    assert lint._scan_file(f) == []


def test_scan_multiple_violations_on_separate_lines(tmp_path: pathlib.Path) -> None:
    f = _write(
        tmp_path,
        "import time\nfrom datetime import datetime\na = time.time()\nb = datetime.utcnow()\n",
    )
    violations = lint._scan_file(f)
    assert violations == [(3, "time.time"), (4, "datetime.utcnow")]


def test_scan_handles_unparseable_file_silently(tmp_path: pathlib.Path) -> None:
    f = tmp_path / "broken.py"
    f.write_text("def f(:\n", encoding="utf-8")  # syntax error
    assert lint._scan_file(f) == []


# ---------------------------------------------------------------------------
# _is_test_file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "p",
    [
        "services/foo/tests/test_x.py",
        "services/foo/tests/conftest.py",
        "tests/integration/test_y.py",
        "shared/atms_common/test_helpers.py",
        "test_module.py",
    ],
)
def test_is_test_file_true(p: str) -> None:
    assert lint._is_test_file(pathlib.Path(p))


@pytest.mark.parametrize(
    "p",
    [
        "services/foo/src/main.py",
        "shared/atms_common/safety.py",
        "tools/lint_safety_clock.py",
    ],
)
def test_is_test_file_false(p: str) -> None:
    assert not lint._is_test_file(pathlib.Path(p))


# ---------------------------------------------------------------------------
# _load_legacy
# ---------------------------------------------------------------------------


def test_load_legacy_returns_empty_when_file_missing(tmp_path: pathlib.Path) -> None:
    assert lint._load_legacy(tmp_path) == set()


def test_load_legacy_parses_paths_and_skips_comments(tmp_path: pathlib.Path) -> None:
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / ".safety_clock_legacy.txt").write_text(
        "# header\n\n  # indented comment\nservices/a.py\n   services/b.py  \n",
        encoding="utf-8",
    )
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "a.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "services" / "b.py").write_text("pass\n", encoding="utf-8")
    legacy = lint._load_legacy(tmp_path)
    expected = {
        (tmp_path / "services" / "a.py").resolve(),
        (tmp_path / "services" / "b.py").resolve(),
    }
    assert legacy == expected
