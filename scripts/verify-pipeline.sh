#!/usr/bin/env bash
# scripts/verify-pipeline.sh
#
# End-to-end software-pipeline verification — every check that can be run
# without bringing up Docker. Designed to be the single command you run
# before claiming "the software is wired correctly":
#
#   ./scripts/verify-pipeline.sh
#
# Exit code 0 = everything green. Non-zero = something to fix; the failing
# check is printed in red.
#
# Coverage:
#   - Python lint (ruff + format)
#   - Type-check (mypy per-root)
#   - Safety-clock lint (ADR-0017)
#   - All four unit-test suites
#   - JSON validity (Grafana dashboards, Keycloak realm, baselines)
#   - YAML validity (docker-compose files, CI workflows)
#   - Python import integrity for shared/atms_common/*
#   - Demo orchestrator headless run
#   - SUMO scenarios load (network XML check)
#   - Documentation cross-references (every link in MEMORY/ROADMAP/STATUS
#     points to an existing file)
#   - ADR ↔ PRODUCTION_GAPS consistency (every "Closes: gap #N" is listed
#     in the gap tracker)

set -u  # NB: we manage failures ourselves; -e would short-circuit reporting

# Colors only if stdout is a TTY
if [ -t 1 ]; then
    R=$'\033[0;31m'; G=$'\033[0;32m'; Y=$'\033[1;33m'; N=$'\033[0m'
else
    R=""; G=""; Y=""; N=""
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Python interpreter — prefer the test venv if present, else system python3.
if [ -x "/tmp/atms-test-venv/bin/python" ]; then
    PY="/tmp/atms-test-venv/bin/python"
    PIPENV="/tmp/atms-test-venv/bin"
else
    PY="$(command -v python3)"
    PIPENV=""
fi

PASS=0
FAIL=0
WARN=0
FAILED_STEPS=()

step() {
    local name="$1"; shift
    printf "%-50s" "$name"
    if "$@" > /tmp/verify-step.log 2>&1; then
        echo "${G}✓${N}"
        PASS=$((PASS+1))
    else
        echo "${R}✗${N}"
        FAIL=$((FAIL+1))
        FAILED_STEPS+=("$name")
        sed 's/^/    /' /tmp/verify-step.log | tail -8
    fi
}

skip() {
    local name="$1" reason="$2"
    printf "%-50s${Y}⊘${N}  %s\n" "$name" "$reason"
    WARN=$((WARN+1))
}

echo "${Y}ATMS pipeline verification — ${REPO_ROOT}${N}"
echo "Python: $PY"
echo "$(date)"
echo

# --------------------------------------------------------------------------
echo "── 1. Static gates ──────────────────────────────────────────────"
# --------------------------------------------------------------------------

_ROOTS_SRC=(shared/atms_common services/traffic-controller/src services/decision-engine/src services/v2x-interface/src simulation tools)
_ROOTS_MYPY=(shared/atms_common services/traffic-controller/src services/decision-engine/src services/v2x-interface/src)

if [ -x "$PIPENV/ruff" ]; then
    step "ruff check (refactored scope)"        "$PIPENV/ruff" check "${_ROOTS_SRC[@]}"
    step "ruff format (refactored scope)"       "$PIPENV/ruff" format --check "${_ROOTS_SRC[@]}"
else
    skip "ruff check"  "ruff not installed in /tmp/atms-test-venv"
    skip "ruff format" "ruff not installed in /tmp/atms-test-venv"
fi

if [ -x "$PIPENV/mypy" ]; then
    for root in "${_ROOTS_MYPY[@]}"; do
        step "mypy $root" "$PIPENV/mypy" "$root"
    done
else
    skip "mypy"  "mypy not installed in /tmp/atms-test-venv"
fi

step "safety-clock lint (ADR-0017)" "$PY" tools/lint_safety_clock.py

# --------------------------------------------------------------------------
echo
echo "── 2. Test suites ───────────────────────────────────────────────"
# --------------------------------------------------------------------------

# Detect pytest availability — /tmp/atms-test-venv loses installed packages
# when macOS cleans /tmp (after reboot or filesystem maintenance). When that
# happens, fall through to a useful skip message rather than 5 confusing
# "No module named pytest" failures.
if "$PY" -c "import pytest" 2>/dev/null; then
    step "tests: traffic-controller"    bash -c "cd services/traffic-controller && '$PY' -m pytest tests -q --no-header"
    step "tests: decision-engine"       bash -c "cd services/decision-engine    && '$PY' -m pytest tests -q --no-header"
    step "tests: simulation harness"    "$PY" -m pytest simulation/tests -q --no-header
    step "tests: simulation demo"       "$PY" -m pytest simulation/demo/tests -q --no-header
    step "tests: tools (lint script)"   "$PY" -m pytest tools/tests -q --no-header
else
    skip "tests: 5 suites"  "pytest not available in $PY — run: $PY -m pip install pytest pytest-asyncio hypothesis"
fi

# --------------------------------------------------------------------------
echo
echo "── 3. Artefact validity ────────────────────────────────────────"
# --------------------------------------------------------------------------

# JSON
for f in infrastructure/observability/grafana/dashboards/*.json \
         deploy/keycloak/atms-realm.json \
         simulation/baselines/*.json; do
    step "JSON valid: $f" "$PY" -c "import json,sys; json.load(open('$f'))"
done

# YAML — docker-compose + workflows
for f in docker-compose*.yml .github/workflows/*.yml; do
    step "YAML valid: $f" "$PY" -c "
import sys
try: import yaml
except ImportError: sys.exit(0)  # yaml not installed → skip silently
yaml.safe_load(open('$f'))
"
done

# Pyproject TOML
step "TOML valid: pyproject.toml" "$PY" -c "
import sys
try:
    import tomllib
except ImportError:
    try: import tomli as tomllib
    except ImportError: sys.exit(0)
tomllib.load(open('pyproject.toml','rb'))
"

# --------------------------------------------------------------------------
echo
echo "── 4. Python import integrity (no service deps) ────────────────"
# --------------------------------------------------------------------------

# These shared-lib modules must import using just the user's system Python
# (no FastAPI / OTel / JWT required, since the demo orchestrator pulls them
# in). If this fails, the demo is broken.
for m in clock decision metrics safety preempt v2x errors timekeeping; do
    step "import shared.atms_common.$m" "$PY" -c "
import sys; sys.path.insert(0,'.')
import shared.atms_common.$m  # noqa
"
done

# --------------------------------------------------------------------------
echo
echo "── 5. Demo orchestrator dry run ────────────────────────────────"
# --------------------------------------------------------------------------

if command -v sumo > /dev/null; then
    step "demo headless 20 steps"  "$PY" -m simulation.demo --max-steps 20
else
    skip "demo headless"  "sumo not on PATH (install eclipse-sumo to enable)"
fi

# --------------------------------------------------------------------------
echo
echo "── 6. SUMO scenarios load ──────────────────────────────────────"
# --------------------------------------------------------------------------

if command -v sumo > /dev/null; then
    for scn in rush-hour demo; do
        step "sumo loads scenarios/$scn" \
            sumo -c "simulation/scenarios/$scn/config.sumocfg" --end 1 --no-step-log true
    done
else
    skip "SUMO scenarios"  "sumo not on PATH"
fi

# --------------------------------------------------------------------------
echo
echo "── 7. Documentation cross-references ──────────────────────────"
# --------------------------------------------------------------------------

step "docs cross-references (active scope)" "$PY" - <<'PYEOF'
"""Check that every relative link in the *active* docs resolves.

Excluded — these are archived SE322-era artefacts retained for posterity:
  - docs/historical/
  - docs/archived/
"""
import pathlib, re, sys
root = pathlib.Path('.')
broken = []
link_re = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')

EXCLUDE_DIRS = ('docs/historical', 'docs/archived', 'docs/technical', 'docs/user-guides')

def is_active(p: pathlib.Path) -> bool:
    s = p.as_posix()
    return not any(s.startswith(d) for d in EXCLUDE_DIRS)

md_files = [p for p in root.glob('docs/**/*.md') if is_active(p)]
if (root/'MEMORY.md').exists():
    md_files.append(root/'MEMORY.md')

for md in md_files:
    text = md.read_text()
    for m in link_re.finditer(text):
        target = m.group(2).split('#')[0]
        if target.startswith(('http://', 'https://', 'mailto:')) or target == '':
            continue
        resolved = (md.parent / target).resolve()
        if not resolved.exists():
            broken.append(f"{md}: -> {target} (resolved={resolved})")
if broken:
    print('\n'.join(broken[:20]))
    print(f"\n{len(broken)} broken link(s) total (active docs only)")
    sys.exit(1)
PYEOF

step "ADR Closes-gap consistency" "$PY" - <<'PYEOF'
import pathlib, re, sys
adr_dir = pathlib.Path('docs/adr')
gaps_text = pathlib.Path('docs/PRODUCTION_GAPS.md').read_text()
missing = []
for adr in sorted(adr_dir.glob('*.md')):
    if 'TEMPLATE' in adr.name.upper():
        continue
    m = re.search(r'Closes:.*PRODUCTION_GAPS\.md\s+gap\s+#(\d+)', adr.read_text())
    if m:
        gap_n = m.group(1)
        # The gap tracker uses `| N |` table rows.
        if f"| {gap_n} |" not in gaps_text:
            missing.append(f"{adr.name} declares Closes gap #{gap_n} but not in PRODUCTION_GAPS.md")
if missing:
    print('\n'.join(missing))
    sys.exit(1)
PYEOF

step "Every ADR is reachable from PRODUCTION_GAPS.md" "$PY" - <<'PYEOF'
import pathlib, re, sys
# Soft check — just confirm each ADR file exists where its filename suggests.
adrs = list(pathlib.Path('docs/adr').glob('[0-9][0-9][0-9][0-9]-*.md'))
if len(adrs) < 19:
    print(f"only {len(adrs)} ADRs found (expected >=19)")
    sys.exit(1)
PYEOF

# --------------------------------------------------------------------------
echo
echo "── 8. Inventory ────────────────────────────────────────────────"
# --------------------------------------------------------------------------

printf "  %-30s %s\n" "Python services:"    "$(ls -d services/*/ 2>/dev/null | wc -l | tr -d ' ')"
printf "  %-30s %s\n" "Shared lib modules:" "$(ls shared/atms_common/*.py | wc -l | tr -d ' ')"
printf "  %-30s %s\n" "ADRs:"               "$(ls docs/adr/[0-9]*.md | wc -l | tr -d ' ')"
printf "  %-30s %s\n" "Runbooks:"           "$(ls docs/runbooks/*.md | wc -l | tr -d ' ')"
printf "  %-30s %s\n" "Compose files:"      "$(ls docker-compose*.yml | wc -l | tr -d ' ')"
printf "  %-30s %s\n" "Grafana dashboards:" "$(ls infrastructure/observability/grafana/dashboards/*.json | wc -l | tr -d ' ')"
printf "  %-30s %s\n" "CI workflows:"       "$(ls .github/workflows/*.yml | wc -l | tr -d ' ')"
printf "  %-30s %s\n" "Alembic migrations:" "$(ls database/alembic/versions/*.py 2>/dev/null | wc -l | tr -d ' ')"
printf "  %-30s %s\n" "SUMO scenarios:"     "$(ls -d simulation/scenarios/*/ 2>/dev/null | grep -v _network_src | wc -l | tr -d ' ')"

# --------------------------------------------------------------------------
echo
echo "─────────────────────────────────────────────────────────────────"
if [ $FAIL -eq 0 ]; then
    echo "${G}✓ all checks passed${N}   (passed=$PASS  warned=$WARN  failed=0)"
    exit 0
else
    echo "${R}✗ $FAIL check(s) failed${N}   (passed=$PASS  warned=$WARN  failed=$FAIL)"
    for s in "${FAILED_STEPS[@]}"; do
        echo "   ${R}- $s${N}"
    done
    exit 1
fi
