#!/usr/bin/env bash
# One-command panel demo: start the gateway and add a looping demo camera.
#
#   ./services/panel-gateway/demo.sh
#
# Then, in another terminal, launch the app:
#   cd panel && npm install && npm run tauri dev     # desktop window
#   # or just the web UI:  cd panel && npm run dev   # http://localhost:1420
#
# Python selection (first that exists):
#   $PANEL_PYTHON  ->  services/panel-gateway/.venv/bin/python  ->  python3
# The interpreter needs the gateway deps (see requirements.txt).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${PANEL_PORT:-8090}"
DEMO_VIDEO="${PANEL_DEMO_VIDEO:-videos/T1.mp4}"

PY="${PANEL_PYTHON:-}"
[ -z "$PY" ] && [ -x "${ROOT}/services/panel-gateway/.venv/bin/python" ] && PY="${ROOT}/services/panel-gateway/.venv/bin/python"
[ -z "$PY" ] && PY="python3"

cd "$ROOT"
echo "▶ starting panel gateway on 127.0.0.1:${PORT} (python: ${PY})"
"$PY" -m uvicorn main:app --app-dir services/panel-gateway/src \
  --host 127.0.0.1 --port "$PORT" --log-level warning &
GW=$!
trap 'kill $GW 2>/dev/null' EXIT

echo "▶ waiting for gateway…"
for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1 && break
  sleep 1
done

echo "▶ adding demo camera (${DEMO_VIDEO}, looping)"
curl -s -X POST "http://127.0.0.1:${PORT}/cameras" \
  -H 'Content-Type: application/json' \
  -d "{\"camera_id\":\"demo\",\"source\":\"${DEMO_VIDEO}\",\"loop_file\":true}" >/dev/null || true

echo "✓ gateway up. Now run the app:  cd panel && npm run tauri dev"
echo "  (Ctrl-C here stops the gateway)"
wait $GW
