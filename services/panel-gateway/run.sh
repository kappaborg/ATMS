#!/usr/bin/env bash
# Start the ATMS Panel Gateway.
#
#   ./services/panel-gateway/run.sh                 # port 8090
#   PANEL_PORT=9000 ./services/panel-gateway/run.sh
#
# First run: create the venv and install deps:
#   python3.12 -m venv services/panel-gateway/.venv
#   services/panel-gateway/.venv/bin/pip install -r services/panel-gateway/requirements.txt
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PANEL_PORT:-8090}"
PY="${HERE}/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

exec "$PY" -m uvicorn main:app \
  --app-dir "${HERE}/src" \
  --host "${PANEL_HOST:-127.0.0.1}" \
  --port "${PORT}"
