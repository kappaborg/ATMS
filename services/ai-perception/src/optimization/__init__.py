"""
Optimization Module - Week 11 Performance Optimization
"""

from .model_quantization import ModelQuantizer, quantize_yolov8_model
from .atms_optimizer import (
    ATMSTrafficOptimizer,
    SignalOptimization,
    PedestrianSafety,
    EmergencyPriority
)

__all__ = [
    'ModelQuantizer',
    'quantize_yolov8_model',
    'ATMSTrafficOptimizer',
    'SignalOptimization',
    'PedestrianSafety',
    'EmergencyPriority'
]
