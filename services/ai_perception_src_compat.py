"""
Compatibility imports for scripts.

Reason: the service lives under `services/ai-perception/src/` (hyphenated path),
which is not importable as a normal Python package. This module provides a stable
import surface for experiment scripts.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


_repo_root = Path(__file__).resolve().parents[1]
_src = _repo_root / "services" / "ai-perception" / "src"
if _src.exists() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


def create_yolo_detector(*, model_path: str, device: str):
    from detection.yolo_detector import YOLODetector

    return YOLODetector(
        model_path=model_path,
        device=device,
    )

