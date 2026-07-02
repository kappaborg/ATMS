#!/usr/bin/env python3
"""
Decision Engine Service
======================

AI-powered traffic decision engine as a microservice.

Features:
- Wraps ai_decision_system.py as a FastAPI service
- Kafka consumer for traffic metrics
- Kafka producer for decisions
- REST API for manual control
"""

import asyncio
import itertools
import json
import logging
import os
import sys
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

try:
    from ai_decision_system import AIDecisionEngine

    AI_SYSTEM_AVAILABLE = True
except ImportError:
    AI_SYSTEM_AVAILABLE = False
    logging.warning("AI decision system not available")

# Phase A1: schema for failsafe-aware controller.
try:
    from shared.atms_common.decision import CommandedPhase  # noqa: F401

    SCHEMA_AVAILABLE = True
except ImportError:
    SCHEMA_AVAILABLE = False
    logging.warning("atms_common.decision not importable; emitting legacy schema only")

# Phase A6 (extended to decision-engine in A3): JWT auth for HTTP endpoints.
from shared.atms_common.auth import (  # noqa: E402
    AuthConfig,
    JWTVerifier,
    Principal,
    build_role_dependency,
)

# Phase B1 + B2 — shared logging + tracing + health probes.
from shared.atms_common.health import CheckResult, HealthRouter  # noqa: E402
from shared.atms_common.logging import configure_logging  # noqa: E402
from shared.atms_common.tracing import (  # noqa: E402
    configure_tracing,
    instrument_fastapi,
)

configure_logging(
    service="decision-engine",
    version="1.1.0",
    intersection_id=int(os.getenv("ATMS_INTERSECTION_ID", "1")),
    level=os.getenv("LOG_LEVEL", "INFO"),
    development=os.getenv("ATMS_LOG_DEV", "").lower() in ("1", "true", "yes"),
)

_otel_dev = os.getenv("ATMS_OTEL_DEV", "1").lower() in ("1", "true", "yes")
configure_tracing(
    service="decision-engine",
    version="1.1.0",
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    sample_ratio=float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")),
    development=_otel_dev,
)

# Producer config — sourced from env so SOPS-decrypted prod secrets can override.
INTERSECTION_ID = int(os.getenv("ATMS_INTERSECTION_ID", "1"))
DECISION_TTL_MS = int(os.getenv("ATMS_DECISION_TTL_MS", "2500"))

# Monotonic decision_id generator. Initialized to a wall-clock-derived seed so
# decision_ids are still monotonic across restarts on a single producer. The
# seed only needs to be roughly increasing — drift from NTP corrections is
# acceptable here because the in-process counter dominates after the first tick.
_decision_id_counter = itertools.count(start=int(time.time() * 1000))  # noqa: ATMS-CLOCK  seed for cross-restart monotonicity


def _next_decision_id() -> int:
    return next(_decision_id_counter)


# ---------------------------------------------------------------------------
# Phase → wire `commanded_phase` mapping (fixed in A3).
#
# The upstream AIDecisionEngine returns a `TrafficPhase` of GREEN/RED/YELLOW/
# ALL_RED — direction-agnostic. The wire schema (ADR-0005) needs a directional
# phase like `ns_green` or `ew_green`. The mapping helpers live in
# `shared.atms_common.decision` so the simulation harness (and any other
# non-service caller) can use them without pulling in the FastAPI/JWT/OTel
# stack this service depends on.
# ---------------------------------------------------------------------------

from shared.atms_common.decision import (  # noqa: E402
    _priority_direction,
    _score_direction,  # noqa: F401  re-exported for tests
    _wire_commanded_phase,
)

try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logging.warning("Kafka not available - running in standalone mode")

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="Decision Engine Service",
    description="AI-powered traffic decision engine",
    version="1.1.0",
)

# Phase B2 — FastAPI auto-instrumentation.
instrument_fastapi(app)


# Phase A6 — JWT/RBAC for HTTP endpoints.
def _build_verifier() -> JWTVerifier:
    cfg = AuthConfig(
        issuer=os.getenv("AUTH_ISSUER", "atms-dev"),
        audience=os.getenv("AUTH_AUDIENCE", "atms-decision-engine"),
        algorithm=os.getenv("AUTH_ALGORITHM", "HS256"),
        hs256_secret=os.getenv("AUTH_HS256_SECRET"),
        rs256_jwks_uri=os.getenv("AUTH_JWKS_URI"),
        clock_skew_s=int(os.getenv("AUTH_CLOCK_SKEW_S", "30")),
    )
    return JWTVerifier(cfg)


def _audit_log(event: dict) -> None:
    logger.warning("operator_action %s", json.dumps(event))


_verifier = _build_verifier()
require_role = build_role_dependency(_verifier, audit_logger=_audit_log)
_VIEWER_DEP = Depends(require_role("viewer"))
_ENGINEER_DEP = Depends(require_role("engineer"))
_ADMIN_DEP = Depends(require_role("admin"))


# Pydantic models
class TrafficData(BaseModel):
    """Traffic data model"""

    vehicle_count: int
    average_emission: float
    average_waiting_time: float
    average_velocity: float
    total_emission: float | None = 0.0
    environmental_impact_score: float | None = 0.0


class DecisionRequest(BaseModel):
    """Decision request model"""

    north_south: TrafficData
    east_west: TrafficData


class DecisionEngineService:
    """Decision engine microservice"""

    def __init__(self):
        """Initialize decision engine service"""
        self.engine = AIDecisionEngine() if AI_SYSTEM_AVAILABLE else None
        self.kafka_consumer: AIOKafkaConsumer | None = None
        self.kafka_producer: AIOKafkaProducer | None = None
        self.auto_mode = True  # Automatic decision making
        self._consume_task: asyncio.Task | None = None
        # Rolling window of recent per-vehicle CO2 readings from the
        # emission-data topic (ai-perception). Feeds the decision inputs
        # in place of the former hardcoded 150.0 constant.
        self._recent_co2: deque[float] = deque(maxlen=500)

        logger.info("Decision Engine Service initialized")

    def _record_emissions(self, message: dict) -> None:
        """Fold an emission-data message into the rolling CO2 window."""
        for record in message.get("emissions", []):
            co2 = record.get("co2_g_km")
            if isinstance(co2, (int, float)) and co2 > 0:
                self._recent_co2.append(float(co2))

    def _average_emission(self, default: float = 150.0) -> float:
        """Mean CO2 g/km over the rolling window; `default` until data arrives."""
        if not self._recent_co2:
            return default
        return sum(self._recent_co2) / len(self._recent_co2)

    async def start_kafka(self, bootstrap_servers: str = "localhost:9092"):
        """Start Kafka consumer and producer"""
        if not KAFKA_AVAILABLE:
            logger.warning("Kafka not available - skipping Kafka initialization")
            return

        try:
            # Initialize consumer for traffic metrics
            self.kafka_consumer = AIOKafkaConsumer(
                "traffic-metrics",
                "emission-data",
                bootstrap_servers=bootstrap_servers,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                group_id="decision-engine-group",
                auto_offset_reset="latest",
            )

            # Initialize producer for decisions
            self.kafka_producer = AIOKafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )

            await self.kafka_consumer.start()
            await self.kafka_producer.start()

            logger.info("Kafka consumer and producer started")
        except Exception as e:
            logger.error(f"Failed to start Kafka: {e}")

    async def stop_kafka(self):
        """Stop Kafka consumer and producer"""
        if self.kafka_consumer:
            await self.kafka_consumer.stop()
        if self.kafka_producer:
            await self.kafka_producer.stop()
        logger.info("Kafka consumer and producer stopped")

    async def consume_messages(self):
        """Consume messages from Kafka topics"""
        if not self.kafka_consumer or not self.auto_mode:
            return

        # Accumulate traffic data
        traffic_data = {"north_south": {}, "east_west": {}}

        try:
            async for message in self.kafka_consumer:
                if message.topic == "traffic-metrics":
                    # Process traffic metrics and make decisions
                    await self.process_traffic_metrics(message.value, traffic_data)
                elif message.topic == "emission-data":
                    self._record_emissions(message.value)
        except Exception as e:
            logger.error(f"Error consuming messages: {e}")

    async def process_traffic_metrics(self, metrics: dict, traffic_data: dict):
        """Process traffic metrics and make decision"""
        try:
            # Update traffic data (simplified - in reality would track by direction)
            # For now, split data between north-south and east-west.
            # average_emission comes from the emission-data topic's rolling
            # window (per-direction attribution is not yet available from
            # ai-perception, so both approaches share the fleet average).
            avg_emission = self._average_emission()
            impact_score = min(100.0, avg_emission / 2.5)
            traffic_data["north_south"] = {
                "vehicle_count": metrics.get("statistics", {}).get("total_detections", 0) // 2,
                "average_emission": avg_emission,
                "average_waiting_time": 30.0,
                "average_velocity": 5.0,
                "total_emission": avg_emission,
                "environmental_impact_score": impact_score,
            }

            traffic_data["east_west"] = {
                "vehicle_count": metrics.get("statistics", {}).get("total_detections", 0) // 2,
                "average_emission": avg_emission,
                "average_waiting_time": 25.0,
                "average_velocity": 6.0,
                "total_emission": avg_emission,
                "environmental_impact_score": impact_score,
            }

            # Make decision
            decision = await self.make_decision(
                traffic_data["north_south"], traffic_data["east_west"]
            )

            # Publish decision
            await self.publish_decision(decision)

        except Exception as e:
            logger.error(f"Error processing traffic metrics: {e}")

    async def make_decision(self, north_south: dict, east_west: dict) -> dict:
        """Make traffic decision"""
        if not self.engine:
            raise Exception("AI decision engine not available")

        try:
            decision = self.engine.make_decision(north_south, east_west)

            # Execute decision
            self.engine.execute_decision(decision)

            # Phase A1: emit both the legacy fields (for any non-controller consumers)
            # and the new schema fields the failsafe controller validates against.
            # Phase A3: derive the directional `commanded_phase` from the same
            # priority-direction scoring the AI engine uses internally; the AI
            # engine itself emits only RED/GREEN/YELLOW/ALL_RED (no direction).
            now_ns = time.monotonic_ns()
            wire_decision_id = _next_decision_id()
            priority_dir = _priority_direction(north_south, east_west)
            commanded = _wire_commanded_phase(decision.recommended_phase.value, priority_dir)
            return {
                # --- new schema (ADR-0005 / shared.atms_common.decision) ---
                "decision_id": wire_decision_id,
                "intersection_id": INTERSECTION_ID,
                "producer_timestamp_ns": now_ns,
                "valid_until_ns": now_ns + DECISION_TTL_MS * 1_000_000,
                "commanded_phase": commanded,
                "priority": decision.priority.value,
                "confidence": decision.confidence,
                "reason": decision.reason,
                # --- legacy fields (retained during rollout) ---
                "legacy_decision_id": decision.decision_id,
                "timestamp": decision.timestamp.isoformat(),
                "current_phase": decision.current_phase.value,
                "recommended_phase": decision.recommended_phase.value,
                "expected_impact": decision.expected_impact,
            }
        except Exception as e:
            logger.error(f"Error making decision: {e}")
            raise

    async def publish_decision(self, decision: dict):
        """Publish decision to Kafka"""
        if not self.kafka_producer:
            return

        try:
            await self.kafka_producer.send("decisions", value=decision)
            logger.info(f"Published decision: {decision['recommended_phase']}")
        except Exception as e:
            logger.error(f"Error publishing decision: {e}")

    def get_statistics(self) -> dict:
        """Get engine statistics"""
        if not self.engine:
            return {"error": "Engine not available"}

        return self.engine.get_statistics()

    def get_current_phase(self) -> dict:
        """Get current traffic phase"""
        if not self.engine:
            return {"error": "Engine not available"}

        # Note: AIDecisionEngine does not expose a phase_start_time; the
        # authoritative phase-duration source is the failsafe controller in
        # services/traffic-controller (see /status on that service).
        return {
            "current_phase": self.engine.current_phase.value,
        }


# Global service instance
service = DecisionEngineService()


# Phase B1 — shared HealthRouter providing /live, /ready, /startup.
_health_router = HealthRouter(service_name="decision-engine")


async def _kafka_dep_check() -> CheckResult:
    if not KAFKA_AVAILABLE:
        return CheckResult(ok=True, detail="kafka disabled (standalone mode)")
    producer_ok = service.kafka_producer is not None
    consumer_ok = service.kafka_consumer is not None
    if producer_ok and consumer_ok:
        return CheckResult(ok=True, detail="producer + consumer connected")
    missing = [
        name for name, ok in (("producer", producer_ok), ("consumer", consumer_ok)) if not ok
    ]
    return CheckResult(ok=False, detail=f"kafka not connected: missing {', '.join(missing)}")


async def _engine_dep_check() -> CheckResult:
    if not AI_SYSTEM_AVAILABLE:
        return CheckResult(ok=False, detail="AI decision system not importable")
    if service.engine is None:
        return CheckResult(ok=False, detail="AI engine not initialised")
    return CheckResult(ok=True, detail="engine loaded")


_health_router.add_check("kafka", _kafka_dep_check)
_health_router.add_check("engine", _engine_dep_check)
_health_router.attach(app)


# FastAPI endpoints
@app.on_event("startup")
async def startup_event():
    """Startup event handler"""
    logger.info("Starting Decision Engine Service...")
    await service.start_kafka()

    # Start background task for consuming messages
    if KAFKA_AVAILABLE and service.kafka_consumer and service.auto_mode:
        service._consume_task = asyncio.create_task(service.consume_messages())

    _health_router.mark_started()
    logger.info("Decision Engine Service started successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler"""
    logger.info("Stopping Decision Engine Service...")
    await service.stop_kafka()
    logger.info("Decision Engine Service stopped")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Decision Engine Service",
        "version": "1.0.0",
        "status": "operational",
        "ai_available": AI_SYSTEM_AVAILABLE,
        "kafka_available": KAFKA_AVAILABLE,
        "auto_mode": service.auto_mode,
    }


@app.get("/health")
async def health_check():
    """Legacy combined health endpoint. Prefer /ready for K8s probes (Phase B1)."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),  # noqa: ATMS-CLOCK
        "kafka_connected": service.kafka_consumer is not None,
        "engine_available": service.engine is not None,
    }


@app.get("/phase/current")
async def get_current_phase(_p: Principal = _VIEWER_DEP):
    """Get current traffic phase"""
    return JSONResponse(content=service.get_current_phase())


@app.get("/statistics")
async def get_statistics(_p: Principal = _VIEWER_DEP):
    """Get engine statistics"""
    return JSONResponse(content=service.get_statistics())


@app.post("/decision/make")
async def make_decision(request: DecisionRequest, principal: Principal = _ENGINEER_DEP):
    """Make a traffic decision. Operator-only; audit-logged."""
    try:
        decision = await service.make_decision(request.north_south.dict(), request.east_west.dict())
        # Append principal to the audit trail so the controller's failsafe
        # transition logs and the decision-engine logs are correlatable.
        decision["audit_principal_sub"] = principal.sub
        decision["audit_principal_jti"] = principal.jti
        return JSONResponse(content=decision)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/mode/auto")
async def set_auto_mode(enabled: bool, _p: Principal = _ADMIN_DEP):
    """Enable/disable automatic decision mode. Admin-only."""
    service.auto_mode = enabled
    return {
        "auto_mode": service.auto_mode,
        "timestamp": datetime.now(UTC).isoformat(),  # noqa: ATMS-CLOCK
    }


@app.get("/mode")
async def get_mode(_p: Principal = _VIEWER_DEP):
    """Get current mode"""
    return {
        "auto_mode": service.auto_mode,
        "timestamp": datetime.now(UTC).isoformat(),  # noqa: ATMS-CLOCK
    }


def main():
    """Main entry point"""
    uvicorn.run(app, host="0.0.0.0", port=8007, log_level="info")


if __name__ == "__main__":
    main()
