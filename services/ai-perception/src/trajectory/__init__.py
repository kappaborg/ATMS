"""
Trajectory Prediction Module for ATMS
Based on research from City-scale Vehicle Trajectory Data study
https://pmc.ncbi.nlm.nih.gov/articles/PMC10582153/

This module provides optimized trajectory prediction capabilities
for real-time traffic management systems.
"""

from .predictor import (
    TrajectoryPoint,
    TrajectoryPrediction,
    PredictionMode,
    PhysicsBasedPredictor,
    MLTrajectoryPredictor,
    HybridTrajectoryPredictor
)

__all__ = [
    'TrajectoryPoint',
    'TrajectoryPrediction', 
    'PredictionMode',
    'PhysicsBasedPredictor',
    'MLTrajectoryPredictor',
    'HybridTrajectoryPredictor'
]
