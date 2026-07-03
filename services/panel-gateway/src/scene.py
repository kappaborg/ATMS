"""
Per-camera scene configuration: calibration + approach zones.

Parsed from the /cameras/{id}/scene payload and applied to a running worker.
All parts are optional — without a calibration the panel reports no speed;
without zones it falls back to a left/right-of-centre split for the two
decision-engine approaches.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from calibration import ApproachZones, GroundPlaneCalibration, SpeedEstimator


@dataclass
class SceneConfig:
    calibration: GroundPlaneCalibration | None = None
    zones: ApproachZones | None = None
    directions: dict[str, str] = field(default_factory=dict)  # zone name -> "ns" | "ew"
    speed: SpeedEstimator | None = None

    @classmethod
    def from_payload(cls, payload: dict) -> "SceneConfig":
        calib = None
        speed = None
        cal = payload.get("calibration")
        if cal:
            calib = GroundPlaneCalibration(
                [tuple(p) for p in cal["image_points"]],
                [tuple(p) for p in cal["world_points_m"]],
            )
            speed = SpeedEstimator(calib)

        zones = None
        z = payload.get("zones")
        if z:
            zones = ApproachZones({name: [tuple(p) for p in poly] for name, poly in z.items()})

        directions = {k: str(v).lower() for k, v in (payload.get("zone_directions") or {}).items()}
        return cls(calibration=calib, zones=zones, directions=directions, speed=speed)

    def info(self) -> dict:
        return {
            "calibrated": self.calibration is not None,
            "reprojection_error_m": (
                round(self.calibration.reprojection_error_m, 3) if self.calibration else None
            ),
            "zones": self.zones.names if self.zones else [],
            "zone_directions": self.directions,
        }

    def to_payload(self) -> dict:
        """Serialise back to the /scene request form so it can be persisted
        and re-applied verbatim after a restart."""
        out: dict = {}
        if self.calibration is not None:
            out["calibration"] = {
                "image_points": [list(p) for p in self.calibration.image_points],
                "world_points_m": [list(p) for p in self.calibration.world_points_m],
            }
        if self.zones is not None:
            out["zones"] = self.zones.to_dict()
        if self.directions:
            out["zone_directions"] = dict(self.directions)
        return out

    def is_empty(self) -> bool:
        return self.calibration is None and self.zones is None
