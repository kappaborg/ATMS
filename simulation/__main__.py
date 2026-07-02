"""
Simulation entrypoint — Phase C3.

`python -m simulation <scenario-name>` runs the scenario at
`simulation/scenarios/<name>/config.sumocfg`, writes `kpis.json` and
`report.html` to `simulation/out/<name>/`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Make `shared.*` and `ai_decision_system` importable.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from simulation.harness.report import render_report  # noqa: E402
from simulation.harness.runner import (  # noqa: E402
    SimulationConfig,
    SimulationError,
    SimulationRunner,
)

log = logging.getLogger("simulation")


def _resolve_scenario(name: str) -> Path:
    base = _REPO_ROOT / "simulation" / "scenarios" / name
    cfg = base / "config.sumocfg"
    if not cfg.exists():
        raise SystemExit(f"scenario not found: {cfg}")
    return cfg


def _load_baseline(name: str) -> dict | None:
    base = _REPO_ROOT / "simulation" / "baselines" / f"{name}.json"
    if base.exists():
        try:
            with base.open() as f:
                return json.load(f)
        except Exception as e:
            log.warning("could not load baseline %s: %s", base, e)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simulation")
    parser.add_argument("scenario", help="name under simulation/scenarios/")
    parser.add_argument("--max-steps", type=int, default=3600)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", default=None, help="defaults to simulation/out/<scenario>")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    cfg_path = _resolve_scenario(args.scenario)
    out_dir = (
        Path(args.out_dir) if args.out_dir else _REPO_ROOT / "simulation" / "out" / args.scenario
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    runner = SimulationRunner()
    try:
        kpis = runner.run(
            SimulationConfig(
                scenario_name=args.scenario,
                config_path=cfg_path,
                max_steps=args.max_steps,
                seed=args.seed,
            )
        )
    except SimulationError as e:
        print(f"\n✗ simulation could not run: {e}\n", file=sys.stderr)
        return 2

    (out_dir / "kpis.json").write_text(json.dumps(kpis.to_dict(), indent=2))
    baseline = _load_baseline(args.scenario)
    html = render_report(kpis, baseline=baseline, git_sha=os.getenv("GIT_SHA", ""))
    (out_dir / "report.html").write_text(html)

    print(f"✓ wrote {out_dir / 'report.html'}")
    print(
        f"  conflicts: {kpis.conflicts}  delay: {kpis.avg_delay_s}s  "
        f"throughput: {kpis.throughput_vph} vph"
    )
    return 1 if kpis.conflicts > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
