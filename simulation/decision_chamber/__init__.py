"""ATMS AI Decision Chamber.

A 6-layer deliberation pipeline that takes per-direction sensor state and
emits an explainable, auditable, safety-aware phase request. Designed for
production deployment: every input is a real sensor signal (no mocks at
the boundaries), every decision is logged with full provenance, every
output respects the SIL boundary between this advisory engine and the
signal controller.

Layer architecture:
    L0 — Sensor Fusion    aggregate + health-check multi-source inputs
    L1 — Preemption       emergency / safety hard overrides
    L2 — Policy Gates     min/max phase, pedestrian active, clearance
    L3 — Optimization     queue + emission cost + fairness scoring
    L4 — Hysteresis       anti-oscillation, coordination hooks
    L5 — Commit + Audit   NTCIP-shape phase request + decision log

The chamber does NOT control signal lights directly. It emits ADVISORY
phase requests; the SIL-rated signal controller (NTCIP 1202 device)
enforces hard safety. If this chamber crashes or disagrees with the
controller's safety rules, the controller falls back to fixed-time mode
on its own watchdog — by design.
"""

from simulation.decision_chamber.chamber import DecisionChamber
from simulation.decision_chamber.site_config import SiteConfig
from simulation.decision_chamber.state import (
    ChamberConfig,
    ChamberInput,
    ChamberOutput,
    DirectionState,
    EmergencySignal,
    LayerTrace,
)

__all__ = [
    "DecisionChamber",
    "ChamberConfig",
    "ChamberInput",
    "ChamberOutput",
    "DirectionState",
    "EmergencySignal",
    "LayerTrace",
    "SiteConfig",
    "build_chamber_from_site_config",
]


def build_chamber_from_site_config(site_config_path: str) -> DecisionChamber:
    """One-call factory: load a site YAML, instantiate all detectors +
    bridges + mesh + metrics + audit, return a fully-wired chamber.

    This is the production deployment entry point — every per-site
    knob comes from the YAML, the chamber needs no code changes per
    intersection.

    Args:
        site_config_path: path to the intersection's site YAML.

    Returns:
        DecisionChamber ready for `tick()` calls. All background
        threads (audio, V2X, mesh, NTCIP poll, transit, metrics
        server) are started.
    """
    from pathlib import Path  # noqa: PLC0415

    from simulation.decision_chamber.audio import AudioSirenDetector  # noqa: PLC0415
    from simulation.decision_chamber.audit_db import SQLiteAuditLogger  # noqa: PLC0415
    from simulation.decision_chamber.controller_bridge import (  # noqa: PLC0415
        NtcipControllerBridge,
    )
    from simulation.decision_chamber.coordination import (  # noqa: PLC0415
        CoordinationConfig,
        GreenWaveCoordinator,
        WaveNeighbor,
    )
    from simulation.decision_chamber.mesh import MqttMeshNode, NullMeshNode  # noqa: PLC0415
    from simulation.decision_chamber.metrics import PrometheusMetrics  # noqa: PLC0415
    from simulation.decision_chamber.pedestrian import (  # noqa: PLC0415
        ButtonPedestrianDetector,
        VisionPedestrianDetector,
    )
    from simulation.decision_chamber.preemption import (  # noqa: PLC0415
        OperatorOverrideDetector,
        VisualLightbarDetector,
    )
    from simulation.decision_chamber.transit import (  # noqa: PLC0415
        TransitPriorityDetector,
    )
    from simulation.decision_chamber.v2x import V2XSrmDetector  # noqa: PLC0415

    cfg = SiteConfig.load(site_config_path)

    # ----- detectors (L1 emergency) -----
    detectors = [
        OperatorOverrideDetector(Path("/tmp/atms-operator-override.json")),
        VisualLightbarDetector(),
        V2XSrmDetector(listen_host="127.0.0.1", listen_port=4444),
        AudioSirenDetector(direction="unknown"),  # mic-driven; no localisation in Phase 5
    ]

    # ----- pedestrian detectors (L2/L3) -----
    ped_detectors = [
        ButtonPedestrianDetector(Path("/tmp/atms-ped-button.json")),
        VisionPedestrianDetector(crosswalk_zones=cfg.crosswalk_zones or None),
    ]

    # ----- NTCIP controller bridge (L5 output) -----
    # Pick v1 or v3 per site config. Production deployment uses v3
    # authPriv; v1 stays for dev / legacy controller compatibility.
    if cfg.ntcip.snmp_version == 3:
        from simulation.decision_chamber.ntcip_v3_bridge import (  # noqa: PLC0415
            NtcipV3ControllerBridge,
        )

        bridge = NtcipV3ControllerBridge(
            controller_host=cfg.ntcip.controller_host,
            controller_port=cfg.ntcip.controller_port,
            username=cfg.ntcip.v3_username,
            auth_passphrase=cfg.ntcip.v3_auth_passphrase or None,
            priv_passphrase=cfg.ntcip.v3_priv_passphrase or None,
            security_level=cfg.ntcip.v3_security_level,
            closed_loop_poll_interval_s=cfg.ntcip.closed_loop_poll_seconds,
        )
    else:
        bridge = NtcipControllerBridge(
            controller_host=cfg.ntcip.controller_host,
            controller_port=cfg.ntcip.controller_port,
            community=cfg.ntcip.community,
            closed_loop_poll_interval_s=cfg.ntcip.closed_loop_poll_seconds,
        )

    # ----- MQTT mesh + green wave (L4) -----
    if cfg.mqtt.broker_host:
        mesh = MqttMeshNode(
            intersection_id=cfg.intersection_id,
            broker_host=cfg.mqtt.broker_host,
            broker_port=cfg.mqtt.broker_port,
            username=cfg.mqtt.username or None,
            password=cfg.mqtt.password or None,
            upstream_neighbors=list(cfg.mqtt.upstream_neighbors),
        )
    else:
        mesh = NullMeshNode(cfg.intersection_id)

    coord = GreenWaveCoordinator(
        CoordinationConfig(
            upstream_neighbors=tuple(
                WaveNeighbor(
                    intersection_id=n.intersection_id,
                    offset_seconds=n.offset_seconds,
                    through_direction=n.through_direction,
                )
                for n in cfg.green_wave
            ),
        )
    )

    # ----- TSP (L3) -----
    tsp = None
    if cfg.transit.feed_url:
        tsp = TransitPriorityDetector(
            feed_url=cfg.transit.feed_url,
            route_direction_map=dict(cfg.transit.routes),
            delay_threshold_s=cfg.transit.delay_threshold_s,
            poll_interval_s=cfg.transit.poll_interval_s,
            bonus_per_late_bus=cfg.transit.bonus_per_late_bus,
        )

    # ----- Prometheus metrics (L5) -----
    try:
        metrics = PrometheusMetrics(
            intersection_id=cfg.intersection_id,
            listen_host=cfg.prometheus.listen_host,
            listen_port=cfg.prometheus.listen_port,
        )
    except Exception:
        metrics = None

    # ----- chamber (with optional SQLite audit) -----
    chamber_config = ChamberConfig(audit_log_path=None)  # we plug SQLite below
    chamber = DecisionChamber(
        config=chamber_config,
        detectors=detectors,
        pedestrian_detectors=ped_detectors,
        controller_bridge=bridge,
        mesh=mesh,
        coordinator=coord,
        metrics=metrics,
        intersection_id=cfg.intersection_id,
        transit_priority=tsp,
    )
    if cfg.audit.db_path:
        chamber._audit = SQLiteAuditLogger(
            db_path=cfg.audit.db_path,
            max_size_mb=cfg.audit.max_size_mb,
            retention_days=cfg.audit.retention_days,
        )
    return chamber
