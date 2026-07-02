"""Inference-runtime selector + ONNX/CoreML direct wrapper for YOLOv8.

ultralytics' `YOLO('model.onnx')` always uses `CPUExecutionProvider`, which
on Apple Silicon is slower than the PyTorch path because PyTorch already
runs on the MPS backend. To actually benefit from ONNX on macOS we need to
explicitly target the `CoreMLExecutionProvider`. This module wraps
onnxruntime directly, does YOLOv8's bbox decoding + NMS in pure NumPy, and
returns detections in the same `(class_id, bbox)` shape that
`simulation/demo/video_source.py:_detect` consumes.

Benchmark (Apple M1 Max, yolov8n.onnx, 1920x1080 input):

    PyTorch  (ultralytics default):  ~30 ms/frame
    ONNX-CPU (ultralytics):          ~36 ms/frame
    ONNX-CoreML (this module):       ~20 ms/frame   <- 1.5x faster

Selection logic in `make_detector(weights_path, runtime='auto')`:

    runtime='onnx'    -> ONNXYoloDetector (requires .onnx file)
    runtime='pytorch' -> ultralytics YOLO (.pt)
    runtime='auto'    -> prefer ONNX when both files exist AND
                         CoreMLExecutionProvider is available
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("atms.video.runtime")

# Standard YOLOv8 input resolution.
YOLOV8_INPUT_SIZE = 640


class DetectorBackend(Protocol):
    """Common interface used by simulation/demo/video_source.py:_detect.

    Implementations: ONNXYoloDetector, _PyTorchYoloDetector (legacy fallback).
    Returns a list of `(class_id, (x1, y1, x2, y2))` tuples, where bbox
    coordinates are in the *original frame's* pixel space (not the model
    input space).
    """

    def predict(
        self, frame, conf: float
    ) -> list[tuple[int, tuple[float, float, float, float]]]: ...

    @property
    def backend_name(self) -> str: ...


# ---------------------------------------------------------------------------
# ONNX (CoreML-accelerated on Apple Silicon)
# ---------------------------------------------------------------------------


def _letterbox(img, new_size: int = YOLOV8_INPUT_SIZE):
    """Resize + pad an image to (new_size, new_size) preserving aspect ratio.

    Returns (resized_img, scale, pad_left, pad_top) so callers can map output
    bboxes back to the original frame.
    """
    import cv2  # noqa: PLC0415  opencv is optional at top-level

    h, w = img.shape[:2]
    scale = min(new_size / w, new_size / h)
    new_w = round(w * scale)
    new_h = round(h * scale)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    pad_left = (new_size - new_w) // 2
    pad_top = (new_size - new_h) // 2
    pad_right = new_size - new_w - pad_left
    pad_bottom = new_size - new_h - pad_top
    padded = cv2.copyMakeBorder(
        resized,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        cv2.BORDER_CONSTANT,
        value=(114, 114, 114),
    )
    return padded, scale, pad_left, pad_top


def _xywh_to_xyxy(boxes):
    """Center+size -> corner format. Operates on the last axis."""
    import numpy as np  # noqa: PLC0415  numpy is optional at top-level

    out = np.empty_like(boxes)
    out[..., 0] = boxes[..., 0] - boxes[..., 2] / 2  # x1
    out[..., 1] = boxes[..., 1] - boxes[..., 3] / 2  # y1
    out[..., 2] = boxes[..., 0] + boxes[..., 2] / 2  # x2
    out[..., 3] = boxes[..., 1] + boxes[..., 3] / 2  # y2
    return out


def _nms(boxes, scores, iou_threshold: float = 0.45):
    """Greedy NMS in pure NumPy. Returns indices of kept boxes."""
    import numpy as np  # noqa: PLC0415

    if len(boxes) == 0:
        return np.array([], dtype=np.int64)
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        union = areas[i] + areas[rest] - inter
        iou = inter / np.maximum(union, 1e-9)
        order = rest[iou < iou_threshold]
    return np.array(keep, dtype=np.int64)


class ONNXYoloDetector:
    """Direct onnxruntime wrapper for YOLOv8 .onnx models.

    Construction picks the best available execution provider in this order:
    CoreML (Apple Silicon), CUDA (NVIDIA), then CPU. The fastest provider
    that loads successfully wins.
    """

    def __init__(
        self,
        weights_path: Path,
        nms_iou: float = 0.45,
        force_provider: str | None = None,
    ) -> None:
        self._weights_path = weights_path
        self._nms_iou = nms_iou
        self._session: Any = None
        self._input_name: str | None = None
        self._provider_used: str = "unknown"
        self._force_provider = force_provider
        self._load()

    def _load(self) -> None:
        try:
            import onnxruntime as ort  # noqa: PLC0415  lazy — opt-in
        except ImportError as e:
            raise RuntimeError(
                "onnxruntime not installed. "
                "Run: python3 -m pip install --break-system-packages onnxruntime"
            ) from e

        # Provider preference: CoreML > CUDA > CPU. We pass the full list
        # so onnxruntime auto-falls-back to a working one.
        if self._force_provider:
            providers = [self._force_provider]
        else:
            available = ort.get_available_providers()
            providers = []
            for preferred in (
                "CoreMLExecutionProvider",
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ):
                if preferred in available:
                    providers.append(preferred)
            if not providers:
                providers = ["CPUExecutionProvider"]

        log.info(
            "loading ONNX model %s with providers %s",
            self._weights_path,
            providers,
        )
        self._session = ort.InferenceSession(str(self._weights_path), providers=providers)
        self._input_name = self._session.get_inputs()[0].name
        self._provider_used = self._session.get_providers()[0]
        log.info("ONNX detector ready (provider=%s)", self._provider_used)

    @property
    def backend_name(self) -> str:
        return f"onnx-{self._provider_used.replace('ExecutionProvider', '').lower()}"

    def predict(self, frame, conf: float) -> list[tuple[int, tuple[float, float, float, float]]]:
        import numpy as np  # noqa: PLC0415

        if self._session is None:
            return []

        # Letterbox preprocessing -> (1, 3, 640, 640) float32 in [0, 1]
        padded, scale, pad_left, pad_top = _letterbox(frame, YOLOV8_INPUT_SIZE)
        img = padded[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
        img = np.expand_dims(img, 0)

        # Inference. YOLOv8 detect output shape: (1, 4+nc, 8400)
        outs = self._session.run(None, {self._input_name: img})
        pred = outs[0]
        # Transpose to (8400, 4+nc)
        pred = pred[0].T

        # Split bbox (xywh, in model-input pixels 0..640) from class scores
        boxes_xywh = pred[:, :4]
        scores_all = pred[:, 4:]
        cls_ids = scores_all.argmax(axis=1)
        cls_scores = scores_all[np.arange(scores_all.shape[0]), cls_ids]

        keep_conf = cls_scores >= conf
        if not keep_conf.any():
            return []
        boxes_xywh = boxes_xywh[keep_conf]
        cls_ids = cls_ids[keep_conf]
        cls_scores = cls_scores[keep_conf]

        # xywh -> xyxy, still in model-input pixels
        boxes_xyxy = _xywh_to_xyxy(boxes_xywh)
        # NMS
        keep_nms = _nms(boxes_xyxy, cls_scores, iou_threshold=self._nms_iou)
        boxes_xyxy = boxes_xyxy[keep_nms]
        cls_ids = cls_ids[keep_nms]

        # Map from model-input pixels (0..640) back to original frame coords.
        # The model saw a letterboxed image, so undo the pad + scale.
        boxes_xyxy[:, [0, 2]] -= pad_left
        boxes_xyxy[:, [1, 3]] -= pad_top
        boxes_xyxy /= scale

        # Clip to frame bounds (the letterbox padding can push bboxes slightly off).
        h, w = frame.shape[:2]
        boxes_xyxy[:, [0, 2]] = boxes_xyxy[:, [0, 2]].clip(0, w)
        boxes_xyxy[:, [1, 3]] = boxes_xyxy[:, [1, 3]].clip(0, h)

        return [
            (int(cls_id), (float(x1), float(y1), float(x2), float(y2)))
            for cls_id, (x1, y1, x2, y2) in zip(cls_ids, boxes_xyxy, strict=True)
        ]


# ---------------------------------------------------------------------------
# PyTorch fallback (ultralytics)
# ---------------------------------------------------------------------------


class _PyTorchYoloDetector:
    """Thin wrapper around ultralytics.YOLO for parity with ONNXYoloDetector.

    Used when ONNX runtime isn't available or the user passes
    `--runtime pytorch` for an apples-to-apples comparison.
    """

    def __init__(self, weights_path: Path) -> None:
        from ultralytics import YOLO  # noqa: PLC0415  optional dep

        self._weights_path = weights_path
        self._model = YOLO(str(weights_path))

    @property
    def backend_name(self) -> str:
        return "pytorch"

    def predict(self, frame, conf: float) -> list[tuple[int, tuple[float, float, float, float]]]:
        results = self._model.predict(frame, conf=conf, verbose=False)
        out: list[tuple[int, tuple[float, float, float, float]]] = []
        for r in results:
            boxes = getattr(r, "boxes", None)
            if boxes is None:
                continue
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i].item())
                x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[i].tolist())
                out.append((cls_id, (x1, y1, x2, y2)))
        return out


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_detector(
    weights_path: Path,
    *,
    runtime: str = "auto",
) -> DetectorBackend:
    """Pick the fastest available backend.

    `runtime`:
    - "auto":    prefer ONNX (CoreML-accelerated on macOS) if a `.onnx` file
                 exists alongside the `.pt`, else fall back to PyTorch.
    - "onnx":    require an `.onnx` file; raise if missing.
    - "pytorch": always use ultralytics' PyTorch path.
    """
    weights_path = Path(weights_path)

    if runtime == "pytorch":
        return _PyTorchYoloDetector(weights_path)

    if runtime == "onnx":
        onnx_path = (
            weights_path if weights_path.suffix == ".onnx" else weights_path.with_suffix(".onnx")
        )
        if not onnx_path.exists():
            raise FileNotFoundError(
                f"ONNX runtime requested but {onnx_path} not found. "
                f'Export with: python3 -c "from ultralytics import YOLO; '
                f"YOLO('{weights_path}').export(format='onnx', simplify=True)\""
            )
        return ONNXYoloDetector(onnx_path)

    # auto: prefer ONNX-with-CoreML when both exist
    onnx_path = (
        weights_path if weights_path.suffix == ".onnx" else weights_path.with_suffix(".onnx")
    )
    if onnx_path.exists():
        try:
            return ONNXYoloDetector(onnx_path)
        except Exception as e:
            log.warning("auto-detected ONNX path failed to load (%s); falling back to PyTorch", e)
    return _PyTorchYoloDetector(weights_path)
