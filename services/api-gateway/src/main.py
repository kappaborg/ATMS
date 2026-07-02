#!/usr/bin/env python3
"""
ATMS API Gateway
===============

Central API gateway with authentication, rate limiting, and routing.
Optimized for low latency and high throughput.
"""

import asyncio
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# Make `shared.*` importable.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Phase B1/B2/B3 — shared observability bootstrap.
from shared.atms_common.logging import configure_logging  # noqa: E402
from shared.atms_common.tracing import configure_tracing, instrument_fastapi  # noqa: E402

configure_logging(
    service="api-gateway",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    intersection_id=int(os.getenv("ATMS_INTERSECTION_ID", "1")),
    level=os.getenv("LOG_LEVEL", "INFO"),
    development=os.getenv("ATMS_LOG_DEV", "").lower() in ("1", "true", "yes"),
)
configure_tracing(
    service="api-gateway",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    sample_ratio=float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")),
    development=os.getenv("ATMS_OTEL_DEV", "1").lower() in ("1", "true", "yes"),
)
logger = logging.getLogger(__name__)

# ============================================================================
# Data Models
# ============================================================================

class APIKey(BaseModel):
    """API Key model"""
    key: str
    name: str
    rate_limit: int = 100  # Requests per minute
    allowed_endpoints: List[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None

class RateLimitInfo(BaseModel):
    """Rate limit information"""
    remaining: int
    reset_at: datetime
    limit: int

# ============================================================================
# Authentication & Rate Limiting
# ============================================================================

security = HTTPBearer()

class RateLimiter:
    """Simple in-memory rate limiter (for production, use Redis)"""
    
    def __init__(self):
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self.cleanup_interval = 60  # seconds
    
    def is_allowed(self, key: str, limit: int, window: int = 60) -> bool:
        """Check if request is allowed"""
        now = time.time()
        # Clean old requests
        self.requests[key] = [
            req_time for req_time in self.requests[key]
            if now - req_time < window
        ]
        
        # Check limit
        if len(self.requests[key]) >= limit:
            return False
        
        # Record request
        self.requests[key].append(now)
        return True
    
    def get_remaining(self, key: str, limit: int, window: int = 60) -> int:
        """Get remaining requests"""
        now = time.time()
        self.requests[key] = [
            req_time for req_time in self.requests[key]
            if now - req_time < window
        ]
        return max(0, limit - len(self.requests[key]))

rate_limiter = RateLimiter()

# API keys are provisioned via environment, never hardcoded.
# ATMS_API_KEYS format: "<key>:<name>:<rate_limit>[,<key>:<name>:<rate_limit>...]"
def _load_api_keys() -> Dict[str, APIKey]:
    keys: Dict[str, APIKey] = {}
    raw = os.getenv("ATMS_API_KEYS", "")
    for entry in filter(None, (e.strip() for e in raw.split(","))):
        parts = entry.split(":")
        if len(parts) != 3 or not parts[0]:
            raise ValueError("ATMS_API_KEYS entry must be <key>:<name>:<rate_limit>")
        keys[parts[0]] = APIKey(
            key=parts[0],
            name=parts[1],
            rate_limit=int(parts[2]),
            allowed_endpoints=["*"]
        )
    if not keys:
        logger.warning("ATMS_API_KEYS is not set — all API-key authenticated requests will be rejected")
    return keys

API_KEYS: Dict[str, APIKey] = _load_api_keys()

async def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> APIKey:
    """Verify API key"""
    api_key = credentials.credentials
    
    if api_key not in API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    key_info = API_KEYS[api_key]
    
    # Check expiration
    if key_info.expires_at and datetime.now() > key_info.expires_at:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key expired"
        )
    
    # Check rate limit
    if not rate_limiter.is_allowed(api_key, key_info.rate_limit):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )
    
    return key_info

# ============================================================================
# Service Routing
# ============================================================================

class ServiceRouter:
    """Service router with load balancing"""
    
    def __init__(self):
        self.services = {
            "ai-perception": {
                "urls": ["http://localhost:8004"],
                "health_endpoint": "/health"
            },
            "analytics": {
                "urls": ["http://localhost:8005"],
                "health_endpoint": "/health"
            },
            "dashboard": {
                "urls": ["http://localhost:8006"],
                "health_endpoint": "/health"
            },
            "sensor-fusion": {
                "urls": ["http://localhost:8003"],
                "health_endpoint": "/health"
            },
            "decision-engine": {
                "urls": ["http://localhost:8007"],
                "health_endpoint": "/health"
            }
        }
        self.current_index: Dict[str, int] = defaultdict(int)
        self.http_client = httpx.AsyncClient(timeout=5.0)  # Low latency: 5s timeout
    
    async def route_request(
        self,
        service_name: str,
        path: str,
        method: str = "GET",
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None
    ) -> Dict:
        """Route request to service"""
        if service_name not in self.services:
            raise HTTPException(status_code=404, detail=f"Service {service_name} not found")
        
        service_config = self.services[service_name]
        urls = service_config["urls"]
        
        # Simple round-robin load balancing
        url_index = self.current_index[service_name] % len(urls)
        base_url = urls[url_index]
        self.current_index[service_name] += 1
        
        full_url = f"{base_url}{path}"
        
        try:
            # Make request
            response = await self.http_client.request(
                method=method,
                url=full_url,
                params=params,
                json=json_data,
                headers=headers
            )
            
            # Handle response
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text
                )
            
            return response.json()
            
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Service timeout")
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Service error: {str(e)}")
    
    async def check_service_health(self, service_name: str) -> bool:
        """Check if service is healthy"""
        if service_name not in self.services:
            return False
        
        service_config = self.services[service_name]
        health_endpoint = service_config["health_endpoint"]
        
        try:
            result = await self.route_request(service_name, health_endpoint)
            return result.get("status") == "healthy"
        except:
            return False
    
    async def get_all_services_health(self) -> Dict[str, bool]:
        """Get health status of all services"""
        health_status = {}
        for service_name in self.services.keys():
            health_status[service_name] = await self.check_service_health(service_name)
        return health_status

service_router = ServiceRouter()

# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="ATMS API Gateway",
    version="1.0.0",
    description="Central API gateway for ATMS services"
)

# Phase B2 — FastAPI auto-instrumentation. Every HTTP request is a span.
instrument_fastapi(app)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    """Initialize gateway on startup"""
    logger.info("🚀 API Gateway started")

@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    await service_router.http_client.aclose()
    logger.info("API Gateway stopped")

@app.get("/")
async def root():
    """Gateway information"""
    return {
        "service": "ATMS API Gateway",
        "version": "1.0.0",
        "status": "running",
        "services": list(service_router.services.keys())
    }

@app.get("/health")
async def health():
    """Gateway health check"""
    services_health = await service_router.get_all_services_health()
    all_healthy = all(services_health.values())
    
    return {
        "status": "healthy" if all_healthy else "degraded",
        "gateway": "healthy",
        "services": services_health
    }

def _downstream_headers(request: Request, api_key: APIKey) -> Dict[str, str]:
    """Headers forwarded to backend services.

    The gateway API key must NEVER leave the gateway — backends verify
    JWTs, not gateway keys, and forwarding the key leaks it to every
    downstream log. Clients calling JWT-gated backend routes supply the
    JWT in `X-Forwarded-Authorization`, which becomes the downstream
    `Authorization`. The key's name (not the key) is passed for audit.
    """
    headers = {"X-Gateway-Client": api_key.name}
    client_jwt = request.headers.get("X-Forwarded-Authorization")
    if client_jwt:
        headers["Authorization"] = client_jwt
    return headers


@app.get("/api/v1/{service_name}/{path:path}")
async def proxy_get(
    service_name: str,
    path: str,
    request: Request,
    api_key: APIKey = Depends(verify_api_key)
):
    """Proxy GET request to service"""
    # Check endpoint access
    if api_key.allowed_endpoints != ["*"]:
        if path not in api_key.allowed_endpoints:
            raise HTTPException(status_code=403, detail="Endpoint not allowed")
    
    params = dict(request.query_params)
    result = await service_router.route_request(
        service_name=service_name,
        path=f"/{path}",
        method="GET",
        params=params,
        headers=_downstream_headers(request, api_key)
    )
    
    # Add rate limit info to response headers
    remaining = rate_limiter.get_remaining(api_key.key, api_key.rate_limit)
    return JSONResponse(
        content=result,
        headers={
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Limit": str(api_key.rate_limit)
        }
    )

@app.post("/api/v1/{service_name}/{path:path}")
async def proxy_post(
    service_name: str,
    path: str,
    request: Request,
    api_key: APIKey = Depends(verify_api_key)
):
    """Proxy POST request to service"""
    # Check endpoint access
    if api_key.allowed_endpoints != ["*"]:
        if path not in api_key.allowed_endpoints:
            raise HTTPException(status_code=403, detail="Endpoint not allowed")
    
    json_data = await request.json()
    result = await service_router.route_request(
        service_name=service_name,
        path=f"/{path}",
        method="POST",
        json_data=json_data,
        headers=_downstream_headers(request, api_key)
    )
    
    remaining = rate_limiter.get_remaining(api_key.key, api_key.rate_limit)
    return JSONResponse(
        content=result,
        headers={
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Limit": str(api_key.rate_limit)
        }
    )

@app.get("/api/v1/services/{service_name}/health")
async def service_health(service_name: str):
    """Check service health"""
    is_healthy = await service_router.check_service_health(service_name)
    return {
        "service": service_name,
        "status": "healthy" if is_healthy else "unhealthy"
    }

@app.get("/api/v1/services")
async def list_services():
    """List all available services"""
    return {
        "services": list(service_router.services.keys()),
        "count": len(service_router.services)
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        loop="uvloop"  # Low latency event loop
    )

