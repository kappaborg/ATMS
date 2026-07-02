"""Layer 5 — audit log writer.

JSON-lines format: each tick appends one line containing the full
`ChamberInput` + `ChamberOutput`. Designed for:
- replayability (re-run the chamber on a logged input → same output)
- regulatory audit (incident investigation can replay any decision)
- A/B testing (run shadow chamber with new weights against the same
  inputs offline)

In production this writes to a local SQLite file (rotation-friendly)
and forwards to the city archive. For Phase 1 MVP, JSON-lines on local
disk is enough.

The log NEVER contains PII. Vehicle bboxes, track IDs, brand
identifications are aggregate (counts per direction); no plate
numbers, no per-vehicle fingerprints.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import logging
from datetime import datetime
from pathlib import Path

from simulation.decision_chamber.state import ChamberInput, ChamberOutput

log = logging.getLogger("atms.chamber.audit")


def _serialise(obj):
    """JSON-encoder helper: dataclasses, enums, datetimes."""
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"non-serialisable type: {type(obj)}")


class AuditLogger:
    """Appends one JSON-line per chamber tick to `path`. Creates parent
    dirs as needed. Path None → no-op (used when audit is disabled).
    """

    def __init__(self, path: Path | None):
        self._path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            log.info("audit log: %s", path)

    def write(self, decision_input: ChamberInput, output: ChamberOutput) -> None:
        if self._path is None:
            return
        record = {
            "v": 1,
            "input": dataclasses.asdict(decision_input),
            "output": dataclasses.asdict(output),
        }
        try:
            with self._path.open("a") as f:
                f.write(json.dumps(record, default=_serialise) + "\n")
        except OSError as e:
            log.warning("audit write failed: %s", e)
