#!/usr/bin/env python3
"""
V2X Interface Service — Phase C8 (ADR-0019).

Bridges incoming SAE J2735 BSM messages (from MQTT in production, from a
direct injection endpoint in dev) to:
- Kafka topic `v2x.bsm.<intersection_id>` for the decision-engine to consume.
- Direct preempt POSTs to traffic-controller when the BSM is EV / transit.

The MQTT consumer side is implementation-specific per OBU vendor; the stub
exposes an HTTP injection endpoint so simulators (C3) can exercise the path
without a real broker.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

# Make `shared.*` importable.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Phase B1/B2/B3 — shared observability bootstrap.
from shared.atms_common.auth import (  # noqa: E402
    AuthConfig,
    JWTVerifier,
    Principal,
    build_role_dependency,
)
from shared.atms_common.health import HealthRouter  # noqa: E402
from shared.atms_common.logging import configure_logging  # noqa: E402
from shared.atms_common.tracing import (  # noqa: E402
    configure_tracing,
    instrument_fastapi,
)
from shared.atms_common.v2x import (  # noqa: E402
    BSMMessage,
    V2XValidationResult,
    bsm_to_preempt_request,
)

configure_logging(
    service="v2x-interface",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    intersection_id=int(os.getenv("ATMS_INTERSECTION_ID", "1")),
    level=os.getenv("LOG_LEVEL", "INFO"),
    development=os.getenv("ATMS_LOG_DEV", "").lower() in ("1", "true", "yes"),
)
configure_tracing(
    service="v2x-interface",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    sample_ratio=float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")),
    development=os.getenv("ATMS_OTEL_DEV", "1").lower() in ("1", "true", "yes"),
)

logger = logging.getLogger(__name__)

# Phase A6 — JWT auth.
_verifier = JWTVerifier(
    AuthConfig(
        issuer=os.getenv("AUTH_ISSUER", "atms-dev"),
        audience=os.getenv("AUTH_AUDIENCE", "atms-v2x-interface"),
        algorithm=os.getenv("AUTH_ALGORITHM", "HS256"),
        hs256_secret=os.getenv("AUTH_HS256_SECRET"),
        rs256_jwks_uri=os.getenv("AUTH_JWKS_URI"),
        clock_skew_s=int(os.getenv("AUTH_CLOCK_SKEW_S", "30")),
    )
)


def _audit_log(event: dict) -> None:
    logger.warning("operator_action %s", json.dumps(event))


require_role = build_role_dependency(_verifier, audit_logger=_audit_log)
_ENGINEER_DEP = Depends(require_role("engineer"))
_OPERATOR_DEP = Depends(require_role("operator"))

INTERSECTION_ID = int(os.getenv("ATMS_INTERSECTION_ID", "1"))

app = FastAPI(
    title="V2X Interface Service",
    description="J2735 BSM ingestion (MQTT → Kafka) + EV/transit preempt bridge.",
    version="1.0.0",
)
instrument_fastapi(app)

# Health probes.
_health = HealthRouter(service_name="v2x-interface")
_health.attach(app)
_health.mark_started()


# ---------------------------------------------------------------------------
# HTTP injection endpoint (used by sim + tests; production reads MQTT).
# ---------------------------------------------------------------------------


class BSMInjection(BaseModel):
    """Wire shape mirrors shared.atms_common.v2x.BSMMessage.from_dict."""

    temporary_id: str
    intersection_id: int
    message_type: str
    vehicle_class: str
    latitude_deg: float
    longitude_deg: float
    speed_mps: float
    heading_deg: float
    approach: str
    distance_to_intersection_m: float
    elevation_m: float = 0.0
    acceleration_mps2: float = 0.0
    siren_active: bool = False
    light_bar_active: bool = False
    transit_route_id: str = ""
    signature_valid: bool = False
    transponder_id: str = ""


@app.post("/admin/inject")
async def inject_bsm(body: BSMInjection, principal: Principal = _ENGINEER_DEP):
    """Inject a simulated BSM for testing the full V2X-to-preempt path."""
    parsed = BSMMessage.from_dict(body.model_dump())
    if isinstance(parsed, V2XValidationResult):
        raise HTTPException(
            status_code=400,
            detail={"reason": parsed.status.value, "detail": parsed.detail},
        )

    out = {
        "accepted": True,
        "temporary_id": parsed.temporary_id,
        "intersection_id": parsed.intersection_id,
        "vehicle_class": parsed.vehicle_class.value,
        "principal_sub": principal.sub,
    }

    # If this BSM is preempt-eligible, surface the would-be PreemptRequest so
    # operators can verify the bridge. The actual POST to traffic-controller
    # is a follow-up — needs the in-cluster service-to-service URL + mTLS.
    preempt_req = bsm_to_preempt_request(parsed)
    if preempt_req is not None:
        out["preempt_request"] = {
            "approach": preempt_req.approach.value,
            "priority": preempt_req.priority.value,
            "transponder_id": preempt_req.transponder_id,
            "valid_until_ns": preempt_req.valid_until_ns,
        }

    return out


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@app.get("/")
async def root():
    return {
        "service": "v2x-interface",
        "version": "1.0.0",
        "intersection_id": INTERSECTION_ID,
        "mqtt_status": "stub",  # follow-up: real MQTT subscriber status
    }


@app.get("/status")
async def get_status(_p: Principal = _OPERATOR_DEP):
    return {
        "intersection_id": INTERSECTION_ID,
        "mqtt_status": "stub",
        "bridge_target": "kafka:v2x.bsm.<intersection_id>",
    }


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8009, log_level="info")


if __name__ == "__main__":
    main()
