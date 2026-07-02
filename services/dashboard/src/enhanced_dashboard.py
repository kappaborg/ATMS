#!/usr/bin/env python3
"""
ATMS Enhanced Dashboard Service
================================

Comprehensive visualization dashboard with video upload, real-time metrics,
detection visualization, and complete system status.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import deque, defaultdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
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

class ComprehensiveMetrics(BaseModel):
    """Comprehensive dashboard metrics"""
    timestamp: datetime
    
    # Detection metrics
    total_detections: int = 0
    active_vehicles: int = 0
    detections_per_second: float = 0.0
    
    # Vehicle breakdown
    cars: int = 0
    trucks: int = 0
    buses: int = 0
    motorcycles: int = 0
    bicycles: int = 0
    pedestrians: int = 0
    
    # Trajectory metrics
    active_trajectories: int = 0
    avg_speed_kmh: float = 0.0
    max_speed_kmh: float = 0.0
    
    # License plate metrics
    plates_detected: int = 0
    plates_recognized: int = 0
    plate_recognition_rate: float = 0.0
    
    # Brand classification
    brands_classified: int = 0
    brand_distribution: Dict[str, int] = {}
    
    # Emission metrics
    total_emissions_co2: float = 0.0
    avg_emission_per_vehicle: float = 0.0
    
    # Anomaly metrics
    active_anomalies: int = 0
    anomaly_types: Dict[str, int] = {}
    
    # System performance
    system_fps: float = 0.0
    system_latency_ms: float = 0.0
    kafka_lag: int = 0
    
    # Multi-view fusion
    fusion_detections: int = 0
    fusion_confidence: float = 0.0

# ============================================================================
# Enhanced Dashboard Service
# ============================================================================

class EnhancedDashboardService:
    """Enhanced dashboard service with comprehensive metrics"""
    
    def __init__(self):
        self.kafka_consumer: Optional[AIOKafkaConsumer] = None
        self.redis_client: Optional[redis.Redis] = None
        self.websocket_connections: List[WebSocket] = []
        
        # Data storage
        self.recent_metrics: deque = deque(maxlen=1000)
        self.recent_detections: deque = deque(maxlen=500)
        self.recent_plates: deque = deque(maxlen=100)
        self.recent_anomalies: deque = deque(maxlen=100)
        self.recent_emissions: deque = deque(maxlen=200)
        
        # Real-time counters
        self.counters = defaultdict(int)
        self.last_update = datetime.now()
        
    async def initialize_kafka(self, bootstrap_servers: List[str], topics: List[str]):
        """Initialize Kafka consumer"""
        if not KAFKA_AVAILABLE:
            return False
        
        try:
            self.kafka_consumer = AIOKafkaConsumer(
                *topics,
                bootstrap_servers=bootstrap_servers,
                group_id="enhanced-dashboard",
                auto_offset_reset="latest",
                enable_auto_commit=True,
                max_poll_records=100
            )
            await self.kafka_consumer.start()
            logger.info("✅ Kafka consumer initialized for enhanced dashboard")
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
        logger.info(f"WebSocket connected. Total: {len(self.websocket_connections)}")
    
    async def remove_websocket(self, websocket: WebSocket):
        """Remove WebSocket connection"""
        if websocket in self.websocket_connections:
            self.websocket_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.websocket_connections)}")
    
    async def broadcast(self, message: Dict):
        """Broadcast message to all WebSocket connections"""
        if not self.websocket_connections:
            return
        
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
                elif topic == "license-plates":
                    await self._process_plates(data)
                elif topic == "traffic-metrics":
                    await self._process_traffic_metrics(data)
                
                # Send comprehensive update every 500ms
                now = datetime.now()
                if (now - self.last_update).total_seconds() >= 0.5:
                    await self._send_comprehensive_update()
                    self.last_update = now
                
        except Exception as e:
            logger.error(f"Error processing Kafka messages: {e}", exc_info=True)
    
    async def _process_detections(self, data: Dict):
        """Process detection data - REAL-TIME ONLY"""
        detections = data.get('detections', [])
        
        # Only count detections from the last 60 seconds (real-time window)
        current_time = datetime.now()
        
        # Add to recent detections with timestamp
        self.recent_detections.append({
            'timestamp': current_time,
            'data': data,
            'count': len(detections)
        })
        
        # Clean old detections (older than 60 seconds)
        cutoff_time = current_time - timedelta(seconds=60)
        while self.recent_detections and self.recent_detections[0]['timestamp'] < cutoff_time:
            self.recent_detections.popleft()
        
        # Calculate REAL-TIME counts from recent window only
        total_in_window = sum(d['count'] for d in self.recent_detections)
        self.counters['total_detections'] = total_in_window
        self.counters['active_vehicles'] = len(detections)  # Current frame only
        
        # Count by class from recent window
        for class_key in ['class_car', 'class_truck', 'class_bus', 'class_motorcycle', 'class_bicycle', 'class_pedestrian']:
            self.counters[class_key] = 0
        
        for det_item in self.recent_detections:
            for det in det_item['data'].get('detections', []):
                obj_class = det.get('class', det.get('object_class', 'unknown'))
                self.counters[f'class_{obj_class}'] += 1
    
    async def _process_trajectories(self, data: Dict):
        """Process trajectory data"""
        trajectories = data.get('trajectories', [])
        self.counters['active_trajectories'] = len(trajectories)
        
        speeds = [t.get('speed_kmh', 0) for t in trajectories if t.get('speed_kmh')]
        if speeds:
            self.counters['avg_speed'] = sum(speeds) / len(speeds)
            self.counters['max_speed'] = max(speeds)
    
    async def _process_emissions(self, data: Dict):
        """Process emission data"""
        emissions = data.get('emissions', [])
        total_co2 = sum(e.get('co2_grams', 0) for e in emissions)
        self.counters['total_emissions'] += total_co2
        self.recent_emissions.append({
            'timestamp': datetime.now(),
            'data': data
        })
    
    async def _process_anomalies(self, data: Dict):
        """Process anomaly data"""
        anomalies = data.get('anomalies', [])
        self.counters['active_anomalies'] = len(anomalies)
        
        for anomaly in anomalies:
            reasons = anomaly.get('reasons', [])
            for reason in reasons:
                self.counters[f'anomaly_{reason}'] += 1
        
        self.recent_anomalies.extend(anomalies)
    
    async def _process_plates(self, data: Dict):
        """Process license plate data"""
        plates = data.get('plates', [])
        self.counters['plates_detected'] += len(plates)
        recognized = len([p for p in plates if p.get('text')])
        self.counters['plates_recognized'] += recognized
        self.recent_plates.extend(plates)
    
    async def _process_traffic_metrics(self, data: Dict):
        """Process traffic metrics"""
        # Extract various metrics from traffic data
        pass
    
    async def _send_comprehensive_update(self):
        """Send comprehensive metrics update"""
        metrics = ComprehensiveMetrics(
            timestamp=datetime.now(),
            total_detections=self.counters.get('total_detections', 0),
            active_vehicles=self.counters.get('active_vehicles', 0),
            cars=self.counters.get('class_car', 0),
            trucks=self.counters.get('class_truck', 0),
            buses=self.counters.get('class_bus', 0),
            motorcycles=self.counters.get('class_motorcycle', 0),
            bicycles=self.counters.get('class_bicycle', 0),
            pedestrians=self.counters.get('class_pedestrian', 0),
            active_trajectories=self.counters.get('active_trajectories', 0),
            avg_speed_kmh=self.counters.get('avg_speed', 0.0),
            max_speed_kmh=self.counters.get('max_speed', 0.0),
            plates_detected=self.counters.get('plates_detected', 0),
            plates_recognized=self.counters.get('plates_recognized', 0),
            total_emissions_co2=self.counters.get('total_emissions', 0.0),
            active_anomalies=self.counters.get('active_anomalies', 0)
        )
        
        # Use model_dump(mode='json') for proper datetime serialization
        await self.broadcast({
            'type': 'comprehensive_metrics',
            'data': metrics.model_dump(mode='json')
        })

# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="ATMS Enhanced Dashboard",
    version="2.0.0",
    description="Comprehensive traffic analysis dashboard"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global service instance
dashboard_service = EnhancedDashboardService()

@app.on_event("startup")
async def startup():
    """Initialize service on startup"""
    import os
    
    # Kafka configuration
    kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
    kafka_topics = [
        "detections",
        "trajectory-data",
        "emission-data",
        "trajectory-anomalies",
        "license-plates",
        "traffic-metrics"
    ]
    
    await dashboard_service.initialize_kafka(kafka_servers, kafka_topics)
    
    # Redis configuration
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    await dashboard_service.initialize_redis(redis_url)
    
    # Start Kafka message processing
    asyncio.create_task(dashboard_service.process_kafka_messages())
    
    logger.info("🚀 Enhanced Dashboard Service started")

@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    if dashboard_service.kafka_consumer:
        await dashboard_service.kafka_consumer.stop()
    if dashboard_service.redis_client:
        await dashboard_service.redis_client.close()
    logger.info("Enhanced Dashboard Service stopped")

@app.get("/")
async def root():
    """Enhanced dashboard HTML page"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ATMS Enhanced Dashboard</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                background: #0a0e27;
                color: #ffffff;
                overflow-x: hidden;
            }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 30px;
                text-align: center;
                box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            }
            .header h1 {
                font-size: 2.5em;
                margin-bottom: 10px;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
            }
            .header p {
                font-size: 1.1em;
                opacity: 0.9;
            }
            .container {
                max-width: 1600px;
                margin: 30px auto;
                padding: 0 20px;
            }
            .section {
                background: #1a1f3a;
                border-radius: 15px;
                padding: 25px;
                margin-bottom: 25px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.3);
            }
            .section-title {
                font-size: 1.5em;
                margin-bottom: 20px;
                color: #667eea;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .metrics-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
            }
            .metric-card {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 25px;
                border-radius: 12px;
                box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
                transition: transform 0.3s ease, box-shadow 0.3s ease;
            }
            .metric-card:hover {
                transform: translateY(-5px);
                box-shadow: 0 6px 25px rgba(102, 126, 234, 0.5);
            }
            .metric-value {
                font-size: 3em;
                font-weight: bold;
                margin-bottom: 5px;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
            }
            .metric-label {
                font-size: 0.9em;
                opacity: 0.9;
            }
            .status-indicator {
                width: 12px;
                height: 12px;
                border-radius: 50%;
                background: #4caf50;
                display: inline-block;
                animation: pulse 2s ease-in-out infinite;
            }
            @keyframes pulse {
                0%, 100% { opacity: 1; transform: scale(1); }
                50% { opacity: 0.7; transform: scale(1.1); }
            }
            .chart-container {
                height: 300px;
                background: #0f1425;
                border-radius: 10px;
                padding: 20px;
                margin-top: 15px;
            }
            .anomaly-list {
                max-height: 400px;
                overflow-y: auto;
            }
            .anomaly-item {
                background: #2a2f4a;
                padding: 15px;
                border-radius: 8px;
                margin-bottom: 10px;
                border-left: 4px solid #f44336;
            }
            .anomaly-header {
                display: flex;
                justify-content: space-between;
                margin-bottom: 8px;
            }
            .anomaly-track {
                font-weight: bold;
                color: #667eea;
            }
            .anomaly-time {
                font-size: 0.85em;
                opacity: 0.7;
            }
            .anomaly-reasons {
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
            }
            .anomaly-tag {
                background: #f44336;
                padding: 4px 10px;
                border-radius: 12px;
                font-size: 0.85em;
            }
            .btn {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                padding: 12px 30px;
                border-radius: 25px;
                font-size: 1em;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
                margin: 5px;
            }
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
            }
            .actions {
                text-align: center;
                margin: 20px 0;
            }
            .vehicle-breakdown {
                display: flex;
                gap: 15px;
                flex-wrap: wrap;
            }
            .vehicle-type {
                background: #2a2f4a;
                padding: 15px 20px;
                border-radius: 10px;
                flex: 1;
                min-width: 120px;
                text-align: center;
            }
            .vehicle-icon {
                font-size: 2em;
                margin-bottom: 8px;
            }
            .vehicle-count {
                font-size: 1.8em;
                font-weight: bold;
                color: #667eea;
            }
            .vehicle-label {
                font-size: 0.9em;
                opacity: 0.8;
            }
            .connection-status {
                position: fixed;
                top: 20px;
                right: 20px;
                background: #1a1f3a;
                padding: 12px 20px;
                border-radius: 25px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.3);
                display: flex;
                align-items: center;
                gap: 10px;
                z-index: 1000;
            }
        </style>
    </head>
    <body>
        <div class="connection-status">
            <div class="status-indicator"></div>
            <span>Live</span>
        </div>
        
        <div class="header">
            <h1>🚦 ATMS Complete Traffic Analysis Dashboard</h1>
            <p>Real-time AI-powered traffic monitoring and analysis</p>
        </div>
        
        <div class="container">
            <div class="actions">
                <a href="http://localhost:8008" target="_blank">
                    <button class="btn">📹 Upload Video</button>
                </a>
                <button class="btn" onclick="resetMetrics()">🔄 Reset Metrics</button>
                <button class="btn" onclick="exportData()">📊 Export Data</button>
            </div>
            
            <div class="section">
                <div class="section-title">
                    📊 Real-Time Metrics
                </div>
                <div class="metrics-grid" id="mainMetrics">
                    <div class="metric-card">
                        <div class="metric-value" id="activeVehicles">0</div>
                        <div class="metric-label">Active Vehicles</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="totalDetections">0</div>
                        <div class="metric-label">Total Detections</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="detectionsPerSec">0</div>
                        <div class="metric-label">Detections/sec</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="systemFPS">0</div>
                        <div class="metric-label">System FPS</div>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">
                    🚗 Vehicle Breakdown
                </div>
                <div class="vehicle-breakdown">
                    <div class="vehicle-type">
                        <div class="vehicle-icon">🚗</div>
                        <div class="vehicle-count" id="carCount">0</div>
                        <div class="vehicle-label">Cars</div>
                    </div>
                    <div class="vehicle-type">
                        <div class="vehicle-icon">🚚</div>
                        <div class="vehicle-count" id="truckCount">0</div>
                        <div class="vehicle-label">Trucks</div>
                    </div>
                    <div class="vehicle-type">
                        <div class="vehicle-icon">🚌</div>
                        <div class="vehicle-count" id="busCount">0</div>
                        <div class="vehicle-label">Buses</div>
                    </div>
                    <div class="vehicle-type">
                        <div class="vehicle-icon">🏍️</div>
                        <div class="vehicle-count" id="motorcycleCount">0</div>
                        <div class="vehicle-label">Motorcycles</div>
                    </div>
                    <div class="vehicle-type">
                        <div class="vehicle-icon">🚴</div>
                        <div class="vehicle-count" id="bicycleCount">0</div>
                        <div class="vehicle-label">Bicycles</div>
                    </div>
                    <div class="vehicle-type">
                        <div class="vehicle-icon">🚶</div>
                        <div class="vehicle-count" id="pedestrianCount">0</div>
                        <div class="vehicle-label">Pedestrians</div>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">
                    📈 Trajectory & Speed Analysis
                </div>
                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-value" id="activeTrajectories">0</div>
                        <div class="metric-label">Active Trajectories</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="avgSpeed">0</div>
                        <div class="metric-label">Avg Speed (km/h)</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="maxSpeed">0</div>
                        <div class="metric-label">Max Speed (km/h)</div>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">
                    🔢 License Plate Recognition
                </div>
                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-value" id="platesDetected">0</div>
                        <div class="metric-label">Plates Detected</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="platesRecognized">0</div>
                        <div class="metric-label">Plates Recognized</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="plateRecRate">0%</div>
                        <div class="metric-label">Recognition Rate</div>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">
                    💨 Emission Analysis
                </div>
                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-value" id="totalEmissions">0</div>
                        <div class="metric-label">Total CO₂ (kg)</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="avgEmission">0</div>
                        <div class="metric-label">Avg per Vehicle (g)</div>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">
                    ⚠️ Active Anomalies
                </div>
                <div class="anomaly-list" id="anomalyList">
                    <p style="text-align: center; opacity: 0.5; padding: 40px;">No anomalies detected</p>
                </div>
            </div>
        </div>

        <script>
            let ws = null;
            let reconnectInterval = null;
            
            function connectWebSocket() {
                ws = new WebSocket('ws://localhost:8009/ws');
                
                ws.onopen = () => {
                    console.log('WebSocket connected');
                    if (reconnectInterval) {
                        clearInterval(reconnectInterval);
                        reconnectInterval = null;
                    }
                };
                
                ws.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    if (data.type === 'comprehensive_metrics') {
                        updateMetrics(data.data);
                    }
                };
                
                ws.onclose = () => {
                    console.log('WebSocket disconnected');
                    if (!reconnectInterval) {
                        reconnectInterval = setInterval(connectWebSocket, 5000);
                    }
                };
                
                ws.onerror = (error) => {
                    console.error('WebSocket error:', error);
                };
            }
            
            function updateMetrics(metrics) {
                // Main metrics
                document.getElementById('activeVehicles').textContent = metrics.active_vehicles;
                document.getElementById('totalDetections').textContent = metrics.total_detections;
                document.getElementById('detectionsPerSec').textContent = metrics.detections_per_second.toFixed(1);
                document.getElementById('systemFPS').textContent = metrics.system_fps.toFixed(1);
                
                // Vehicle breakdown
                document.getElementById('carCount').textContent = metrics.cars;
                document.getElementById('truckCount').textContent = metrics.trucks;
                document.getElementById('busCount').textContent = metrics.buses;
                document.getElementById('motorcycleCount').textContent = metrics.motorcycles;
                document.getElementById('bicycleCount').textContent = metrics.bicycles;
                document.getElementById('pedestrianCount').textContent = metrics.pedestrians;
                
                // Trajectory
                document.getElementById('activeTrajectories').textContent = metrics.active_trajectories;
                document.getElementById('avgSpeed').textContent = metrics.avg_speed_kmh.toFixed(1);
                document.getElementById('maxSpeed').textContent = metrics.max_speed_kmh.toFixed(1);
                
                // License plates
                document.getElementById('platesDetected').textContent = metrics.plates_detected;
                document.getElementById('platesRecognized').textContent = metrics.plates_recognized;
                const recRate = metrics.plates_detected > 0 
                    ? (metrics.plates_recognized / metrics.plates_detected * 100).toFixed(1)
                    : 0;
                document.getElementById('plateRecRate').textContent = recRate + '%';
                
                // Emissions
                document.getElementById('totalEmissions').textContent = (metrics.total_emissions_co2 / 1000).toFixed(2);
                document.getElementById('avgEmission').textContent = metrics.avg_emission_per_vehicle.toFixed(1);
            }
            
            function resetMetrics() {
                if (confirm('Reset all metrics?')) {
                    fetch('/api/reset', { method: 'POST' })
                        .then(() => alert('Metrics reset!'))
                        .catch(err => alert('Reset failed: ' + err));
                }
            }
            
            function exportData() {
                window.open('/api/export', '_blank');
            }
            
            // Connect on load
            connectWebSocket();
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
    """Get current comprehensive metrics"""
    metrics = ComprehensiveMetrics(
        timestamp=datetime.now(),
        total_detections=dashboard_service.counters.get('total_detections', 0),
        active_vehicles=dashboard_service.counters.get('active_vehicles', 0),
        cars=dashboard_service.counters.get('class_car', 0),
        trucks=dashboard_service.counters.get('class_truck', 0),
        buses=dashboard_service.counters.get('class_bus', 0),
        motorcycles=dashboard_service.counters.get('class_motorcycle', 0),
        bicycles=dashboard_service.counters.get('class_bicycle', 0),
        pedestrians=dashboard_service.counters.get('class_pedestrian', 0),
        active_trajectories=dashboard_service.counters.get('active_trajectories', 0),
        avg_speed_kmh=dashboard_service.counters.get('avg_speed', 0.0),
        max_speed_kmh=dashboard_service.counters.get('max_speed', 0.0),
        plates_detected=dashboard_service.counters.get('plates_detected', 0),
        plates_recognized=dashboard_service.counters.get('plates_recognized', 0),
        total_emissions_co2=dashboard_service.counters.get('total_emissions', 0.0),
        active_anomalies=dashboard_service.counters.get('active_anomalies', 0)
    )
    return metrics

@app.post("/api/reset")
async def reset_metrics():
    """Reset all metrics"""
    dashboard_service.counters.clear()
    dashboard_service.recent_metrics.clear()
    dashboard_service.recent_detections.clear()
    dashboard_service.recent_plates.clear()
    dashboard_service.recent_anomalies.clear()
    dashboard_service.recent_emissions.clear()
    return {"status": "reset", "message": "All metrics reset successfully"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await dashboard_service.add_websocket(websocket)
    
    try:
        # Send initial metrics
        metrics = ComprehensiveMetrics(
            timestamp=datetime.now(),
            total_detections=dashboard_service.counters.get('total_detections', 0),
            active_vehicles=dashboard_service.counters.get('active_vehicles', 0)
        )
        await websocket.send_json({
            'type': 'comprehensive_metrics',
            'data': metrics.model_dump(mode='json')
        })
        
        # Keep connection alive
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        await dashboard_service.remove_websocket(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await dashboard_service.remove_websocket(websocket)

if __name__ == "__main__":
    uvicorn.run(
        "enhanced_dashboard:app",
        host="0.0.0.0",
        port=8009,
        log_level="info"
    )

