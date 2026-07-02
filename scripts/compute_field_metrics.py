#!/usr/bin/env python3
"""Compare a brand-detector model's predictions against human ground-truth labels.

Workflow:
1. `scripts/prepare_ground_truth.py`     — extract crops
2. `services/labeler/app.py` (streamlit) — human labels each crop
3. `scripts/compute_field_metrics.py`   — runs the model on every labelled
                                          crop and outputs:
   - overall precision / recall / F1
   - per-brand precision / recall
   - confusion summary (top mistakes)
   - per-model JSON + Markdown report

Why precision and recall both matter:
- precision = of the brand commits, how many were correct?
- recall    = of the labelled vehicles, how many got identified?
The brand pipeline opt-out via `brand_conf_threshold` trades recall for
precision; this script makes that trade visible.

Run:
    # Default: use the current pipeline default weights + conf threshold
    python3 scripts/compute_field_metrics.py

    # Compare a specific model
    python3 scripts/compute_field_metrics.py \\
        --weights models/car_brand_classification/outputs/dvm_car_v2/weights/best.pt \\
        --conf 0.20
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

import cv2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
GT_DIR = REPO_ROOT / "data" / "ground_truth"

# Labels in this set mean "the labeller said this isn't really a labelled
# branded vehicle" — we count them separately rather than as ground-truth
# brand decisions. _other_brand is its own category (a real brand we can't
# train against), and the metrics report flags it.
META_LABELS = {"_other_brand", "_not_a_car", "_unsure"}


def main() -> int:
    p = argparse.ArgumentParser(prog="compute_field_metrics.py")
    p.add_argument(
        "--weights",
        type=Path,
        default=None,
        help="brand-detector weights (default: current VideoConfig.brand_weights)",
    )
    p.add_argument(
        "--conf",
        type=float,
        default=None,
        help="brand confidence threshold (default: current VideoConfig.brand_conf_threshold)",
    )
    p.add_argument(
        "--out-tag",
        type=str,
        default=None,
        help="filename suffix for the report (default: derived from weights dir)",
    )
    args = p.parse_args()

    metadata_path = GT_DIR / "metadata.json"
    labels_path = GT_DIR / "labels.json"
    if not metadata_path.exists() or not labels_path.exists():
        log.error(
            "ground truth not present. Run prepare_ground_truth.py + the labeller first."
        )
        return 2

    metadata = json.loads(metadata_path.read_text())
    labels = json.loads(labels_path.read_text())

    if not labels:
        log.error("no labels yet — open the streamlit labeller and label some crops first.")
        return 2

    # Resolve the model + conf threshold against the live pipeline defaults so
    # this script reflects what the production pipeline actually uses unless
    # the user overrides.
    sys.path.insert(0, str(REPO_ROOT))
    from simulation.demo.video_source import (  # noqa: PLC0415
        BRAND_LABEL_NORMALISATION,
        VideoConfig,
        normalise_brand,
    )

    cfg = VideoConfig(video_path="x")
    weights = args.weights or cfg.brand_weights
    conf = args.conf if args.conf is not None else cfg.brand_conf_threshold
    if weights is None or not Path(weights).exists():
        log.error("weights file not found: %s", weights)
        return 2
    log.info("evaluating %s @ conf >= %.2f", weights, conf)

    from ultralytics import YOLO  # noqa: PLC0415

    model = YOLO(str(weights))

    # --- Run the model on every labelled crop -----------------------------
    md_by_id = {m["id"]: m for m in metadata}
    crops_to_eval = [cid for cid in labels if cid in md_by_id]
    log.info("evaluating %d labelled crops", len(crops_to_eval))

    predictions: dict[str, dict] = {}
    for cid in crops_to_eval:
        crop_path = GT_DIR / "crops" / f"{cid}.jpg"
        if not crop_path.exists():
            continue
        img = cv2.imread(str(crop_path))
        if img is None:
            continue
        res = model.predict(img, conf=conf, verbose=False)
        best: tuple[str, float] | None = None
        for r in res:
            boxes = getattr(r, "boxes", None)
            if boxes is None:
                continue
            names = model.names
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i].item())
                raw_label = names.get(cls_id, "")
                canonical = normalise_brand(raw_label)
                c = float(boxes.conf[i].item())
                if canonical is None:
                    continue
                if best is None or c > best[1]:
                    best = (canonical, c)
        predictions[cid] = {
            "brand": best[0] if best else None,
            "conf": round(best[1], 3) if best else None,
        }

    # --- Score ------------------------------------------------------------
    # For each labelled crop, compare prediction to label.
    # Buckets:
    #  - tp: model committed a brand AND label is a real brand AND they match
    #  - fp: model committed a brand AND (label is _not_a_car OR label is a
    #        different real brand)
    #  - fn: label is a real brand AND model committed nothing
    #  - tn: label is _not_a_car AND model committed nothing
    #  - skipped: label is _unsure or _other_brand (excluded from the headline
    #             metric because they're not in the model's class set)
    per_brand_tp: Counter = Counter()
    per_brand_fn: Counter = Counter()
    per_brand_fp: Counter = Counter()
    confusion: Counter = Counter()  # (label, prediction) pairs for FP/FN

    tp = fp = fn = tn = skipped = 0

    for cid in crops_to_eval:
        label = labels[cid]["brand"]
        pred = predictions.get(cid, {}).get("brand")

        if label == "_unsure" or label == "_other_brand":
            skipped += 1
            continue

        if label == "_not_a_car":
            if pred is None:
                tn += 1
            else:
                fp += 1
                confusion[(label, pred)] += 1
            continue

        # label is a real brand
        if pred is None:
            fn += 1
            per_brand_fn[label] += 1
            confusion[(label, "(no commit)")] += 1
        elif pred == label:
            tp += 1
            per_brand_tp[label] += 1
        else:
            fp += 1
            # FP is bookkept against the *predicted* brand (we incorrectly
            # said "this is X"), and FN against the *true* brand (we missed
            # an X). Earlier version mistakenly bumped fp[label] which made
            # the per-brand "Predicted" column misleading.
            per_brand_fp[pred] += 1
            per_brand_fn[label] += 1
            confusion[(label, pred)] += 1

    # Overall
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)

    # Per-brand precision/recall
    per_brand_stats = []
    for brand in sorted(set(per_brand_tp) | set(per_brand_fn) | set(per_brand_fp)):
        b_tp = per_brand_tp[brand]
        b_fn = per_brand_fn[brand]
        b_fp = per_brand_fp[brand]
        b_prec = b_tp / max(b_tp + b_fp, 1)
        b_rec = b_tp / max(b_tp + b_fn, 1)
        per_brand_stats.append(
            {
                "brand": brand,
                "labelled": b_tp + b_fn,
                "predictions": b_tp + b_fp,
                "correct": b_tp,
                "precision": round(b_prec, 3),
                "recall": round(b_rec, 3),
            }
        )

    # --- Report -----------------------------------------------------------
    weights_tag = args.out_tag or Path(weights).parent.parent.name
    report = {
        "weights": str(weights),
        "conf_threshold": conf,
        "total_labelled": len(crops_to_eval),
        "skipped_unsure_or_other_brand": skipped,
        "overall": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "true_negative": tn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        },
        "per_brand": per_brand_stats,
        "top_confusions": [
            {"label": lbl, "predicted": pr, "count": n}
            for (lbl, pr), n in confusion.most_common(15)
        ],
    }

    json_path = GT_DIR / f"metrics_{weights_tag}.json"
    md_path = GT_DIR / f"metrics_{weights_tag}.md"
    json_path.write_text(json.dumps(report, indent=2))

    # Markdown
    md = [
        f"# Field metrics — {weights_tag}",
        "",
        f"- Weights: `{weights}`",
        f"- Conf threshold: **{conf}**",
        f"- Labelled crops evaluated: **{len(crops_to_eval)}** "
        f"(skipped {skipped} _unsure/_other_brand)",
        "",
        "## Overall",
        "",
        f"- **Precision: {precision:.1%}**",
        f"- **Recall: {recall:.1%}**",
        f"- F1: {f1:.3f}",
        f"- TP {tp} / FP {fp} / FN {fn} / TN {tn}",
        "",
        "## Per-brand",
        "",
        "| Brand | Labelled | Predicted | Correct | Precision | Recall |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for s in per_brand_stats:
        md.append(
            f"| {s['brand']} | {s['labelled']} | {s['predictions']} | "
            f"{s['correct']} | {s['precision']:.2f} | {s['recall']:.2f} |"
        )
    md.append("")
    md.append("## Top confusions (mismatches)")
    md.append("")
    md.append("| Label | Predicted | Count |")
    md.append("|---|---|---:|")
    for c in report["top_confusions"]:
        md.append(f"| {c['label']} | {c['predicted']} | {c['count']} |")
    md_path.write_text("\n".join(md))

    log.info("wrote %s + %s", md_path, json_path)
    print("\n".join(md[:20]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
