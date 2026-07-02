"""Data contracts for the Decision Chamber.

Frozen dataclasses everywhere — every input + output of the chamber is
immutable so any decision can be replayed deterministically. The audit
log stores `ChamberInput` + `ChamberOutput` together so a replayer can
re-run a single tick and verify the same output emerges.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class ChamberMode(str, enum.Enum):
    """Top-level operational mode. Real intersections need to handle
    several distinct regimes and the chamber must declare which one it's
    in so the operator console + controller can react appropriately.
    """

    ADAPTIVE = "adaptive"  # default — full 6-layer optimization
    PREEMPT = "preempt"  # emergency vehicle: bypass optimization
    FIXED_TIME = "fixed_time"  # sensor failure fallback — fixed cycle
    MANUAL = "manual"  # operator has taken direct control
    FLASH_CAUTION = "flash_caution"  # critical failure — yellow flash citywide


class EmergencySource(str, enum.Enum):
    """Where an emergency signal came from. Multi-source by design — the
    chamber treats them as a logical OR so any one source can trigger
    preemption. Source matters for audit + reliability weighting in
    future versions (e.g., V2X SRM is more trustworthy than visual
    heuristic).
    """

    OPERATOR_OVERRIDE = "operator_override"
    VISUAL_LIGHTBAR = "visual_lightbar"
    AUDIO_SIREN = "audio_siren"  # stub for Phase 2
    V2X_SRM = "v2x_srm"  # stub for Phase 2 (SAE J2735 Signal Request Message)


@dataclass(frozen=True)
class EmergencySignal:
    """One reported emergency vehicle approach. Multiple signals may exist
    per tick (e.g., visual + audio together). Direction tells the chamber
    which approach to grant green.
    """

    source: EmergencySource
    direction: str  # e.g., "north_south", "east_west"
    confidence: float  # [0.0, 1.0]
    detected_at: datetime
    notes: str = ""


@dataclass(frozen=True)
class DirectionState:
    """Per-direction sensor snapshot. All values are REAL measurements,
    not estimates with a fallback. If a sensor can't provide a value the
    field is None and the chamber's L0 fusion adjusts (it will not silently
    substitute a default — that's exactly the "fallback data" anti-pattern
    the user called out).
    """

    name: str
    vehicle_count: int  # current queue size (real detection)
    avg_speed_kmh: float | None  # None if speed cannot be measured reliably
    instantaneous_co2_g_per_min: float  # from EmissionEstimator
    idling_vehicle_count: int  # vehicles with speed ≤ 5 km/h
    seconds_since_green: float  # starvation timer
    has_pedestrian_demand: bool = False  # ped button OR vision detection


@dataclass(frozen=True)
class LayerTrace:
    """Per-layer execution record. Joined together they form the
    `rule_chain` — a human + machine-readable explanation of why the
    decision came out the way it did. Essential for audit and operator
    transparency.
    """

    layer: str  # "L0_sensor_fusion", "L1_preemption", etc.
    result: str  # "passed", "blocked", "preempted", "downgraded", "skipped"
    notes: str  # short human-readable explanation
    detail: dict = field(default_factory=dict)  # structured detail for replay


@dataclass(frozen=True)
class ChamberInput:
    """Full input snapshot for one chamber tick. Replay-friendly:
    serialise this to disk + the audit log; re-run the chamber on the
    same input → guaranteed same output (deterministic given the same
    chamber state).
    """

    tick_time: datetime
    current_phase: str  # "north_south_green", "east_west_green", "all_red"
    seconds_in_current_phase: float
    directions: list[DirectionState]
    emergency_signals: list[EmergencySignal]
    pedestrian_phase_active: bool = False
    pedestrian_clearance_remaining_s: float = 0.0


@dataclass(frozen=True)
class ChamberOutput:
    """The chamber's decision for this tick. The `commanded_phase` is an
    ADVISORY request — the signal controller (NTCIP device) has final say
    on whether to honour it.
    """

    decision_id: str  # ISO timestamp + sequence
    timestamp: datetime
    mode: ChamberMode
    commanded_phase: str
    seconds_until_next_review: float
    priority_scores: dict[str, float]  # per-direction final score
    dominant_factor: str  # which input drove the decision
    rule_chain: list[LayerTrace]
    reasoning: str  # one-line human summary
    # Min/max time the controller should hold this phase (advisory)
    min_phase_seconds: float = 10.0
    max_phase_seconds: float = 60.0


@dataclass(frozen=True)
class ChamberConfig:
    """Static configuration for the chamber. Loaded per-deployment;
    operator can adjust weights via the console without restarting (the
    config is re-read on the next tick — see DecisionChamber for the
    hot-reload hook).
    """

    # Optimization weights (must sum to ~1.0; chamber normalises)
    w_queue: float = 0.30
    w_emission: float = 0.40  # slightly higher per the project's emission focus
    w_fairness: float = 0.30

    # Phase timing (seconds)
    min_phase_seconds: float = 10.0
    max_phase_seconds: float = 60.0
    max_starvation_seconds: float = 90.0  # hard upper bound on red wait
    yellow_clearance_seconds: float = 4.0

    # Hysteresis — bonus to the current phase to prevent flip-flopping
    current_phase_bonus: float = 0.10
    challenger_margin: float = 0.05  # challenger must beat by this much

    # Tick rate
    review_interval_seconds: float = 2.0

    # Audit
    audit_log_path: str | None = None  # JSONL path; None = stdout only

    # Pedestrian
    min_walk_seconds: float = 7.0  # MUTCD minimum walk
    ped_clearance_speed_mps: float = 1.0  # 1.0 m/s assumed walking speed
    crossing_distance_m: float = 12.0  # estimated; per-intersection override
