"""
Compatibility layer for the reusable trajectory predictor.

The original predictor mixed ATMS-specific logic, heavy optional ML
dependencies, and a broken OpenCV-based path. This wrapper keeps the old public
API while delegating trajectory prediction to the new portable package in
`trajectory_reuse`.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from trajectory_reuse import PredictionMode, TrajectoryPoint, TrajectoryPrediction
from trajectory_reuse import ReusableTrajectoryPredictor as _ReusableTrajectoryPredictor


class PhysicsBasedPredictor(_ReusableTrajectoryPredictor):
    """Backward-compatible alias for the improved reusable predictor."""


class MLTrajectoryPredictor(_ReusableTrajectoryPredictor):
    """
    Compatibility shim for legacy imports.

    This project never trains the old LSTM path in production, so the reusable
    predictor is used as a stable fallback while keeping the original class
    available for imports.
    """

    def __init__(
        self,
        input_size: int = 4,
        hidden_size: int = 64,
        num_layers: int = 2,
        prediction_horizon: float = 5.0,
    ) -> None:
        super().__init__(prediction_horizon=prediction_horizon)
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.is_trained = False
        self.training_samples = 0

    def add_training_data(
        self, trajectory: List[Tuple[float, float]], velocity: Tuple[float, float]
    ) -> None:
        if len(trajectory) >= 4:
            self.training_samples += 1

    def train_model(self, epochs: int = 10) -> None:
        # Preserve the old method name without pulling in PyTorch.
        self.is_trained = self.training_samples >= max(20, epochs)

    def predict(
        self,
        track_id: int,
        trajectory: List[Tuple[float, float]],
        velocity: Tuple[float, float],
        object_type: str,
    ) -> Optional[List[TrajectoryPoint]]:
        prediction = super().predict(
            track_id=track_id,
            trajectory=trajectory,
            velocity=velocity,
            object_type=object_type,
        )
        if prediction is None:
            return []

        prediction.method_used = PredictionMode.ML_ONLY
        prediction.confidence = max(0.05, min(0.9, prediction.confidence * 0.92))
        for point in prediction.predicted_points:
            point.confidence = max(0.2, min(0.9, point.confidence * 0.92))
        return prediction.predicted_points


class HybridTrajectoryPredictor(_ReusableTrajectoryPredictor):
    """Main predictor used by the current ATMS integration."""

    def __init__(
        self,
        prediction_horizon: float = 5.0,
        confidence_threshold: float = 0.7,
    ) -> None:
        super().__init__(
            prediction_horizon=prediction_horizon,
            confidence_threshold=confidence_threshold,
        )

    def predict(
        self,
        track_id: int,
        trajectory: List[Tuple[float, float]],
        velocity: Tuple[float, float],
        object_type: str,
        context: Optional[Dict] = None,
    ) -> Optional[TrajectoryPrediction]:
        return super().predict(
            track_id=track_id,
            trajectory=trajectory,
            velocity=velocity,
            object_type=object_type,
            context=context,
        )
