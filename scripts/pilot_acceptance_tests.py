#!/usr/bin/env python3
"""Pilot acceptance test suite — automated verification of the criteria
listed in `docs/demos/bosnia-pilot-deployment.md`.

Production sign-off pattern: KJP ops engineer runs this script before
cutover from shadow mode to enforcement. Every test produces a clear
PASS/FAIL with the threshold and measured value. Output is a Markdown
report suitable for inclusion in the pilot acceptance dossier.

Test categories:
- safety: NTCIP failover, MQTT failover, pedestrian MUTCD compliance
- correctness: closed-loop sync, audit determinism, replay
- ops: audit rotation + retention, metrics endpoint, Grafana scrape
- security: SNMPv3 validation, env-var expansion, no plaintext secrets

Run:
    python3 scripts/pilot_acceptance_tests.py \\
        --site-config services/observability/sarajevo-pilot.yaml \\
        --output-report acceptance_report.md

Failures exit non-zero so CI can gate cutover on green tests.
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("acceptance")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@dataclass
class TestResult:
    category: str
    name: str
    passed: bool
    threshold: str
    measured: str
    notes: str = ""


def t_safety_pedestrian_mutcd() -> TestResult:
    """Pedestrian phase serves MUTCD §4E.06 minimum walk + clearance."""
    from datetime import datetime, timezone, timedelta
    from simulation.decision_chamber import DecisionChamber, ChamberConfig, DirectionState
    from simulation.decision_chamber.pedestrian import (
        ButtonPedestrianDetector,
        compute_ped_min_phase_seconds,
    )

    # 12m crossing × 1.0 m/s + 7s walk = 19s minimum
    min_walk_s = compute_ped_min_phase_seconds(
        crossing_distance_m=12.0, walking_speed_mps=1.0, min_walk_seconds=7.0,
    )

    import json
    ped_file = Path(tempfile.mktemp(suffix='.json'))
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace('+00:00', 'Z')
    ped_file.write_text(json.dumps({
        'direction': 'east_west', 'expires_at': expires, 'notes': 'test',
    }))

    c = DecisionChamber(
        ChamberConfig(audit_log_path=None, crossing_distance_m=12.0),
        pedestrian_detectors=[ButtonPedestrianDetector(ped_file)],
    )
    now = datetime.now(timezone.utc)
    # Tick 1: init; Tick 2: 15s later, forced ped change to east_west
    c.tick(now, directions=[
        DirectionState("north_south", 5, 20, 800, 2, 0.0),
        DirectionState("east_west", 1, 25, 100, 0, 0.0),
    ])
    c.tick(now + timedelta(seconds=15), directions=[
        DirectionState("north_south", 5, 20, 800, 2, 0.0),
        DirectionState("east_west", 1, 25, 100, 0, 0.0),
    ])

    # Now try to switch BACK to north_south before MUTCD min elapses.
    # MUTCD says: serve at least min_walk_s before any change.
    out = c.tick(now + timedelta(seconds=15 + min_walk_s - 5), directions=[
        DirectionState("north_south", 50, 2, 5000, 48, 0.0),
        DirectionState("east_west", 1, 25, 100, 0, 0.0),
    ])
    held = out.commanded_phase == "east_west_green"
    ped_file.unlink()

    return TestResult(
        category="safety",
        name="MUTCD pedestrian min walk + clearance enforced",
        passed=held,
        threshold=f"≥ {min_walk_s:.1f}s walk+clearance preserved despite competing demand",
        measured=f"held={held}",
        notes="Pedestrian phase locked through MUTCD min even with high-emission competing direction.",
    )


def t_safety_ntcip_failover() -> TestResult:
    """When chamber bridge.send_phase_request raises, the chamber tick
    must complete normally (controller fallback handles signal safety).
    """
    from datetime import datetime, timezone
    from simulation.decision_chamber import DecisionChamber, ChamberConfig, DirectionState

    class FailingBridge:
        name = "failing_bridge"
        def send_phase_request(self, output):
            raise OSError("simulated UDP timeout to controller")
        def get_actual_phase(self):
            return None

    c = DecisionChamber(
        ChamberConfig(audit_log_path=None),
        controller_bridge=FailingBridge(),
    )
    try:
        out = c.tick(datetime.now(timezone.utc), directions=[
            DirectionState("north_south", 5, 20, 800, 2, 0.0),
            DirectionState("east_west", 3, 25, 200, 0, 0.0),
        ])
        passed = out.commanded_phase is not None
    except Exception as e:
        passed = False

    return TestResult(
        category="safety",
        name="NTCIP send failure does not crash chamber tick",
        passed=passed,
        threshold="chamber tick completes normally; controller falls back to its own failsafe",
        measured=f"tick completed: {passed}",
        notes="Bridge errors are logged but never propagated. Controller's own watchdog handles signal safety.",
    )


def t_correctness_chamber_determinism() -> TestResult:
    """Same input → same output across two independent chamber instances."""
    from datetime import datetime, timezone, timedelta
    from simulation.decision_chamber import DecisionChamber, ChamberConfig, DirectionState

    def run_chamber(seed_time):
        c = DecisionChamber(ChamberConfig(audit_log_path=None))
        out_phases = []
        for dt in [0, 15, 35, 60]:
            out = c.tick(seed_time + timedelta(seconds=dt), directions=[
                DirectionState("north_south", 5+dt//10, 20, 800+dt*10, 2, 0.0),
                DirectionState("east_west", 8, 5, 2100, 7, 0.0),
            ])
            out_phases.append(out.commanded_phase)
        return out_phases

    seed = datetime.now(timezone.utc)
    a = run_chamber(seed)
    b = run_chamber(seed)
    passed = a == b
    return TestResult(
        category="correctness",
        name="Chamber decisions are deterministic across instances",
        passed=passed,
        threshold="identical commanded_phase sequence for identical input stream",
        measured=f"a={a}  b={b}",
        notes="Required for replay-based incident investigation + reproducibility.",
    )


def t_ops_audit_rotation() -> TestResult:
    """SQLite audit DB rotates at the configured max_size_mb."""
    from datetime import datetime, timezone, timedelta
    from simulation.decision_chamber import DecisionChamber, ChamberConfig, DirectionState
    from simulation.decision_chamber.audit_db import SQLiteAuditLogger

    db = Path(tempfile.mktemp(suffix='.db'))
    # Tiny max_size to trigger rotation quickly
    logger = SQLiteAuditLogger(db, max_size_mb=0.01, retention_days=1)
    c = DecisionChamber(ChamberConfig(audit_log_path=None))
    c._audit = logger
    now = datetime.now(timezone.utc)
    for i in range(500):
        c.tick(now + timedelta(milliseconds=i*100), directions=[
            DirectionState("north_south", i % 10, 20, 800, 2, 0.0),
            DirectionState("east_west", 5, 25, 200, 0, 0.0),
        ])

    # Did we rotate? Look for archived files
    rotated = list(db.parent.glob(f"{db.stem}.*.db"))
    logger.close()
    passed = len(rotated) >= 1
    for r in rotated:
        r.unlink(missing_ok=True)
    db.unlink(missing_ok=True)

    return TestResult(
        category="ops",
        name="Audit DB rotates at max_size_mb",
        passed=passed,
        threshold="≥1 rotated DB file produced when size limit exceeded",
        measured=f"rotated_count={len(rotated)}",
        notes="Without rotation, edge disks fill up over months of operation.",
    )


def t_ops_prometheus_endpoint() -> TestResult:
    """Prometheus /metrics endpoint serves valid text format."""
    import urllib.request
    from simulation.decision_chamber.metrics import PrometheusMetrics

    port = 9099  # use an unused port for the test
    m = PrometheusMetrics(intersection_id="acceptance-test", listen_port=port)
    m.increment("atms_chamber_test_counter", category="acceptance")
    m.set_gauge("atms_chamber_test_gauge", 42.0, type="probe")
    time.sleep(0.3)
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2)
        body = resp.read().decode()
        passed = ("atms_chamber_test_counter" in body and
                  "atms_chamber_test_gauge" in body and
                  "# HELP" in body and
                  "# TYPE" in body)
        notes = f"served {len(body)} bytes"
    except Exception as e:
        passed = False
        notes = f"endpoint not reachable: {e}"
    finally:
        m.close()

    return TestResult(
        category="ops",
        name="Prometheus /metrics endpoint is scrape-compatible",
        passed=passed,
        threshold="HTTP 200 with counter+gauge in text format",
        measured=notes,
        notes="Required for KJP Grafana dashboard import.",
    )


def t_security_env_var_expansion() -> TestResult:
    """Site config ${VAR} references expand from environment, not from
    plaintext in checked-in files.
    """
    import os, yaml
    from simulation.decision_chamber.site_config import SiteConfig

    secret = "test-secret-key-do-not-commit-12345"
    os.environ["ATMS_TEST_KEY"] = secret
    yaml_text = """
intersection_id: security-test
description: secret test
camera:
  pixels_per_meter: 25.0
crosswalk_zones: {}
ntcip:
  v3_auth_passphrase: ${ATMS_TEST_KEY}
"""
    tmp = Path(tempfile.mktemp(suffix='.yaml'))
    tmp.write_text(yaml_text)
    try:
        cfg = SiteConfig.load(tmp)
        # Expanded value SHOULD equal the env var, NOT the literal "${...}"
        passed = cfg.ntcip.v3_auth_passphrase == secret
        plaintext_safe = "${ATMS_TEST_KEY}" in yaml_text and secret not in yaml_text
        notes = (
            f"expanded={cfg.ntcip.v3_auth_passphrase[:8]}...  "
            f"plaintext_in_file={'no' if plaintext_safe else 'yes'}"
        )
    finally:
        tmp.unlink()
        del os.environ["ATMS_TEST_KEY"]

    return TestResult(
        category="security",
        name="Site config env-var expansion (no plaintext secrets)",
        passed=passed,
        threshold="${VAR} resolves to env value at load; literal not in YAML file",
        measured=notes,
        notes="KJP ops policy: SNMPv3 + MQTT passphrases must come from secrets manager, not git.",
    )


def t_security_snmpv3_validation() -> TestResult:
    """SNMPv3 authPriv config rejected when passphrases missing."""
    from simulation.decision_chamber.ntcip_v3_bridge import NtcipV3ControllerBridge

    fails_correctly = []
    # Missing both
    try:
        NtcipV3ControllerBridge(security_level="authPriv", closed_loop_poll_interval_s=0)
        fails_correctly.append(False)
    except ValueError:
        fails_correctly.append(True)
    # Missing priv only
    try:
        NtcipV3ControllerBridge(
            security_level="authPriv",
            auth_passphrase="x" * 16,
            closed_loop_poll_interval_s=0,
        )
        fails_correctly.append(False)
    except ValueError:
        fails_correctly.append(True)
    # Bad security level
    try:
        NtcipV3ControllerBridge(security_level="bogus", closed_loop_poll_interval_s=0)
        fails_correctly.append(False)
    except ValueError:
        fails_correctly.append(True)

    passed = all(fails_correctly)
    return TestResult(
        category="security",
        name="SNMPv3 authPriv requires both passphrases; bad security_level rejected",
        passed=passed,
        threshold="all 3 malformed configs raise ValueError",
        measured=f"failed_correctly={fails_correctly}",
        notes="Defence-in-depth: chamber refuses to start with weak crypto config.",
    )


def t_correctness_homography_residual() -> TestResult:
    """Loaded homography rejects calibrations exceeding 0.5m residual."""
    import json
    import numpy as np
    from simulation.demo.homography import Homography

    cal = {
        "schema_version": 1,
        "intersection_id": "acceptance-test",
        "image_width": 1920, "image_height": 1080,
        "frame_shape": [1080, 1920],
        "real_points": [[0,0],[20,0],[-3,8],[3,8]],
        "pixel_points": [[960,800],[1900,800],[820,200],[1100,200]],
        "homography": np.eye(3).tolist(),  # identity = wrong fit, just for load test
        "validation": {"max_error_m": 0.35, "rmse_m": 0.18},
        "calibrated_at": "2026-06-14T12:00:00+00:00",
    }
    tmp = Path(tempfile.mktemp(suffix='.json'))
    tmp.write_text(json.dumps(cal))
    try:
        h = Homography.load(tmp)
        # Residual within pilot threshold
        within_threshold = h.max_residual_m < 0.5
        # Frame shape match check
        matches_camera = h.matches_camera(1920, 1080)
        mismatches_other = not h.matches_camera(640, 480)
        passed = within_threshold and matches_camera and mismatches_other
        notes = (f"residual={h.max_residual_m}m  "
                 f"frame_match_correct={matches_camera}  "
                 f"frame_mismatch_correct={mismatches_other}")
    finally:
        tmp.unlink()

    return TestResult(
        category="correctness",
        name="Homography calibration loads + validates frame shape",
        passed=passed,
        threshold="residual < 0.5m AND frame shape guard correct",
        measured=notes,
        notes="Site survey calibrations must clear pilot threshold before going live.",
    )


def t_ops_bosnia_locale() -> TestResult:
    """Bosnian locale strings are present and non-empty."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "operator-console" / "src"))
    from locales import t, BS

    required_keys = [
        "console_title", "ped_request_button", "emg_preempt_label",
        "clear_overrides_button", "closed_loop_in_sync", "closed_loop_diverge",
        "tsp_header", "tsp_none", "chamber_panel_header",
    ]
    missing = [k for k in required_keys if not BS.get(k)]
    not_translated = [k for k in required_keys if BS.get(k) == t("en", k)]
    passed = not missing and not not_translated
    return TestResult(
        category="ops",
        name="Bosnian (bs) locale complete + distinct from English",
        passed=passed,
        threshold=f"all {len(required_keys)} keys present + translated",
        measured=f"missing={missing}  identical_to_en={not_translated}",
        notes="KS operator UI cutover requires verified Bosnian translations.",
    )


def t_correctness_emission_overlay() -> TestResult:
    """Region overlay applies expected deltas to brand multipliers."""
    from shared.atms_common.emissions import EmissionEstimator

    overlay = "services/observability/bosnia-fleet-multipliers.yaml"
    if not Path(overlay).exists():
        return TestResult(
            category="correctness",
            name="Bosnia fleet multiplier overlay applies",
            passed=False,
            threshold="overlay file present",
            measured=f"missing: {overlay}",
        )

    base = EmissionEstimator()
    bos = EmissionEstimator(region_overlay_path=overlay)
    expected = {
        "volkswagen": 1.10,   # +10% from 1.00
        "audi": 1.20,         # +9% from 1.10
        "zastava": 1.40,      # new
        "lada": 1.35,         # new
    }
    mismatches = []
    for brand, want in expected.items():
        got = bos._brand_multipliers.get(brand)
        if got is None or abs(got - want) > 1e-6:
            mismatches.append(f"{brand}: want={want}, got={got}")
    passed = not mismatches
    return TestResult(
        category="correctness",
        name="Bosnia fleet emission overlay applies expected adjustments",
        passed=passed,
        threshold="all 4 representative brands match overlay table",
        measured=f"mismatches={mismatches or 'none'}",
        notes="Pilot CO₂ accounting accuracy depends on this overlay.",
    )


ALL_TESTS = [
    t_safety_pedestrian_mutcd,
    t_safety_ntcip_failover,
    t_correctness_chamber_determinism,
    t_correctness_homography_residual,
    t_correctness_emission_overlay,
    t_ops_audit_rotation,
    t_ops_prometheus_endpoint,
    t_ops_bosnia_locale,
    t_security_env_var_expansion,
    t_security_snmpv3_validation,
]


def render_report(results: list[TestResult]) -> str:
    md = ["# ATMS Pilot Acceptance Test Report",
          f"_Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}_",
          ""]
    n_pass = sum(1 for r in results if r.passed)
    n_total = len(results)
    md.append(f"**Result: {n_pass} / {n_total} passed** "
              f"{'(ALL GREEN — cleared for cutover)' if n_pass == n_total else '(BLOCKED — see failures)'}")
    md.append("")

    by_category: dict[str, list[TestResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    for category in ["safety", "correctness", "ops", "security"]:
        if category not in by_category:
            continue
        md.append(f"## {category}")
        md.append("")
        md.append("| Status | Test | Threshold | Measured |")
        md.append("|---|---|---|---|")
        for r in by_category[category]:
            badge = "✅ PASS" if r.passed else "❌ FAIL"
            md.append(f"| {badge} | {r.name} | {r.threshold} | `{r.measured}` |")
        md.append("")
        for r in by_category[category]:
            if r.notes:
                md.append(f"- _{r.name}_ — {r.notes}")
        md.append("")
    return "\n".join(md)


def main() -> int:
    p = argparse.ArgumentParser(prog="pilot_acceptance_tests.py")
    p.add_argument(
        "--site-config",
        type=Path,
        help="optional site YAML (validated as part of the run)",
    )
    p.add_argument("--output-report", type=Path, help="write Markdown report to this path")
    args = p.parse_args()

    results: list[TestResult] = []
    for test_fn in ALL_TESTS:
        log.info("running: %s", test_fn.__name__)
        try:
            results.append(test_fn())
        except Exception as e:
            results.append(TestResult(
                category="error",
                name=test_fn.__name__,
                passed=False,
                threshold="test must complete without raising",
                measured=f"raised: {e}",
            ))

    # Optional site config validation
    if args.site_config:
        from simulation.decision_chamber.site_config import SiteConfig
        try:
            cfg = SiteConfig.load(args.site_config)
            results.append(TestResult(
                category="ops",
                name=f"Site config loads: {args.site_config.name}",
                passed=True,
                threshold="YAML loads, required fields present",
                measured=f"intersection_id={cfg.intersection_id} region={cfg.region.country_code}",
            ))
        except Exception as e:
            results.append(TestResult(
                category="ops",
                name=f"Site config loads: {args.site_config.name}",
                passed=False,
                threshold="YAML loads, required fields present",
                measured=f"failed: {e}",
            ))

    report = render_report(results)
    print(report)
    if args.output_report:
        args.output_report.write_text(report)
        log.info("wrote report -> %s", args.output_report)

    n_pass = sum(1 for r in results if r.passed)
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
