"""
Durable state for the panel gateway.

Persists the camera list and each camera's scene (calibration + zones) to a
JSON file so an operator's setup — especially calibration — survives a
restart. Writes are atomic (temp file + rename) so a crash mid-write can't
corrupt the state.

Path: PANEL_STATE_FILE, default services/panel-gateway/data/panel_state.json.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parents[1] / "data" / "panel_state.json"


def state_path() -> Path:
    return Path(os.getenv("PANEL_STATE_FILE", str(_DEFAULT)))


def load() -> dict:
    p = state_path()
    if not p.exists():
        return {"cameras": []}
    try:
        with p.open() as f:
            data = json.load(f)
        if not isinstance(data, dict) or "cameras" not in data:
            return {"cameras": []}
        return data
    except (json.JSONDecodeError, OSError):
        return {"cameras": []}


def save(state: dict) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".panel_state.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, p)  # atomic on POSIX
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
