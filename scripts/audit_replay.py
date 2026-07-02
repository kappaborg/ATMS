#!/usr/bin/env python3
"""Audit replay tool — re-run a logged chamber decision.

Production incident investigation:

    "Why did the chamber preempt the east_west approach at 14:32:18
     on 2026-09-15? Was that a real V2X SRM or a false positive on
     the audio detector?"

This script reads the SQLite audit DB, picks the decision (by
decision_id OR by tick_time range), reconstructs the exact ChamberInput
the chamber saw, runs it through a fresh chamber, and prints the
re-computed output alongside the original.

Acceptance criterion: re-tick output MATCHES the logged output exactly
(commanded_phase, mode, dominant_factor, priority_scores). Mismatch
indicates either a non-determinism bug or a chamber-state-dependent
decision (e.g., seconds_in_current_phase depends on prior transitions
— the replayer warm-starts the chamber via the input's current_phase
+ seconds_in_current_phase fields to handle this).

Run:
    # Single decision
    python3 scripts/audit_replay.py \\
        --db /var/lib/atms/sarajevo-marijindvor-001.db \\
        --decision-id 20260915T143218-0042

    # Time window
    python3 scripts/audit_replay.py \\
        --db /var/lib/atms/sarajevo-marijindvor-001.db \\
        --since 2026-09-15T14:30:00Z \\
        --until 2026-09-15T14:35:00Z \\
        --diff-only

    # Latest N
    python3 scripts/audit_replay.py \\
        --db /tmp/atms-chamber-audit.db \\
        --latest 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("audit_replay")

# Reach the chamber modules
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fetch_rows(
    db_path: Path,
    decision_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    latest: int | None = None,
) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if decision_id:
            cur = conn.execute(
                "SELECT input_json, output_json FROM decisions "
                "WHERE decision_id = ?",
                (decision_id,),
            )
        elif since and until:
            cur = conn.execute(
                "SELECT input_json, output_json FROM decisions "
                "WHERE tick_time >= ? AND tick_time <= ? "
                "ORDER BY tick_time ASC",
                (since.isoformat(), until.isoformat()),
            )
        elif latest:
            cur = conn.execute(
                "SELECT input_json, output_json FROM decisions "
                "ORDER BY tick_time DESC LIMIT ?",
                (latest,),
            )
        else:
            raise SystemExit("specify --decision-id, --since/--until, or --latest")
        return [
            {"input": json.loads(r["input_json"]), "output": json.loads(r["output_json"])}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def reconstruct_input(input_dict: dict) -> tuple[Any, list[Any]]:
    """Rebuild ChamberInput + DirectionState list from the logged JSON."""
    from simulation.decision_chamber.state import (  # noqa: PLC0415
        DirectionState,
        EmergencySignal,
        EmergencySource,
    )

    tick_time = datetime.fromisoformat(input_dict["tick_time"])
    directions = [
        DirectionState(
            name=d["name"],
            vehicle_count=d["vehicle_count"],
            avg_speed_kmh=d.get("avg_speed_kmh"),
            instantaneous_co2_g_per_min=d["instantaneous_co2_g_per_min"],
            idling_vehicle_count=d["idling_vehicle_count"],
            seconds_since_green=d["seconds_since_green"],
            has_pedestrian_demand=d.get("has_pedestrian_demand", False),
        )
        for d in input_dict["directions"]
    ]
    emergency_signals = [
        EmergencySignal(
            source=EmergencySource(s["source"]),
            direction=s["direction"],
            confidence=s["confidence"],
            detected_at=datetime.fromisoformat(s["detected_at"]),
            notes=s.get("notes", ""),
        )
        for s in input_dict.get("emergency_signals", [])
    ]
    return tick_time, directions, emergency_signals, input_dict


def replay_one(record: dict) -> dict:
    """Re-tick a fresh chamber on the logged input. Returns a diff
    report comparing re-tick output to the logged output.
    """
    from simulation.decision_chamber import (  # noqa: PLC0415
        ChamberConfig,
        DecisionChamber,
    )

    input_dict = record["input"]
    output_dict = record["output"]

    tick_time, directions, emergency_signals, _ = reconstruct_input(input_dict)

    # Warm-start chamber to match the original's transient state.
    # Phase 10.1: when internal_state is present in the audit, we
    # reconstruct the chamber's full timer state for deterministic
    # replay (perfect score reproduction, not just phase commands).
    from datetime import timedelta  # noqa: PLC0415

    chamber = DecisionChamber(ChamberConfig(audit_log_path=None))
    chamber._current_phase = input_dict["current_phase"]
    chamber._phase_started_at = tick_time - timedelta(
        seconds=input_dict["seconds_in_current_phase"]
    )
    # Phase 10.1 fix: setting _last_tick_time = tick_time makes delta_s=0
    # so the chamber doesn't add elapsed time to the injected seconds_since_green
    # values (those are already POST-update values from the audit).
    chamber._last_tick_time = tick_time

    # Try to use the FULL internal state captured in Phase 10.1+ audits
    internal = output_dict.get("internal_state") or {}
    if internal:
        chamber._seconds_since_green = dict(internal.get("seconds_since_green") or {})
        chamber._divergence_ticks = int(internal.get("divergence_ticks", 0))
        chamber._decision_counter = max(
            0, int(internal.get("decision_counter", 1)) - 1
        )  # -1 because the tick about to run will increment
        chamber._ped_phase_direction = internal.get("ped_phase_direction")
        if internal.get("ped_phase_started_at"):
            chamber._ped_phase_started_at = datetime.fromisoformat(
                internal["ped_phase_started_at"]
            )
    else:
        # Legacy audits (before Phase 10.1) — best-effort reconstruction
        chamber._seconds_since_green = {
            d.name: d.seconds_since_green for d in directions
        }

    # Inject the emergency signals via a one-shot stub detector
    class _StubDetector:
        name = "replay_stub"

        def poll(self, tick_time, context):
            return emergency_signals

    chamber._detectors = [_StubDetector()]

    output = chamber.tick(
        tick_time=tick_time,
        directions=directions,
        detector_context={},
        pedestrian_phase_active=input_dict.get("pedestrian_phase_active", False),
        pedestrian_clearance_remaining_s=input_dict.get(
            "pedestrian_clearance_remaining_s", 0.0
        ),
    )

    # Build diff report
    fields_to_compare = [
        "commanded_phase",
        "mode",
        "dominant_factor",
    ]
    diffs = {}
    for f in fields_to_compare:
        original = output_dict.get(f)
        replayed = getattr(output, f, None)
        if hasattr(replayed, "value"):  # enum
            replayed = replayed.value
        if original != replayed:
            diffs[f] = {"original": original, "replayed": replayed}

    # Priority scores diff (numeric tolerance)
    orig_scores = output_dict.get("priority_scores") or {}
    new_scores = output.priority_scores or {}
    score_diff = {}
    for k in set(orig_scores) | set(new_scores):
        a = orig_scores.get(k, 0.0)
        b = new_scores.get(k, 0.0)
        if abs(a - b) > 0.001:
            score_diff[k] = {"original": a, "replayed": b}

    return {
        "decision_id": output_dict.get("decision_id"),
        "tick_time": input_dict.get("tick_time"),
        "original_phase": output_dict.get("commanded_phase"),
        "replayed_phase": output.commanded_phase,
        "match": not diffs and not score_diff,
        "diffs": diffs,
        "score_diffs": score_diff,
        "rule_chain_summary": [
            f"{t.layer}: {t.result}" for t in output.rule_chain
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser(prog="audit_replay.py")
    p.add_argument("--db", type=Path, required=True, help="SQLite audit DB path")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--decision-id", help="specific decision_id")
    grp.add_argument("--since", type=datetime.fromisoformat, help="time window start (ISO-8601)")
    grp.add_argument("--latest", type=int, help="N most recent decisions")
    p.add_argument("--until", type=datetime.fromisoformat, help="time window end (used with --since)")
    p.add_argument(
        "--diff-only",
        action="store_true",
        help="suppress matching decisions; only print mismatches",
    )
    args = p.parse_args()

    rows = fetch_rows(
        args.db,
        decision_id=args.decision_id,
        since=args.since,
        until=args.until,
        latest=args.latest,
    )
    if not rows:
        log.error("no decisions matched the query")
        return 2
    log.info("replaying %d decision(s)", len(rows))

    n_match = 0
    n_diff = 0
    for record in rows:
        report = replay_one(record)
        if report["match"]:
            n_match += 1
            if not args.diff_only:
                print(
                    f"  ✓ {report['decision_id']}  "
                    f"@ {report['tick_time'][:19]}  "
                    f"phase={report['original_phase']:20s}  MATCH"
                )
        else:
            n_diff += 1
            print(
                f"  ✗ {report['decision_id']}  "
                f"@ {report['tick_time'][:19]}  "
                f"original={report['original_phase']:18s} replayed={report['replayed_phase']:18s}"
            )
            for field, d in report["diffs"].items():
                print(f"      {field}: orig={d['original']!r}  replay={d['replayed']!r}")
            for k, d in report["score_diffs"].items():
                print(f"      score[{k}]: orig={d['original']:.3f}  replay={d['replayed']:.3f}")

    print(f"\nReplay summary: {n_match} match  /  {n_diff} diverged  /  {len(rows)} total")
    return 0 if n_diff == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
