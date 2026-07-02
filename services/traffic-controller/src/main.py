#!/usr/bin/env python3
"""
Traffic Controller Service.

Phase A1 (gap #1): the controller is now stateful and safety-led. Incoming
Kafka decisions feed a `FailsafeController` (see failsafe.py and
docs/adr/0005-failsafe-controller-state-machine.md), which:

- Validates each decision against the wire schema.
- Watches AI staleness; falls back to a RiLSA fixed-time plan if the AI is
  silent for `MAX_AI_STALENESS_MS`.
- Escalates to ALL_RED_FLASH after a configured number of failsafe transitions
  within a window.

A background tick task runs every `WATCHDOG_TICK_MS` and applies the failsafe's
commanded phase to the local `TrafficSignal` objects (which today are an
in-memory proxy for the NTCIP layer; Phase C1 replaces them with real
NTCIP 1202 SNMP commands).
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Make `shared.*` importable when running from the service directory.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logging.warning("Kafka not available - running in standalone mode")

from shared.atms_common.auth import (  # noqa: E402
    AuthConfig,
    JWTVerifier,
    Principal,
    build_role_dependency,
)
from shared.atms_common.clock import MonotonicClock  # noqa: E402
from shared.atms_common.decision import CommandedPhase  # noqa: E402
from shared.atms_common.health import CheckResult, HealthRouter  # noqa: E402
from shared.atms_common.logging import configure_logging  # noqa: E402
from shared.atms_common.metrics import InMemoryMetrics, MetricsRecorder  # noqa: E402
from shared.atms_common.safety import FixedTimePlan, SafetyConfig  # noqa: E402
from shared.atms_common.tracing import (  # noqa: E402
    configure_tracing,
    instrument_fastapi,
)

# Local module — sits next to this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from failsafe import (  # noqa: E402
    FailsafeConfig,
    FailsafeController,
    Mode,
    TransitionLogger,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

configure_logging(
    service="traffic-controller",
    version="2.0.0",
    intersection_id=int(os.getenv("ATMS_INTERSECTION_ID", "1")),
    level=os.getenv("LOG_LEVEL", "INFO"),
    development=os.getenv("ATMS_LOG_DEV", "").lower() in ("1", "true", "yes"),
)

# Phase B2 — distributed tracing. In dev (or under tests) use the console
# exporter so we don't need a collector. Production sets ATMS_OTEL_DEV=0 and
# points OTEL_EXPORTER_OTLP_ENDPOINT at the collector.
_otel_dev = os.getenv("ATMS_OTEL_DEV", "1").lower() in ("1", "true", "yes")
configure_tracing(
    service="traffic-controller",
    version="2.0.0",
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    sample_ratio=float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")),
    development=_otel_dev,
)

logger = logging.getLogger(__name__)


class _StdlibTransitionLogger(TransitionLogger):
    """
    Bridge the failsafe's structured transition event onto stdlib logging.

    Phase B (B3) will replace this with a structlog JSON logger that propagates
    `trace_id` / `span_id`. For Phase A we just log the dict as JSON so the
    fields are queryable in whatever log aggregator the operator runs.
    """

    def log_transition(self, event) -> None:
        logger.warning("controller_mode_transition %s", json.dumps(dict(event)))


# ---------------------------------------------------------------------------
# Prometheus metrics — try real client; fall back to in-memory recorder.
# ---------------------------------------------------------------------------


def _build_metrics() -> MetricsRecorder:
    try:
        # Lazy: avoid hard-requiring prometheus_client in unit-test envs.
        from shared.atms_common.metrics import PrometheusMetrics  # noqa: PLC0415

        return PrometheusMetrics()
    except Exception:
        logger.warning("prometheus_client unavailable; using in-memory metrics")
        return InMemoryMetrics()


# ---------------------------------------------------------------------------
# Auth: build the JWT verifier and the per-role FastAPI dependency.
# See docs/adr/0006-rbac-jwt-roles.md.
# ---------------------------------------------------------------------------


def _build_verifier() -> JWTVerifier:
    algorithm = os.getenv("AUTH_ALGORITHM", "HS256")
    cfg = AuthConfig(
        issuer=os.getenv("AUTH_ISSUER", "atms-dev"),
        audience=os.getenv("AUTH_AUDIENCE", "atms-traffic-controller"),
        algorithm=algorithm,
        hs256_secret=os.getenv("AUTH_HS256_SECRET"),
        rs256_jwks_uri=os.getenv("AUTH_JWKS_URI"),
        clock_skew_s=int(os.getenv("AUTH_CLOCK_SKEW_S", "30")),
    )
    return JWTVerifier(cfg)


def _audit_log(event: dict) -> None:
    logger.warning("operator_action %s", json.dumps(event))


_verifier = _build_verifier()
require_role = build_role_dependency(_verifier, audit_logger=_audit_log)

# Per-role dependency singletons. Ruff's B008 rule (and FastAPI best practice)
# wants `Depends(...)` calls hoisted out of argument defaults.
_VIEWER_DEP = Depends(require_role("viewer"))
_OPERATOR_DEP = Depends(require_role("operator"))
_ENGINEER_DEP = Depends(require_role("engineer"))


# ---------------------------------------------------------------------------
# Local signal proxy — represents the NTCIP layer.
# ---------------------------------------------------------------------------


class SignalState(str, Enum):
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    RED_YELLOW = "red_yellow"
    FLASH_RED = "flash_red"


class Direction(str, Enum):
    NORTH_SOUTH = "north_south"
    EAST_WEST = "east_west"


class SignalCommand(BaseModel):
    direction: Direction
    state: SignalState


class TrafficSignal:
    """Display proxy for the controller's per-direction signal state.

    Safety-critical phase duration is computed in `failsafe.py` using
    `Clock.now_ns()` (monotonic). The `datetime.utcnow()` calls here drive
    the `/status` JSON shape only and are therefore ATMS-CLOCK exempt.
    """

    def __init__(self, intersection_id: int, direction: Direction) -> None:
        self.intersection_id = intersection_id
        self.direction = direction
        self.current_state = SignalState.RED
        self.state_start_time = datetime.utcnow()  # noqa: ATMS-CLOCK  display only

    def set_state(self, state: SignalState) -> None:
        if self.current_state != state:
            logger.info(
                "Signal %s changing: %s -> %s",
                self.direction.value,
                self.current_state.value,
                state.value,
            )
            self.current_state = state
            self.state_start_time = datetime.utcnow()  # noqa: ATMS-CLOCK  display only

    def to_dict(self) -> dict:
        return {
            "intersection_id": self.intersection_id,
            "direction": self.direction.value,
            "state": self.current_state.value,
            "duration_s": (
                datetime.utcnow() - self.state_start_time  # noqa: ATMS-CLOCK  display only
            ).total_seconds(),
        }


# CommandedPhase -> per-direction signal state mapping.
def _signals_for_phase(phase: CommandedPhase) -> tuple[SignalState, SignalState]:
    """Return (ns_state, ew_state) for a commanded phase."""
    return {
        CommandedPhase.NS_GREEN: (SignalState.GREEN, SignalState.RED),
        CommandedPhase.NS_YELLOW: (SignalState.YELLOW, SignalState.RED),
        CommandedPhase.EW_GREEN: (SignalState.RED, SignalState.GREEN),
        CommandedPhase.EW_YELLOW: (SignalState.RED, SignalState.YELLOW),
        CommandedPhase.ALL_RED: (SignalState.RED, SignalState.RED),
        CommandedPhase.ALL_RED_FLASH: (SignalState.FLASH_RED, SignalState.FLASH_RED),
        # Pedestrian phases command both vehicular reds with ped indication
        # handled by the NTCIP layer (not modelled here in Phase A).
        CommandedPhase.PED_NS_WALK: (SignalState.RED, SignalState.RED),
        CommandedPhase.PED_EW_WALK: (SignalState.RED, SignalState.RED),
        # Phase A7 — pedestrian clearance: cars still red, ped flashing-green.
        CommandedPhase.PED_NS_FLASHING_GREEN: (SignalState.RED, SignalState.RED),
        CommandedPhase.PED_EW_FLASHING_GREEN: (SignalState.RED, SignalState.RED),
        # Phase A7 — EV preempt: priority approach gets green, conflicts go red.
        CommandedPhase.EV_PREEMPT_NS: (SignalState.GREEN, SignalState.RED),
        CommandedPhase.EV_PREEMPT_EW: (SignalState.RED, SignalState.GREEN),
    }[phase]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TrafficControllerService:
    """Traffic controller microservice with failsafe state machine."""

    def __init__(self, intersection_id: int) -> None:
        self.intersection_id = intersection_id

        self.signals: dict[Direction, TrafficSignal] = {
            Direction.NORTH_SOUTH: TrafficSignal(intersection_id, Direction.NORTH_SOUTH),
            Direction.EAST_WEST: TrafficSignal(intersection_id, Direction.EAST_WEST),
        }

        # Failsafe wiring
        self._clock = MonotonicClock()
        self._metrics = _build_metrics()
        self._transition_logger = _StdlibTransitionLogger()

        cfg = FailsafeConfig(
            intersection_id=intersection_id,
            max_ai_staleness_ms=int(os.getenv("ATMS_MAX_AI_STALENESS_MS", "2000")),
            invalid_decision_burst=int(os.getenv("ATMS_INVALID_DECISION_BURST", "3")),
            fixed_time_min_dwell_s=float(os.getenv("ATMS_FIXED_TIME_MIN_DWELL_S", "30")),
            consecutive_valid_to_recover=int(os.getenv("ATMS_CONSECUTIVE_VALID_TO_RECOVER", "5")),
            flap_window_s=float(os.getenv("ATMS_FAILSAFE_FLAP_WINDOW_S", "300")),
            flap_threshold=int(os.getenv("ATMS_FAILSAFE_FLAP_THRESHOLD", "3")),
        )
        plan = FixedTimePlan.rilsa_default()
        safety = SafetyConfig()

        self.failsafe = FailsafeController(
            config=cfg,
            plan=plan,
            safety=safety,
            clock=self._clock,
            metrics=self._metrics,
            logger=self._transition_logger,
        )

        # Kafka
        self.kafka_consumer: AIOKafkaConsumer | None = None
        self.kafka_producer: AIOKafkaProducer | None = None

        # Background task handles
        self._consume_task: asyncio.Task | None = None
        self._tick_task: asyncio.Task | None = None

        # Readiness gate
        self._kafka_ready = False
        self._startup_complete = False

        logger.info("Traffic Controller initialized for intersection %s", intersection_id)

    # ------------------------------------------------------------------
    # Kafka lifecycle
    # ------------------------------------------------------------------

    async def start_kafka(self, bootstrap_servers: str) -> None:
        if not KAFKA_AVAILABLE:
            logger.warning("Kafka not available - skipping Kafka initialization")
            return
        try:
            self.kafka_consumer = AIOKafkaConsumer(
                "decisions",
                bootstrap_servers=bootstrap_servers,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                group_id="traffic-controller-group",
                auto_offset_reset="latest",
            )
            self.kafka_producer = AIOKafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            await self.kafka_consumer.start()
            await self.kafka_producer.start()
            self._kafka_ready = True
            logger.info("Kafka consumer and producer started")
        except Exception as e:
            logger.error("Failed to start Kafka: %s", e)

    async def stop_kafka(self) -> None:
        if self.kafka_consumer:
            await self.kafka_consumer.stop()
        if self.kafka_producer:
            await self.kafka_producer.stop()
        self._kafka_ready = False
        logger.info("Kafka consumer and producer stopped")

    # ------------------------------------------------------------------
    # Consumer + tick loops
    # ------------------------------------------------------------------

    async def consume_decisions(self) -> None:
        if not self.kafka_consumer:
            return
        try:
            async for message in self.kafka_consumer:
                outcome = self.failsafe.submit_decision(message.value)
                if not outcome.accepted:
                    logger.debug(
                        "Rejected decision: %s (%s)",
                        outcome.validation.status.value,
                        outcome.validation.detail,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Error consuming decisions: %s", e)

    async def tick_loop(self) -> None:
        """Drive the failsafe watchdog every WATCHDOG_TICK_MS."""
        period_s = FailsafeController.WATCHDOG_TICK_MS / 1000.0
        try:
            while True:
                commanded = self.failsafe.tick()
                ns_state, ew_state = _signals_for_phase(commanded)
                self.signals[Direction.NORTH_SOUTH].set_state(ns_state)
                self.signals[Direction.EAST_WEST].set_state(ew_state)
                await asyncio.sleep(period_s)
        except asyncio.CancelledError:
            raise

    # ------------------------------------------------------------------
    # Operator controls (auditable)
    # ------------------------------------------------------------------

    def force_emergency(self, reason: str) -> None:
        self.failsafe.force_mode(Mode.ALL_RED_FLASH, reason=reason)

    def operator_recover(self, target: Mode, reason: str) -> None:
        if target is Mode.ALL_RED_FLASH:
            raise ValueError("recover target must be AI_ADAPTIVE or FIXED_TIME")
        self.failsafe.force_mode(target, reason=reason)

    # ------------------------------------------------------------------
    # Status views
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        return {
            "intersection_id": self.intersection_id,
            "failsafe": self.failsafe.status(),
            "signals": {d.value: s.to_dict() for d, s in self.signals.items()},
            "kafka_connected": self._kafka_ready,
            "timestamp": datetime.utcnow().isoformat() + "Z",  # noqa: ATMS-CLOCK  display only
        }

    def is_live(self) -> bool:
        return True

    def is_ready(self) -> bool:
        # Ready means: startup complete AND Kafka attached (or running standalone)
        # AND failsafe at least initialized (always true once we exist).
        if not self._startup_complete:
            return False
        return not (KAFKA_AVAILABLE and not self._kafka_ready)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Traffic Controller Service",
    description="Failsafe-gated traffic controller (Phase A1).",
    version="2.0.0",
)

# Phase B2 — FastAPI auto-instrumentation. Every HTTP request becomes a span.
instrument_fastapi(app)

service = TrafficControllerService(intersection_id=int(os.getenv("ATMS_INTERSECTION_ID", "1")))

# Phase B1 — shared HealthRouter. The bespoke /live, /ready, /startup definitions
# further below are kept for backward-compat shapes; the router provides the
# canonical multi-check `/ready` semantics.
_health_router = HealthRouter(service_name="traffic-controller")


async def _kafka_dep_check() -> CheckResult:
    if not KAFKA_AVAILABLE:
        return CheckResult(ok=True, detail="kafka disabled (standalone mode)")
    return (
        CheckResult(ok=True, detail="connected")
        if service._kafka_ready
        else CheckResult(ok=False, detail="not connected")
    )


_health_router.add_check("kafka", _kafka_dep_check)


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("Starting Traffic Controller Service...")
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    await service.start_kafka(bootstrap)
    service._tick_task = asyncio.create_task(service.tick_loop())
    if service.kafka_consumer:
        service._consume_task = asyncio.create_task(service.consume_decisions())
    service._startup_complete = True
    _health_router.mark_started()
    logger.info("Traffic Controller Service started successfully")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    logger.info("Stopping Traffic Controller Service...")
    for task in (service._consume_task, service._tick_task):
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    await service.stop_kafka()
    logger.info("Traffic Controller Service stopped")


# --- Probes ---
# `/live`, `/ready`, `/startup` are provided by `shared.atms_common.health.HealthRouter`
# (Phase B1). The legacy `/health` endpoint stays for clients that consume its
# specific shape; consider it deprecated.
_health_router.attach(app)


@app.get("/health")
async def health_check():
    """Legacy combined health endpoint. Prefer /ready for K8s probes."""
    return {
        "status": "healthy" if service.is_ready() else "degraded",
        "timestamp": datetime.utcnow().isoformat() + "Z",  # noqa: ATMS-CLOCK  display only
        "kafka_connected": service._kafka_ready,
        "mode": service.failsafe.current_mode().value,
    }


# --- Status ---


@app.get("/")
async def root():
    return {
        "service": "Traffic Controller Service",
        "version": "2.0.0",
        "intersection_id": service.intersection_id,
        "kafka_available": KAFKA_AVAILABLE,
        "mode": service.failsafe.current_mode().value,
    }


@app.get("/status")
async def get_status(_p: Principal = _VIEWER_DEP):
    return JSONResponse(content=service.get_status())


@app.get("/signals/{direction}")
async def get_signal(direction: Direction, _p: Principal = _VIEWER_DEP):
    if direction not in service.signals:
        raise HTTPException(status_code=404, detail="Signal not found")
    return JSONResponse(content=service.signals[direction].to_dict())


# --- Operator controls ---


class EmergencyRequest(BaseModel):
    reason: str


@app.post("/control/emergency")
async def control_emergency(req: EmergencyRequest, principal: Principal = _ENGINEER_DEP):
    """Force ALL_RED_FLASH. Operator-only; audit-logged."""
    service.force_emergency(f"{req.reason} (by sub={principal.sub} jti={principal.jti})")
    return {"mode": service.failsafe.current_mode().value, "principal_sub": principal.sub}


class RecoverRequest(BaseModel):
    target: str  # "ai_adaptive" | "fixed_time"
    reason: str


@app.post("/control/recover")
async def control_recover(req: RecoverRequest, principal: Principal = _ENGINEER_DEP):
    """Recover out of ALL_RED_FLASH. Operator-only; audit-logged."""
    try:
        target = Mode(req.target)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"unknown target mode: {req.target}") from e
    try:
        service.operator_recover(
            target, f"{req.reason} (by sub={principal.sub} jti={principal.jti})"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"mode": service.failsafe.current_mode().value, "principal_sub": principal.sub}


# Manual signal control retained but explicitly does NOT bypass the failsafe.
# Operators who need a manual override use /control/emergency or /control/recover.
@app.post("/control/manual")
async def manual_control(command: SignalCommand, _p: Principal = _ENGINEER_DEP):
    raise HTTPException(
        status_code=410,
        detail=(
            "Direct signal manipulation removed in Phase A1. "
            "Use /control/emergency or /control/recover instead. "
            "See docs/runbooks/failsafe.md."
        ),
    )


# --- Phase A7: EV preempt + ped-call endpoints ---


class PreemptArmRequest(BaseModel):
    approach: str  # "north_south" | "east_west"
    priority: str  # "fire_rescue" | "ambulance" | "police" | "transit"
    valid_until_ns: int
    transponder_id: str


class PreemptClearRequest(BaseModel):
    approach: str
    reason: str = "operator"


class PedCallBody(BaseModel):
    approach: str  # "north_south" | "east_west"
    valid_until_ns: int
    accessibility: bool = False


@app.post("/control/preempt")
async def control_preempt_arm(req: PreemptArmRequest, principal: Principal = _ENGINEER_DEP):
    """Arm an emergency-vehicle preempt. See docs/adr/0007-preempt-pedestrian-ada.md."""
    raw = {
        "intersection_id": service.intersection_id,
        "approach": req.approach,
        "priority": req.priority,
        "valid_until_ns": req.valid_until_ns,
        "transponder_id": req.transponder_id,
        "producer_timestamp_ns": service._clock.now_ns(),
    }
    outcome = service.failsafe.submit_preempt(raw)
    if not outcome.accepted:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": outcome.validation.status.value,
                "detail": outcome.validation.detail,
            },
        )
    return {
        "armed": True,
        "approach": req.approach,
        "priority": req.priority,
        "principal_sub": principal.sub,
    }


@app.post("/control/preempt/clear")
async def control_preempt_clear(req: PreemptClearRequest, principal: Principal = _ENGINEER_DEP):
    """Clear an active preempt. Honours preempt_min_dwell_s."""
    from shared.atms_common.preempt import Approach  # noqa: PLC0415

    try:
        approach = Approach(req.approach)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"unknown approach: {req.approach}") from e
    service.failsafe.submit_preempt_clear(approach, reason=f"{req.reason} (by sub={principal.sub})")
    return {
        "cleared": not service.failsafe.has_active_preempt(),
        "approach": req.approach,
        "principal_sub": principal.sub,
    }


@app.post("/control/ped-call")
async def control_ped_call(req: PedCallBody, principal: Principal = _OPERATOR_DEP):
    """Queue a pedestrian-call. Operator+ (push-button / NTCIP MIB writer)."""
    raw = {
        "intersection_id": service.intersection_id,
        "approach": req.approach,
        "valid_until_ns": req.valid_until_ns,
        "accessibility": req.accessibility,
        "producer_timestamp_ns": service._clock.now_ns(),
    }
    outcome = service.failsafe.submit_ped_call(raw)
    if not outcome.accepted:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": outcome.validation.status.value,
                "detail": outcome.validation.detail,
            },
        )
    return {
        "queued": True,
        "approach": req.approach,
        "accessibility": req.accessibility,
        "principal_sub": principal.sub,
    }


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8003, log_level="info")


if __name__ == "__main__":
    main()
