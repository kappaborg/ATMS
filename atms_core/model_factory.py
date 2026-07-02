from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Iterable, Optional, Tuple


# Ensure ai-perception src is importable from this shared module.
_repo_root = Path(__file__).resolve().parents[1]
_ai_perception_src = _repo_root / "services" / "ai-perception" / "src"
if _ai_perception_src.exists() and str(_ai_perception_src) not in sys.path:
    sys.path.insert(0, str(_ai_perception_src))


def resolve_auto_device(device_pref: str) -> str:
    """
    Auto-switch to `mps` on macOS when available, otherwise return the preference.
    """
    if platform.system() != "Darwin":
        return device_pref

    # Torch import is optional for this helper.
    try:
        import torch

        if device_pref in ("cuda", "gpu", "auto", "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        # If torch isn't available, just keep the preference.
        pass

    return device_pref


def first_existing_path(candidates: Iterable[Path]) -> Optional[Path]:
    for p in candidates:
        try:
            if p and Path(p).exists():
                return Path(p)
        except Exception:
            # If path is weird/unreadable, skip.
            continue
    return None


def create_speed_calculator(
    *,
    pixel_to_meter_ratio: float,
    fps: float,
    min_track_length: int,
    max_track_history: int,
    use_kalman: bool = True,
    use_cvm: bool = True,
    use_wls: bool = True,
):
    from calculations.speed_calculator import SpeedCalculator

    return SpeedCalculator(
        fps=fps,
        pixel_to_meter_ratio=pixel_to_meter_ratio,
        min_track_length=min_track_length,
        max_track_history=max_track_history,
        use_kalman=use_kalman,
        use_cvm=use_cvm,
        use_wls=use_wls,
    )


def create_emission_calculators() -> Tuple[object, object]:
    from emission.emission_calculator import EmissionCalculator
    from calculations.enhanced_emission_calculator import EnhancedEmissionCalculator

    return EmissionCalculator(), EnhancedEmissionCalculator()


def create_integrated_atms_system(
    *,
    intersection_id: int = 1,
    prediction_horizon: float = 5.0,
    optimization_enabled: bool = True,
):
    from trajectory_integration import IntegratedATMSSystem

    return IntegratedATMSSystem(
        intersection_id=intersection_id,
        prediction_horizon=prediction_horizon,
        optimization_enabled=optimization_enabled,
    )


def create_tracker():
    from tracking.bytetrack_simple import SimpleByteTracker

    return SimpleByteTracker()


def try_create_license_plate_processor(
    *,
    yolo_model_path: Optional[str],
    ocr_primary_method: str = "professional",
    ocr_fallback_methods: Optional[list[str]] = None,
    supported_countries: Optional[list[str]] = None,
    anonymization_level: str = "partial",
    confidence_threshold: float = 0.15,
):
    from license_plate_processor import LicensePlateProcessor

    try:
        kwargs = {
            "ocr_primary_method": ocr_primary_method,
            "ocr_fallback_methods": ocr_fallback_methods,
            "supported_countries": supported_countries,
            "anonymization_level": anonymization_level,
            "confidence_threshold": confidence_threshold,
        }
        if yolo_model_path:
            if not Path(yolo_model_path).exists():
                return None
            kwargs["yolo_model_path"] = str(yolo_model_path)
        # If yolo_model_path is None, LicensePlateProcessor uses its internal default.
        return LicensePlateProcessor(**kwargs)
    except Exception:
        return None


def try_create_brand_classifier(
    *,
    model_path: Optional[str],
    confidence_threshold: float,
    device: str,
):
    from brand.brand_classifier import BrandClassifier

    try:
        kwargs = {"confidence_threshold": confidence_threshold, "device": device}
        if model_path:
            if not Path(model_path).exists():
                return None
            kwargs["model_path"] = str(model_path)

        bc = BrandClassifier(**kwargs)
        if not bc.load_model():
            return None
        return bc
    except Exception:
        return None


def try_create_multiview_detector(
    *,
    top_model_path: Optional[str],
    side_model_path: Optional[str],
    front_model_path: Optional[str],
    confidence_threshold: float,
    iou_threshold: float,
    device: str,
    enable_fusion: bool = True,
):
    from multiview.multiview_detector import MultiViewDetector

    try:
        # If all paths are provided, validate existence. If any are missing,
        # fall back to MultiViewDetector defaults (if you pass None for all).
        if top_model_path or side_model_path or front_model_path:
            if not (top_model_path and side_model_path and front_model_path):
                return None
            if not (
                Path(top_model_path).exists()
                and Path(side_model_path).exists()
                and Path(front_model_path).exists()
            ):
                return None

            mv = MultiViewDetector(
                top_model_path=str(top_model_path),
                side_model_path=str(side_model_path),
                front_model_path=str(front_model_path),
                confidence_threshold=confidence_threshold,
                iou_threshold=iou_threshold,
                device=device,
                enable_fusion=enable_fusion,
            )
        else:
            mv = MultiViewDetector(
                confidence_threshold=confidence_threshold,
                iou_threshold=iou_threshold,
                device=device,
                enable_fusion=enable_fusion,
            )

        if not mv.load_models():
            return None
        return mv
    except Exception:
        return None


def try_create_tramway_detector(
    *,
    model_path: Optional[str],
    confidence_threshold: float,
    device: str,
):
    from tramway.tramway_detector import TramwayDetector

    try:
        kwargs = {"confidence_threshold": confidence_threshold, "device": device}
        if model_path:
            if not Path(model_path).exists():
                return None
            kwargs["model_path"] = str(model_path)

        td = TramwayDetector(**kwargs)
        if not td.load_model():
            return None
        return td
    except Exception:
        return None

