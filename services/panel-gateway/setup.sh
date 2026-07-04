#!/bin/bash
# Bare-metal setup for the ATMS Panel Gateway (macOS / Linux).
# Creates a self-contained venv; launch.command / run.sh prefer it automatically.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PANEL_PYTHON:-}"
if [ -z "$PY" ]; then
  for cand in python3.12 python3.11; do
    command -v "$cand" >/dev/null 2>&1 && PY="$cand" && break
  done
fi
[ -z "$PY" ] && { echo "Need python3.11 or 3.12 on PATH (or set PANEL_PYTHON)."; exit 1; }

echo "▶ creating .venv with $PY …"
"$PY" -m venv .venv
./.venv/bin/pip install --upgrade pip >/dev/null
echo "▶ installing dependencies (torch/ultralytics — a few minutes on first run) …"
./.venv/bin/pip install -r requirements.txt

echo
echo "✓ done. Start the gateway with:"
echo "    ./services/panel-gateway/launch.command      (from the repo root)"
echo "  or auto-start at login via deploy/launchagents/com.atms.panel-gateway.plist"
