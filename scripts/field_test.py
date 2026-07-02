#!/usr/bin/env python3
"""Cumulative field-test instrument for the brand-perception pipeline.

The default `/tmp/atms-demo-state.json` is a *snapshot* of currently-active
tracks. Short-lived vehicles that pass through during the video are pruned
before the snapshot — making the snapshot useless for "did the model
identify N% of the vehicles in this clip?". This script instruments the
pipeline to capture every brand commit and every observation across the
whole run.

Output: a Markdown + JSON summary of cumulative brand activity.

Run:
    python3 scripts/field_test.py <video.mp4>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("field_test")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    p = argparse.ArgumentParser(prog="field_test.py")
    p.add_argument("video", type=Path)
    p.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "models" / "car_brand_classification" / "outputs" / "field_test",
    )
    p.add_argument(
        "--min-bbox",
        type=int,
        default=None,
        help="override VideoConfig.brand_min_bbox_px (default uses VideoConfig=40); "
        "lower to ~25 for wide-angle traffic footage",
    )
    p.add_argument(
        "--classify-every",
        type=int,
        default=None,
        help="override VideoConfig.brand_classify_every_n_frames (default 60 = 2s); "
        "lower to ~30 for fast-moving wide-angle traffic",
    )
    p.add_argument(
        "--brand-conf",
        type=float,
        default=None,
        help="override brand_conf_threshold (default 0.20)",
    )
    args = p.parse_args()

    if not args.video.exists():
        log.error("video not found: %s", args.video)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)

    from simulation.demo.video_source import (  # noqa: PLC0415
        VideoConfig,
        VideoEmissionPipeline,
    )

    # Instrument: we wrap the pipeline's per-frame loop to harvest tracks
    # *before* expiration. The pipeline already calls `_classify_track_brands`
    # which updates t.brand_observations + t.brand/t.brand_confidence; we just
    # snapshot the tracker after each step.
    cfg_overrides: dict = {}
    if args.min_bbox is not None:
        cfg_overrides["brand_min_bbox_px"] = args.min_bbox
    if args.classify_every is not None:
        cfg_overrides["brand_classify_every_n_frames"] = args.classify_every
    if args.brand_conf is not None:
        cfg_overrides["brand_conf_threshold"] = args.brand_conf

    cfg = VideoConfig(video_path=args.video, **cfg_overrides)
    log.info(
        "config: min_bbox=%d classify_every=%d conf=%.2f",
        cfg.brand_min_bbox_px,
        cfg.brand_classify_every_n_frames,
        cfg.brand_conf_threshold,
    )
    pipeline = VideoEmissionPipeline(cfg)

    seen_track_ids: set[int] = set()
    track_first_seen: dict[int, dict] = {}  # id -> {direction, observations, final_brand, final_conf}

    original_loop = pipeline.run

    # Patch the IoUTracker.step return path so we can read live track state.
    # We piggy-back on VideoEmissionPipeline._emit_state (called every N
    # frames) by wrapping it.
    original_emit = pipeline._emit_state

    def emit_with_audit(*pargs, **pkwargs):
        # Sweep every live track BEFORE the state file is written.
        tracker = getattr(pipeline, "tracker", None) or getattr(pipeline, "_tracker", None)
        tracks_dict = getattr(tracker, "_tracks", None) if tracker else None
        if tracks_dict is None:
            return original_emit(*pargs, **pkwargs)
        for tid, t in tracks_dict.items():
            if tid not in seen_track_ids:
                seen_track_ids.add(tid)
                # direction may not be assigned yet — get when it stabilises
            entry = track_first_seen.setdefault(
                tid,
                {
                    "direction": None,
                    "observations": list(t.brand_observations),
                    "final_brand": None,
                    "final_conf": 0.0,
                    "frames_alive": 0,
                },
            )
            entry["observations"] = list(t.brand_observations)
            entry["final_brand"] = t.brand
            entry["final_conf"] = t.brand_confidence
            entry["frames_alive"] += 1
            # Direction: only assigned by the pipeline after movement; read
            # whatever it's currently classified as.
            direction = getattr(t, "current_direction", None)
            if direction:
                entry["direction"] = direction
        return original_emit(*pargs, **pkwargs)

    pipeline._emit_state = emit_with_audit

    log.info("running pipeline on %s ...", args.video)
    t0 = time.monotonic()
    pipeline.run()
    elapsed = time.monotonic() - t0
    log.info("pipeline finished in %.1fs", elapsed)

    # -------------------------------------------------------------
    # Aggregate cumulative stats
    # -------------------------------------------------------------
    total_tracks = len(track_first_seen)
    branded = [e for e in track_first_seen.values() if e["final_brand"]]
    unbranded = total_tracks - len(branded)

    brand_counts: Counter = Counter(e["final_brand"] for e in branded)
    brand_confidences: dict[str, list[float]] = defaultdict(list)
    for e in branded:
        brand_confidences[e["final_brand"]].append(e["final_conf"])

    obs_with_any_signal = sum(1 for e in track_first_seen.values() if e["observations"])
    avg_obs_per_track = (
        mean(len(e["observations"]) for e in track_first_seen.values() if e["observations"])
        if obs_with_any_signal
        else 0
    )

    # -------------------------------------------------------------
    # Report
    # -------------------------------------------------------------
    md_lines = [
        f"# Field test — {args.video.name}",
        "",
        f"- Wall-clock: **{elapsed:.1f}s** to process **{cfg.video_path}**",
        f"- Total tracks observed: **{total_tracks}**",
        f"- Tracks that received any brand inference: **{obs_with_any_signal}** "
        f"({100 * obs_with_any_signal / max(total_tracks, 1):.0f}%)",
        f"- Tracks with a *committed* brand: **{len(branded)}** "
        f"({100 * len(branded) / max(total_tracks, 1):.0f}%)",
        f"- Avg classification attempts per inferred track: **{avg_obs_per_track:.1f}**",
        "",
        "## Brand commits",
        "",
        "| Brand | Count | Mean confidence |",
        "|---|---:|---:|",
    ]
    for brand, n in brand_counts.most_common():
        m = mean(brand_confidences[brand])
        md_lines.append(f"| {brand} | {n} | {m:.3f} |")
    if not brand_counts:
        md_lines.append("| — | 0 | — |")
    md_lines.append("")

    report = {
        "video": str(args.video),
        "elapsed_seconds": round(elapsed, 1),
        "total_tracks": total_tracks,
        "tracks_with_observations": obs_with_any_signal,
        "tracks_with_commit": len(branded),
        "avg_observations_per_inferred_track": round(avg_obs_per_track, 2),
        "brand_commits": [
            {"brand": b, "count": n, "mean_confidence": round(mean(brand_confidences[b]), 3)}
            for b, n in brand_counts.most_common()
        ],
    }

    md_path = args.out / f"{args.video.stem}.md"
    json_path = args.out / f"{args.video.stem}.json"
    md_path.write_text("\n".join(md_lines))
    json_path.write_text(json.dumps(report, indent=2))
    log.info("wrote: %s + %s", md_path, json_path)

    print("\n".join(md_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
