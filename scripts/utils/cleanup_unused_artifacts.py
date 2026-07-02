#!/usr/bin/env python3
import os
import sys
from pathlib import Path
import argparse

CANDIDATE_PATTERNS = [
    # YOLO training visualizations
    "train_batch*.jpg",
    "val_batch*_labels.jpg",
    "val_batch*_pred.jpg",
    "labels.jpg",
    "results.png",
    "Box*_curve.png",
    "confusion_matrix*.png",
    # Large cached datasets or zips in model dirs (keep Roboflow downloaded set)
]

SEARCH_ROOTS = [
    "/Users/kappasutra/Traffic/models",
    "/Users/kappasutra/Traffic/multiview_models",
]

# Keep essential weight formats
ESSENTIAL_NAMES = {"best.pt", "best.onnx", "best.mlpackage", "last.pt"}


def find_candidates():
    files = []
    for root in SEARCH_ROOTS:
        for base, dirs, filenames in os.walk(root):
            p = Path(base)
            # skip venvs
            if "venv" in p.parts:
                continue
            # collect pattern matches
            for pattern in CANDIDATE_PATTERNS:
                files.extend([str(fp) for fp in p.glob(pattern)])
            # nonessential epoch checkpoints (keep epochN.pt? => remove epoch*.pt)
            for fp in p.glob("epoch*.pt"):
                files.append(str(fp))
            # keep essential weights; do not remove
    # de-duplicate
    files = sorted(set(files))
    # filter out essential names just in case
    files = [f for f in files if Path(f).name not in ESSENTIAL_NAMES]
    return files


def main():
    ap = argparse.ArgumentParser(description="Safe cleanup for nonessential training artifacts")
    ap.add_argument("--dry-run", action="store_true", help="List files without deleting")
    ap.add_argument("--yes", action="store_true", help="Confirm deletion")
    args = ap.parse_args()

    candidates = find_candidates()
    if not candidates:
        print("No cleanup candidates found.")
        return 0

    print(f"Found {len(candidates)} nonessential artifact(s):")
    for f in candidates:
        print(f"  {f}")

    if args.dry_run:
        print("\nDry-run complete. No files deleted.")
        return 0

    if not args.yes:
        print("\nAdd --yes to confirm deletion or use --dry-run to preview.")
        return 1

    # delete
    deleted = 0
    for f in candidates:
        try:
            Path(f).unlink(missing_ok=True)
            deleted += 1
        except Exception as e:
            print(f"Failed to delete {f}: {e}")
    print(f"Deleted {deleted} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
