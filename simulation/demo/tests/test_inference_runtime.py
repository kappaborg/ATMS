"""Unit tests for simulation/demo/inference_runtime.py.

The actual ONNX/PyTorch model loading + inference requires the model files
and an `onnxruntime` install — exercised by the end-to-end demo run.
Here we test the pure-function helpers + the runtime selector's choice
logic.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from simulation.demo.inference_runtime import (
    _letterbox,
    _nms,
    _xywh_to_xyxy,
    make_detector,
)

# ---------------------------------------------------------------------------
# _letterbox — resize + pad preserving aspect ratio
# ---------------------------------------------------------------------------


class TestLetterbox:
    def test_square_input_no_padding(self):
        img = np.zeros((640, 640, 3), dtype=np.uint8)
        padded, scale, pl, pt = _letterbox(img)
        assert padded.shape == (640, 640, 3)
        assert scale == 1.0
        assert pl == 0 and pt == 0

    def test_wide_input_gets_horizontal_padding(self):
        img = np.zeros((720, 1280, 3), dtype=np.uint8)  # 16:9
        padded, scale, pl, pt = _letterbox(img)
        assert padded.shape == (640, 640, 3)
        assert scale == pytest.approx(0.5)
        # No horizontal padding (image fills width); vertical padding present.
        assert pl == 0
        assert pt > 0

    def test_tall_input_gets_vertical_padding(self):
        img = np.zeros((1280, 720, 3), dtype=np.uint8)  # portrait
        padded, _scale, pl, pt = _letterbox(img)
        assert padded.shape == (640, 640, 3)
        assert pt == 0
        assert pl > 0

    def test_custom_input_size(self):
        img = np.zeros((300, 300, 3), dtype=np.uint8)
        padded, _scale, _, _ = _letterbox(img, new_size=320)
        assert padded.shape == (320, 320, 3)


# ---------------------------------------------------------------------------
# _xywh_to_xyxy
# ---------------------------------------------------------------------------


class TestXywhToXyxy:
    def test_single_box(self):
        boxes = np.array([[10.0, 10.0, 20.0, 30.0]])  # center=(10,10) size=(20,30)
        out = _xywh_to_xyxy(boxes)
        assert out.tolist() == [[0.0, -5.0, 20.0, 25.0]]

    def test_multiple_boxes(self):
        boxes = np.array(
            [
                [5.0, 5.0, 10.0, 10.0],  # center=5,5 -> 0,0,10,10
                [50.0, 50.0, 20.0, 20.0],  # center=50,50 -> 40,40,60,60
            ]
        )
        out = _xywh_to_xyxy(boxes)
        assert out.tolist() == [[0.0, 0.0, 10.0, 10.0], [40.0, 40.0, 60.0, 60.0]]


# ---------------------------------------------------------------------------
# _nms — greedy IoU
# ---------------------------------------------------------------------------


class TestNms:
    def test_empty_returns_empty(self):
        kept = _nms(np.zeros((0, 4)), np.zeros((0,)))
        assert kept.tolist() == []

    def test_single_box_kept(self):
        boxes = np.array([[0.0, 0.0, 10.0, 10.0]])
        scores = np.array([0.9])
        kept = _nms(boxes, scores)
        assert kept.tolist() == [0]

    def test_disjoint_boxes_all_kept(self):
        boxes = np.array(
            [
                [0.0, 0.0, 10.0, 10.0],
                [100.0, 100.0, 110.0, 110.0],
            ]
        )
        scores = np.array([0.9, 0.8])
        kept = sorted(_nms(boxes, scores).tolist())
        assert kept == [0, 1]

    def test_overlapping_keeps_higher_score(self):
        boxes = np.array(
            [
                [0.0, 0.0, 10.0, 10.0],
                [1.0, 1.0, 11.0, 11.0],  # high IoU with #0
            ]
        )
        scores = np.array([0.9, 0.8])
        kept = _nms(boxes, scores, iou_threshold=0.3)
        assert kept.tolist() == [0]  # only the higher-scoring box survives

    def test_high_iou_threshold_keeps_all(self):
        # iou_threshold=0.99 means even nearly-identical boxes survive
        boxes = np.array(
            [
                [0.0, 0.0, 10.0, 10.0],
                [1.0, 1.0, 11.0, 11.0],
            ]
        )
        scores = np.array([0.9, 0.8])
        kept = sorted(_nms(boxes, scores, iou_threshold=0.99).tolist())
        assert kept == [0, 1]


# ---------------------------------------------------------------------------
# make_detector — factory selection logic
# ---------------------------------------------------------------------------


class TestMakeDetector:
    def test_pytorch_runtime_always_uses_pytorch(self, tmp_path: Path):
        # Verify the function ROUTES to the PyTorch path. The fake .pt
        # will cause ultralytics to raise — we just care it tried.
        fake_pt = tmp_path / "fake.pt"
        fake_pt.write_bytes(b"not a real model")
        with pytest.raises(BaseException):  # noqa: B017 — ultralytics raises various
            make_detector(fake_pt, runtime="pytorch")

    def test_onnx_runtime_requires_onnx_file(self, tmp_path: Path):
        fake_pt = tmp_path / "fake.pt"
        fake_pt.write_bytes(b"")
        # no fake.onnx alongside
        with pytest.raises(FileNotFoundError, match="ONNX runtime requested"):
            make_detector(fake_pt, runtime="onnx")

    def test_auto_falls_back_to_pytorch_when_no_onnx(self, tmp_path: Path):
        fake_pt = tmp_path / "fake.pt"
        fake_pt.write_bytes(b"")
        # No fake.onnx. Auto should attempt PyTorch (which fails because
        # the .pt is empty, but the failure happens in the PyTorch path).
        with pytest.raises(BaseException):  # noqa: B017
            make_detector(fake_pt, runtime="auto")
