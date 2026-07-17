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

# No footage ships with this repo — media is deliberately kept out of git — so
# the historic `videos/T1.mp4` default resolves to nothing on a clean clone.
# Check before starting anything: the gateway would otherwise come up with a
# camera that silently never opens, and the script would still print "✓".
# Streams are left to the gateway, which validates them (and rejects SSRF).
case "$DEMO_VIDEO" in
  rtsp://* | http://* | https://* | [0-9]) ;;
  *)
    if [ ! -f "$DEMO_VIDEO" ]; then
      cat >&2 <<MSG
✗ demo source not found: ${DEMO_VIDEO}

No video is bundled with this repo. Give the demo a real source:

  # a clip — must sit under ${ROOT}/videos or ${ROOT}/Processed_Videos
  # (the gateway confines file sources to those; widen with ATMS_ALLOWED_VIDEO_DIRS)
  mkdir -p "${ROOT}/videos" && cp /your/clip.mp4 "${ROOT}/videos/T1.mp4"
  ./services/panel-gateway/demo.sh

  # or a live stream / USB camera, which have no such restriction
  PANEL_DEMO_VIDEO=rtsp://user:pass@host/stream  ./services/panel-gateway/demo.sh
  PANEL_DEMO_VIDEO=0                             ./services/panel-gateway/demo.sh
MSG
      exit 1
    fi
    ;;
esac

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
# Report a rejection instead of swallowing it: `|| true` here meant a refused
# source (missing file, SSRF block, auth) still printed "✓ gateway up".
add_body="$(curl -s -o /tmp/atms-demo-add.$$ -w '%{http_code}' \
  -X POST "http://127.0.0.1:${PORT}/cameras" \
  -H 'Content-Type: application/json' \
  -d "{\"camera_id\":\"demo\",\"source\":\"${DEMO_VIDEO}\",\"loop_file\":true}" || echo 000)"
if [ "$add_body" != "200" ]; then
  echo "✗ the gateway refused the demo camera (HTTP ${add_body}):" >&2
  cat /tmp/atms-demo-add.$$ >&2 2>/dev/null || true
  echo >&2
  rm -f /tmp/atms-demo-add.$$
  exit 1
fi
rm -f /tmp/atms-demo-add.$$

echo "✓ gateway up. Now run the app:  cd panel && npm run tauri dev"
echo "  (Ctrl-C here stops the gateway)"
wait $GW
