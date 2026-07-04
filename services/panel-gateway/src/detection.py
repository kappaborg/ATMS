"""
Lean detection + annotation for the panel gateway.

Uses ultralytics YOLO directly (same yolov8n weights as the rest of ATMS)
for detection, and draws the annotated overlay. Kept deliberately small and
decoupled from the ai-perception service so the gateway is self-contained.

Fail-loud: if ultralytics is unavailable and mock mode is not explicitly
enabled (ATMS_ALLOW_MOCK_DETECTIONS=1), detection raises instead of silently
fabricating data — consistent with the rest of the system.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

# Strict live mode (government/production): all data must be real. Overrides
# any mock opt-in and forbids file sources (see security.validate_source).
STRICT_LIVE = os.getenv("ATMS_STRICT_LIVE", "").lower() in ("1", "true", "yes")
MOCK_ALLOWED = (
    os.getenv("ATMS_ALLOW_MOCK_DETECTIONS", "").lower() in ("1", "true", "yes")
    and not STRICT_LIVE
)

# COCO class ids we care about for traffic, mapped to display labels + colours.
_CLASSES: dict[int, tuple[str, tuple[int, int, int]]] = {
    0: ("person", (0, 200, 255)),
    1: ("bicycle", (0, 255, 200)),
    2: ("car", (0, 220, 0)),
    3: ("motorcycle", (0, 255, 120)),
    5: ("bus", (255, 160, 0)),
    7: ("truck", (255, 90, 0)),
}
_VEHICLE_IDS = {1, 2, 3, 5, 7}
_PEDESTRIAN_IDS = {0}


@dataclass
class Detection:
    track_id: int
    cls_id: int
    label: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    speed_kmh: float | None = None
    approach: str | None = None
    stopped: bool = False
    speeding: bool = False
    wrong_way: bool = False
    red_light: bool = False
    reckless: bool = False
    drift: bool = False

    @property
    def center(self) -> tuple[float, float]:
        return (self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2

    @property
    def is_vehicle(self) -> bool:
        return self.cls_id in _VEHICLE_IDS


@dataclass
class FrameResult:
    detections: list[Detection] = field(default_factory=list)
    vehicle_count: int = 0
    pedestrian_count: int = 0


def _resolve_model_path() -> str | None:
    root = Path(__file__).resolve().parents[3]
    for p in (root / "models/yolov8n.pt", root / "yolov8n.pt"):
        if p.exists():
            return str(p)
    return "yolov8n.pt"  # ultralytics will fetch if network is available


class Detector:
    """Thin YOLO wrapper. Constructed once per gateway process (shared across
    camera workers; ultralytics inference is called under the worker's own
    lock to keep the model single-threaded)."""

    def __init__(self, confidence: float = 0.35, model_path: str | None = None):
        self.confidence = confidence
        self.model = None
        self._load(model_path or _resolve_model_path())

    def _load(self, model_path: str | None) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as e:
            if not MOCK_ALLOWED:
                raise RuntimeError(
                    "ultralytics is not installed and mock mode is not enabled "
                    "(ATMS_ALLOW_MOCK_DETECTIONS=1). Install requirements.txt."
                ) from e
            self.model = None
            return
        self.model = YOLO(model_path)

    def infer(self, frame: np.ndarray) -> list[tuple[int, float, tuple[float, float, float, float]]]:
        """Return raw detections as (cls_id, confidence, (x1,y1,x2,y2))."""
        if self.model is None:
            return []  # mock mode: no synthetic data, just empty
        results = self.model(
            frame, verbose=False, conf=self.confidence, classes=list(_CLASSES.keys())
        )
        out: list[tuple[int, float, tuple[float, float, float, float]]] = []
        if not results:
            return out
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return out
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        clss = boxes.cls.cpu().numpy()
        for i in range(len(boxes)):
            out.append((int(clss[i]), float(confs[i]), tuple(map(float, xyxy[i][:4]))))
        return out


def to_tracker_input(raw) -> list[dict]:
    """Adapt raw detections to the SimpleByteTracker input schema."""
    dets = []
    for cls_id, conf, (x1, y1, x2, y2) in raw:
        dets.append(
            {"bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2}, "confidence": conf, "class_id": cls_id}
        )
    return dets


def summarize(tracked: list[dict]) -> FrameResult:
    result = FrameResult()
    for t in tracked:
        cls_id = int(t.get("class_id", 2))
        label, _ = _CLASSES.get(cls_id, ("object", (200, 200, 200)))
        bbox = t.get("bbox", {})
        det = Detection(
            track_id=int(t.get("track_id", -1)),
            cls_id=cls_id,
            label=label,
            confidence=float(t.get("confidence", 0.0)),
            bbox=(
                float(bbox.get("x1", 0)),
                float(bbox.get("y1", 0)),
                float(bbox.get("x2", 0)),
                float(bbox.get("y2", 0)),
            ),
        )
        result.detections.append(det)
        if cls_id in _VEHICLE_IDS:
            result.vehicle_count += 1
        elif cls_id in _PEDESTRIAN_IDS:
            result.pedestrian_count += 1
    return result


def annotate(frame: np.ndarray, result: FrameResult, phase: str | None, fps: float) -> np.ndarray:
    """Draw boxes, track ids, and a compact status header onto the frame."""
    for d in result.detections:
        x1, y1, x2, y2 = map(int, d.bbox)
        # Most-severe violation wins the box colour/label (BGR).
        flagged = (d.drift or d.wrong_way or d.red_light or d.reckless
                   or d.stopped or d.speeding)
        if d.drift:
            colour, tag = (255, 255, 0), f"DRIFT #{d.track_id}"           # cyan
        elif d.wrong_way:
            colour, tag = (255, 0, 255), f"WRONG-WAY #{d.track_id}"       # magenta
        elif d.red_light:
            colour, tag = (0, 0, 200), f"RED-LIGHT #{d.track_id}"         # dark red
        elif d.reckless:
            colour, tag = (255, 0, 128), f"RECKLESS #{d.track_id}"        # purple
        elif d.stopped:
            colour, tag = (0, 0, 255), f"STOPPED #{d.track_id}"           # red
        elif d.speeding:
            colour = (0, 140, 255)                                        # orange
            tag = f"SPEEDING #{d.track_id} {d.speed_kmh:.0f}km/h"
        else:
            _, colour = _CLASSES.get(d.cls_id, ("object", (200, 200, 200)))
            tag = f"{d.label} #{d.track_id}"
            if d.speed_kmh is not None:
                tag += f" {d.speed_kmh:.0f}km/h"
            else:
                tag += f" {d.confidence:.0%}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 3 if flagged else 2)
        (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), colour, -1)
        cv2.putText(frame, tag, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)

    header = (
        f"Veh {result.vehicle_count}  Ped {result.pedestrian_count}  "
        f"{fps:.0f} FPS" + (f"  Phase {phase}" if phase else "")
    )
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 26), (20, 20, 20), -1)
    cv2.putText(frame, header, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1)
    return frame
