#!/usr/bin/env python3
"""
ATMS safety-clock lint (ADR-0017 §rule).

Bans wall-clock time sources in safety-scope modules:

    time.time()           # forbidden
    time.time_ns()        # forbidden
    datetime.now(...)     # forbidden (including datetime.now(tz=UTC))
    datetime.utcnow()     # forbidden
    datetime.datetime.*   # forbidden (dotted form of the above)

The monotonic-clock safety rule from ADR-0017 requires every comparison
that influences a control decision to use ``time.monotonic_ns()`` or the
``shared.atms_common.timekeeping.SyncedTimestamp`` helper. Wall-clock
sources are subject to NTP step adjustments and can break min-green /
max-red / preempt-valid-until gates.

Per-line exemption: tag the line with ``# noqa: ATMS-CLOCK`` when the
usage is display-only (HTTP response timestamps, audit-log fields,
JWT iat/exp where the spec requires Unix epoch, etc.).

File-level grandfathering: legacy files awaiting their Phase A2 refactor
are listed in ``tools/.safety_clock_legacy.txt`` and skipped wholesale.
As each file is refactored, remove its entry from that list.

Test files (``tests/`` paths or ``test_*.py``) are always skipped.

Run from repo root:

    python tools/lint_safety_clock.py

Exit status:
    0 — no violations
    1 — one or more violations found
"""

from __future__ import annotations

import ast
import pathlib
import sys

SAFETY_SCOPE = (
    "shared/atms_common",
    "services/traffic-controller/src",
    "services/decision-engine/src",
    "services/ai-perception/src",
)

BANNED_CALLS = frozenset(
    {
        "time.time",
        "time.time_ns",
        "datetime.now",
        "datetime.utcnow",
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
    }
)

EXEMPT_TAG = "ATMS-CLOCK"
LEGACY_LIST = "tools/.safety_clock_legacy.txt"


def _dotted_call(call: ast.Call) -> str | None:
    """Return ``module.func`` for dotted calls, else ``None``.

    ``time.time()`` -> ``"time.time"``;
    ``datetime.datetime.now()`` -> ``"datetime.datetime.now"``;
    ``obj.method()`` (where obj is not a known module name) is returned as
    e.g. ``"obj.method"`` and never matches the banned set.
    """
    parts: list[str] = []
    node: ast.AST = call.func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self, source_lines: list[str]) -> None:
        self._lines = source_lines
        self.violations: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        dotted = _dotted_call(node)
        if dotted in BANNED_CALLS:
            idx = node.lineno - 1
            line = self._lines[idx] if 0 <= idx < len(self._lines) else ""
            if EXEMPT_TAG not in line:
                self.violations.append((node.lineno, dotted))
        self.generic_visit(node)


def _scan_file(path: pathlib.Path) -> list[tuple[int, str]]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    visitor = _Visitor(source.splitlines())
    visitor.visit(tree)
    return visitor.violations


def _is_test_file(path: pathlib.Path) -> bool:
    return any(part == "tests" for part in path.parts) or path.name.startswith("test_")


def _load_legacy(root: pathlib.Path) -> set[pathlib.Path]:
    legacy_file = root / LEGACY_LIST
    if not legacy_file.exists():
        return set()
    out: set[pathlib.Path] = set()
    for raw in legacy_file.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        out.add((root / s).resolve())
    return out


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    legacy = _load_legacy(root)
    total = 0
    files_scanned = 0
    for scope in SAFETY_SCOPE:
        scope_dir = root / scope
        if not scope_dir.exists():
            continue
        for path in sorted(scope_dir.rglob("*.py")):
            if _is_test_file(path):
                continue
            if path.resolve() in legacy:
                continue
            files_scanned += 1
            violations = _scan_file(path)
            if not violations:
                continue
            rel = path.relative_to(root)
            for lineno, kind in violations:
                print(
                    f"{rel}:{lineno}: ATMS-CLOCK {kind}() banned in safety scope "
                    f"(ADR-0017). Use time.monotonic_ns() or "
                    f"shared.atms_common.timekeeping.SyncedTimestamp.now(). "
                    f"For display-only code, append '# noqa: ATMS-CLOCK'."
                )
                total += 1
    if total:
        print(f"\n{total} ATMS-CLOCK violation(s) across {files_scanned} files scanned")
        print("See ADR-0017 §rule.")
        return 1
    print(f"ATMS-CLOCK lint: 0 violations ({files_scanned} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
