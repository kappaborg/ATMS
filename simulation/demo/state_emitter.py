"""Demo state emitter — writes a JSON snapshot per tick so the operator
console (and any other observer) can poll live demo state without needing
the docker-compose stack up.

State file path: `/tmp/atms-demo-state.json` (override via `DEMO_STATE_PATH`).

Single file is intentionally simple. Atomic write via os.rename so a reader
never sees a half-written file.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path(os.getenv("DEMO_STATE_PATH", "/tmp/atms-demo-state.json"))


class StateEmitter:
    """Atomically write a snapshot of the demo's live state.

    The Streamlit operator console (services/operator-console/) polls the
    file at ~2 Hz and renders it. The state shape is intentionally flat so
    a non-Python reader can consume it just as easily.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_STATE_PATH
        self._recent_events: list[dict[str, Any]] = []
        self._max_events = 30

    def append_event(self, kind: str, message: str, sim_time_s: float) -> None:
        """Add a one-line event to the rolling buffer (cues, faults, recoveries)."""
        self._recent_events.append(
            {"sim_time_s": round(sim_time_s, 1), "kind": kind, "message": message}
        )
        # Cap the buffer to keep the JSON small.
        if len(self._recent_events) > self._max_events:
            self._recent_events = self._recent_events[-self._max_events :]

    def emit(self, state: dict[str, Any]) -> None:
        """Write the state dict atomically. Logs but never raises."""
        payload = {**state, "recent_events": list(self._recent_events)}
        try:
            # Atomic rename — readers see either the old or the new file,
            # never an in-progress write.
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self._path.parent,
                prefix=".atms-demo-state-",
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            ) as f:
                json.dump(payload, f, indent=2)
                tmp_name = f.name
            os.replace(tmp_name, self._path)
        except OSError as e:
            log.warning("state emitter could not write %s: %s", self._path, e)
