"""
Smoke test for simulation/harness/runner.py — Phase C3.

The full SUMO end-to-end runs only when the SUMO binary + Python bindings
are installed. Without them, the runner raises a clean `SimulationError`
with the install instructions. This test asserts that error path.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from simulation.harness.runner import (  # noqa: E402
    SimulationConfig,
    SimulationError,
    SimulationRunner,
    wire_to_tl_phase,
)


class TestPhaseMap:
    @pytest.mark.parametrize(
        ("wire", "expected"),
        [
            ("ns_green", 0),
            ("ns_yellow", 1),
            ("ew_green", 2),
            ("ew_yellow", 3),
            ("all_red", 1),
            ("unknown_phase", 1),  # safe fallback
        ],
    )
    def test_wire_to_tl_phase(self, wire, expected):
        assert wire_to_tl_phase(wire) == expected


@pytest.mark.skipif(
    shutil.which("sumo") is not None,
    reason="SUMO is installed — full end-to-end test runs elsewhere",
)
def test_clean_error_when_sumo_missing():
    """If SUMO isn't installed, the runner must raise SimulationError, not crash."""
    runner = SimulationRunner()
    cfg = SimulationConfig(
        scenario_name="rush-hour",
        config_path=_REPO_ROOT / "simulation" / "scenarios" / "rush-hour" / "config.sumocfg",
        max_steps=10,
    )
    try:
        from traci import start as _maybe  # noqa: F401, PLC0415

        # If traci IS importable we won't hit the install-instructions branch;
        # skip in that case.
        pytest.skip("traci is installed; this test only covers the missing-bindings path")
    except ImportError:
        pass

    with pytest.raises(SimulationError, match="SUMO Python bindings"):
        runner.run(cfg)
