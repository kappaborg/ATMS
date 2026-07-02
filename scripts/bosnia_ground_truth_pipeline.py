#!/usr/bin/env python3
"""Bosnia ground-truth labeling pipeline.

Pilot data collection plan: train dvm_car_v2_bih from operator-labelled
Sarajevo footage. The existing English-language labeler
(services/labeler/app.py) is too generic for KJP/KS shift workers; this
pipeline adds:

1. **Automated pre-labelling** — runs dvm_car_v1 on each crop to
   produce an initial guess. Operator reviews + corrects (much faster
   than blank-slate labeling).
2. **BiH fleet bias** — sorts the brand picker by Bosnia-prevalence
   (VW, Skoda, Audi top; Lamborghini/Ferrari bottom). Faster keyboard
   navigation for the brands that actually appear.
3. **Audit trail** — every label decision logged with operator user
   (from Keycloak / SSO header), crop path, predicted vs final brand,
   confidence override reason.
4. **Quality control** — every 10th crop is shown to TWO operators
   independently; agreement rate computed per session. <90% triggers
   training pause + ops review.
5. **Export to YOLO format** — `data/car_brand_dataset_bih/` ready for
   train_traffic_realistic.py with the same pipeline as dvm_car_v1.

This script is the prep + export tool; the labeling UI itself is the
existing Streamlit app extended with these BiH-specific config knobs.

Run:
    # Extract crops from a multi-hour Sarajevo recording
    python3 scripts/bosnia_ground_truth_pipeline.py extract \\
        --video recordings/sarajevo-marijindvor-001-20260914.mp4 \\
        --output data/bih-crops/

    # After operators label them via the Streamlit labeler:
    python3 scripts/bosnia_ground_truth_pipeline.py export \\
        --crops-dir data/bih-crops/ \\
        --labels data/bih-labels.json \\
        --output data/car_brand_dataset_bih/
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bosnia_gt")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Sarajevo fleet prevalence (informational ordering for the picker;
# Bosnian-language labels for KJP operators).
BIH_BRAND_ORDER = [
    # Most common in BiH passenger fleet (per BiH Federation Stats 2024):
    "volkswagen", "skoda", "audi", "opel", "ford", "renault", "peugeot",
    "citroen", "fiat", "bmw", "mercedes-benz", "dacia", "toyota",
    "hyundai", "kia", "nissan", "mazda", "honda",
    # Regional + legacy
    "zastava", "yugo", "lada",
    # Lower prevalence in BiH
    "alfa romeo", "seat", "mini", "porsche", "land rover", "jaguar",
    # Special labels
    "_other_brand", "_not_a_car", "_unsure",
]


def cmd_extract(args: argparse.Namespace) -> int:
    """Extract candidate vehicle crops from a Sarajevo recording.

    Strategy:
    - Sample frames every N seconds (default 5) — avoid back-to-back
      duplicates of the same vehicle
    - For each frame, run YOLOv8 + dvm_car_v1
    - Save crops where the brand model committed (any confidence) as
      "pre-labelled candidates"
    - Save crops where the model opted out as "needs from-scratch"
    - Track both pools so the operator gets a mix

    Output layout:
        <output>/
            crops/<id>.jpg
            metadata.json     # one entry per crop with predictions
            sample_strategy.json
    """
    import cv2  # noqa: PLC0415
    from ultralytics import YOLO  # noqa: PLC0415

    output = Path(args.output)
    (output / "crops").mkdir(parents=True, exist_ok=True)

    log.info("loading vehicle + brand models")
    yolo = YOLO("models/yolov8n.pt")
    brand_model = YOLO("models/car_brand_classification/outputs/dvm_car_v1/weights/best.pt")

    video_path = Path(args.video)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        log.error("cannot open %s", video_path)
        return 2
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    sample_every_frames = int(args.sample_seconds * fps)
    log.info("sampling every %d frames (%.1f s) from %s @ %.1f fps",
             sample_every_frames, args.sample_seconds, video_path, fps)

    metadata = []
    crop_idx = 0
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % sample_every_frames != 0:
            frame_idx += 1
            continue
        # Vehicle detection
        results = yolo.predict(frame, classes=[2, 3, 5, 7], conf=0.4, verbose=False)
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                crop = frame[y1:y2, x1:x2]
                if crop.size == 0 or (x2-x1) < args.min_bbox_px or (y2-y1) < args.min_bbox_px:
                    continue
                # Pre-label via dvm_car_v1
                b_results = brand_model.predict(crop, conf=0.10, verbose=False)
                predicted_brand = None
                predicted_conf = 0.0
                for br in b_results:
                    if len(br.boxes) > 0:
                        cls_id = int(br.boxes.cls[0].cpu().item())
                        conf = float(br.boxes.conf[0].cpu().item())
                        predicted_brand = brand_model.names[cls_id]
                        predicted_conf = conf
                        break

                crop_path = output / "crops" / f"{crop_idx:06d}.jpg"
                cv2.imwrite(str(crop_path), crop)
                metadata.append({
                    "id": f"{crop_idx:06d}",
                    "crop_path": str(crop_path.relative_to(output)),
                    "source_video": str(video_path),
                    "frame_idx": frame_idx,
                    "time_s": round(frame_idx / fps, 2),
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "predicted_brand": predicted_brand,
                    "predicted_conf": round(predicted_conf, 3),
                    "needs_review": predicted_brand is None or predicted_conf < 0.5,
                })
                crop_idx += 1
        frame_idx += 1

    cap.release()
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2))
    (output / "sample_strategy.json").write_text(json.dumps({
        "source_video": str(video_path),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "sample_seconds": args.sample_seconds,
        "min_bbox_px": args.min_bbox_px,
        "total_crops": len(metadata),
        "pre_labelled": sum(1 for m in metadata if m["predicted_brand"] is not None),
        "needs_from_scratch": sum(1 for m in metadata if m["needs_review"]),
        "bih_brand_order": BIH_BRAND_ORDER,
    }, indent=2))
    log.info("extracted %d crops to %s", len(metadata), output)
    log.info("  pre-labelled (model confident): %d",
             sum(1 for m in metadata if not m["needs_review"]))
    log.info("  needs review:                   %d",
             sum(1 for m in metadata if m["needs_review"]))
    return 0


def cmd_qc(args: argparse.Namespace) -> int:
    """Quality control: take every 10th labelled crop and verify it was
    shown to two different operators. Compute agreement rate.
    """
    labels_path = Path(args.labels)
    if not labels_path.exists():
        log.error("labels file %s not found", labels_path)
        return 2
    labels = json.loads(labels_path.read_text())

    # Expected format: list of {crop_id, operator_email, brand}
    if not isinstance(labels, list):
        log.error("labels file must be a list of {crop_id, operator_email, brand}")
        return 2

    # Group by crop_id
    by_crop: dict[str, list[dict]] = {}
    for entry in labels:
        by_crop.setdefault(entry["crop_id"], []).append(entry)

    # Find crops with 2+ labels (the QC overlap set)
    multilabel = {k: v for k, v in by_crop.items() if len(v) >= 2}
    log.info("QC pool: %d crops with 2+ independent labels", len(multilabel))

    if not multilabel:
        log.warning("no overlapping labels yet — operators haven't reached the QC threshold")
        return 0

    agree = 0
    disagree = 0
    disagreements = []
    for crop_id, entries in multilabel.items():
        brands = {e["brand"] for e in entries}
        if len(brands) == 1:
            agree += 1
        else:
            disagree += 1
            disagreements.append({"crop_id": crop_id, "brands": list(brands),
                                  "operators": [e["operator_email"] for e in entries]})

    rate = agree / (agree + disagree) if (agree + disagree) else 0.0
    log.info("agreement rate: %.1f%% (%d agree / %d disagree)",
             rate * 100, agree, disagree)

    if rate < 0.90:
        log.warning("QC THRESHOLD BREACH — agreement < 90%%")
        log.warning("Sample disagreements (first 5):")
        for d in disagreements[:5]:
            log.warning("  %s: %s", d["crop_id"], d)

    report = {
        "qc_pool_size": len(multilabel),
        "agreement_count": agree,
        "disagreement_count": disagree,
        "agreement_rate": round(rate, 3),
        "threshold_met": rate >= 0.90,
        "disagreements": disagreements,
    }
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2))
        log.info("wrote QC report -> %s", args.report)
    return 0 if rate >= 0.90 else 1


def cmd_export(args: argparse.Namespace) -> int:
    """Export labels as YOLO-format dataset for retraining."""
    crops_dir = Path(args.crops_dir)
    labels_path = Path(args.labels)
    output = Path(args.output)

    metadata = json.loads((crops_dir / "metadata.json").read_text())
    labels = json.loads(labels_path.read_text())

    # Resolve final brand per crop (majority vote if multiple labels)
    final_brands: dict[str, str] = {}
    crop_to_labels: dict[str, list[str]] = {}
    for entry in labels:
        crop_to_labels.setdefault(entry["crop_id"], []).append(entry["brand"])
    for crop_id, brand_list in crop_to_labels.items():
        # Most common (random on tie)
        counts = {b: brand_list.count(b) for b in set(brand_list)}
        winner = max(counts.items(), key=lambda kv: (kv[1], random.random()))[0]
        final_brands[crop_id] = winner

    # Skip meta-labels
    real_brand_crops = [
        m for m in metadata
        if final_brands.get(m["id"], "_unsure") not in ("_other_brand", "_not_a_car", "_unsure")
    ]

    # Build YOLO class list from observed brands (sorted alphabetically
    # for stability across exports)
    observed_brands = sorted({final_brands[m["id"]] for m in real_brand_crops})
    class_to_id = {b: i for i, b in enumerate(observed_brands)}

    # 70/20/10 train/valid/test split
    random.Random(0).shuffle(real_brand_crops)
    n = len(real_brand_crops)
    splits = {
        "train": real_brand_crops[: int(n * 0.7)],
        "valid": real_brand_crops[int(n * 0.7): int(n * 0.9)],
        "test":  real_brand_crops[int(n * 0.9):],
    }

    for split_name, items in splits.items():
        (output / split_name / "images").mkdir(parents=True, exist_ok=True)
        (output / split_name / "labels").mkdir(parents=True, exist_ok=True)
        for m in items:
            src = crops_dir / m["crop_path"]
            dst_img = output / split_name / "images" / f"{m['id']}.jpg"
            dst_lbl = output / split_name / "labels" / f"{m['id']}.txt"
            if dst_img.exists():
                dst_img.unlink()
            dst_img.symlink_to(src.resolve())
            class_id = class_to_id[final_brands[m["id"]]]
            # Whole-image bbox like dvm_car_v1 dataset
            dst_lbl.write_text(f"{class_id} 0.5 0.5 1.0 1.0\n")

    # data.yaml
    yaml_content = [
        f"# BiH ground-truth dataset for dvm_car_v2_bih retraining",
        f"# Generated: {datetime.now(timezone.utc).isoformat()}",
        f"path: {output.resolve()}",
        "train: train/images",
        "val: valid/images",
        "test: test/images",
        "",
        f"nc: {len(observed_brands)}",
        "names:",
    ]
    for b in observed_brands:
        yaml_content.append(f'  - "{b}"')
    (output / "data.yaml").write_text("\n".join(yaml_content) + "\n")
    log.info("exported %d crops across %d brands to %s",
             len(real_brand_crops), len(observed_brands), output)
    log.info("  train=%d valid=%d test=%d",
             len(splits["train"]), len(splits["valid"]), len(splits["test"]))
    log.info("next step: ATMS_DATASET_YAML=%s python3 models/car_brand_classification/train_traffic_realistic.py",
             output / "data.yaml")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="bosnia_ground_truth_pipeline.py")
    sub = p.add_subparsers(dest="command", required=True)

    ext = sub.add_parser("extract", help="extract candidate crops from a recording")
    ext.add_argument("--video", required=True)
    ext.add_argument("--output", required=True)
    ext.add_argument("--sample-seconds", type=float, default=5.0)
    ext.add_argument("--min-bbox-px", type=int, default=120)

    qc = sub.add_parser("qc", help="quality control on multi-labelled crops")
    qc.add_argument("--labels", required=True)
    qc.add_argument("--report")

    exp = sub.add_parser("export", help="export to YOLO-format dataset")
    exp.add_argument("--crops-dir", required=True)
    exp.add_argument("--labels", required=True)
    exp.add_argument("--output", required=True)

    args = p.parse_args()
    if args.command == "extract":
        return cmd_extract(args)
    if args.command == "qc":
        return cmd_qc(args)
    if args.command == "export":
        return cmd_export(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
