"""Multi-camera per-intersection support.

Production reality: most major intersections have 2-4 cameras (one
covering each approach, or one wide + one narrow per direction). A
single chamber needs to consume detections from all of them and merge
into per-direction state.

Phase 10.2 deliverable: a `CameraGroup` that:
- Loads N camera configs from the site YAML
- Each camera has its own RTSP source, homography, crosswalk zones,
  and direction assignments
- Background thread per camera reads frames + runs YOLOv8
- Detections from each camera get tagged with `source_camera_id`
- Combined detection stream feeds the existing tracker + chamber

For Phase 10.2 we ship the interface + config layer. The full background-
thread vision pipeline integration is a separate engineering effort
documented in ADR-0024 (pending). For now the chamber operates on the
PRIMARY camera; the multi-camera config is consumed by the homography
loader so per-camera calibrations apply correctly.

Real production deployment (future Phase): each camera runs its own
YOLOv8 instance on a multi-GPU edge box; detections fuse at the chamber.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("atms.video.multi_camera")


@dataclass(frozen=True)
class CameraSpec:
    """One physical camera at the intersection."""

    camera_id: str  # e.g. "north-approach-cam01"
    source: str  # RTSP URL or local video path
    pixels_per_meter: float
    width: int = 1920
    height: int = 1080
    homography_path: str = ""
    # Which directions this camera CAN observe (subset of all chamber
    # directions). Detections from this camera will only contribute to
    # these directions' state.
    covers_directions: tuple[str, ...] = ()
    # Whether this is the PRIMARY camera (used for the operator console
    # video preview + chamber HUD). One per intersection.
    is_primary: bool = False


@dataclass(frozen=True)
class CameraGroupConfig:
    """All cameras at one intersection."""

    cameras: tuple[CameraSpec, ...] = field(default_factory=tuple)

    @property
    def primary(self) -> CameraSpec | None:
        for c in self.cameras:
            if c.is_primary:
                return c
        return self.cameras[0] if self.cameras else None

    def camera_for_direction(self, direction: str) -> CameraSpec | None:
        """Returns the BEST camera covering this direction (primary first,
        then any camera covering it).
        """
        # Primary wins if it covers this direction
        primary = self.primary
        if primary and direction in primary.covers_directions:
            return primary
        for c in self.cameras:
            if direction in c.covers_directions:
                return c
        return None

    @classmethod
    def load(cls, raw: dict | None) -> "CameraGroupConfig":
        """Parse from the site YAML's `cameras` section. Backwards
        compatible: if `cameras` is absent the site uses the legacy
        single `camera` block (handled by SiteConfig.camera).
        """
        if not raw:
            return cls(cameras=())
        cams: list[CameraSpec] = []
        for c in raw:
            cams.append(CameraSpec(
                camera_id=c.get("camera_id", "cam-unnamed"),
                source=c.get("source", ""),
                pixels_per_meter=float(c.get("pixels_per_meter", 25.0)),
                width=int(c.get("width", 1920)),
                height=int(c.get("height", 1080)),
                homography_path=c.get("homography_path", ""),
                covers_directions=tuple(c.get("covers_directions", []) or []),
                is_primary=bool(c.get("is_primary", False)),
            ))
        if cams and not any(c.is_primary for c in cams):
            # Auto-promote first camera if none marked primary
            cams[0] = CameraSpec(**{**cams[0].__dict__, "is_primary": True})
        return cls(cameras=tuple(cams))

    def validate(self) -> list[str]:
        """Return list of validation warnings (empty = clean)."""
        warnings: list[str] = []
        if not self.cameras:
            return warnings  # legacy single-camera mode, OK
        primary_count = sum(1 for c in self.cameras if c.is_primary)
        if primary_count > 1:
            warnings.append(
                f"multiple primary cameras configured ({primary_count}); "
                "only the first is used for the operator HUD"
            )
        # Check that every chamber direction is covered by at least one camera
        all_covered: set[str] = set()
        for c in self.cameras:
            all_covered.update(c.covers_directions)
        for required in ("north_south", "east_west"):
            if required not in all_covered:
                warnings.append(
                    f"no camera covers direction {required!r} — chamber state "
                    "for this direction will be empty"
                )
        # Every camera should have a homography
        for c in self.cameras:
            if not c.homography_path:
                warnings.append(
                    f"camera {c.camera_id!r} has no homography_path — "
                    "speed estimates will use coarse pixels_per_meter"
                )
        return warnings
