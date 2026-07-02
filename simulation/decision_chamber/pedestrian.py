"""Pedestrian phase integration — Layer 2 input to the Decision Chamber.

Pedestrian demand is treated as a HARD constraint, not a soft signal:

1. When a pedestrian requests the crossing (button OR vision), the chamber's
   L2 policy gate enforces a minimum WALK + clearance time for the direction
   serving that crossing.
2. The chamber cannot interrupt an active pedestrian phase.
3. If demand persists across multiple cycles without service, a hard
   `max_pedestrian_wait_seconds` triggers preemption-level priority (Phase 3
   addition; Phase 2 relies on the normal max_phase + fairness terms).

Real-world data flow (production):
    push button  → NTCIP detector input → ButtonPedestrianDetector
    person in    → camera + YOLOv8       → VisionPedestrianDetector
    crosswalk      class 0 + zone check
    operator     → /tmp/atms-ped-button.json (operator console writes)
    request

Walk + clearance timing follows MUTCD §4E.06:
    minimum walk     ≥ 7 s
    clearance time   = crossing_distance / walking_speed   (1.0 m/s default)

For a 12 m crossing: walk(7) + clearance(12) = 19 s minimum red+walk
indication for vehicles on the cross street.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("atms.chamber.pedestrian")


class PedestrianDetector(Protocol):
    """Real implementations talk to a real demand source (NTCIP detector,
    camera-based vision, REST endpoint from a mobile app). They report
    which direction has pedestrian demand. The chamber treats all
    detector outputs as a logical OR — any source can register demand.
    """

    name: str

    def poll(self, tick_time: datetime, context: dict[str, Any]) -> set[str]:
        """Return the set of direction names with current pedestrian demand.
        Empty set = no demand. Must not raise — detector errors → log + empty.
        """
        ...


class ButtonPedestrianDetector:
    """File-based pedestrian button. Operator console writes a small JSON
    file when the operator (or in real-world: the push button via NTCIP
    detector input) requests a pedestrian phase. Format:

        {
            "direction": "north_south",
            "expires_at": "2026-06-14T05:00:00Z",
            "notes": "operator button"
        }

    Production swap: replace this with a real NTCIP detector reader. The
    interface stays identical — only the implementation changes.
    """

    name = "pedestrian_button"

    def __init__(self, button_file: Path):
        self._path = button_file

    def poll(self, tick_time: datetime, context: dict[str, Any]) -> set[str]:
        if not self._path.exists():
            return set()
        try:
            data = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning("ped button file unreadable: %s", e)
            return set()
        try:
            expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError) as e:
            log.warning("ped button missing/bad expires_at: %s", e)
            return set()
        if tick_time.astimezone() > expires_at.astimezone():
            return set()
        direction = data.get("direction")
        return {direction} if direction else set()


class VisionPedestrianDetector:
    """Camera-based pedestrian detection — Phase 4 real implementation.

    The video pipeline detects YOLOv8 class 0 (person) bboxes in the
    same inference pass that produces vehicle detections (zero extra
    inference cost). The pipeline passes those person bboxes through
    `detector_context['person_bboxes']`. This detector checks whether
    any person's bbox center lies within a configured "crosswalk zone"
    rectangle for each direction, and emits pedestrian demand for the
    matching direction.

    Real production deployment:
    - Per-camera homography calibrated during site survey
    - Crosswalk zones loaded from intersection JSON (x1,y1,x2,y2 in
      pixel coords for each direction)
    - Optional: separate "waiting zone" (curb area) vs "crossing zone"
      (street area) for finer-grained intent inference

    Dev defaults (when `crosswalk_zones` is None and `frame_shape` is
    available): NS zone = bottom 25% of frame, EW zone = left 25% of
    frame. These are heuristics for a typical 4-way arterial camera.
    Override by passing explicit zones.
    """

    name = "vision_pedestrian"

    def __init__(
        self,
        crosswalk_zones: dict[str, tuple[int, int, int, int]] | None = None,
        default_frame_shape: tuple[int, int] | None = None,
    ):
        self._zones = crosswalk_zones or {}
        self._default_frame_shape = default_frame_shape

    def _resolve_zones(self, frame_shape: tuple[int, int] | None) -> dict[str, tuple[int, int, int, int]]:
        """Return active crosswalk zones. Explicit config wins; otherwise
        derive heuristic defaults from the frame shape.
        """
        if self._zones:
            return self._zones
        shape = frame_shape or self._default_frame_shape
        if shape is None:
            return {}
        H, W = shape
        return {
            # NS crossing: bottom strip of frame (people crossing E-W traffic)
            "north_south": (0, int(H * 0.75), W, H),
            # EW crossing: left strip of frame (people crossing N-S traffic)
            "east_west": (0, 0, int(W * 0.25), H),
        }

    def poll(self, tick_time: datetime, context: dict[str, Any]) -> set[str]:
        person_bboxes: list[tuple[float, float, float, float]] = (
            context.get("person_bboxes") or []
        )
        if not person_bboxes:
            return set()
        frame_shape = context.get("frame_shape")
        zones = self._resolve_zones(frame_shape)
        if not zones:
            return set()

        demands: set[str] = set()
        for bbox in person_bboxes:
            x1, y1, x2, y2 = bbox
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            for direction, (zx1, zy1, zx2, zy2) in zones.items():
                if zx1 <= cx <= zx2 and zy1 <= cy <= zy2:
                    demands.add(direction)
        return demands


def aggregate_demand(
    detectors: list[PedestrianDetector],
    tick_time: datetime,
    context: dict[str, Any],
) -> set[str]:
    """Logical OR across all pedestrian detectors. Detector exceptions
    are logged and skipped, never propagated.
    """
    out: set[str] = set()
    for det in detectors:
        try:
            out |= det.poll(tick_time, context)
        except Exception as e:
            log.warning("ped detector %s raised: %s — skipping", det.name, e)
    return out


def compute_ped_min_phase_seconds(
    crossing_distance_m: float,
    walking_speed_mps: float = 1.0,
    min_walk_seconds: float = 7.0,
) -> float:
    """MUTCD §4E.06 calculation: WALK indication + flashing DON'T WALK
    clearance. Returns the minimum vehicle red phase time so a pedestrian
    starting at the legal latest moment still finishes safely.

    Defaults: 1.0 m/s walking speed (slow walker accommodation), 7s
    minimum WALK indication. Override per-jurisdiction (e.g., NYC uses
    3.0 ft/s ≈ 0.91 m/s in some legislation).
    """
    clearance = crossing_distance_m / max(walking_speed_mps, 0.5)
    return max(min_walk_seconds, clearance) + min_walk_seconds
