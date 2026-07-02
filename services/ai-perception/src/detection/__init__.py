"""Detection Module"""
from .yolo_detector import YOLODetector
from .model_optimizer import ModelOptimizer, create_optimization_report

__all__ = ["YOLODetector", "ModelOptimizer", "create_optimization_report"]

