#!/usr/bin/env python3
"""
Intersection Coordinator Service
Week 12: Multi-Intersection Coordination

Coordinates multiple intersections for:
- Green wave optimization
- Traffic flow coordination
- Priority-based scheduling
- Emergency vehicle routing
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import json

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from atms_config import get_atms_runtime_config

# Kafka imports
try:
    from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logging.warning("Kafka not available")

# Phase B1/B2/B3 — shared observability bootstrap.
import os
from shared.atms_common.auth import (
    AuthConfig,
    JWTVerifier,
    Principal,
    build_role_dependency,
)
from shared.atms_common.logging import configure_logging
from shared.atms_common.tracing import configure_tracing, instrument_fastapi

configure_logging(
    service="intersection-coordinator",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    intersection_id=int(os.getenv("ATMS_INTERSECTION_ID", "1")),
    level=os.getenv("LOG_LEVEL", "INFO"),
    development=os.getenv("ATMS_LOG_DEV", "").lower() in ("1", "true", "yes"),
)
configure_tracing(
    service="intersection-coordinator",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    sample_ratio=float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")),
    development=os.getenv("ATMS_OTEL_DEV", "1").lower() in ("1", "true", "yes"),
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth: coordination commands influence signal timing across intersections —
# state-changing endpoints require an authenticated engineer.
# See docs/adr/0006-rbac-jwt-roles.md.
# ---------------------------------------------------------------------------


def _build_verifier() -> JWTVerifier:
    cfg = AuthConfig(
        issuer=os.getenv("AUTH_ISSUER", "atms-dev"),
        audience=os.getenv("AUTH_AUDIENCE", "atms-traffic-controller"),
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
_ENGINEER_DEP = Depends(require_role("engineer"))
_OPERATOR_DEP = Depends(require_role("operator"))


# ============================================================================
# Data Models
# ============================================================================

class TrafficPhase(str, Enum):
    """Traffic signal phases"""
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    ALL_RED = "ALL_RED"


class Priority(str, Enum):
    """Traffic priority levels"""
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EMERGENCY = "EMERGENCY"


@dataclass
class IntersectionState:
    """State of a single intersection"""
    intersection_id: str
    current_phase: TrafficPhase
    phase_start_time: datetime
    vehicle_count_ns: int
    vehicle_count_ew: int
    queue_length_ns: int
    queue_length_ew: int
    waiting_time_ns: float
    waiting_time_ew: float
    emergency_vehicle_detected: bool
    last_update: datetime


@dataclass
class CoordinationDecision:
    """Decision for coordinating intersections"""
    intersection_id: str
    recommended_phase: TrafficPhase
    phase_duration: float
    priority: Priority
    reason: str
    green_wave_enabled: bool
    synchronized_with: List[str]  # Other intersection IDs
    timestamp: datetime


class IntersectionMetrics(BaseModel):
    """Metrics from an intersection"""
    intersection_id: str
    vehicle_count_ns: int
    vehicle_count_ew: int
    queue_length_ns: int
    queue_length_ew: int
    waiting_time_ns: float
    waiting_time_ew: float
    current_phase: str
    emergency_detected: bool


class CoordinationRequest(BaseModel):
    """Request for coordination"""
    intersection_id: str
    metrics: IntersectionMetrics
    requested_phase: Optional[str] = None
    priority: str = "NORMAL"


# ============================================================================
# Green Wave Algorithm
# ============================================================================

class GreenWaveAlgorithm:
    """Green wave optimization algorithm"""
    
    def __init__(self, max_wave_speed: float = 50.0, min_green_time: float = 10.0):
        """
        Initialize green wave algorithm
        
        Args:
            max_wave_speed: Maximum speed for green wave (km/h)
            min_green_time: Minimum green phase duration (seconds)
        """
        self.max_wave_speed = max_wave_speed
        self.min_green_time = min_green_time
        self.intersection_distances: Dict[Tuple[str, str], float] = {}  # (id1, id2) -> distance in meters
    
    def set_intersection_distance(self, id1: str, id2: str, distance_m: float):
        """Set distance between two intersections"""
        self.intersection_distances[(id1, id2)] = distance_m
        self.intersection_distances[(id2, id1)] = distance_m
    
    def calculate_green_wave(
        self,
        intersections: List[IntersectionState],
        direction: str = "north_south"
    ) -> List[CoordinationDecision]:
        """
        Calculate green wave timing for a sequence of intersections
        
        Args:
            intersections: List of intersection states in order
            direction: Direction of traffic flow
            
        Returns:
            List of coordination decisions with synchronized timing
        """
        if len(intersections) < 2:
            return []
        
        decisions = []
        base_green_time = self.min_green_time
        
        # Calculate timing offsets for green wave
        for i, intersection in enumerate(intersections):
            if i == 0:
                # First intersection starts immediately
                offset = 0.0
            else:
                # Calculate offset based on distance and wave speed
                prev_id = intersections[i-1].intersection_id
                curr_id = intersection.intersection_id
                distance = self.intersection_distances.get((prev_id, curr_id), 100.0)  # Default 100m
                
                # Time for vehicle to travel from prev to current intersection
                travel_time = (distance / 1000.0) / (self.max_wave_speed / 3600.0)  # Convert to hours
                offset = travel_time
            
            # Determine phase based on direction
            if direction == "north_south":
                recommended_phase = TrafficPhase.GREEN if intersection.vehicle_count_ns > 0 else TrafficPhase.RED
            else:
                recommended_phase = TrafficPhase.GREEN if intersection.vehicle_count_ew > 0 else TrafficPhase.RED
            
            decision = CoordinationDecision(
                intersection_id=intersection.intersection_id,
                recommended_phase=recommended_phase,
                phase_duration=base_green_time,
                priority=Priority.NORMAL,
                reason=f"Green wave coordination ({direction})",
                green_wave_enabled=True,
                synchronized_with=[i.intersection_id for i in intersections if i.intersection_id != intersection.intersection_id],
                timestamp=datetime.utcnow() + timedelta(seconds=offset)
            )
            decisions.append(decision)
        
        return decisions


# ============================================================================
# Priority Scheduler
# ============================================================================

class PriorityScheduler:
    """Priority-based scheduling for intersections"""
    
    def __init__(self):
        self.emergency_queue: List[IntersectionState] = []
        self.priority_intersections: Dict[str, int] = {}  # intersection_id -> priority score
    
    def set_priority(self, intersection_id: str, priority_score: int):
        """Set priority score for an intersection (higher = more priority)"""
        self.priority_intersections[intersection_id] = priority_score
    
    def schedule_emergency(
        self,
        intersection: IntersectionState,
        target_intersections: List[str]
    ) -> List[CoordinationDecision]:
        """
        Schedule emergency vehicle priority route
        
        Args:
            intersection: Intersection with emergency vehicle
            target_intersections: List of intersection IDs in route
            
        Returns:
            List of coordination decisions for emergency route
        """
        decisions = []
        
        # Immediate green for current intersection
        decisions.append(CoordinationDecision(
            intersection_id=intersection.intersection_id,
            recommended_phase=TrafficPhase.GREEN,
            phase_duration=30.0,  # Extended green for emergency
            priority=Priority.EMERGENCY,
            reason="Emergency vehicle detected",
            green_wave_enabled=True,
            synchronized_with=target_intersections,
            timestamp=datetime.utcnow()
        ))
        
        # Pre-empt green for route intersections
        for target_id in target_intersections:
            decisions.append(CoordinationDecision(
                intersection_id=target_id,
                recommended_phase=TrafficPhase.GREEN,
                phase_duration=25.0,
                priority=Priority.EMERGENCY,
                reason=f"Emergency vehicle route - synchronized with {intersection.intersection_id}",
                green_wave_enabled=True,
                synchronized_with=[intersection.intersection_id] + [t for t in target_intersections if t != target_id],
                timestamp=datetime.utcnow() + timedelta(seconds=5.0)  # Staggered timing
            ))
        
        return decisions


# ============================================================================
# Intersection Coordinator Service
# ============================================================================

class IntersectionCoordinator:
    """Main coordinator service for multiple intersections"""
    
    def __init__(self):
        self.intersections: Dict[str, IntersectionState] = {}
        self.green_wave_algorithm = GreenWaveAlgorithm()
        self.priority_scheduler = PriorityScheduler()
        self.kafka_producer: Optional[AIOKafkaProducer] = None
        self.kafka_consumer: Optional[AIOKafkaConsumer] = None
        self.websocket_connections: List[WebSocket] = []
        
        # Coordination history
        self.coordination_history: List[CoordinationDecision] = []
        self.max_history = 1000
    
    async def initialize_kafka(self):
        """Initialize Kafka producer and consumer"""
        runtime_cfg = get_atms_runtime_config()
        if not runtime_cfg.enable_kafka:
            logger.info(
                f"ATMS run mode: {runtime_cfg.run_mode.value} -> Kafka disabled (offline mode)"
            )
            return False

        if not KAFKA_AVAILABLE:
            logger.warning("Kafka not available - coordination will work locally only")
            return False
        
        try:
            import os
            kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
            
            # Producer for coordination decisions
            self.kafka_producer = AIOKafkaProducer(
                bootstrap_servers=kafka_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            await self.kafka_producer.start()
            logger.info("✅ Kafka producer initialized")
            
            # Consumer for intersection metrics
            self.kafka_consumer = AIOKafkaConsumer(
                'intersection-metrics',
                bootstrap_servers=kafka_servers,
                group_id='intersection-coordinator',
                value_deserializer=lambda m: json.loads(m.decode('utf-8'))
            )
            await self.kafka_consumer.start()
            logger.info("✅ Kafka consumer initialized")
            
            # Start consuming metrics
            asyncio.create_task(self._consume_metrics())
            
            return True
        except Exception as e:
            logger.error(f"❌ Kafka initialization failed: {e}")
            return False
    
    async def _consume_metrics(self):
        """Consume intersection metrics from Kafka"""
        if not self.kafka_consumer:
            return
        
        try:
            async for message in self.kafka_consumer:
                try:
                    data = message.value
                    metrics = IntersectionMetrics(**data)
                    await self.update_intersection_metrics(metrics)
                except Exception as e:
                    logger.error(f"Error processing metrics: {e}")
        except Exception as e:
            logger.error(f"Error consuming metrics: {e}")
    
    async def update_intersection_metrics(self, metrics: IntersectionMetrics):
        """Update metrics for an intersection"""
        intersection_id = metrics.intersection_id
        
        # Update or create intersection state
        if intersection_id not in self.intersections:
            self.intersections[intersection_id] = IntersectionState(
                intersection_id=intersection_id,
                current_phase=TrafficPhase(metrics.current_phase),
                phase_start_time=datetime.utcnow(),
                vehicle_count_ns=0,
                vehicle_count_ew=0,
                queue_length_ns=0,
                queue_length_ew=0,
                waiting_time_ns=0.0,
                waiting_time_ew=0.0,
                emergency_vehicle_detected=False,
                last_update=datetime.utcnow()
            )
        
        state = self.intersections[intersection_id]
        state.vehicle_count_ns = metrics.vehicle_count_ns
        state.vehicle_count_ew = metrics.vehicle_count_ew
        state.queue_length_ns = metrics.queue_length_ns
        state.queue_length_ew = metrics.queue_length_ew
        state.waiting_time_ns = metrics.waiting_time_ns
        state.waiting_time_ew = metrics.waiting_time_ew
        state.emergency_vehicle_detected = metrics.emergency_detected
        state.last_update = datetime.utcnow()
        
        logger.debug(f"Updated metrics for intersection {intersection_id}")
    
    async def coordinate_intersections(
        self,
        intersection_ids: List[str],
        mode: str = "green_wave"
    ) -> List[CoordinationDecision]:
        """
        Coordinate multiple intersections
        
        Args:
            intersection_ids: List of intersection IDs to coordinate
            mode: Coordination mode ("green_wave", "priority", "balanced")
            
        Returns:
            List of coordination decisions
        """
        # Get intersection states
        intersections = [self.intersections[iid] for iid in intersection_ids if iid in self.intersections]
        
        if len(intersections) < 2:
            logger.warning(f"Need at least 2 intersections for coordination, got {len(intersections)}")
            return []
        
        decisions = []
        
        if mode == "green_wave":
            # Determine direction based on traffic flow
            total_ns = sum(i.vehicle_count_ns for i in intersections)
            total_ew = sum(i.vehicle_count_ew for i in intersections)
            direction = "north_south" if total_ns >= total_ew else "east_west"
            
            decisions = self.green_wave_algorithm.calculate_green_wave(intersections, direction)
        
        elif mode == "priority":
            # Check for emergency vehicles
            emergency_intersections = [i for i in intersections if i.emergency_vehicle_detected]
            if emergency_intersections:
                # Schedule emergency route
                for emergency in emergency_intersections:
                    route = [iid for iid in intersection_ids if iid != emergency.intersection_id]
                    decisions.extend(self.priority_scheduler.schedule_emergency(emergency, route))
            else:
                # Priority-based scheduling
                sorted_intersections = sorted(
                    intersections,
                    key=lambda i: self.priority_scheduler.priority_intersections.get(i.intersection_id, 0),
                    reverse=True
                )
                for i, intersection in enumerate(sorted_intersections):
                    # Give green to highest priority
                    recommended_phase = TrafficPhase.GREEN if i == 0 else TrafficPhase.RED
                    decisions.append(CoordinationDecision(
                        intersection_id=intersection.intersection_id,
                        recommended_phase=recommended_phase,
                        phase_duration=20.0,
                        priority=Priority.HIGH if i == 0 else Priority.NORMAL,
                        reason=f"Priority-based scheduling (rank {i+1})",
                        green_wave_enabled=False,
                        synchronized_with=[],
                        timestamp=datetime.utcnow()
                    ))
        
        elif mode == "balanced":
            # Balanced coordination - optimize for overall flow
            for intersection in intersections:
                # Determine phase based on queue lengths and waiting times
                ns_score = intersection.queue_length_ns + intersection.waiting_time_ns
                ew_score = intersection.queue_length_ew + intersection.waiting_time_ew
                
                recommended_phase = TrafficPhase.GREEN if ns_score >= ew_score else TrafficPhase.RED
                
                decisions.append(CoordinationDecision(
                    intersection_id=intersection.intersection_id,
                    recommended_phase=recommended_phase,
                    phase_duration=15.0,
                    priority=Priority.NORMAL,
                    reason="Balanced coordination",
                    green_wave_enabled=False,
                    synchronized_with=[],
                    timestamp=datetime.utcnow()
                ))
        
        # Store decisions
        self.coordination_history.extend(decisions)
        if len(self.coordination_history) > self.max_history:
            self.coordination_history = self.coordination_history[-self.max_history:]
        
        # Publish to Kafka
        if self.kafka_producer:
            for decision in decisions:
                try:
                    await self.kafka_producer.send(
                        'coordination-decisions',
                        value=asdict(decision)
                    )
                except Exception as e:
                    logger.error(f"Error publishing decision: {e}")
        
        return decisions
    
    def get_intersection_state(self, intersection_id: str) -> Optional[IntersectionState]:
        """Get current state of an intersection"""
        return self.intersections.get(intersection_id)
    
    def get_all_intersections(self) -> List[IntersectionState]:
        """Get all intersection states"""
        return list(self.intersections.values())
    
    def get_coordination_history(self, limit: int = 100) -> List[CoordinationDecision]:
        """Get recent coordination history"""
        return self.coordination_history[-limit:]


# ============================================================================
# FastAPI Application
# ============================================================================

coordinator = IntersectionCoordinator()
app = FastAPI(
    title="Intersection Coordinator Service",
    version="1.0.0",
    description="Multi-intersection coordination for traffic optimization"
)
instrument_fastapi(app)

# Wildcard origins must not be combined with credentials (Fetch spec);
# pin explicit origins via ATMS_CORS_ORIGINS when browser access is needed.
_cors_origins = [o for o in os.getenv("ATMS_CORS_ORIGINS", "").split(",") if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    """Initialize coordinator on startup"""
    await coordinator.initialize_kafka()
    logger.info("✅ Intersection Coordinator Service started")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    if coordinator.kafka_producer:
        await coordinator.kafka_producer.stop()
    if coordinator.kafka_consumer:
        await coordinator.kafka_consumer.stop()
    logger.info("Intersection Coordinator Service stopped")


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "intersection-coordinator",
        "intersections_registered": len(coordinator.intersections),
        "kafka_available": KAFKA_AVAILABLE
    }


@app.post("/intersections/{intersection_id}/metrics")
async def update_metrics(intersection_id: str, metrics: IntersectionMetrics, _p: Principal = _OPERATOR_DEP):
    """Update metrics for an intersection"""
    metrics.intersection_id = intersection_id
    await coordinator.update_intersection_metrics(metrics)
    return {"status": "updated", "intersection_id": intersection_id}


@app.get("/intersections/{intersection_id}/state")
async def get_intersection_state(intersection_id: str):
    """Get current state of an intersection"""
    state = coordinator.get_intersection_state(intersection_id)
    if not state:
        raise HTTPException(status_code=404, detail="Intersection not found")
    return asdict(state)


@app.get("/intersections")
async def get_all_intersections():
    """Get all intersection states"""
    return [asdict(state) for state in coordinator.get_all_intersections()]


@app.post("/coordinate")
async def coordinate(request: CoordinationRequest, _p: Principal = _ENGINEER_DEP):
    """Coordinate intersections"""
    # Update metrics first
    await coordinator.update_intersection_metrics(request.metrics)
    
    # Get all intersection IDs (or use provided)
    intersection_ids = list(coordinator.intersections.keys())
    if not intersection_ids:
        raise HTTPException(status_code=400, detail="No intersections registered")
    
    # Determine coordination mode
    mode = "green_wave"  # Default
    if request.priority == "EMERGENCY":
        mode = "priority"
    elif len(intersection_ids) > 2:
        mode = "balanced"
    
    # Coordinate
    decisions = await coordinator.coordinate_intersections(intersection_ids, mode)
    
    return {
        "decisions": [asdict(d) for d in decisions],
        "mode": mode,
        "intersections_coordinated": len(intersection_ids)
    }


@app.post("/green-wave")
async def create_green_wave(intersection_ids: List[str], direction: str = "north_south", _p: Principal = _ENGINEER_DEP):
    """Create green wave for specified intersections"""
    intersections = [coordinator.intersections[iid] for iid in intersection_ids if iid in coordinator.intersections]
    
    if len(intersections) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 intersections for green wave")
    
    decisions = coordinator.green_wave_algorithm.calculate_green_wave(intersections, direction)
    
    # Publish to Kafka
    if coordinator.kafka_producer:
        for decision in decisions:
            await coordinator.kafka_producer.send(
                'coordination-decisions',
                value=asdict(decision)
            )
    
    return {
        "decisions": [asdict(d) for d in decisions],
        "direction": direction,
        "intersections": intersection_ids
    }


@app.post("/emergency-route")
async def emergency_route(intersection_id: str, route: List[str], _p: Principal = _ENGINEER_DEP):
    """Create emergency vehicle priority route"""
    intersection = coordinator.get_intersection_state(intersection_id)
    if not intersection:
        raise HTTPException(status_code=404, detail="Intersection not found")
    
    decisions = coordinator.priority_scheduler.schedule_emergency(intersection, route)
    
    # Publish to Kafka
    if coordinator.kafka_producer:
        for decision in decisions:
            await coordinator.kafka_producer.send(
                'coordination-decisions',
                value=asdict(decision)
            )
    
    return {
        "decisions": [asdict(d) for d in decisions],
        "emergency_intersection": intersection_id,
        "route": route
    }


@app.get("/history")
async def get_history(limit: int = 100):
    """Get coordination history"""
    history = coordinator.get_coordination_history(limit)
    return {
        "history": [asdict(d) for d in history],
        "count": len(history)
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await websocket.accept()
    coordinator.websocket_connections.append(websocket)
    
    try:
        while True:
            # Send periodic updates
            states = coordinator.get_all_intersections()
            await websocket.send_json({
                "type": "update",
                "intersections": [asdict(s) for s in states],
                "timestamp": datetime.utcnow().isoformat()
            })
            await asyncio.sleep(1.0)  # Update every second
    except WebSocketDisconnect:
        coordinator.websocket_connections.remove(websocket)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8007,
        reload=True,
        log_level="info"
    )

