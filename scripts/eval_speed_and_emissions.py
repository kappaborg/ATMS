#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2

from atms_config import get_atms_runtime_config
from atms_core.pipeline import ATMSPipeline
from atms_core.model_factory import (
    create_emission_calculators,
    create_speed_calculator,
    create_tracker,
)


def _read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _coerce_int(x: Any, default: int) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _coerce_float(x: Any, default: float) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _write_summary(path: Path, summary: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)


def _write_config_copy(path: Path, cfg: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, sort_keys=True)


def _csv_fieldnames() -> List[str]:
    return [
        "frame_idx",
        "frame_time_s",
        "track_id",
        "class",
        "confidence",
        "bbox_x1",
        "bbox_y1",
        "bbox_x2",
        "bbox_y2",
        "speed_kmh",
        "speed_confidence",
        "direction_deg",
        "emission_co2_g_km",
        "fuel_l_100km",
        "emission_impact",
    ]


def _row_from_det(frame_idx: int, frame_time_s: float, det: Dict[str, Any]) -> Dict[str, Any]:
    bbox = det.get("bbox") or {}
    return {
        "frame_idx": frame_idx,
        "frame_time_s": round(frame_time_s, 3),
        "track_id": det.get("track_id"),
        "class": det.get("class"),
        "confidence": det.get("confidence"),
        "bbox_x1": bbox.get("x1"),
        "bbox_y1": bbox.get("y1"),
        "bbox_x2": bbox.get("x2"),
        "bbox_y2": bbox.get("y2"),
        "speed_kmh": det.get("speed"),
        "speed_confidence": det.get("speed_confidence"),
        "direction_deg": det.get("direction"),
        "emission_co2_g_km": det.get("emission_co2"),
        "fuel_l_100km": det.get("fuel_consumption"),
        "emission_impact": det.get("emission_impact"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline evaluation: speed + emissions using ATMSPipeline.")
    ap.add_argument("--config", required=True, help="Path to experiments config JSON")
    ap.add_argument("--video", required=True, help="Path to local video file")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    video_path = Path(args.video).resolve()
    if not cfg_path.exists():
        raise SystemExit(f"Config not found: {cfg_path}")
    if not video_path.exists():
        raise SystemExit(f"Video not found: {video_path}")

    runtime_cfg = get_atms_runtime_config()
    cfg = _read_json(cfg_path)

    run_id = str(cfg.get("run_id") or f"run_{int(time.time())}")
    results_root = Path(cfg.get("output", {}).get("results_dir", "experiments/results"))
    run_dir = results_root / run_id
    _ensure_dir(run_dir)

    _write_config_copy(run_dir / "config.json", cfg)

    # Input controls
    frame_stride = _coerce_int(cfg.get("input", {}).get("frame_stride", 1), 1)
    max_frames = _coerce_int(cfg.get("input", {}).get("max_frames", 0), 0)

    # Speed config / ablations
    speed_cfg = cfg.get("speed", {})
    fps_override = _coerce_float(speed_cfg.get("fps_override", 0), 0)
    pixel_to_meter_ratio = _coerce_float(speed_cfg.get("pixel_to_meter_ratio", 0.05), 0.05)
    min_track_length = _coerce_int(speed_cfg.get("min_track_length", 5), 5)
    max_track_history = _coerce_int(speed_cfg.get("max_track_history", 30), 30)
    use_kalman = bool(speed_cfg.get("use_kalman", True))
    use_cvm = bool(speed_cfg.get("use_cvm", True))
    use_wls = bool(speed_cfg.get("use_wls", True))

    speed_calculator = create_speed_calculator(
        pixel_to_meter_ratio=pixel_to_meter_ratio,
        fps=25.0,  # updated once we know the real fps
        min_track_length=min_track_length,
        max_track_history=max_track_history,
        use_kalman=use_kalman,
        use_cvm=use_cvm,
        use_wls=use_wls,
    )

    # Emissions ablation
    use_enhanced_emission_model = bool(cfg.get("pipeline", {}).get("use_enhanced_emission_model", True))
    _, enhanced_emission_calculator = create_emission_calculators()
    enhanced_emission_calculator = enhanced_emission_calculator if use_enhanced_emission_model else None

    # Detector (reuse ai-perception YOLODetector)
    from services.ai_perception_src_compat import create_yolo_detector  # type: ignore

    model_cfg = cfg.get("model", {})
    yolo_model_path = str(model_cfg.get("yolo_model_path", "yolov8n.pt"))
    device = str(model_cfg.get("device", "cpu"))
    max_yolo_detections = _coerce_int(model_cfg.get("max_yolo_detections", 200), 200)
    yolo_timeout_seconds = _coerce_float(model_cfg.get("yolo_timeout_seconds", 1.0), 1.0)

    detector = create_yolo_detector(
        model_path=yolo_model_path,
        device=device,
    )
    if not detector.load_model():
        raise SystemExit("Failed to load YOLO model (check model path / environment).")

    tracker = create_tracker()
    trajectory_history: Dict[int, List[Tuple[float, float]]] = {}

    pipe_cfg = cfg.get("pipeline", {})
    pipeline = ATMSPipeline(
        detector=detector,
        tracker=tracker,
        speed_calculator=speed_calculator,
        enhanced_emission_calculator=enhanced_emission_calculator,
        atms_system=None,
        trajectory_history=trajectory_history,
        trajectory_max_length=60,
        plate_processor=None,
        brand_classifier=None,
        multiview_detector=None,
        max_yolo_detections=max_yolo_detections,
        max_tracked_objects=_coerce_int(pipe_cfg.get("max_tracked_objects", 200), 200),
        speed_confidence_threshold=_coerce_float(pipe_cfg.get("speed_confidence_threshold", 0.5), 0.5),
        yolo_timeout_seconds=yolo_timeout_seconds,
    )

    use_distance_aware_filtering = bool(pipe_cfg.get("use_distance_aware_filtering", True))
    dist_params = {
        "vehicle_base_conf": runtime_cfg.detection.vehicle_base_conf,
        "pedestrian_base_conf": runtime_cfg.detection.pedestrian_base_conf,
        "other_base_conf": runtime_cfg.detection.other_base_conf,
        "large_relative_size_threshold": runtime_cfg.detection.large_relative_size_threshold,
        "medium_relative_size_threshold": runtime_cfg.detection.medium_relative_size_threshold,
        "large_size_multiplier": runtime_cfg.detection.large_size_multiplier,
        "medium_size_multiplier": runtime_cfg.detection.medium_size_multiplier,
        "far_size_multiplier": runtime_cfg.detection.far_size_multiplier,
    }

    write_csv = bool(cfg.get("output", {}).get("write_csv", True))
    write_summary_json = bool(cfg.get("output", {}).get("write_summary_json", True))

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit("Failed to open video.")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    if fps_override and fps_override > 0:
        fps = fps_override
    speed_calculator.fps = float(fps)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    t0 = time.time()

    csv_path = run_dir / "detections.csv"
    csv_f = None
    writer = None
    if write_csv:
        csv_f = open(csv_path, "w", newline="", encoding="utf-8")
        writer = csv.DictWriter(csv_f, fieldnames=_csv_fieldnames())
        writer.writeheader()

    processed = 0
    rows_written = 0
    total_dets = 0
    dets_with_speed = 0
    dets_with_emission = 0

    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_stride > 1 and (frame_idx % frame_stride != 0):
            frame_idx += 1
            continue

        dets = pipeline.process_frame(
            frame,
            frame_idx,
            process_plates=bool(pipe_cfg.get("process_plates", False)),
            process_brand=bool(pipe_cfg.get("process_brand", False)),
            process_multiview=bool(pipe_cfg.get("process_multiview", False)),
            run_atms_prediction=bool(pipe_cfg.get("run_atms_prediction", False)),
            return_all_tracked_objects=bool(pipe_cfg.get("return_all_tracked_objects", True)),
            low_confidence_speed_to_none=bool(pipe_cfg.get("low_confidence_speed_to_none", True)),
            compute_emissions_for_all_tracked_objects=bool(
                pipe_cfg.get("compute_emissions_for_all_tracked_objects", True)
            ),
            apply_distance_aware_filtering=use_distance_aware_filtering,
            distance_aware_filter_params=dist_params if use_distance_aware_filtering else None,
            video_fps=float(fps),
            actual_fps=float(fps),
        )

        frame_time_s = frame_idx / float(fps) if fps > 0 else 0.0

        processed += 1
        total_dets += len(dets)
        for d in dets:
            if d.get("speed") is not None:
                dets_with_speed += 1
            if d.get("emission_co2") is not None and (d.get("emission_co2") or 0) > 0:
                dets_with_emission += 1

            if writer:
                writer.writerow(_row_from_det(frame_idx, frame_time_s, d))
                rows_written += 1

        if max_frames and processed >= max_frames:
            break

        frame_idx += 1

    cap.release()
    if csv_f:
        csv_f.close()

    elapsed_s = time.time() - t0
    summary = {
        "run_id": run_id,
        "video": str(video_path),
        "total_frames_in_video": total_frames,
        "processed_frames": processed,
        "frame_stride": frame_stride,
        "fps_used": fps,
        "elapsed_s": round(elapsed_s, 3),
        "rows_written": rows_written,
        "total_detections": total_dets,
        "detections_with_speed": dets_with_speed,
        "detections_with_emission": dets_with_emission,
        "ablation": {
            "use_kalman": use_kalman,
            "use_cvm": use_cvm,
            "use_wls": use_wls,
            "use_distance_aware_filtering": use_distance_aware_filtering,
            "use_enhanced_emission_model": use_enhanced_emission_model,
        },
        "atms_runtime_config": {
            "run_mode": runtime_cfg.run_mode.value,
            "enable_kafka": runtime_cfg.enable_kafka,
            "experiment_output_dir": runtime_cfg.experiment_output_dir,
            "detection_thresholds": asdict(runtime_cfg.detection),
        },
    }

    if write_summary_json:
        _write_summary(run_dir / "summary.json", summary)

    print(f"✅ Done. Results in: {run_dir}")
    if write_csv:
        print(f"   - detections.csv: {csv_path}")
    if write_summary_json:
        print(f"   - summary.json: {run_dir / 'summary.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

