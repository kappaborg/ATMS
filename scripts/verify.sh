#!/usr/bin/env bash
# General verify gate — prod-safe: only runs type-check + test suites.
# Mutates nothing (no build artifacts, no network writes, no deploys).
# Wired as the husky pre-push hook; also runnable by hand: bash scripts/verify.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="$ROOT/services/panel-gateway/.venv/bin/python"
if [ -x "$VENV" ]; then PY="$VENV"; else PY="python3"; fi

echo "▶ frontend: svelte-check"
( cd panel && ./node_modules/.bin/svelte-check --tsconfig ./tsconfig.json )

echo "▶ panel-gateway tests"
( cd services/panel-gateway && "$PY" -m pytest tests/ -q )

echo "▶ decision-engine tests"
( cd services/decision-engine && "$PY" -m pytest tests/ -q )

echo "▶ traffic-controller tests"
( cd services/traffic-controller && "$PY" -m pytest tests/ -q )

echo "✓ verify passed — safe to commit/push"
