#!/usr/bin/env python3
"""
NTCIP Interface Service
Phase 4 - Week 13-14: NTCIP Protocol Implementation

Implements:
- NTCIP 1202 v03 (Traffic Management Data Dictionary)
- NTCIP 1201 (Traffic Signal Controllers)
- Hardware interface for traffic signal controllers
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum
import struct
import socket

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

# Phase B1/B2/B3 — shared observability bootstrap.
import json
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
    service="ntcip-interface",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    intersection_id=int(os.getenv("ATMS_INTERSECTION_ID", "1")),
    level=os.getenv("LOG_LEVEL", "INFO"),
    development=os.getenv("ATMS_LOG_DEV", "").lower() in ("1", "true", "yes"),
)
configure_tracing(
    service="ntcip-interface",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    sample_ratio=float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")),
    development=os.getenv("ATMS_OTEL_DEV", "1").lower() in ("1", "true", "yes"),
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth: this service drives physical signal hardware — every state-changing
# endpoint requires an authenticated engineer. See docs/adr/0006-rbac-jwt-roles.md.
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


# ============================================================================
# NTCIP 1202 v03 - Traffic Management Data Dictionary
# ============================================================================

class NTCIP1202:
    """NTCIP 1202 v03 - Traffic Management Data Dictionary"""
    
    # Object Identifiers (OIDs)
    OID_ROOT = "1.3.6.1.4.1.1206"
    OID_TRAFFIC_MANAGEMENT = f"{OID_ROOT}.4"
    
    # Phase Control
    OID_PHASE_CONTROL = f"{OID_TRAFFIC_MANAGEMENT}.2.3.1"
    OID_PHASE_STATUS = f"{OID_TRAFFIC_MANAGEMENT}.2.3.2"
    
    # Signal Group
    OID_SIGNAL_GROUP = f"{OID_TRAFFIC_MANAGEMENT}.2.3.3"
    
    # Detector
    OID_DETECTOR = f"{OID_TRAFFIC_MANAGEMENT}.2.3.4"
    
    @staticmethod
    def encode_phase_command(phase: int, command: str) -> bytes:
        """
        Encode phase control command
        
        Args:
            phase: Phase number (1-16)
            command: Command ("GREEN", "YELLOW", "RED", "FLASH")
            
        Returns:
            Encoded SNMP message
        """
        command_map = {
            "GREEN": 1,
            "YELLOW": 2,
            "RED": 3,
            "FLASH": 4
        }
        command_value = command_map.get(command.upper(), 3)
        
        # Simplified encoding (full SNMP would be more complex)
        return struct.pack("!BB", phase, command_value)
    
    @staticmethod
    def decode_phase_status(data: bytes) -> Dict[str, Any]:
        """Decode phase status from SNMP response"""
        if len(data) < 2:
            return {"phase": 0, "status": "UNKNOWN"}
        
        phase, status_value = struct.unpack("!BB", data[:2])
        status_map = {1: "GREEN", 2: "YELLOW", 3: "RED", 4: "FLASH"}
        status = status_map.get(status_value, "UNKNOWN")
        
        return {"phase": phase, "status": status}


# ============================================================================
# NTCIP 1201 - Traffic Signal Controllers
# ============================================================================

class NTCIP1201:
    """NTCIP 1201 - Traffic Signal Controllers"""
    
    # Controller States
    class ControllerState(str, Enum):
        NORMAL = "NORMAL"
        FLASH = "FLASH"
        PREEMPT = "PREEMPT"
        COORDINATE = "COORDINATE"
        OFFLINE = "OFFLINE"
    
    # Phase Commands
    class PhaseCommand(str, Enum):
        GREEN = "GREEN"
        YELLOW = "YELLOW"
        RED = "RED"
        FLASH = "FLASH"
        OMIT = "OMIT"
        HOLD = "HOLD"
    
    def __init__(self, controller_address: str, port: int = 161):
        """
        Initialize NTCIP 1201 controller interface
        
        Args:
            controller_address: IP address of traffic signal controller
            port: SNMP port (default 161)
        """
        self.controller_address = controller_address
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.connected = False
    
    async def connect(self) -> bool:
        """Connect to traffic signal controller"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.settimeout(5.0)
            self.connected = True
            logger.info(f"✅ Connected to controller at {self.controller_address}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to connect to controller: {e}")
            self.connected = False
            return False
    
    async def set_phase(self, phase: int, command: PhaseCommand) -> bool:
        """
        Set phase command
        
        Args:
            phase: Phase number (1-16)
            command: Phase command
            
        Returns:
            True if successful
        """
        if not self.connected:
            logger.error("Not connected to controller")
            return False
        
        try:
            # Encode command using NTCIP 1202
            command_data = NTCIP1202.encode_phase_command(phase, command.value)
            
            # Send SNMP SET request (simplified)
            # In production, use proper SNMP library (pysnmp)
            logger.info(f"Setting phase {phase} to {command.value}")
            
            # Simulate successful response
            return True
        except Exception as e:
            logger.error(f"Error setting phase: {e}")
            return False
    
    async def get_phase_status(self, phase: int) -> Optional[Dict[str, Any]]:
        """Get current status of a phase"""
        if not self.connected:
            return None
        
        try:
            # Send SNMP GET request (simplified)
            # In production, use proper SNMP library
            logger.debug(f"Getting status for phase {phase}")
            
            # Simulate response
            return {"phase": phase, "status": "GREEN", "timestamp": datetime.utcnow().isoformat()}
        except Exception as e:
            logger.error(f"Error getting phase status: {e}")
            return None
    
    async def set_controller_state(self, state: ControllerState) -> bool:
        """Set controller state"""
        if not self.connected:
            return False
        
        try:
            logger.info(f"Setting controller state to {state.value}")
            return True
        except Exception as e:
            logger.error(f"Error setting controller state: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from controller"""
        if self.socket:
            self.socket.close()
            self.connected = False
            logger.info("Disconnected from controller")


# ============================================================================
# Hardware Interface Manager
# ============================================================================

class HardwareInterfaceManager:
    """Manages connections to multiple traffic signal controllers"""
    
    def __init__(self):
        self.controllers: Dict[str, NTCIP1201] = {}
    
    def register_controller(self, controller_id: str, address: str, port: int = 161):
        """Register a traffic signal controller"""
        controller = NTCIP1201(address, port)
        self.controllers[controller_id] = controller
        logger.info(f"Registered controller {controller_id} at {address}:{port}")
    
    async def connect_all(self):
        """Connect to all registered controllers"""
        results = {}
        for controller_id, controller in self.controllers.items():
            results[controller_id] = await controller.connect()
        return results
    
    async def set_phase_all(self, phase: int, command: NTCIP1201.PhaseCommand):
        """Set phase for all controllers"""
        results = {}
        for controller_id, controller in self.controllers.items():
            results[controller_id] = await controller.set_phase(phase, command)
        return results
    
    async def get_all_statuses(self) -> Dict[str, Dict[str, Any]]:
        """Get status from all controllers"""
        statuses = {}
        for controller_id, controller in self.controllers.items():
            # Get status for all phases (1-8 typically)
            controller_status = {}
            for phase in range(1, 9):
                phase_status = await controller.get_phase_status(phase)
                if phase_status:
                    controller_status[f"phase_{phase}"] = phase_status
            statuses[controller_id] = controller_status
        return statuses


# ============================================================================
# FastAPI Application
# ============================================================================

hardware_manager = HardwareInterfaceManager()
app = FastAPI(
    title="NTCIP Interface Service",
    version="1.0.0",
    description="NTCIP 1202 v03 and 1201 protocol implementation"
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


class ControllerRegistration(BaseModel):
    """Controller registration request"""
    controller_id: str
    address: str
    port: int = 161


class PhaseCommandRequest(BaseModel):
    """Phase command request"""
    controller_id: str
    phase: int
    command: str  # "GREEN", "YELLOW", "RED", "FLASH"


@app.on_event("startup")
async def startup():
    """Initialize on startup"""
    await hardware_manager.connect_all()
    logger.info("✅ NTCIP Interface Service started")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    for controller in hardware_manager.controllers.values():
        await controller.disconnect()
    logger.info("NTCIP Interface Service stopped")


@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "service": "ntcip-interface",
        "controllers_registered": len(hardware_manager.controllers),
        "controllers_connected": sum(1 for c in hardware_manager.controllers.values() if c.connected)
    }


@app.post("/controllers/register")
async def register_controller(registration: ControllerRegistration, _p: Principal = _ENGINEER_DEP):
    """Register a traffic signal controller"""
    hardware_manager.register_controller(
        registration.controller_id,
        registration.address,
        registration.port
    )
    await hardware_manager.controllers[registration.controller_id].connect()
    return {"status": "registered", "controller_id": registration.controller_id}


@app.post("/controllers/{controller_id}/phase")
async def set_phase(controller_id: str, request: PhaseCommandRequest, _p: Principal = _ENGINEER_DEP):
    """Set phase command for a controller"""
    if controller_id not in hardware_manager.controllers:
        raise HTTPException(status_code=404, detail="Controller not found")
    
    controller = hardware_manager.controllers[controller_id]
    command = NTCIP1201.PhaseCommand(request.command.upper())
    
    success = await controller.set_phase(request.phase, command)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to set phase")
    
    return {
        "status": "success",
        "controller_id": controller_id,
        "phase": request.phase,
        "command": request.command
    }


@app.get("/controllers/{controller_id}/status")
async def get_controller_status(controller_id: str):
    """Get status of a controller"""
    if controller_id not in hardware_manager.controllers:
        raise HTTPException(status_code=404, detail="Controller not found")
    
    controller = hardware_manager.controllers[controller_id]
    statuses = {}
    for phase in range(1, 9):
        phase_status = await controller.get_phase_status(phase)
        if phase_status:
            statuses[f"phase_{phase}"] = phase_status
    
    return {
        "controller_id": controller_id,
        "connected": controller.connected,
        "phases": statuses
    }


@app.get("/controllers")
async def get_all_controllers():
    """Get all registered controllers"""
    controllers = []
    for controller_id, controller in hardware_manager.controllers.items():
        controllers.append({
            "controller_id": controller_id,
            "address": controller.controller_address,
            "port": controller.port,
            "connected": controller.connected
        })
    return {"controllers": controllers}


@app.post("/controllers/{controller_id}/state")
async def set_controller_state(controller_id: str, state: str, _p: Principal = _ENGINEER_DEP):
    """Set controller state"""
    if controller_id not in hardware_manager.controllers:
        raise HTTPException(status_code=404, detail="Controller not found")
    
    controller = hardware_manager.controllers[controller_id]
    controller_state = NTCIP1201.ControllerState(state.upper())
    
    success = await controller.set_controller_state(controller_state)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to set controller state")
    
    return {
        "status": "success",
        "controller_id": controller_id,
        "state": state
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8008,
        reload=True,
        log_level="info"
    )

