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
    emergency: bool = False  # flashing blue/red light bar detected

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
        self._model_path = model_path or _resolve_model_path()
        # SAHI (Slicing Aided Hyper Inference): tile the frame so small, distant
        # objects (aerial/drone views) become detectable. Much slower (N tiles
        # per frame) — opt-in via PANEL_USE_SAHI, tune tile size with
        # PANEL_SAHI_SLICE (px).
        self.use_sahi = os.getenv("PANEL_USE_SAHI", "").lower() in ("1", "true", "yes")
        # Smaller tiles detect smaller objects but are slower (more tiles);
        # 384 balances aerial detection vs speed. Use 256 for very dense/high
        # aerial views, 512 for lighter load.
        self.slice = int(os.getenv("PANEL_SAHI_SLICE", "384"))
        self._sahi = None
        self._load(self._model_path)

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

    def _sahi_model(self):
        if self._sahi is None:
            from sahi import AutoDetectionModel

            self._sahi = AutoDetectionModel.from_pretrained(
                model_type="ultralytics", model_path=self._model_path,
                confidence_threshold=self.confidence, device="cpu",
            )
        return self._sahi

    def _infer_sahi(self, frame):
        from sahi.predict import get_sliced_prediction

        res = get_sliced_prediction(
            frame, self._sahi_model(),
            slice_height=self.slice, slice_width=self.slice,
            overlap_height_ratio=0.2, overlap_width_ratio=0.2,
            verbose=0, postprocess_type="NMS",
        )
        out = []
        for o in res.object_prediction_list:
            cid = int(o.category.id)
            if cid in _CLASSES:
                x1, y1, x2, y2 = o.bbox.to_xyxy()
                out.append((cid, float(o.score.value), (float(x1), float(y1), float(x2), float(y2))))
        return out

    @staticmethod
    def _dedup(raw: list) -> list:
        """Drop duplicate boxes on the SAME physical object.

        YOLO's NMS is class-aware, so one vehicle is often returned as BOTH
        car and truck (measured: IoU 0.95 pairs on real footage), and loose
        same-class overlaps (IoU 0.5-0.7) also survive — each duplicate becomes
        a ghost track that inflates counts. Greedy keep-highest-confidence,
        class-AGNOSTIC within vehicle classes and within persons. Person-vs-
        vehicle overlaps are kept (a rider on a motorcycle is legitimate)."""
        def iou(a, b):
            ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
            ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
            inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
            ua = ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)
            return inter / ua if ua > 0 else 0.0

        kept: list = []
        for det in sorted(raw, key=lambda r: -r[1]):
            cls, _conf, box = det
            group = "veh" if cls in _VEHICLE_IDS else "ped"
            dup = any(
                ("veh" if k[0] in _VEHICLE_IDS else "ped") == group and iou(box, k[2]) > 0.55
                for k in kept
            )
            if not dup:
                kept.append(det)
        return kept

    def infer(
        self, frame: np.ndarray, use_sahi: bool | None = None
    ) -> list[tuple[int, float, tuple[float, float, float, float]]]:
        """Return raw detections as (cls_id, confidence, (x1,y1,x2,y2)).

        `use_sahi` overrides the global default per call — each camera chooses
        sliced (aerial/small-object, slower) vs whole-frame (fast) inference."""
        if self.model is None:
            return []  # mock mode: no synthetic data, just empty
        sahi = self.use_sahi if use_sahi is None else use_sahi
        if sahi:
            try:
                return self._dedup(self._infer_sahi(frame))
            except Exception as e:  # noqa: BLE001 — fall back to whole-frame on any SAHI error
                import logging
                logging.getLogger("panel.detect").warning("SAHI failed, using whole-frame: %s", e)
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
        return self._dedup(out)


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
        flagged = (d.emergency or d.drift or d.wrong_way or d.red_light
                   or d.reckless or d.stopped or d.speeding)
        if d.emergency:
            colour, tag = (255, 120, 0), f"EMERGENCY #{d.track_id}"       # bright blue
        elif d.drift:
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
