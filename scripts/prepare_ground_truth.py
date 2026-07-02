#!/usr/bin/env python3
"""Extract vehicle crops + context frames for human ground-truth labelling.

Why this exists: every model evaluation up to this point has measured "did
the model commit a brand?" — a circular metric, because we have no way to
know whether the brand it committed was correct. To get real precision /
recall numbers we need ~200 vehicles labelled by a human. This script
prepares the crops; `services/labeler/app.py` is the labelling UI;
`scripts/compute_field_metrics.py` compares model predictions to labels.

Sampling strategy:
- Walk each video at a sparse frame rate (default ~0.5 fps) so we don't
  draw 50 near-identical crops of the same slow-moving truck.
- Run YOLOv8 on each sampled frame, keep vehicle detections above
  `--min-bbox-px` on each side (default 100 — small enough to be common
  in wide-angle footage, large enough that a human can recognise the
  brand).
- Save the cropped vehicle (`crops/<id>.jpg`) plus the full frame with
  the bbox highlighted (`frames/<id>.jpg`) so the labeller can see both
  context AND detail.
- Cap per-video crop count so a single long clip can't dominate the
  ground-truth distribution.

Output layout:
    data/ground_truth/
        crops/<id>.jpg              # the cropped vehicle for labelling
        frames/<id>.jpg             # full frame with bbox highlighted (context)
        metadata.json               # crop metadata, source-frame map

Run:
    python3 scripts/prepare_ground_truth.py \\
        --videos videos/TEST.mp4 \\
                 videos/youtube_MNn9qKG2UFI_full.mp4 \\
                 videos/youtube_cJatWBDNabE_full.mp4 \\
        --max-per-video 100
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import cv2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]

# COCO vehicle classes from the off-the-shelf YOLOv8n.pt detector
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def main() -> int:
    p = argparse.ArgumentParser(prog="prepare_ground_truth.py")
    p.add_argument(
        "--videos",
        nargs="+",
        type=Path,
        required=True,
        help="one or more .mp4 source videos",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "data" / "ground_truth",
    )
    p.add_argument(
        "--sample-every-n-frames",
        type=int,
        default=60,
        help="run YOLO every Nth frame (default: 60 ~= 2s at 30 fps)",
    )
    p.add_argument(
        "--min-bbox-px",
        type=int,
        default=100,
        help="skip detections smaller than this on either side (default: 100)",
    )
    p.add_argument(
        "--max-per-video",
        type=int,
        default=100,
        help="cap crops per source video (default: 100)",
    )
    p.add_argument(
        "--yolo-weights",
        type=Path,
        default=REPO_ROOT / "models" / "yolov8n.pt",
    )
    args = p.parse_args()

    (args.out / "crops").mkdir(parents=True, exist_ok=True)
    (args.out / "frames").mkdir(parents=True, exist_ok=True)

    from ultralytics import YOLO  # noqa: PLC0415

    log.info("loading YOLOv8: %s", args.yolo_weights)
    yolo = YOLO(str(args.yolo_weights))

    # Load existing metadata if present so we can incrementally extend the
    # ground-truth set across multiple runs.
    metadata_path = args.out / "metadata.json"
    if metadata_path.exists():
        metadata: list[dict] = json.loads(metadata_path.read_text())
        log.info("loaded %d existing crops; will extend", len(metadata))
        next_id = max(int(m["id"]) for m in metadata) + 1 if metadata else 0
        existing_keys = {(m["source_video"], m["frame_idx"], tuple(m["bbox"])) for m in metadata}
    else:
        metadata = []
        next_id = 0
        existing_keys = set()

    for video_path in args.videos:
        if not video_path.exists():
            log.warning("skipping missing video: %s", video_path)
            continue
        log.info("=" * 60)
        log.info("scanning %s", video_path)

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            log.warning("could not open %s", video_path)
            continue

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n_frames_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        per_video_count = 0
        frame_idx = 0

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx % args.sample_every_n_frames != 0:
                frame_idx += 1
                continue

            results = yolo.predict(frame, conf=0.30, verbose=False)
            for r in results:
                if r.boxes is None:
                    continue
                for i in range(len(r.boxes)):
                    cls_id = int(r.boxes.cls[i].item())
                    if cls_id not in VEHICLE_CLASSES:
                        continue
                    yolo_conf = float(r.boxes.conf[i].item())
                    x1, y1, x2, y2 = (
                        r.boxes.xyxy[i].cpu().numpy().astype(int).tolist()
                    )
                    w, h = x2 - x1, y2 - y1
                    if w < args.min_bbox_px or h < args.min_bbox_px:
                        continue

                    bbox_key = (str(video_path), frame_idx, (x1, y1, x2, y2))
                    if bbox_key in existing_keys:
                        continue

                    # Pad the crop a touch so we see brand logo + grille area
                    H, W = frame.shape[:2]
                    pad = int(0.08 * max(w, h))
                    cx1 = max(0, x1 - pad)
                    cy1 = max(0, y1 - pad)
                    cx2 = min(W, x2 + pad)
                    cy2 = min(H, y2 + pad)
                    crop = frame[cy1:cy2, cx1:cx2]
                    if crop.size == 0:
                        continue

                    # Annotated frame: original + bright bbox so the labeller
                    # can see vehicle-in-context
                    frame_annotated = frame.copy()
                    cv2.rectangle(
                        frame_annotated,
                        (x1, y1),
                        (x2, y2),
                        (0, 255, 0),
                        3,
                    )

                    crop_id = f"{next_id:05d}"
                    crop_path = args.out / "crops" / f"{crop_id}.jpg"
                    frame_path = args.out / "frames" / f"{crop_id}.jpg"
                    cv2.imwrite(str(crop_path), crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    cv2.imwrite(str(frame_path), frame_annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])

                    metadata.append(
                        {
                            "id": crop_id,
                            "source_video": str(video_path),
                            "frame_idx": frame_idx,
                            "time_in_video_s": round(frame_idx / fps, 2),
                            "bbox": [x1, y1, x2, y2],
                            "bbox_size_px": [w, h],
                            "vehicle_class": VEHICLE_CLASSES[cls_id],
                            "yolo_conf": round(yolo_conf, 3),
                            "added_at": datetime.now().isoformat(timespec="seconds"),
                        }
                    )
                    existing_keys.add(bbox_key)
                    next_id += 1
                    per_video_count += 1

                    if per_video_count >= args.max_per_video:
                        break
                if per_video_count >= args.max_per_video:
                    break
            if per_video_count >= args.max_per_video:
                break

            frame_idx += 1

        cap.release()
        log.info(
            "  %s: scanned %d frames, saved %d crops",
            video_path.name,
            min(frame_idx, n_frames_total),
            per_video_count,
        )

    metadata_path.write_text(json.dumps(metadata, indent=2))
    log.info("wrote %d total crops -> %s", len(metadata), metadata_path)
    log.info(
        "\nNext step:\n"
        "  cd /Users/kappasutra/Traffic && \\\n"
        "  streamlit run services/labeler/app.py"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
