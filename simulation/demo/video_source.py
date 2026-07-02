"""Real-video emission pipeline.

YOLOv8 → simple IoU tracker → speed estimate → per-class emission → per-direction
aggregation → state-file emit. Writes the SAME state JSON the SUMO demo writes,
so the Streamlit operator console renders the result unchanged.

This is the "real data" path: the vehicles are detections from an actual video,
not SUMO-spawned agents. The emission factors per class come from the same
`shared.atms_common.emissions.EmissionEstimator` the SUMO path uses, so the
numbers are directly comparable.

Run:

    python -m simulation.demo --video videos/TEST.mp4 [--show]

    # --show opens an OpenCV preview window with bounding boxes + speed +
    # emission overlay per vehicle. Off by default so the run is headless
    # and can stream to the Streamlit console in another terminal.

Direction assignment is heuristic: the frame is split into quadrants and
each detection's bbox-centre quadrant determines whether it's NS or EW. A
real deployment uses per-lane masks from the camera calibration; for the
demo this is good enough to populate both directions with realistic data.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared.atms_common.emissions import EmissionEstimator, VehicleClass
from simulation.demo.state_emitter import StateEmitter

log = logging.getLogger("atms.video")


# Physical sanity cap for speed estimation. Anything above this is treated
# as a tracker error (identity swap, occlusion hand-off) — see
# `_update_speeds` for the rationale. 180 km/h ≈ EU motorway limit + 50 km/h
# tolerance; covers every realistic scenario while rejecting glitch values
# that used to produce 400-500 km/h overlay labels.
MAX_REALISTIC_SPEED_KMH: float = 180.0


# ---------------------------------------------------------------------------
# YOLOv8 class id -> our VehicleClass (COCO classes)
# ---------------------------------------------------------------------------

COCO_TO_VEHICLE_CLASS: dict[int, VehicleClass] = {
    1: VehicleClass.BICYCLE,
    2: VehicleClass.CAR,
    3: VehicleClass.MOTORCYCLE,
    5: VehicleClass.BUS,
    7: VehicleClass.TRUCK,
}


# ---------------------------------------------------------------------------
# Brand-detector class id -> canonical brand string used by
# `shared.atms_common.emissions._DEFAULT_BRAND_MULTIPLIERS`.
#
# Two model families currently land here:
#   1. cars-brand-32 / traffic_realistic (13 classes) — Roboflow naming with
#      typos (hyndai, Byd_F3) and an explicit no-brand "car" class.
#   2. DVM-Car (54 classes including _other) — lowercase brand names per
#      data/car_brand_dataset_dvm/data.yaml.
#
# `_other` and `car` are non-brand opt-outs → None so the estimator falls
# back to the per-VehicleClass baseline. Brands without an entry in the
# emission multiplier table also resolve to None (1.0× multiplier).
# ---------------------------------------------------------------------------

BRAND_LABEL_NORMALISATION: dict[str, str | None] = {
    # --- cars-brand-32 / traffic_realistic legacy classes ---
    "byd_f3": "byd",
    "hyndai": "hyundai",  # training-set typo
    "mercedes": "mercedes-benz",  # cars-brand-32 short form
    "car": None,  # generic no-brand detection
    # --- DVM-Car: _other class (opt-out, no brand info) ---
    "_other": None,
    # --- DVM-Car: brands present in the ATMS emission table ---
    "alfa romeo": "alfa romeo",
    "aston martin": "aston martin",
    "audi": "audi",
    "bentley": "bentley",
    "bmw": "bmw",
    "byd": "byd",
    "chevrolet": "chevrolet",
    "chrysler": "chrysler",
    "citroen": "citroen",
    "dacia": "dacia",
    "dodge": "dodge",
    "ds": "ds",
    "ferrari": "ferrari",
    "fiat": "fiat",
    "ford": "ford",
    "honda": "honda",
    "hyundai": "hyundai",
    "infiniti": "infiniti",
    "isuzu": "isuzu",
    "jaguar": "jaguar",
    "jeep": "jeep",
    "kia": "kia",
    "lamborghini": "lamborghini",
    "land rover": "land rover",
    "lexus": "lexus",
    "maserati": "maserati",
    "mazda": "mazda",
    "mercedes-benz": "mercedes-benz",
    "mg": "mg",
    "mini": "mini",
    "mitsubishi": "mitsubishi",
    "nissan": "nissan",
    "peugeot": "peugeot",
    "porsche": "porsche",
    "renault": "renault",
    "rolls-royce": "rolls-royce",
    "saab": "saab",
    "seat": "seat",
    "skoda": "skoda",
    "smart": "smart",
    "subaru": "subaru",
    "suzuki": "suzuki",
    "tesla": "tesla",
    "toyota": "toyota",
    "vauxhall": "vauxhall",
    "volkswagen": "volkswagen",
    "volvo": "volvo",
    # --- DVM-Car brands added 2026-06-13 with multipliers now in the ATMS table ---
    # Abarth aggregates to fiat (it IS Fiat's performance arm and shares engines).
    "abarth": "fiat",
    "daihatsu": "daihatsu",
    "great wall": "great wall",
    "lotus": "lotus",
    "mclaren": "mclaren",
    "rover": "rover",
    "ssangyong": "ssangyong",
    # --- Bosnia pilot 2026-06-14: regional brands not in DVM-Car training
    # set but present in BiH fleet. Brand identification still requires
    # operator override / V2X SRM until a Bosnia-specific brand model
    # is trained, but the canonical keys are wired so emission lookup
    # works once a label arrives.
    "zastava": "zastava",
    "yugo": "yugo",
    "lada": "lada",
}


def normalise_brand(raw: str | None) -> str | None:
    """Map a brand-detector class name to the canonical key used by the
    emission multiplier table. Returns None for the generic `car` class
    or any unknown label so the estimator falls back to the class baseline.
    """
    if not raw:
        return None
    return BRAND_LABEL_NORMALISATION.get(raw.lower().strip())


# ---------------------------------------------------------------------------
# Simple IoU tracker — minimal per-frame matching for speed estimation
# ---------------------------------------------------------------------------


@dataclass
class TrackedVehicle:
    track_id: int
    vehicle_class: VehicleClass
    bbox: tuple[float, float, float, float]  # (x1, y1, x2, y2)
    last_seen_frame: int
    speed_kmh: float = 0.0
    pixel_history: list[tuple[float, float]] = field(default_factory=list)  # bbox centres
    # `brand` is the COMMITTED label produced by the multi-frame voter in
    # simulation/demo/brand_voting.py. Once committed it stays sticky
    # because the voter is a deterministic function of the observation list.
    brand: str | None = None
    brand_confidence: float = 0.0
    # Every per-frame classification result accumulates here. The voter
    # reads this list each time it considers an upgrade.
    brand_observations: list[tuple[str, float]] = field(default_factory=list)

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Intersection-over-Union of two (x1,y1,x2,y2) bboxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    a_area = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    b_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = a_area + b_area - inter
    return inter / union if union > 0 else 0.0


@dataclass(frozen=True)
class Detection:
    """One per-frame detection. `brand` is optional and supplied by a separate
    brand detector when present; the tracker caches it on the matched track."""

    vehicle_class: VehicleClass
    bbox: tuple[float, float, float, float]
    brand: str | None = None
    brand_confidence: float = 0.0


class IoUTracker:
    """Greedy IoU-match tracker. Simple enough to be testable; good enough
    for per-frame speed estimation on intersection footage where vehicles
    don't change appearance much between frames.

    Brand handling: brand observations are sticky-with-upgrade — once a
    track has any non-None brand, later detections only overwrite it if the
    new observation's confidence is at least 0.1 higher. This prevents a
    single misclassification from flipping a stably-identified vehicle.
    """

    def __init__(self, iou_threshold: float = 0.3, ttl_frames: int = 5) -> None:
        self._iou_threshold = iou_threshold
        self._ttl_frames = ttl_frames
        self._tracks: dict[int, TrackedVehicle] = {}
        self._next_id = 1
        self._max_history = 10

    def update(
        self,
        detections: list[Detection] | list[tuple[VehicleClass, tuple[float, float, float, float]]],
        frame_idx: int,
    ) -> list[TrackedVehicle]:
        # Back-compat: callers (and tests) can pass either the new Detection
        # dataclass or the legacy (class, bbox) tuple. Normalise once.
        normalised: list[Detection] = []
        for d in detections:
            if isinstance(d, Detection):
                normalised.append(d)
            else:
                cls, bbox = d
                normalised.append(Detection(vehicle_class=cls, bbox=bbox))

        # Greedy match: each detection picks the best-IoU still-alive track.
        unmatched_dets: list[int] = list(range(len(normalised)))
        matched_track_ids: set[int] = set()
        for det_idx in list(unmatched_dets):
            det = normalised[det_idx]
            best_id = None
            best_iou = self._iou_threshold
            for tid, track in self._tracks.items():
                if tid in matched_track_ids:
                    continue
                if track.vehicle_class is not det.vehicle_class:
                    continue
                iou = _iou(track.bbox, det.bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_id = tid
            if best_id is not None:
                track = self._tracks[best_id]
                track.bbox = det.bbox
                track.last_seen_frame = frame_idx
                track.pixel_history.append(track.center)
                track.pixel_history = track.pixel_history[-self._max_history :]
                # Brand sticky-with-upgrade: only overwrite an existing brand
                # if the new observation is meaningfully more confident.
                if det.brand is not None and (
                    track.brand is None or det.brand_confidence > track.brand_confidence + 0.1
                ):
                    track.brand = det.brand
                    track.brand_confidence = det.brand_confidence
                matched_track_ids.add(best_id)
                unmatched_dets.remove(det_idx)

        # Unmatched detections become new tracks.
        for det_idx in unmatched_dets:
            det = normalised[det_idx]
            track = TrackedVehicle(
                track_id=self._next_id,
                vehicle_class=det.vehicle_class,
                bbox=det.bbox,
                last_seen_frame=frame_idx,
                brand=det.brand,
                brand_confidence=det.brand_confidence,
            )
            track.pixel_history.append(track.center)
            self._tracks[self._next_id] = track
            self._next_id += 1

        # Expire stale tracks
        stale = [
            tid
            for tid, track in self._tracks.items()
            if frame_idx - track.last_seen_frame > self._ttl_frames
        ]
        for tid in stale:
            del self._tracks[tid]

        return list(self._tracks.values())


# ---------------------------------------------------------------------------
# Direction inference (heuristic)
# ---------------------------------------------------------------------------


def _fuse_brand_observations(
    detections: list[Detection],
    brand_obs: list[tuple[tuple[float, float, float, float], str, float]],
    iou_threshold: float = 0.30,
) -> list[Detection]:
    """For each vehicle detection, attach the brand whose bbox has the highest
    IoU above the threshold. Brand observations that don't match any vehicle
    detection are dropped — they're probably the brand detector misfiring on
    a non-vehicle region.
    """
    if not brand_obs:
        return list(detections)
    used: set[int] = set()
    fused: list[Detection] = []
    for det in detections:
        best_idx: int | None = None
        best_iou = iou_threshold
        for i, (bbox, _brand, _conf) in enumerate(brand_obs):
            if i in used:
                continue
            iou = _iou(det.bbox, bbox)
            if iou > best_iou:
                best_iou = iou
                best_idx = i
        if best_idx is not None:
            _, brand, conf = brand_obs[best_idx]
            used.add(best_idx)
            fused.append(
                Detection(
                    vehicle_class=det.vehicle_class,
                    bbox=det.bbox,
                    brand=brand,
                    brand_confidence=conf,
                )
            )
        else:
            fused.append(det)
    return fused


def _assign_direction(center_xy: tuple[float, float], frame_width: int, frame_height: int) -> str:
    """Coarse heuristic: top + bottom halves of the frame are NS; left +
    right halves are EW. The dominant axis (whichever distance from frame
    centre is larger) decides.

    Production deployments replace this with per-lane masks drawn at
    camera-calibration time.
    """
    cx, cy = center_xy
    dx = abs(cx - frame_width / 2)
    dy = abs(cy - frame_height / 2)
    return "east_west" if dx >= dy else "north_south"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@dataclass
class VideoConfig:
    video_path: Path
    # Pixels-per-meter at the camera's typical depth of focus. THIS IS
    # CAMERA-SPECIFIC and must be calibrated for accurate speed/emission
    # numbers. Default 25.0 matches a typical wide-angle traffic camera
    # capturing ~75 m horizontally on a 1920px frame; for narrower angles
    # the value goes up (e.g. ~40 for a 50-m FOV camera), for fisheye it
    # drops (e.g. ~15 for 120 m). To calibrate against a known reference
    # in your footage:
    #   1. Identify two points whose real-world distance you know (e.g., a
    #      lane width of 3.5 m, a vehicle length of 4.5 m).
    #   2. Measure the pixel distance between them in a representative
    #      frame.
    #   3. pixels_per_meter = pixel_distance / real_distance.
    # The CLI exposes `--pixels-per-meter` to override per video.
    # NOTE: the prior default of 8.0 was wrong by a factor of ~3-6 for the
    # YouTube traffic clips, producing 400-500 km/h speed overlays. Fixed
    # 2026-06-13 alongside the time-interval and outlier-rejection fixes
    # in `_update_speeds`.
    pixels_per_meter: float = 25.0
    yolo_weights: Path = Path("models/yolov8n.pt")
    conf_threshold: float = 0.35
    show: bool = False  # OpenCV preview window
    # Optional mp4 path to write the annotated frames to (bbox + brand + speed
    # + emission overlay). Useful for pre-recording demo material so a stage
    # presenter has a guaranteed-working video to fall back on if live
    # inference hits a glitch. Writes every source frame (not just inference
    # frames) so playback is smooth.
    save_video_path: Path | None = None
    # Region-specific emission multiplier overlay YAML (e.g.
    # services/observability/bosnia-fleet-multipliers.yaml). Forwarded
    # to the EmissionEstimator at construction. None = global defaults.
    emission_overlay_path: str | None = None
    # Operator console locale forwarded into the state JSON for the
    # Streamlit UI's translation layer. "en" / "bs" / "tr" supported.
    operator_locale: str = "en"
    # Per-camera homography JSON path (produced by
    # scripts/calibrate_camera_homography.py during site survey). When
    # set, speed calculation uses pixel→metre projection via the
    # homography instead of the single-ratio `pixels_per_meter`. None =
    # fallback to the single ratio.
    homography_path: str | None = None
    state_emitter_path: Path | None = None
    state_emit_every_n_frames: int = 5  # ~6 Hz at 30 fps
    brand_weights: Path | None = Path(
        "models/car_brand_classification/outputs/dvm_car_v1/weights/best.pt"
    )
    # 2026-06-13: validated against 240-crop labelled ground truth.
    # dvm_car_v1 @ conf 0.50 = 66.7% precision (4 TP / 2 FP / 175 FN) on
    # wide-angle footage. The "_other" opt-out behaviour I once interpreted
    # as failure mode IS the intended behaviour — it correctly opts out on
    # uncertain crops rather than committing wrongly. The 13-class
    # traffic_realistic baseline at the same conf delivered 0% precision
    # (every commit wrong); at conf 0.20 it dropped to 1.8% with 55 FPs.
    # See `data/ground_truth/metrics_*.{md,json}` for the per-brand
    # break-down and `services/labeler/app.py` for the labelling tool.
    # Frame skipping — process every Nth frame. The pipeline cost on CPU is
    # dominated by the two YOLO models (vehicle + brand). Default 3 = 10fps
    # effective; vehicle detections don't change meaningfully in 100ms so the
    # visual stays smooth.
    frame_skip: int = 3
    # 2026-06-13: raised from 0.20 to 0.50 alongside the temporary revert to
    # traffic_realistic. The 13-class model produces low-confidence BYD/MG
    # noise commits under ~0.50 on wide-angle footage; 0.50 suppresses them
    # cleanly. Will drop back to 0.20 once dvm_car_v2 (retrained without
    # the `_other` domain-confound class) lands as the default.
    brand_conf_threshold: float = 0.50
    # Brand classification cost is bounded by a four-stage filter:
    # 1. Throttle: only every Nth frame (default 30 = once per sim-second).
    # 2. Permanent cache: once a track has ANY brand identification (conf >=
    #    `brand_cache_confidence`), don't re-classify. The 0.15 default is
    #    deliberately low — brand detectors trained on close-up datasets
    #    rarely exceed 0.40 even when correct, so a higher threshold would
    #    re-classify the same vehicles every frame.
    # 3. Size filter: skip bboxes smaller than `brand_min_bbox_px`.
    # 4. Batch: remaining crops go through one model.predict call.
    # Net effect: brand inference is O(distinct vehicle tracks) over the
    # video lifetime, not O(vehicles x frames).
    brand_classify_every_n_frames: int = 60  # every 2s at 30 fps
    brand_cache_confidence: float = 0.15
    brand_min_bbox_px: int = 40
    # "trained" -> use the local YOLOv8 model at brand_weights (13 classes,
    # fast). "clip" -> use OpenAI CLIP zero-shot via transformers (70+
    # brands, ~10x slower per crop).
    brand_model: str = "trained"
    # Detection runtime selector for the primary YOLOv8 vehicle detector.
    # "auto" (default) prefers ONNX via the CoreML execution provider when
    # available (1.5x faster than PyTorch on Apple Silicon). See
    # simulation/demo/inference_runtime.py.
    runtime: str = "auto"


# ---------------------------------------------------------------------------
# Brand identifier — runs the trained car-brand detector and exposes the
# results as (bbox, brand, confidence) tuples the pipeline matches to the
# YOLOv8n vehicle detections.
# ---------------------------------------------------------------------------


class BrandIdentifier:
    """Lazy-loaded wrapper around the trained YOLOv8 brand detector at
    `models/car_brand_classification/.../best.pt`.

    The brand detector was trained on the `cars-brand-32` dataset, which is
    close-up single-car images. Running it on a wide-angle traffic frame
    produces almost zero confident detections because individual cars are
    small relative to the training distribution. So we run it **per crop**:
    each YOLOv8 vehicle bbox becomes a single input to the brand detector,
    padded slightly so the model has context. This produces far more
    confident outputs than full-frame inference.
    """

    def __init__(
        self,
        weights_path: Path | None,
        conf_threshold: float = 0.20,
        bbox_pad_ratio: float = 0.10,
    ) -> None:
        self._weights_path = weights_path
        self._conf_threshold = conf_threshold
        self._bbox_pad_ratio = bbox_pad_ratio
        self._model = None  # lazy
        self._available = weights_path is not None and weights_path.exists()

    @property
    def available(self) -> bool:
        return self._available

    def _ensure_loaded(self) -> None:
        if self._model is not None or not self._available:
            return
        try:
            from ultralytics import YOLO  # noqa: PLC0415

            log.info("loading brand detector from %s ...", self._weights_path)
            self._model = YOLO(str(self._weights_path))
        except Exception as e:
            log.warning("could not load brand detector (%s); proceeding without it", e)
            self._available = False

    def identify_batch(self, crops: list[Any]) -> list[tuple[str, float] | None]:
        """Run a single batched inference over many crops. Returns a list of
        `(brand, conf)` (or None) parallel to the input crops. This is the
        fast path used by the live pipeline — one model call per frame instead
        of one per vehicle.
        """
        self._ensure_loaded()
        if self._model is None or not crops:
            return [None] * len(crops)
        try:
            results = self._model.predict(crops, conf=self._conf_threshold, verbose=False)
        except Exception as e:
            log.warning("brand batch inference failed: %s", e)
            return [None] * len(crops)

        names = self._model.names if hasattr(self._model, "names") else {}
        out: list[tuple[str, float] | None] = []
        for r in results:
            boxes = getattr(r, "boxes", None)
            best: tuple[str, float] | None = None
            if boxes is not None:
                for i in range(len(boxes)):
                    cls_id = int(boxes.cls[i].item())
                    conf = float(boxes.conf[i].item())
                    raw_label = names.get(cls_id, "")
                    canonical = normalise_brand(raw_label)
                    if canonical is None:
                        continue
                    if best is None or conf > best[1]:
                        best = (canonical, conf)
            out.append(best)
        return out

    def identify_for_bbox(
        self, frame, bbox: tuple[float, float, float, float]
    ) -> tuple[str, float] | None:
        """Crop `frame` to `bbox` (with padding) and run the brand detector.
        Returns `(canonical_brand, confidence)` for the best match, or `None`
        if nothing brand-bearing was found in the crop.
        """
        self._ensure_loaded()
        if self._model is None:
            return None

        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]
        pad_x = (x2 - x1) * self._bbox_pad_ratio
        pad_y = (y2 - y1) * self._bbox_pad_ratio
        cx1 = max(0, int(x1 - pad_x))
        cy1 = max(0, int(y1 - pad_y))
        cx2 = min(w, int(x2 + pad_x))
        cy2 = min(h, int(y2 + pad_y))
        if cx2 <= cx1 or cy2 <= cy1:
            return None

        crop = frame[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return None

        try:
            results = self._model.predict(crop, conf=self._conf_threshold, verbose=False)
        except Exception as e:
            log.warning("brand inference (crop) failed: %s", e)
            return None

        names = self._model.names if hasattr(self._model, "names") else {}
        best: tuple[str, float] | None = None
        for r in results:
            boxes = getattr(r, "boxes", None)
            if boxes is None:
                continue
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i].item())
                conf = float(boxes.conf[i].item())
                raw_label = names.get(cls_id, "")
                canonical = normalise_brand(raw_label)
                if canonical is None:
                    continue
                if best is None or conf > best[1]:
                    best = (canonical, conf)
        return best


def _build_brand_identifier(config: VideoConfig) -> Any:
    """Pick the brand identifier per `config.brand_model`. Both implementations
    expose the same `identify_batch(crops) -> list[(brand, conf) | None]` and
    `available` interface, so the pipeline doesn't care which one it gets.
    """
    if config.brand_model == "clip":
        # Lazy import — keeps the trained-model code path zero-cost when the
        # user doesn't ask for CLIP.
        from simulation.demo.brand_clip import CLIPBrandIdentifier  # noqa: PLC0415

        return CLIPBrandIdentifier(conf_threshold=config.brand_conf_threshold)
    return BrandIdentifier(config.brand_weights, conf_threshold=config.brand_conf_threshold)


class VideoEmissionPipeline:
    """Top-level run loop. Reads frames, runs detection + tracking, emits state."""

    def __init__(self, config: VideoConfig) -> None:
        self.config = config
        self.tracker = IoUTracker()
        # Estimator picks up the region-specific multiplier overlay if
        # one was forwarded from the site config (Bosnia pilot uses
        # services/observability/bosnia-fleet-multipliers.yaml).
        self.estimator = EmissionEstimator(
            region_overlay_path=config.emission_overlay_path,
        )
        # Per-camera homography (Phase 7) — when set, speed calculation
        # transforms pixel motion via the 3×3 H matrix instead of the
        # single-value pixels_per_meter approximation. Refuses to load
        # if the calibrated frame_shape doesn't match the live camera.
        self._homography = None
        if config.homography_path:
            from simulation.demo.homography import Homography  # noqa: PLC0415

            try:
                self._homography = Homography.load(config.homography_path)
                log.info(
                    "homography loaded: residual_max=%.2fm (pilot accept <0.5m)",
                    self._homography.max_residual_m,
                )
            except Exception as e:
                log.warning(
                    "homography %s failed to load (%s) — falling back to "
                    "single-ratio pixels_per_meter=%.1f",
                    config.homography_path, e, config.pixels_per_meter,
                )

        # Scene change detector (Phase 8) — when a camera mount shifts
        # or the scene structurally changes (construction, road
        # resurfacing) the homography becomes silently invalid. This
        # detector compares each frame against a baseline reference;
        # 60+ consecutive divergent frames triggers an operator alert.
        from simulation.demo.scene_change import SceneChangeDetector  # noqa: PLC0415

        self._scene_change = SceneChangeDetector(
            check_interval_seconds=1.0,
            threshold_diff=0.25,
            threshold_frames=60,
        )
        self.state_emitter = StateEmitter(path=config.state_emitter_path)
        self.brand_identifier = _build_brand_identifier(config)
        # Person detections from the most recent inference, consumed by
        # the chamber's VisionPedestrianDetector. Default zones place
        # crosswalks at the bottom-25% (NS) and left-25% (EW) of the
        # frame — sensible defaults for an arterial 4-way intersection
        # viewed head-on. Production swap: per-camera homography +
        # explicit zone polygons in deployment config.
        self._current_persons: list[tuple[float, float, float, float]] = []

        # AI Decision Chamber (Phase 1 — see ADR 0021). The chamber takes
        # per-direction aggregated state on every emit cycle and produces
        # an explainable phase request that the operator console renders.
        # In production this advisory phase request would feed an NTCIP
        # signal controller; for the demo we surface it via the state JSON.
        from simulation.decision_chamber import (  # noqa: PLC0415
            ChamberConfig,
            DecisionChamber,
        )
        from simulation.decision_chamber.pedestrian import (  # noqa: PLC0415
            ButtonPedestrianDetector,
            VisionPedestrianDetector,
        )
        from simulation.decision_chamber.preemption import (  # noqa: PLC0415
            OperatorOverrideDetector,
            VisualLightbarDetector,
        )
        from simulation.decision_chamber.metrics import PrometheusMetrics  # noqa: PLC0415
        from simulation.decision_chamber.v2x import V2XSrmDetector  # noqa: PLC0415

        chamber_config = ChamberConfig(
            audit_log_path=str(
                config.state_emitter_path.parent / "chamber_audit.jsonl"
            )
            if config.state_emitter_path is not None
            else "/tmp/atms-chamber-audit.jsonl",
        )
        # Prometheus metrics — exposed on /metrics endpoint for Grafana
        # scrape. Disabled gracefully if port 9090 is taken.
        try:
            metrics = PrometheusMetrics(intersection_id="demo", listen_port=9090)
        except Exception as e:
            log.warning("metrics disabled: %s", e)
            metrics = None

        self.chamber = DecisionChamber(
            config=chamber_config,
            detectors=[
                OperatorOverrideDetector(
                    Path("/tmp/atms-operator-override.json")
                ),
                VisualLightbarDetector(),
                V2XSrmDetector(listen_host="127.0.0.1", listen_port=4444),
            ],
            pedestrian_detectors=[
                ButtonPedestrianDetector(
                    Path("/tmp/atms-ped-button.json")
                ),
                # VisionPedestrianDetector with default heuristic zones:
                # NS = bottom 25% of frame, EW = left 25% of frame.
                # Production swap: load per-camera crosswalk_zones from
                # site-survey JSON.
                VisionPedestrianDetector(),
            ],
            metrics=metrics,
            intersection_id="demo",
        )

    def run(self) -> int:
        """Process the video end-to-end. Returns process exit code."""
        try:
            import cv2  # noqa: PLC0415
        except ImportError as e:
            print(
                f"✗ video pipeline needs opencv-python\n"
                f"  ImportError: {e}\n"
                f"  Install: python3 -m pip install --break-system-packages opencv-python",
                flush=True,
            )
            return 2

        weights = Path(self.config.yolo_weights)
        if not weights.exists():
            print(
                f"✗ YOLOv8 weights not found at {weights}.\n"
                f"  Place yolov8n.pt under models/ or pass --yolo-weights.",
                flush=True,
            )
            return 2

        from simulation.demo.inference_runtime import make_detector  # noqa: PLC0415

        try:
            detector = make_detector(weights, runtime=self.config.runtime)
        except Exception as e:
            print(f"✗ failed to load YOLOv8 detector: {e}", flush=True)
            return 2
        log.info("vehicle detector backend: %s", detector.backend_name)
        model = detector  # alias — _detect uses .predict(frame, conf)

        if self.brand_identifier.available:
            log.info("brand identifier ENABLED — emissions will use per-brand multipliers")
        else:
            log.info(
                "brand identifier disabled (weights not found at %s)",
                self.config.brand_weights,
            )

        cap = cv2.VideoCapture(str(self.config.video_path))
        if not cap.isOpened():
            print(f"✗ could not open video {self.config.video_path}", flush=True)
            return 2

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        log.info("video opened: %s  %dx%d @ %.1f fps", self.config.video_path, width, height, fps)

        # Optional annotated-output recorder. mp4v fourcc is universally
        # readable; H264 would compress smaller but isn't built into the
        # macOS opencv wheels.
        writer: Any | None = None
        if self.config.save_video_path is not None:
            self.config.save_video_path.parent.mkdir(parents=True, exist_ok=True)
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(
                str(self.config.save_video_path), fourcc, fps, (width, height)
            )
            if not writer.isOpened():
                log.warning(
                    "could not open VideoWriter for %s; recording disabled",
                    self.config.save_video_path,
                )
                writer = None
            else:
                log.info("recording annotated video -> %s", self.config.save_video_path)

        frame_idx = 0
        sim_time_offset = time.monotonic()
        tracks: list[TrackedVehicle] = []  # last computed; reused on skipped frames
        skip = max(1, self.config.frame_skip)
        log.info(
            "frame_skip=%d -> inference on every %d%s frame (target ~%.1f fps inference)",
            skip,
            skip,
            "st" if skip == 1 else ("nd" if skip == 2 else ("rd" if skip == 3 else "th")),
            fps / skip,
        )

        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    log.info("end of video at frame %d", frame_idx)
                    break

                frame_idx += 1
                # Frame-skip: only run YOLO + tracker + brand-classifier on
                # every Nth frame. The remaining frames just display the last
                # known tracks (overlay stays steady; emission state doesn't
                # change meaningfully in 100ms).
                if frame_idx % skip == 0:
                    detections = self._detect(model, frame)
                    tracks = self.tracker.update(detections, frame_idx)
                    self._update_speeds(tracks, fps)
                    if self.brand_identifier.available:
                        self._classify_track_brands(frame, tracks, frame_idx)

                    # Scene change check — bounded ~1 Hz cost
                    sc_status = self._scene_change.consider_frame(frame)
                    # Forward scene-change gauge to chamber's Prometheus
                    # exporter so Grafana panel 12 has a series.
                    sc_metrics = getattr(self.chamber, "_metrics", None)
                    if sc_metrics is not None:
                        sc_metrics.set_gauge(
                            "atms_scene_change_alert_active",
                            1.0 if sc_status.alert_active else 0.0,
                        )
                        sc_metrics.set_gauge(
                            "atms_scene_change_latest_diff",
                            sc_status.latest_diff,
                        )
                    if frame_idx % self.config.state_emit_every_n_frames == 0:
                        elapsed = time.monotonic() - sim_time_offset
                        self._emit_state(
                            tracks, width, height, sim_time=elapsed, frame=frame
                        )

                # Draw once if either the preview window OR the recorder is on
                # — both consume the same annotated frame, so a single _draw
                # serves them.
                if self.config.show or writer is not None:
                    self._draw(frame, tracks)
                if writer is not None:
                    writer.write(frame)
                if self.config.show:
                    cv2.imshow("ATMS — real-video emission pipeline", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        log.info("user pressed q; exiting")
                        break
        finally:
            cap.release()
            if writer is not None:
                writer.release()
                log.info("recorded annotated video: %s", self.config.save_video_path)
            if self.config.show:
                cv2.destroyAllWindows()

        print(
            f"\n✓ video processing complete  "
            f"({frame_idx} frames, ~{frame_idx / fps:.1f}s of footage)\n"
            f"  Open the operator console (http://localhost:8501) to review state."
        )
        return 0

    # ----- per-frame steps -------------------------------------------------

    def _draw_virtual_signals(
        self, frame, commanded_direction: str, mode: str, W: int, H: int
    ) -> None:
        """Render two mini 3-light traffic signals (NS + EW) in the top-
        right corner. The signal corresponding to the chamber's
        commanded direction shows GREEN; the other shows RED. During
        preempt mode both signals get a red border alert.

        This makes the chamber's decision IMMEDIATELY visible on the
        recorded video — stakeholder watching the mp4 doesn't need the
        operator console open in parallel to see what direction is
        being prioritised. Standard 3-light vertical stack (red, yellow,
        green from top to bottom) matches real traffic signals.
        """
        import cv2  # noqa: PLC0415

        # Geometry — generous spacing so labels don't collide
        signal_w = 72
        signal_h = 220
        light_r = 28
        spacing = 18
        header_h = 26
        label_h = 26
        margin_top = 100  # below the HUD
        margin_right = 28
        pad = 14

        signals = [
            ("N-S", "north_south"),
            ("E-W", "east_west"),
        ]
        total_w = len(signals) * signal_w + (len(signals) - 1) * spacing
        x0 = W - margin_right - total_w

        # Header sits ABOVE the labels, both inside the backdrop.
        backdrop_x1 = x0 - pad
        backdrop_y1 = margin_top
        backdrop_x2 = x0 + total_w + pad
        backdrop_y2 = margin_top + header_h + label_h + signal_h + pad

        roi = frame[backdrop_y1:backdrop_y2, backdrop_x1:backdrop_x2].copy()
        overlay = roi.copy()
        overlay[:] = (24, 26, 27)
        blended = cv2.addWeighted(overlay, 0.80, roi, 0.20, 0)
        frame[backdrop_y1:backdrop_y2, backdrop_x1:backdrop_x2] = blended

        # Border in preempt mode
        if mode == "preempt":
            cv2.rectangle(
                frame,
                (backdrop_x1, backdrop_y1),
                (backdrop_x2, backdrop_y2),
                (67, 68, 219),
                3,
            )

        # Row 1: Header (its own row, no collision with labels)
        cv2.putText(
            frame,
            "SIGNAL HEADS",
            (backdrop_x1 + 10, backdrop_y1 + 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (180, 200, 210),
            1,
            cv2.LINE_AA,
        )

        # Row 2: Direction labels
        label_y_baseline = backdrop_y1 + header_h + 18
        # Row 3: Signal housings
        housing_y = backdrop_y1 + header_h + label_h

        for i, (label, direction) in enumerate(signals):
            cx = x0 + i * (signal_w + spacing) + signal_w // 2
            (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
            cv2.putText(
                frame,
                label,
                (cx - tw // 2, label_y_baseline),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (235, 235, 235),
                2,
                cv2.LINE_AA,
            )

            cv2.rectangle(
                frame,
                (cx - signal_w // 2, housing_y),
                (cx + signal_w // 2, housing_y + signal_h),
                (38, 40, 42),
                -1,
            )
            cv2.rectangle(
                frame,
                (cx - signal_w // 2, housing_y),
                (cx + signal_w // 2, housing_y + signal_h),
                (90, 92, 94),
                2,
            )

            is_green = direction == commanded_direction
            # Bright/dim colour pairs (BGR) — bright when active, dim otherwise.
            bright_red = (60, 60, 240)
            dim_red = (40, 50, 100)
            bright_green = (60, 220, 80)
            dim_green = (40, 70, 38)
            dim_yellow = (40, 90, 100)  # MVP: no yellow phase rendering

            red_color = dim_red if is_green else bright_red
            green_color = bright_green if is_green else dim_green
            yellow_color = dim_yellow

            light_x = cx
            light_gap = (signal_h - 30) // 3
            for j, color in enumerate([red_color, yellow_color, green_color]):
                light_y = housing_y + 22 + j * light_gap
                # Glow for active lights only
                is_active = (j == 0 and not is_green) or (j == 2 and is_green)
                if is_active:
                    # Soft glow ring
                    cv2.circle(frame, (light_x, light_y), light_r + 6, color, -1)
                cv2.circle(frame, (light_x, light_y), light_r, color, -1)
                cv2.circle(frame, (light_x, light_y), light_r, (15, 15, 15), 1)

    def _classify_track_brands(self, frame, tracks: list[TrackedVehicle], frame_idx: int) -> None:
        """Batched, cached brand classification operating on tracks.

        Three speed-ups vs the previous per-detection-per-frame approach:
        1. **Cache**: skip any track whose brand_confidence already exceeds
           `brand_cache_confidence`. Once a vehicle is confidently classified,
           we don't re-classify on later frames.
        2. **Throttle**: only run on every Nth frame
           (`brand_classify_every_n_frames`).
        3. **Size filter + batch**: skip bboxes smaller than `brand_min_bbox_px`
           (brand detector is unreliable on tiny vehicles), then submit the
           remainder as a single batched model.predict call.

        Updates each classified track's `brand` / `brand_confidence` in place.
        """
        if frame_idx % self.config.brand_classify_every_n_frames != 0:
            return

        # Filter: tracks that need classification
        candidates: list[TrackedVehicle] = []
        crops: list[Any] = []
        h, w = frame.shape[:2]
        min_px = self.config.brand_min_bbox_px
        cache_conf = self.config.brand_cache_confidence
        pad_ratio = 0.10
        for t in tracks:
            if t.brand is not None and t.brand_confidence >= cache_conf:
                continue  # already confidently classified — cached
            x1, y1, x2, y2 = t.bbox
            if (x2 - x1) < min_px or (y2 - y1) < min_px:
                continue  # bbox too small for reliable brand recognition
            pad_x = (x2 - x1) * pad_ratio
            pad_y = (y2 - y1) * pad_ratio
            cx1 = max(0, int(x1 - pad_x))
            cy1 = max(0, int(y1 - pad_y))
            cx2 = min(w, int(x2 + pad_x))
            cy2 = min(h, int(y2 + pad_y))
            if cx2 <= cx1 or cy2 <= cy1:
                continue
            crop = frame[cy1:cy2, cx1:cx2]
            if crop.size == 0:
                continue
            candidates.append(t)
            crops.append(crop)

        if not crops:
            return

        # One batched inference for the whole frame
        results = self.brand_identifier.identify_batch(crops)
        # Append each new observation, then let the multi-frame voter decide
        # whether the accumulated evidence is enough to commit / upgrade.
        # A single misidentification can no longer flip a stable track.
        from simulation.demo.brand_voting import decide_brand  # noqa: PLC0415

        for t, result in zip(candidates, results, strict=False):
            if result is None:
                continue
            t.brand_observations.append(result)
            # Cap the observation list so a long-lived track doesn't grow
            # unboundedly. 20 observations is far more than enough.
            if len(t.brand_observations) > 20:
                t.brand_observations = t.brand_observations[-20:]
            decision = decide_brand(t.brand_observations)
            if decision is not None:
                t.brand, t.brand_confidence = decision

    def _detect(self, model, frame) -> list[Detection]:
        """Run YOLOv8 inference (via the DetectorBackend protocol) and split
        into vehicle detections (returned) + person detections (stashed on
        the pipeline for the VisionPedestrianDetector to consume).

        Single inference pass; the cost is identical to vehicle-only
        detection. We just don't throw away the class-0 person boxes.
        """
        out: list[Detection] = []
        persons: list[tuple[float, float, float, float]] = []
        for cls_id, bbox in model.predict(frame, conf=self.config.conf_threshold):
            if cls_id == 0:  # COCO person
                persons.append(bbox)
                continue
            vclass = COCO_TO_VEHICLE_CLASS.get(cls_id)
            if vclass is None:
                continue
            out.append(Detection(vehicle_class=vclass, bbox=bbox))
        # Stash the latest persons for the chamber's pedestrian detector.
        self._current_persons = persons
        return out

    def _update_speeds(self, tracks: list[TrackedVehicle], fps: float) -> None:
        """Compute speed in km/h from per-track pixel displacement.

        Three corrections vs the older single-step estimator:

        1. **Correct time interval**: with frame_skip=N, _update_speeds runs
           every N frames, so the elapsed time between samples is N/fps,
           NOT 1/fps. The old code overstated all speeds by a factor of N
           (3× at the default skip).
        2. **Whole-window smoothing**: speed = (last position − first
           position) / total elapsed time over the pixel-history window
           (default 10 samples ~= 1 second). One-frame tracker glitches no
           longer produce wild spikes; the window naturally averages them out.
        3. **Physical sanity cap (MAX_REALISTIC_SPEED_KMH = 180)**: anything
           above this is treated as a tracker error (identity swap, occlusion
           hand-off) and clamped to 0. 180 km/h covers EU motorway speed
           limits plus 50 km/h tolerance; on urban traffic the real max is
           much lower, but a single threshold keeps the policy simple.
        """
        # _update_speeds runs once per processed frame, i.e. once every
        # frame_skip source-frames. The elapsed time per stored history
        # entry is therefore frame_skip/fps, not 1/fps.
        interval = self.config.frame_skip / fps if fps > 0 else 0.0
        for t in tracks:
            n = len(t.pixel_history)
            if n < 2 or interval <= 0:
                t.speed_kmh = 0.0
                continue
            x0, y0 = t.pixel_history[0]
            x1, y1 = t.pixel_history[-1]
            # Pixel→metre transformation: prefer per-camera homography
            # when loaded (accurate at any frame location); fall back to
            # single-ratio when not (acceptable for centre-frame only).
            if self._homography is not None:
                meters = self._homography.pixel_distance_meters(x0, y0, x1, y1)
            else:
                dx = x1 - x0
                dy = y1 - y0
                pixel_dist = (dx * dx + dy * dy) ** 0.5
                meters = pixel_dist / self.config.pixels_per_meter
            seconds = (n - 1) * interval
            mps = meters / seconds if seconds > 0 else 0.0
            speed_kmh = mps * 3.6
            # Reject anything physically implausible. Real vehicles on UK/EU
            # roads top out around 130 km/h on motorways; anything above 180
            # is almost certainly a tracker hand-off rather than a real
            # measurement. We zero it rather than display "180" so the
            # operator sees "unknown speed" rather than a fake cap value.
            if speed_kmh > MAX_REALISTIC_SPEED_KMH:
                t.speed_kmh = 0.0
            else:
                t.speed_kmh = speed_kmh

    def _emit_state(
        self,
        tracks: list[TrackedVehicle],
        frame_width: int,
        frame_height: int,
        sim_time: float,
        frame=None,
    ) -> None:
        """Aggregate per direction and write the operator-console state file."""
        per_direction: dict[str, list[tuple[str | VehicleClass, float, str | None]]] = {
            "north_south": [],
            "east_west": [],
        }
        # Mirror fleet for baseline (brand-less) aggregation so the UI can
        # show "with vs without brand multiplier" CO2 side by side. Same
        # vehicles + speeds, brand stripped.
        per_direction_baseline: dict[str, list[tuple[str | VehicleClass, float, str | None]]] = {
            "north_south": [],
            "east_west": [],
        }
        brand_counts: dict[str, dict[str, int]] = {"north_south": {}, "east_west": {}}
        brand_confidences: dict[str, dict[str, list[float]]] = {
            "north_south": {},
            "east_west": {},
        }
        # Idling-vehicle counts feed the chamber's emission-cost calculation.
        # A vehicle with measured speed ≤ 5 km/h is treated as idling/queueing.
        idling_counts: dict[str, int] = {"north_south": 0, "east_west": 0}
        # Vehicle crops by direction for the visual-lightbar emergency
        # detector (Layer 1). Empty if frame not provided.
        vehicle_crops_by_direction: list[tuple[str, "Any"]] = []
        for t in tracks:
            direction = _assign_direction(t.center, frame_width, frame_height)
            per_direction[direction].append((t.vehicle_class, t.speed_kmh, t.brand))
            per_direction_baseline[direction].append((t.vehicle_class, t.speed_kmh, None))
            if 0 < t.speed_kmh <= 5.0 or t.speed_kmh == 0.0:
                idling_counts[direction] += 1
            if t.brand:
                brand_counts[direction][t.brand] = brand_counts[direction].get(t.brand, 0) + 1
                brand_confidences[direction].setdefault(t.brand, []).append(t.brand_confidence)
            # Extract crop for the lightbar detector if we have a frame.
            if frame is not None:
                x1, y1, x2, y2 = (int(v) for v in t.bbox)
                H, W = frame.shape[:2]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(W, x2), min(H, y2)
                if x2 > x1 and y2 > y1:
                    vehicle_crops_by_direction.append((direction, frame[y1:y2, x1:x2]))

        per_direction_metrics: dict[str, dict[str, Any]] = {}
        for direction, fleet in per_direction.items():
            agg = self.estimator.aggregate_direction(direction, fleet)
            baseline_agg = self.estimator.aggregate_direction(
                direction, per_direction_baseline[direction]
            )
            mean_speed = sum(v[1] for v in fleet) / len(fleet) if fleet else 0.0
            identified = sum(1 for v in fleet if v[2])
            # Per-brand average confidence (UI uses this for the colour bar).
            mean_brand_confidence = {
                brand: round(sum(confs) / len(confs), 3)
                for brand, confs in brand_confidences[direction].items()
            }
            per_direction_metrics[direction] = {
                "vehicle_count": agg.vehicle_count,
                "average_emission": round(agg.average_emission_g_per_km, 2),
                "average_waiting_time": round(max(0.0, 30.0 - mean_speed), 2),
                "average_velocity": round(mean_speed if mean_speed > 0 else 0.0, 2),
                "total_emission": round(
                    agg.average_emission_g_per_km * max(1, agg.vehicle_count), 2
                ),
                "environmental_impact_score": round(
                    min(100.0, agg.average_emission_g_per_km * 0.6), 2
                ),
                "emissions": agg.to_dict(),
                # NEW: baseline (brand-less) for the UI's "uncertainty band"
                "emissions_baseline": baseline_agg.to_dict(),
                "brand_breakdown": brand_counts[direction],
                "brand_confidence_by_brand": mean_brand_confidence,
                "brand_identified_count": identified,
            }

        # --- AI Decision Chamber tick -----------------------------------
        # Build per-direction state and let the chamber decide. The
        # chamber's `commanded_phase` becomes the state's
        # `commanded_phase` field — replacing the static "real_video"
        # placeholder from the pre-chamber era.
        from datetime import datetime, timezone  # noqa: PLC0415

        from simulation.decision_chamber.state import DirectionState  # noqa: PLC0415

        chamber_directions = [
            DirectionState(
                name=direction,
                vehicle_count=metrics["vehicle_count"],
                avg_speed_kmh=metrics["average_velocity"]
                if metrics["average_velocity"] > 0
                else None,
                instantaneous_co2_g_per_min=metrics["emissions"][
                    "instantaneous_co2_g_per_min"
                ],
                idling_vehicle_count=idling_counts[direction],
                seconds_since_green=0.0,  # chamber maintains its own timers
                has_pedestrian_demand=False,
            )
            for direction, metrics in per_direction_metrics.items()
        ]
        chamber_output = self.chamber.tick(
            tick_time=datetime.now(timezone.utc),
            directions=chamber_directions,
            detector_context={
                "vehicle_crops": vehicle_crops_by_direction,
                # Vision pedestrian detection: pass the person bboxes
                # detected in the latest YOLOv8 pass + the frame shape
                # so the detector can resolve relative crosswalk zones.
                "person_bboxes": list(self._current_persons),
                "frame_shape": (frame_height, frame_width),
            },
        )

        self.state_emitter.emit(
            {
                "sim_time_s": round(sim_time, 1),
                "step": int(sim_time * 30),  # approximate
                "mode": chamber_output.mode.value.upper(),
                "commanded_phase": chamber_output.commanded_phase,
                "source": "video",
                "video_path": str(self.config.video_path),
                "brand_classifier_enabled": self.brand_identifier.available,
                # Which brand model is producing the labels (operator console
                # shows this at the top). We report `<brand_model>:<run_name>`
                # so e.g. "trained:dvm_car_v1" tells the operator the model
                # family AND the specific run, not just "trained".
                "brand_classifier_model": (
                    f"{self.config.brand_model}:{self.config.brand_weights.parent.parent.name}"
                    if self.config.brand_weights is not None
                    else self.config.brand_model
                ),
                "per_direction": per_direction_metrics,
                # AI Decision Chamber output — operator console renders this
                # as the "decision chamber" panel.
                "decision": self.chamber.to_dict(chamber_output),
                # Scene change detector status — operator console alerts
                # if homography may be invalid (camera shifted / scene
                # changed). Phase 8 auto-recalibration trigger.
                "scene_change": {
                    "has_baseline": self._scene_change.status().has_baseline,
                    "consecutive_change_frames": self._scene_change.status().consecutive_change_frames,
                    "threshold_frames": self._scene_change.status().threshold_frames,
                    "latest_diff": round(self._scene_change.status().latest_diff, 3),
                    "alert_active": self._scene_change.status().alert_active,
                },
                # Operator console language — forwarded from the site
                # config (Bosnia pilot → "bs"). Console reads this and
                # picks the matching string table from
                # services/operator-console/src/locales.py
                "operator_locale": self.config.operator_locale,
            }
        )

    def _draw(self, frame, tracks: list[TrackedVehicle]) -> None:
        """OpenCV overlay: bbox + class + speed + per-vehicle emission +
        AI Decision Chamber HUD at top-left.

        The HUD makes the recorded video self-contained for stakeholder
        review — you can play the mp4 without also opening the operator
        console because the current chamber decision (commanded phase,
        mode, dominant factor) is overlaid on every frame.
        """
        import cv2  # noqa: PLC0415

        # -- AI Decision Chamber HUD (top-left corner) ---------------------
        last = getattr(self.chamber, "last_output", None)
        if last is not None:
            H, W = frame.shape[:2]
            # Mode → bar colour
            mode_colors = {
                "adaptive": (88, 157, 15),  # green
                "preempt": (67, 68, 219),  # red
                "fixed_time": (68, 180, 244),  # amber
                "manual": (244, 133, 66),  # blue-ish
                "flash_caution": (67, 68, 219),
            }
            bar_color = mode_colors.get(last.mode.value, (160, 160, 160))
            # Two-line HUD: phase + dominant factor
            hud_w = 480
            hud_h = 78
            # Semi-transparent black backdrop for legibility on any
            # background. cv2 doesn't do alpha directly — blend the ROI.
            roi = frame[10 : 10 + hud_h, 10 : 10 + hud_w].copy()
            overlay = roi.copy()
            overlay[:] = (24, 26, 27)  # dark backdrop
            blended = cv2.addWeighted(overlay, 0.78, roi, 0.22, 0)
            frame[10 : 10 + hud_h, 10 : 10 + hud_w] = blended

            # Left coloured stripe = mode
            cv2.rectangle(frame, (10, 10), (16, 10 + hud_h), bar_color, -1)

            # Line 1: phase (large). ASCII-only — OpenCV's
            # FONT_HERSHEY_SIMPLEX cannot render arrow / em-dash unicode,
            # they come out as "???".
            phase_label = (
                last.commanded_phase.upper().replace("_GREEN", "  >>  GREEN")
            )
            cv2.putText(
                frame, phase_label, (28, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2,
                cv2.LINE_AA,
            )
            # Line 2: mode + dominant factor (smaller, muted)
            dom = last.dominant_factor or "—"
            sub_label = f"mode: {last.mode.value}  |  dominant: {dom}"
            cv2.putText(
                frame, sub_label, (28, 64),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 200, 210), 1,
                cv2.LINE_AA,
            )
            # Tiny "AI" badge bottom-right of HUD
            cv2.putText(
                frame, "AI DECISION CHAMBER", (W - 290, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 200, 210), 1,
                cv2.LINE_AA,
            )

            # --- Virtual traffic-signal overlay (top-right) ---------------
            # Two mini 3-light signals (NS + EW) showing what the chamber
            # is commanding the controller to display. Lets the audience
            # see the AI's signal-priority decision directly on-screen —
            # without needing to also open the operator console.
            commanded_dir = (
                last.commanded_phase[: -len("_green")]
                if last.commanded_phase.endswith("_green")
                else last.commanded_phase
            )
            self._draw_virtual_signals(frame, commanded_dir, last.mode.value, W, H)

        for t in tracks:
            x1, y1, x2, y2 = (int(v) for v in t.bbox)
            est = self.estimator.estimate(t.vehicle_class, speed_kmh=t.speed_kmh, brand=t.brand)
            color = {
                "zero": (15, 157, 88),
                "low": (15, 157, 88),
                "medium": (66, 180, 244),
                "high": (0, 109, 255),
                "very_high": (68, 68, 219),
            }.get(est.impact_level, (180, 180, 180))
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            brand_tag = f" [{t.brand}]" if t.brand else ""
            # Show "-- km/h" when speed is zero (either truly stopped OR
            # rejected as an outlier above MAX_REALISTIC_SPEED_KMH). The
            # operator gets honest "unknown" rather than a fake number.
            # ASCII-only — cv2.putText with FONT_HERSHEY_SIMPLEX cannot
            # render unicode characters (em-dash renders as "???").
            speed_tag = f"{t.speed_kmh:.0f} km/h" if t.speed_kmh > 0 else "-- km/h"
            label = (
                f"#{t.track_id} {t.vehicle_class.value}{brand_tag}  "
                f"{speed_tag}  "
                f"{est.co2_g_per_km:.0f} g/km"
            )
            cv2.putText(
                frame,
                label,
                (x1, max(15, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
                cv2.LINE_AA,
            )
