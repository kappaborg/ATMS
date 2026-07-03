#!/usr/bin/env bash
# Double-click this in Finder (or run it) to start the ATMS Panel gateway.
# Leave it running; then open "ATMS Panel" from Applications/Launchpad.
# The gateway idles at ~0% CPU when the app isn't open.
cd "$(dirname "$0")/../.." || exit 1   # repo root
PORT="${PANEL_PORT:-8090}"

# Pick a Python with the gateway deps:
#   $PANEL_PYTHON  ->  services/panel-gateway/.venv  ->  Homebrew 3.12 + the
#   ai-perception venv's packages (this machine's existing environment).
PY="${PANEL_PYTHON:-}"
SITE=""
if [ -z "$PY" ] && [ -x "services/panel-gateway/.venv/bin/python" ]; then
  PY="services/panel-gateway/.venv/bin/python"
elif [ -z "$PY" ]; then
  PY="$(ls /opt/homebrew/Cellar/python@3.12/*/Frameworks/Python.framework/Versions/3.12/bin/python3.12 2>/dev/null | head -1)"
  [ -d "services/ai-perception/venv/lib/python3.12/site-packages" ] && \
    SITE="services/ai-perception/venv/lib/python3.12/site-packages"
fi
[ -z "$PY" ] && PY="python3"

echo "▶ ATMS Panel gateway on http://127.0.0.1:${PORT}  (python: ${PY})"
echo "  Leave this window open. Ctrl-C to stop."
exec "$PY" -c "
import os, site, sys
sp = os.environ.get('PANEL_SITE', '${SITE}')
if sp:
    site.addsitedir(sp)
import uvicorn
uvicorn.run('main:app', host='127.0.0.1', port=${PORT},
            app_dir='services/panel-gateway/src', log_level='warning')
"
