#!/usr/bin/env python3
"""
ATMS Dashboard Service
======================

Real-time visualization service with WebSocket support for live updates.
Optimized for low latency and high performance.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import deque

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

# Kafka imports
try:
    from aiokafka import AIOKafkaConsumer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logging.warning("aiokafka not available - Kafka features disabled")

# Phase B1/B2/B3 — shared observability bootstrap.
import os
from shared.atms_common.logging import configure_logging
from shared.atms_common.tracing import configure_tracing, instrument_fastapi

configure_logging(
    service="dashboard",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    intersection_id=int(os.getenv("ATMS_INTERSECTION_ID", "1")),
    level=os.getenv("LOG_LEVEL", "INFO"),
    development=os.getenv("ATMS_LOG_DEV", "").lower() in ("1", "true", "yes"),
)
configure_tracing(
    service="dashboard",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    sample_ratio=float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")),
    development=os.getenv("ATMS_OTEL_DEV", "1").lower() in ("1", "true", "yes"),
)

# Redis imports
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.warning("redis not available - Redis features disabled")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# Data Models
# ============================================================================

class DashboardMetrics(BaseModel):
    """Real-time dashboard metrics"""
    timestamp: datetime
    intersection_id: int
    active_vehicles: int = 0
    active_trajectories: int = 0
    detections_per_second: float = 0.0
    avg_speed_kmh: float = 0.0
    total_emissions_co2: float = 0.0
    active_anomalies: int = 0
    system_fps: float = 0.0
    system_latency_ms: float = 0.0

class AnomalyAlert(BaseModel):
    """Real-time anomaly alert"""
    track_id: str
    timestamp: datetime
    reasons: List[str]
    scores: Dict[str, float]
    intersection_id: int

# ============================================================================
# Dashboard Service
# ============================================================================

class DashboardService:
    """Dashboard service for real-time visualization"""
    
    def __init__(self):
        self.kafka_consumer: Optional[AIOKafkaConsumer] = None
        self.redis_client: Optional[redis.Redis] = None
        self.websocket_connections: List[WebSocket] = []
        self.recent_metrics: deque = deque(maxlen=1000)  # Last 1000 metrics
        self.recent_anomalies: deque = deque(maxlen=100)  # Last 100 anomalies
        
    async def initialize_kafka(self, bootstrap_servers: List[str], topics: List[str]):
        """Initialize Kafka consumer"""
        if not KAFKA_AVAILABLE:
            return False
        
        try:
            self.kafka_consumer = AIOKafkaConsumer(
                *topics,
                bootstrap_servers=bootstrap_servers,
                group_id="dashboard-service",
                auto_offset_reset="latest",
                enable_auto_commit=True,
                max_poll_records=50  # Low latency: smaller batches
            )
            await self.kafka_consumer.start()
            logger.info("✅ Kafka consumer initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Kafka: {e}")
            return False
    
    async def initialize_redis(self, redis_url: str):
        """Initialize Redis client"""
        if not REDIS_AVAILABLE:
            return False
        
        try:
            self.redis_client = redis.from_url(redis_url)
            await self.redis_client.ping()
            logger.info("✅ Redis client initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Redis: {e}")
            return False
    
    async def add_websocket(self, websocket: WebSocket):
        """Add WebSocket connection"""
        await websocket.accept()
        self.websocket_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.websocket_connections)}")
    
    async def remove_websocket(self, websocket: WebSocket):
        """Remove WebSocket connection"""
        if websocket in self.websocket_connections:
            self.websocket_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.websocket_connections)}")
    
    async def broadcast(self, message: Dict):
        """Broadcast message to all WebSocket connections"""
        if not self.websocket_connections:
            return
        
        # Convert datetime objects to ISO format strings for JSON serialization
        def json_serializer(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")
        
        message_json = json.dumps(message, default=json_serializer)
        disconnected = []
        
        for websocket in self.websocket_connections:
            try:
                await websocket.send_text(message_json)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                disconnected.append(websocket)
        
        # Remove disconnected websockets
        for ws in disconnected:
            await self.remove_websocket(ws)
    
    async def process_kafka_messages(self):
        """Process Kafka messages and update dashboard"""
        if not self.kafka_consumer:
            return
        
        try:
            async for message in self.kafka_consumer:
                topic = message.topic
                data = json.loads(message.value.decode('utf-8'))
                
                # Process based on topic
                if topic == "detections":
                    await self._process_detections(data)
                elif topic == "trajectory-data":
                    await self._process_trajectories(data)
                elif topic == "emission-data":
                    await self._process_emissions(data)
                elif topic == "trajectory-anomalies":
                    await self._process_anomalies(data)
                
        except Exception as e:
            logger.error(f"Error processing Kafka messages: {e}")
    
    async def _process_detections(self, data: Dict):
        """Process detection data"""
        # Update metrics
        metrics = DashboardMetrics(
            timestamp=datetime.now(),
            intersection_id=data.get('intersection_id', 1),
            active_vehicles=len(data.get('detections', []))
        )
        self.recent_metrics.append(metrics)
        
        # Broadcast update
        await self.broadcast({
            'type': 'detections',
            'data': data,
            'metrics': metrics.dict()
        })
    
    async def _process_trajectories(self, data: Dict):
        """Process trajectory data"""
        trajectories = data.get('trajectories', [])
        metrics = DashboardMetrics(
            timestamp=datetime.now(),
            intersection_id=data.get('intersection_id', 1),
            active_trajectories=len(trajectories)
        )
        self.recent_metrics.append(metrics)
        
        await self.broadcast({
            'type': 'trajectories',
            'data': data,
            'metrics': metrics.dict()
        })
    
    async def _process_emissions(self, data: Dict):
        """Process emission data"""
        emissions = data.get('emissions', [])
        total_co2 = sum(e.get('co2_grams', 0) for e in emissions)
        
        metrics = DashboardMetrics(
            timestamp=datetime.now(),
            intersection_id=data.get('intersection_id', 1),
            total_emissions_co2=total_co2
        )
        self.recent_metrics.append(metrics)
        
        await self.broadcast({
            'type': 'emissions',
            'data': data,
            'metrics': metrics.dict()
        })
    
    async def _process_anomalies(self, data: Dict):
        """Process anomaly data"""
        anomalies = data.get('anomalies', [])
        
        for anomaly in anomalies:
            alert = AnomalyAlert(
                track_id=str(anomaly.get('track_id', '')),
                timestamp=datetime.fromisoformat(data.get('timestamp', datetime.now().isoformat())),
                reasons=anomaly.get('reasons', []),
                scores=anomaly.get('scores', {}),
                intersection_id=data.get('intersection_id', 1)
            )
            self.recent_anomalies.append(alert)
            
            # Broadcast alert
            await self.broadcast({
                'type': 'anomaly_alert',
                'data': alert.dict()
            })
    
    async def get_current_metrics(self) -> DashboardMetrics:
        """Get current metrics"""
        if self.recent_metrics:
            return self.recent_metrics[-1]
        return DashboardMetrics(
            timestamp=datetime.now(),
            intersection_id=1
        )
    
    async def get_recent_anomalies(self, limit: int = 10) -> List[AnomalyAlert]:
        """Get recent anomalies"""
        return list(self.recent_anomalies)[-limit:]

# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="ATMS Dashboard Service",
    version="1.0.0",
    description="Real-time visualization dashboard"
)
instrument_fastapi(app)

# Global service instance
dashboard_service = DashboardService()

@app.on_event("startup")
async def startup():
    """Initialize service on startup"""
    import os
    
    # Kafka configuration
    kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
    kafka_topics = ["detections", "trajectory-data", "emission-data", "trajectory-anomalies"]
    
    await dashboard_service.initialize_kafka(kafka_servers, kafka_topics)
    
    # Redis configuration
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    await dashboard_service.initialize_redis(redis_url)
    
    # Start Kafka message processing
    asyncio.create_task(dashboard_service.process_kafka_messages())
    
    logger.info("🚀 Dashboard Service started")

@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    if dashboard_service.kafka_consumer:
        await dashboard_service.kafka_consumer.stop()
    if dashboard_service.redis_client:
        await dashboard_service.redis_client.close()
    logger.info("Dashboard Service stopped")

@app.get("/")
async def root():
    """Dashboard HTML page"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ATMS Dashboard</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .metric { display: inline-block; margin: 10px; padding: 15px; background: #f0f0f0; border-radius: 5px; }
            .metric-value { font-size: 24px; font-weight: bold; color: #2196F3; }
            .metric-label { font-size: 12px; color: #666; }
            .anomaly { padding: 10px; margin: 5px; background: #ffebee; border-left: 4px solid #f44336; }
        </style>
    </head>
    <body>
        <h1>ATMS Real-Time Dashboard</h1>
        <div id="metrics"></div>
        <h2>Recent Anomalies</h2>
        <div id="anomalies"></div>
        <script>
            const ws = new WebSocket('ws://localhost:8006/ws');
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'metrics') {
                    updateMetrics(data.metrics);
                } else if (data.type === 'anomaly_alert') {
                    addAnomaly(data.data);
                }
            };
            function updateMetrics(metrics) {
                document.getElementById('metrics').innerHTML = `
                    <div class="metric">
                        <div class="metric-value">${metrics.active_vehicles}</div>
                        <div class="metric-label">Active Vehicles</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">${metrics.active_trajectories}</div>
                        <div class="metric-label">Active Trajectories</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">${metrics.detections_per_second.toFixed(1)}</div>
                        <div class="metric-label">Detections/sec</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">${metrics.system_fps.toFixed(1)}</div>
                        <div class="metric-label">System FPS</div>
                    </div>
                `;
            }
            function addAnomaly(anomaly) {
                const div = document.createElement('div');
                div.className = 'anomaly';
                div.innerHTML = `
                    <strong>Track ${anomaly.track_id}</strong> - ${anomaly.reasons.join(', ')}
                    <br><small>${new Date(anomaly.timestamp).toLocaleString()}</small>
                `;
                document.getElementById('anomalies').prepend(div);
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "kafka": dashboard_service.kafka_consumer is not None,
        "redis": dashboard_service.redis_client is not None,
        "websocket_connections": len(dashboard_service.websocket_connections)
    }

@app.get("/api/metrics")
async def get_metrics():
    """Get current metrics"""
    metrics = await dashboard_service.get_current_metrics()
    return metrics

@app.get("/api/anomalies")
async def get_anomalies(limit: int = 10):
    """Get recent anomalies"""
    anomalies = await dashboard_service.get_recent_anomalies(limit)
    return {"anomalies": [a.dict() for a in anomalies]}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await dashboard_service.add_websocket(websocket)
    
    try:
        # Send initial metrics
        metrics = await dashboard_service.get_current_metrics()
        await websocket.send_json({
            'type': 'metrics',
            'metrics': metrics.dict()
        })
        
        # Keep connection alive
        while True:
            await asyncio.sleep(1)
            # Connection will be maintained by broadcast method
    except WebSocketDisconnect:
        await dashboard_service.remove_websocket(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await dashboard_service.remove_websocket(websocket)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8006,
        log_level="info",
        loop="uvloop"  # Low latency event loop
    )

