from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def default_get_class_id(object_class: Any) -> int:
    """
    Map detected class names to the numeric IDs expected by downstream logic.
    This is copied from `realtime_video_processor.py` to keep behavior consistent.
    """
    class_map = {
        "car": 2,
        "truck": 7,
        "bus": 5,
        "motorcycle": 3,
        "bicycle": 1,
        "pedestrian": 0,
        "person": 0,
    }
    class_str = str(object_class).lower()
    for key, val in class_map.items():
        if key in class_str:
            return val
    return 0


@dataclass(frozen=True)
class PipelineResult:
    detections: List[Dict]


class ATMSPipeline:
    """
    Shared frame-processing pipeline used by scripts and services.

    MVP scope (for now):
    - detection (YOLOv8)
    - tracking (ByteTrack wrapper)
    - speed estimation (SpeedCalculator)
    - emissions (EnhancedEmissionCalculator)
    - optional plate/brand/multiview enrichment
    - optional ATMS trajectory/anomaly prediction
    """

    def __init__(
        self,
        *,
        detector: Any,
        tracker: Any,
        speed_calculator: Any,
        enhanced_emission_calculator: Any,
        atms_system: Any,
        trajectory_history: Dict[int, List[Tuple[float, float]]],
        trajectory_max_length: int,
        plate_processor: Optional[Any] = None,
        brand_classifier: Optional[Any] = None,
        multiview_detector: Optional[Any] = None,
        get_class_id: Callable[[Any], int] = default_get_class_id,
        # Performance/quality knobs (moved here so experiments can toggle them)
        max_yolo_detections: int = 50,
        max_tracked_objects: int = 30,
        speed_confidence_threshold: float = 0.3,
        plate_roi_padding: int = 20,
        plate_process_confidence_threshold: float = 0.5,
        plate_process_max_per_frame: int = 2,
        ocr_timeout_seconds: float = 3.0,
        yolo_timeout_seconds: float = 1.0,
        atms_timeout_seconds: float = 1.0,
        # Async model inference expects an event loop; we reuse the logic used in the script.
        yolo_sensor_id: str = "video",
    ):
        self.detector = detector
        self.tracker = tracker
        self.speed_calculator = speed_calculator
        self.enhanced_emission_calculator = enhanced_emission_calculator
        self.atms_system = atms_system

        self.trajectory_history = trajectory_history
        self.trajectory_max_length = trajectory_max_length

        self.plate_processor = plate_processor
        self.brand_classifier = brand_classifier
        self.multiview_detector = multiview_detector

        self.get_class_id = get_class_id

        self.max_yolo_detections = max_yolo_detections
        self.max_tracked_objects = max_tracked_objects
        self.speed_confidence_threshold = speed_confidence_threshold
        self.plate_roi_padding = plate_roi_padding
        self.plate_process_confidence_threshold = plate_process_confidence_threshold

        self.plate_process_max_per_frame = plate_process_max_per_frame
        self.ocr_timeout_seconds = ocr_timeout_seconds

        self.yolo_timeout_seconds = yolo_timeout_seconds
        self.atms_timeout_seconds = atms_timeout_seconds
        self.yolo_sensor_id = yolo_sensor_id

    def _get_or_create_event_loop(self) -> asyncio.AbstractEventLoop:
        try:
            return asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop

    async def _call_detector(self, frame: np.ndarray, frame_idx: int) -> List[Any]:
        yolo_detections, _ = await self.detector.detect(
            frame, frame_id=f"frame_{frame_idx}", sensor_id=self.yolo_sensor_id
        )
        return yolo_detections

    def process_frame(
        self,
        frame: np.ndarray,
        frame_idx: int,
        *,
        process_plates: bool = True,
        process_brand: bool = True,
        process_multiview: bool = True,
        max_plates_per_frame: Optional[int] = None,
        ocr_timeout: Optional[float] = None,
        video_fps: float = 25.0,
        actual_fps: float = 25.0,
        # Optional: coordinates scaling for detection-on-resized-frame pipelines.
        # When provided, YOLO bboxes are scaled by (sx, sy) before tracking/speed/emissions.
        tracking_frame: Optional[np.ndarray] = None,
        bbox_scale: Optional[Tuple[float, float]] = None,
        # Optional: distance-aware confidence filtering (useful for resized frames / distant objects).
        apply_distance_aware_filtering: bool = False,
        distance_aware_filter_params: Optional[Dict[str, Any]] = None,
        # Emission computation strategy.
        # Default (False) matches `realtime_video_processor.py` where emissions were only computed for top objects.
        compute_emissions_for_all_tracked_objects: bool = False,
        # Optional: run ATMS trajectory/anomaly prediction.
        run_atms_prediction: bool = True,
        # Optional: return all tracked objects (used for decision metrics)
        # instead of only the top-N objects.
        return_all_tracked_objects: bool = False,
        # Optional: when speed confidence is low, set speed to None.
        # This matches the YouTube script (which computes emissions only on real speeds).
        low_confidence_speed_to_none: bool = False,
    ) -> List[Dict]:
        """
        Process a single frame and return a list of enriched detection dicts.
        """
        detections: List[Dict] = []

        loop = self._get_or_create_event_loop()
        roi_frame = tracking_frame if tracking_frame is not None else frame

        # Allow per-call overrides from the caller.
        if max_plates_per_frame is None:
            max_plates_per_frame = self.plate_process_max_per_frame
        if ocr_timeout is None:
            ocr_timeout = self.ocr_timeout_seconds

        try:
            # 1) YOLO detection (async)
            try:
                yolo_detections = loop.run_until_complete(
                    asyncio.wait_for(
                        self._call_detector(frame, frame_idx),
                        timeout=self.yolo_timeout_seconds,
                    )
                )
            except asyncio.TimeoutError:
                if frame_idx % 30 == 0:
                    logger.warning(f"YOLO detection timeout on frame {frame_idx}, skipping")
                yolo_detections = []

            # Convert Detection objects to dicts (minimize early overhead)
            yolo_results: List[Dict] = []
            if yolo_detections:
                yolo_detections_sorted = sorted(
                    yolo_detections,
                    key=lambda x: x.confidence,
                    reverse=True,
                )[: self.max_yolo_detections]

                for det in yolo_detections_sorted:
                    det_dict = {
                        "bbox": {
                            "x1": det.bbox.x1,
                            "y1": det.bbox.y1,
                            "x2": det.bbox.x2,
                            "y2": det.bbox.y2,
                        },
                        "confidence": det.confidence,
                        "class": (
                            det.object_class.value
                            if hasattr(det.object_class, "value")
                            else str(det.object_class)
                        ),
                        "class_id": self.get_class_id(det.object_class),
                        "frame_id": det.frame_id,
                        "detection_id": det.detection_id,
                    }
                    yolo_results.append(det_dict)

            if not yolo_results:
                if frame_idx % 30 == 0:
                    logger.warning(
                        f"Frame {frame_idx}: No detections from YOLO - check model and confidence threshold"
                    )
                return detections

            # Optional: apply distance-aware confidence filtering (mirrors youtube processor).
            if apply_distance_aware_filtering:
                yolo_results = self._apply_distance_aware_filtering(
                    yolo_results=yolo_results,
                    frame_shape=(frame.shape[0], frame.shape[1]),
                    params=distance_aware_filter_params,
                )

            # Optional: scale bboxes to the tracking frame coordinate system.
            if bbox_scale is not None:
                sx, sy = bbox_scale
                for det in yolo_results:
                    bbox = det.get("bbox") or {}
                    bbox["x1"] = bbox.get("x1", 0) * sx
                    bbox["x2"] = bbox.get("x2", 0) * sx
                    bbox["y1"] = bbox.get("y1", 0) * sy
                    bbox["y2"] = bbox.get("y2", 0) * sy

            # 2) Tracking
            tracked_results = self.tracker.update(yolo_results)

            # Release per-track state for tracks the tracker expired this
            # frame — otherwise speed filters and trajectory dicts grow
            # unboundedly on long/live runs.
            for removed_id in getattr(self.tracker, "last_removed_ids", []):
                self.trajectory_history.pop(removed_id, None)
                if self.speed_calculator and hasattr(self.speed_calculator, "remove_track"):
                    self.speed_calculator.remove_track(removed_id)

            tracked_objects: List[Dict] = []
            for tracked_det in tracked_results:
                track_id = tracked_det.get("track_id", frame_idx)
                tracked_det["track_id"] = track_id

                bbox = tracked_det.get("bbox", {})
                if isinstance(bbox, dict):
                    # Keep floats for better speed precision; convert to int only for slicing/drawing.
                    x1, y1 = float(bbox.get("x1", 0)), float(bbox.get("y1", 0))
                    x2, y2 = float(bbox.get("x2", 0)), float(bbox.get("y2", 0))
                else:
                    x1, y1, x2, y2 = (
                        bbox[:4] if len(bbox) >= 4 else (0, 0, 0, 0)
                    )

                # Update trajectory history (used for drawing in the script)
                center_x = (x1 + x2) / 2
                center_y = (y1 + y2) / 2
                if track_id not in self.trajectory_history:
                    self.trajectory_history[track_id] = []
                self.trajectory_history[track_id].append((center_x, center_y))
                if len(self.trajectory_history[track_id]) > self.trajectory_max_length:
                    self.trajectory_history[track_id].pop(0)

                # Speed estimation
                if self.speed_calculator:
                    if video_fps and video_fps > 0:
                        self.speed_calculator.fps = video_fps
                    elif actual_fps and actual_fps > 10:
                        self.speed_calculator.fps = actual_fps

                    self.speed_calculator.update_track(track_id, (center_x, center_y), frame_idx)
                    speed_result = self.speed_calculator.calculate_speed(track_id)

                    if speed_result:
                        if speed_result.confidence > self.speed_confidence_threshold:
                            tracked_det["speed"] = max(0, speed_result.speed_kmh)
                            tracked_det["velocity"] = {
                                "x": float(speed_result.velocity_x),
                                "y": float(speed_result.velocity_y),
                            }
                            tracked_det["direction"] = float(speed_result.direction_deg)
                            tracked_det["speed_method"] = speed_result.method
                            tracked_det["speed_confidence"] = float(speed_result.confidence)
                        else:
                            # Low-confidence speed is stored for logging/visualization,
                            # but later stages can treat it as uncertain.
                            tracked_det["speed"] = (
                                None
                                if low_confidence_speed_to_none
                                else max(0, speed_result.speed_kmh)
                            )
                            tracked_det["speed_confidence"] = float(speed_result.confidence)

                tracked_objects.append(tracked_det)

            # Optional: compute emissions for all tracked objects (used by youtube processor).
            if (
                compute_emissions_for_all_tracked_objects
                and self.enhanced_emission_calculator is not None
            ):
                for det in tracked_objects:
                    try:
                        if det.get("speed"):
                            emissions = (
                                self.enhanced_emission_calculator.calculate_emissions_from_speed(
                                    vehicle_type=det.get("class", "car"),
                                    speed_kmh=det["speed"],
                                    distance_km=0.001,
                                )
                            )
                            det["emission_co2"] = emissions.get("co2_g_km", 0)
                            det["fuel_consumption"] = emissions.get("fuel_l_100km", 0)
                            det["emission_impact"] = emissions.get("impact_level", None)
                    except Exception:
                        # Keep pipeline robust for offline experimentation.
                        pass

            # 3) Enrichment/outputs
            if return_all_tracked_objects:
                tracked_objects_sorted = tracked_objects
            else:
                tracked_objects_sorted = sorted(
                    tracked_objects,
                    key=lambda x: x.get("confidence", 0),
                    reverse=True,
                )[: self.max_tracked_objects]

            plates_processed_this_frame = 0
            for det in tracked_objects_sorted:
                bbox = det.get("bbox", {})
                x1, y1 = int(bbox.get("x1", 0)), int(bbox.get("y1", 0))
                x2, y2 = int(bbox.get("x2", 0)), int(bbox.get("y2", 0))

                # Ensure bbox is within frame
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
                if x2 <= x1 or y2 <= y1:
                    continue

                # ROI is only required for plate OCR and/or multiview detection.
                needs_roi = (self.plate_processor and process_plates) or (
                    self.multiview_detector and process_multiview
                )
                roi = None
                if needs_roi:
                    padding = self.plate_roi_padding
                    roi_x1 = max(0, x1 - padding)
                    roi_y1 = max(0, y1 - padding)
                    roi_x2 = min(roi_frame.shape[1], x2 + padding)
                    roi_y2 = min(roi_frame.shape[0], y2 + padding)

                    roi = (
                        roi_frame[roi_y1:roi_y2, roi_x1:roi_x2]
                        if roi_y2 > roi_y1 and roi_x2 > roi_x1
                        else None
                    )
                    if roi is None or roi.size == 0:
                        continue

                track_id = det.get("track_id", frame_idx)

                # License plate detection & OCR
                if (
                    self.plate_processor
                    and process_plates
                    and plates_processed_this_frame < max_plates_per_frame
                ):
                    if det.get("confidence", 0) > self.plate_process_confidence_threshold:
                        plates_processed_this_frame += 1
                        try:
                            plate_results = loop.run_until_complete(
                                asyncio.wait_for(
                                    self.plate_processor.process_frame(
                                        roi,
                                        frame_id=f"frame_{frame_idx}_track_{track_id}",
                                        context={"vehicle_bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2}},
                                    ),
                                    timeout=ocr_timeout,
                                )
                            )
                        except asyncio.TimeoutError:
                            if frame_idx % 60 == 0:
                                logger.warning(f"OCR timeout for track {track_id} (>{ocr_timeout}s)")
                            plate_results = None

                        except Exception as e:
                            if frame_idx % 60 == 0:
                                logger.warning(f"Plate processing error for track {track_id}: {e}")
                            plate_results = None

                        if plate_results:
                            best_plate = max(
                                plate_results,
                                key=lambda p: (
                                    p.plate_text.ocr_confidence
                                    if p.plate_text and hasattr(p.plate_text, "ocr_confidence")
                                    else 0
                                ),
                            )

                            if best_plate and getattr(best_plate, "plate_text", None):
                                plate_text_obj = best_plate.plate_text
                                plate_text = (
                                    plate_text_obj.text
                                    if plate_text_obj.text
                                    else plate_text_obj.cleaned_text
                                )
                                plate_text = plate_text.strip() if plate_text else ""
                                if (
                                    plate_text
                                    and plate_text.lower() != "null"
                                    and len(plate_text) >= 2
                                ):
                                    det["license_plate"] = plate_text
                                    det["license_plate_confidence"] = float(
                                        plate_text_obj.confidence
                                    ) if getattr(plate_text_obj, "confidence", None) else 0.0

                # Multi-view detection
                multiview_result = None
                if self.multiview_detector and process_multiview:
                    try:
                        multiview_result = self.multiview_detector.detect(roi)
                        if multiview_result:
                            if isinstance(multiview_result, list) and len(multiview_result) > 0:
                                best_mv = max(multiview_result, key=lambda x: x.get("confidence", 0))
                                det["multiview_confidence"] = best_mv.get("confidence", 0.0)
                                det["views"] = best_mv.get("views", [best_mv.get("view", "unknown")])
                            elif isinstance(multiview_result, dict):
                                det["multiview_confidence"] = multiview_result.get("confidence", 0.0)
                                det["views"] = multiview_result.get("views", [])
                    except Exception:
                        pass

                # Brand classification
                if process_brand and det.get("class", "").lower() in ["car", "truck", "suv", "bus"]:
                    if self.brand_classifier and det.get("confidence", 0) > 0.3:
                        try:
                            bbox_dict = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
                            brand_result = self.brand_classifier.classify_vehicle(
                                frame, bbox_dict, det.get("class", "car")
                            )
                            if brand_result and brand_result.get("confidence", 0) > 0.3:
                                det["vehicle_brand"] = brand_result.get("brand", "")
                                det["brand_confidence"] = brand_result.get("confidence", 0.0)
                                det["brand_method"] = brand_result.get("method", "classifier")
                        except Exception:
                            pass

                    if not det.get("vehicle_brand") and multiview_result:
                        try:
                            views = det.get("views", [])
                            if views and len(views) > 0:
                                mv_conf = det.get("multiview_confidence", 0.0)
                                if mv_conf > 0.5:
                                    det["multiview_detected"] = True
                                    det["brand_method"] = "multiview"
                        except Exception:
                            pass

                # Emissions
                if (
                    self.enhanced_emission_calculator
                    and det.get("speed")
                    and not compute_emissions_for_all_tracked_objects
                ):
                    try:
                        emissions = self.enhanced_emission_calculator.calculate_emissions_from_speed(
                            vehicle_type=det.get("class", "car"),
                            speed_kmh=det["speed"],
                            distance_km=0.001,
                        )
                        det["emission_co2"] = emissions.get("co2_g_km", 0)
                        det["fuel_consumption"] = emissions.get("fuel_l_100km", 0)
                        det["emission_impact"] = emissions.get("impact_level", None)
                    except Exception:
                        pass

                detections.append(det)

            # 4) ATMS trajectory prediction (async)
            # Match original script behavior: ATMS runs on *all tracked objects*
            # (not only the top-N enriched ones).
            if self.atms_system and tracked_objects and run_atms_prediction:
                try:
                    atms_detections = []
                    for obj in tracked_objects:
                        bbox = obj.get("bbox", {})
                        atms_detections.append(
                            {
                                "bbox": [
                                    bbox.get("x1", 0),
                                    bbox.get("y1", 0),
                                    bbox.get("x2", 0),
                                    bbox.get("y2", 0),
                                ],
                                "confidence": obj.get("confidence", 0.5),
                                "class_id": obj.get("class_id", 0),
                            }
                        )

                    atms_result = loop.run_until_complete(
                        asyncio.wait_for(
                            self.atms_system.process_frame(
                                detections=atms_detections,
                                frame_id=f"frame_{frame_idx}",
                                context={},
                            ),
                            timeout=self.atms_timeout_seconds,
                        )
                    )

                    if atms_result and hasattr(atms_result, "tracked_objects"):
                        for det in detections:
                            track_id = det.get("track_id")
                            if track_id and atms_result.tracked_objects:
                                for tracked_obj in atms_result.tracked_objects:
                                    if tracked_obj.get("track_id") == track_id:
                                        det["trajectory_predicted"] = tracked_obj.get(
                                            "predicted_trajectory"
                                        )
                                        det["anomaly_detected"] = tracked_obj.get(
                                            "anomaly_detected"
                                        )
                                        break
                except asyncio.TimeoutError:
                    if frame_idx % 60 == 0:
                        logger.debug(f"ATMS timeout on frame {frame_idx}")
                except Exception:
                    if frame_idx % 60 == 0:
                        logger.debug(f"ATMS processing error", exc_info=True)

        except Exception:
            logger.error(f"Error processing frame {frame_idx}", exc_info=True)

        return detections

    def _apply_distance_aware_filtering(
        self,
        *,
        yolo_results: List[Dict],
        frame_shape: Tuple[int, int],
        params: Optional[Dict[str, Any]],
    ) -> List[Dict]:
        """
        Filter detections by distance proxy using bbox area.

        This mirrors the logic from `youtube_decision_processor.py`:
        - Large objects -> normal threshold
        - Medium -> 10% lower
        - Far (small) -> 20% lower
        """
        h, w = frame_shape
        if h <= 0 or w <= 0:
            return yolo_results

        cfg = params or {}

        veh_classes = cfg.get(
            "vehicle_classes", ["car", "truck", "bus", "motorcycle", "bicycle"]
        )
        ped_classes = cfg.get("pedestrian_classes", ["pedestrian", "person"])
        other_default_threshold = float(cfg.get("other_base_conf", 0.50))

        base_vehicle_threshold = float(cfg.get("vehicle_base_conf", 0.42))
        base_ped_threshold = float(cfg.get("pedestrian_base_conf", 0.51))

        # Relative bbox size thresholds.
        large_thr = float(cfg.get("large_relative_size_threshold", 0.02))
        medium_thr = float(cfg.get("medium_relative_size_threshold", 0.005))

        large_mult = float(cfg.get("large_size_multiplier", 1.0))
        medium_mult = float(cfg.get("medium_size_multiplier", 0.9))
        far_mult = float(cfg.get("far_size_multiplier", 0.8))

        frame_area = float(h * w)
        filtered: List[Dict] = []

        for det in yolo_results:
            class_name = str(det.get("class", "")).lower()
            confidence = float(det.get("confidence", 0.0))
            bbox = det.get("bbox") or {}

            bbox_w = float(bbox.get("x2", 0)) - float(bbox.get("x1", 0))
            bbox_h = float(bbox.get("y2", 0)) - float(bbox.get("y1", 0))
            if bbox_w <= 0 or bbox_h <= 0:
                continue

            bbox_area = bbox_w * bbox_h
            relative_size = bbox_area / frame_area if frame_area > 0 else 0.0

            if relative_size > large_thr:
                size_mult = large_mult
            elif relative_size > medium_thr:
                size_mult = medium_mult
            else:
                size_mult = far_mult

            if class_name in veh_classes:
                threshold = base_vehicle_threshold * size_mult
            elif class_name in ped_classes:
                threshold = base_ped_threshold * size_mult
            else:
                threshold = other_default_threshold * size_mult

            if confidence >= threshold:
                filtered.append(det)

        return filtered

