"""
ATMS configuration (research-ready).

Goal: make run behavior explicit and reproducible across services/scripts.

Run modes:
- deployment: allow Kafka/online integrations when available
- experiment: force offline behavior (disable Kafka by default) for repeatable runs
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple


class ATMSRunMode(str, Enum):
    DEPLOYMENT = "deployment"
    EXPERIMENT = "experiment"


def _env_bool(name: str, default: bool) -> bool:
    """Parse common boolean values from env vars."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _validate_detection_thresholds(d: DetectionThresholds) -> Tuple[DetectionThresholds, List[str]]:
    """
    Phase 2.3: basic validation with clamping (safe-by-default).

    We clamp instead of raising to avoid crashing long experiment runs due to
    a single bad env var. All clamps are surfaced via warnings.
    """
    warnings: List[str] = []

    vehicle_base_conf = float(d.vehicle_base_conf)
    pedestrian_base_conf = float(d.pedestrian_base_conf)
    other_base_conf = float(d.other_base_conf)

    # Confidences must be in [0, 1].
    vc2 = _clamp(vehicle_base_conf, 0.0, 1.0)
    if vc2 != vehicle_base_conf:
        warnings.append(f"vehicle_base_conf clamped {vehicle_base_conf} -> {vc2}")

    pc2 = _clamp(pedestrian_base_conf, 0.0, 1.0)
    if pc2 != pedestrian_base_conf:
        warnings.append(f"pedestrian_base_conf clamped {pedestrian_base_conf} -> {pc2}")

    oc2 = _clamp(other_base_conf, 0.0, 1.0)
    if oc2 != other_base_conf:
        warnings.append(f"other_base_conf clamped {other_base_conf} -> {oc2}")

    # Relative size thresholds must be in (0, 1]. Medium must be <= large.
    large_rel = float(d.large_relative_size_threshold)
    medium_rel = float(d.medium_relative_size_threshold)
    lr2 = _clamp(large_rel, 1e-6, 1.0)
    if lr2 != large_rel:
        warnings.append(f"large_relative_size_threshold clamped {large_rel} -> {lr2}")
    mr2 = _clamp(medium_rel, 1e-6, lr2)
    if mr2 != medium_rel:
        warnings.append(f"medium_relative_size_threshold clamped {medium_rel} -> {mr2}")

    # Multipliers should be positive and not insane.
    # Keep a conservative cap so thresholds don't blow up.
    large_mult = float(d.large_size_multiplier)
    medium_mult = float(d.medium_size_multiplier)
    far_mult = float(d.far_size_multiplier)
    lmul2 = _clamp(large_mult, 0.05, 2.0)
    if lmul2 != large_mult:
        warnings.append(f"large_size_multiplier clamped {large_mult} -> {lmul2}")
    mmul2 = _clamp(medium_mult, 0.05, 2.0)
    if mmul2 != medium_mult:
        warnings.append(f"medium_size_multiplier clamped {medium_mult} -> {mmul2}")
    fmul2 = _clamp(far_mult, 0.05, 2.0)
    if fmul2 != far_mult:
        warnings.append(f"far_size_multiplier clamped {far_mult} -> {fmul2}")

    # Optional sanity: enforce non-increasing multipliers with distance (large >= medium >= far).
    # If violated, we clamp downward to maintain monotonicity.
    if mmul2 > lmul2:
        warnings.append(
            f"medium_size_multiplier > large_size_multiplier ({mmul2} > {lmul2}); clamping medium -> {lmul2}"
        )
        mmul2 = lmul2
    if fmul2 > mmul2:
        warnings.append(
            f"far_size_multiplier > medium_size_multiplier ({fmul2} > {mmul2}); clamping far -> {mmul2}"
        )
        fmul2 = mmul2

    validated = DetectionThresholds(
        vehicle_base_conf=vc2,
        pedestrian_base_conf=pc2,
        other_base_conf=oc2,
        large_relative_size_threshold=lr2,
        medium_relative_size_threshold=mr2,
        large_size_multiplier=lmul2,
        medium_size_multiplier=mmul2,
        far_size_multiplier=fmul2,
    )
    return validated, warnings


@dataclass(frozen=True)
class DetectionThresholds:
    """
    Global detection / filtering knobs.

    Phase 2.1: moved the most important magic numbers here so that
    experiments are reproducible across scripts/services.
    """

    # Base confidences (used by distance-aware filtering & post-processing).
    vehicle_base_conf: float = 0.42
    pedestrian_base_conf: float = 0.51
    other_base_conf: float = 0.50

    # Relative bbox size thresholds (fraction of frame area).
    large_relative_size_threshold: float = 0.02
    medium_relative_size_threshold: float = 0.005

    # Size multipliers for distance-aware thresholds.
    large_size_multiplier: float = 1.0
    medium_size_multiplier: float = 0.9
    far_size_multiplier: float = 0.8


def _build_detection_thresholds() -> DetectionThresholds:
    """
    Allow overriding the most important thresholds via env for quick experiments.
    """
    raw = DetectionThresholds(
        vehicle_base_conf=_env_float("ATMS_VEHICLE_BASE_CONF", 0.42),
        pedestrian_base_conf=_env_float("ATMS_PEDESTRIAN_BASE_CONF", 0.51),
        other_base_conf=_env_float("ATMS_OTHER_BASE_CONF", 0.50),
        large_relative_size_threshold=_env_float("ATMS_LARGE_SIZE_REL", 0.02),
        medium_relative_size_threshold=_env_float("ATMS_MEDIUM_SIZE_REL", 0.005),
        large_size_multiplier=_env_float("ATMS_LARGE_SIZE_MULT", 1.0),
        medium_size_multiplier=_env_float("ATMS_MEDIUM_SIZE_MULT", 0.9),
        far_size_multiplier=_env_float("ATMS_FAR_SIZE_MULT", 0.8),
    )
    validated, warnings = _validate_detection_thresholds(raw)
    for w in warnings:
        # Keep it stdout/stderr friendly (services will capture logs).
        print(f"[atms_config] WARNING: {w}")
    return validated


@dataclass(frozen=True)
class ATMSRuntimeConfig:
    run_mode: ATMSRunMode
    enable_kafka: bool

    # Output directory for experiment artifacts (logs/CSVs/figures).
    experiment_output_dir: str

    # Phase 2.1: central detection thresholds.
    detection: DetectionThresholds


def get_atms_runtime_config() -> ATMSRuntimeConfig:
    """
    Central source of truth for run behavior.
    """
    run_mode_raw = os.getenv("ATMS_RUN_MODE", ATMSRunMode.DEPLOYMENT.value).strip().lower()
    run_mode: ATMSRunMode
    if run_mode_raw == ATMSRunMode.EXPERIMENT.value:
        run_mode = ATMSRunMode.EXPERIMENT
    else:
        run_mode = ATMSRunMode.DEPLOYMENT

    # Even in deployment, you can force-disable Kafka to run locally.
    enable_kafka_env_default = True
    enable_kafka_env = _env_bool("ATMS_ENABLE_KAFKA", enable_kafka_env_default)

    # In experiment mode we force Kafka off for repeatability, unless explicitly enabled.
    if run_mode == ATMSRunMode.EXPERIMENT:
        enable_kafka = enable_kafka_env and _env_bool("ATMS_ALLOW_KAFKA_IN_EXPERIMENT", False)
    else:
        enable_kafka = enable_kafka_env

    experiment_output_dir = os.getenv(
        "ATMS_EXPERIMENT_OUTPUT_DIR",
        os.path.join(os.getcwd(), "experiments_out"),
    )

    return ATMSRuntimeConfig(
        run_mode=run_mode,
        enable_kafka=enable_kafka,
        experiment_output_dir=experiment_output_dir,
        detection=_build_detection_thresholds(),
    )

