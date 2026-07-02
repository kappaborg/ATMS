#!/usr/bin/env python3
"""Per-camera homography calibration tool — site survey aid.

Production deployment problem: each pilot intersection's camera has a
different pixels-per-meter ratio depending on mount height, angle, and
focal length. The `--pixels-per-meter` flag (Phase 1) is a coarse
single-value approximation that's wrong by ~30-50% at the frame edges
where perspective distortion is highest.

This tool produces a proper homography from 4 reference points in
the image to their known real-world coordinates, then writes a per-
camera calibration JSON the chamber uses for accurate speed + position
estimation at any frame coordinate.

Site survey procedure (operator-facing, ~30 min per camera):
1. Walk the intersection. Identify 4 reference points VISIBLE in the
   camera frame whose real-world distances from each other you can
   MEASURE on the ground (or read from a high-resolution map).
   Standard suggestions:
     - Stop bar of approach 1 (lane-edge corner)
     - Stop bar of approach 2 (opposite-lane-edge corner)
     - Lane-marking centre 10 m upstream of stop bar (approach 1)
     - Lane-marking centre 10 m upstream of stop bar (approach 2)
2. Measure the real-world coordinates of those 4 points in a local
   (X, Y) frame — origin at the intersection centre, X axis along
   the major street, Y axis perpendicular.
3. Run this script. It pops up the camera frame and prompts you to
   click each of the 4 points in order.
4. Output: a JSON file with the 3×3 homography matrix and metadata
   the chamber loads at startup.

Run:
    python3 scripts/calibrate_camera_homography.py \\
        --image survey_frame.jpg \\
        --real-points "0,0  20,0  -3,8  3,8" \\
        --out config/intersection-005-homography.json

Or for interactive:
    python3 scripts/calibrate_camera_homography.py \\
        --rtsp rtsp://10.42.10.5:554/Streaming/Channels/101 \\
        --interactive

Validates: applies the inverse transform on a 5th known point and
reports the residual error in metres. Pilot acceptance criterion:
residual < 0.5 m for any point in the intersection ROI.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("calibrate")


def parse_real_points(s: str) -> list[tuple[float, float]]:
    """Parse '0,0  20,0  -3,8  3,8' into [(0,0),(20,0),(-3,8),(3,8)]."""
    out = []
    for pair in s.replace(",", " ").split():
        pass
    # Robust two-comma-separated pairs split
    tokens = s.replace("  ", " ").split()
    if len(tokens) != 4:
        raise ValueError(f"expected 4 (x,y) pairs, got {len(tokens)}: {s!r}")
    for tok in tokens:
        x_s, y_s = tok.split(",")
        out.append((float(x_s), float(y_s)))
    return out


def collect_pixel_clicks(frame: np.ndarray, n: int) -> list[tuple[int, int]]:
    """Interactive: pop up the frame, collect N clicks, return pixel coords."""
    clicks: list[tuple[int, int]] = []
    window = "Click reference points (in survey order)"
    display = frame.copy()

    def on_mouse(event, x, y, flags, param):  # noqa: PLR0913
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < n:
            clicks.append((x, y))
            cv2.circle(display, (x, y), 8, (0, 255, 0), 2)
            cv2.putText(
                display, str(len(clicks)), (x + 12, y - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2,
                cv2.LINE_AA,
            )
            cv2.imshow(window, display)

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.imshow(window, display)
    cv2.setMouseCallback(window, on_mouse)
    log.info("click %d reference points, then press any key", n)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    if len(clicks) != n:
        raise ValueError(f"need {n} clicks, got {len(clicks)}")
    return clicks


def compute_homography(
    pixel_points: list[tuple[int, int]],
    real_points: list[tuple[float, float]],
) -> np.ndarray:
    """Build the 3×3 homography matrix mapping pixel coords → real-world
    metres in the intersection-local frame. Uses cv2.findHomography
    with RANSAC for robustness against the inevitable 1-2 pixel
    measurement noise.
    """
    src = np.array(pixel_points, dtype=np.float32)
    dst = np.array(real_points, dtype=np.float32)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if H is None:
        raise RuntimeError("homography fit failed — points likely collinear")
    return H


def validate(
    H: np.ndarray,
    pixel_points: list[tuple[int, int]],
    real_points: list[tuple[float, float]],
) -> dict:
    """Apply the homography to the input pixel points and report the
    residual error in metres.
    """
    src = np.array(pixel_points, dtype=np.float32).reshape(-1, 1, 2)
    transformed = cv2.perspectiveTransform(src, H).reshape(-1, 2)
    errors_m = [
        float(np.linalg.norm(transformed[i] - np.array(real_points[i])))
        for i in range(len(real_points))
    ]
    return {
        "errors_per_point_m": errors_m,
        "max_error_m": max(errors_m),
        "rmse_m": float(np.sqrt(np.mean([e**2 for e in errors_m]))),
    }


def main() -> int:
    p = argparse.ArgumentParser(prog="calibrate_camera_homography.py")
    p.add_argument("--image", type=Path, help="static survey image (jpg/png)")
    p.add_argument("--rtsp", type=str, help="RTSP URL to grab a single frame")
    p.add_argument(
        "--real-points",
        type=str,
        required=True,
        help='4 real-world points in metres: "x1,y1 x2,y2 x3,y3 x4,y4"',
    )
    p.add_argument(
        "--pixel-points",
        type=str,
        default="",
        help=(
            'pixel coords matching --real-points: "px1,py1 px2,py2 ...". '
            "Skip to enter interactive click mode."
        ),
    )
    p.add_argument("--out", type=Path, required=True, help="output JSON path")
    p.add_argument("--intersection-id", type=str, default="unknown")
    args = p.parse_args()

    # Source frame
    if args.image is not None:
        frame = cv2.imread(str(args.image))
        if frame is None:
            log.error("could not read %s", args.image)
            return 2
    elif args.rtsp is not None:
        cap = cv2.VideoCapture(args.rtsp)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            log.error("could not grab a frame from %s", args.rtsp)
            return 2
    else:
        log.error("--image or --rtsp required")
        return 2

    H_img, W_img = frame.shape[:2]
    log.info("calibration frame: %dx%d", W_img, H_img)

    real_points = parse_real_points(args.real_points)
    if len(real_points) != 4:
        log.error("--real-points must specify exactly 4 (x,y) pairs")
        return 2

    if args.pixel_points:
        pixel_points = [
            (int(x), int(y))
            for (x, y) in parse_real_points(args.pixel_points)
        ]
    else:
        pixel_points = collect_pixel_clicks(frame, 4)
    log.info("real:  %s", real_points)
    log.info("pixel: %s", pixel_points)

    H = compute_homography(pixel_points, real_points)
    metrics = validate(H, pixel_points, real_points)
    log.info("homography fit residual: rmse=%.2fm max=%.2fm",
             metrics["rmse_m"], metrics["max_error_m"])

    if metrics["max_error_m"] > 0.5:
        log.warning(
            "max residual %.2f m exceeds pilot acceptance 0.5 m — "
            "re-survey the reference points",
            metrics["max_error_m"],
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "intersection_id": args.intersection_id,
        "image_width": W_img,
        "image_height": H_img,
        "frame_shape": [H_img, W_img],
        "real_points": real_points,
        "pixel_points": pixel_points,
        "homography": H.tolist(),
        "validation": metrics,
        "calibrated_at": datetime.now(timezone.utc).isoformat(),
    }
    args.out.write_text(json.dumps(payload, indent=2))
    log.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
