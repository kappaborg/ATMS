from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple


def bbox_to_center(bbox: Sequence[float]) -> Tuple[float, float]:
    """Convert an `(x1, y1, x2, y2)` box into its center point."""

    if len(bbox) < 4:
        raise ValueError("bbox must contain at least four values")

    x1, y1, x2, y2 = bbox[:4]
    return ((float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0)


def centers_from_bboxes(bboxes: Iterable[Sequence[float]]) -> List[Tuple[float, float]]:
    """Convert a bbox stream into trajectory points."""

    return [bbox_to_center(bbox) for bbox in bboxes]
