#!/usr/bin/env python3
"""
Analytics Service
Phase 4 - Week 15-16: Analytics and BI Dashboards

Features:
- Traffic pattern analysis
- Predictive maintenance
- BI dashboards
- Analytics API
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))
sys.path.append(str(Path(__file__).parent))

from atms_config import get_atms_runtime_config

# Phase B1/B2/B3 — shared observability bootstrap.
import os
from shared.atms_common.logging import configure_logging
from shared.atms_common.tracing import configure_tracing, instrument_fastapi

configure_logging(
    service="analytics",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    intersection_id=int(os.getenv("ATMS_INTERSECTION_ID", "1")),
    level=os.getenv("LOG_LEVEL", "INFO"),
    development=os.getenv("ATMS_LOG_DEV", "").lower() in ("1", "true", "yes"),
)
configure_tracing(
    service="analytics",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    sample_ratio=float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")),
    development=os.getenv("ATMS_OTEL_DEV", "1").lower() in ("1", "true", "yes"),
)

# Import new analytics modules
try:
    from traffic_analyzer import (
        TrafficPatternAnalyzer as PatternAnalyzer,
        PredictiveMaintenance,
        TrendAnalyzer
    )
    NEW_ANALYTICS_AVAILABLE = True
except ImportError:
    NEW_ANALYTICS_AVAILABLE = False
    PatternAnalyzer = None
    PredictiveMaintenance = None
    TrendAnalyzer = None
    logging.warning("New analytics modules not available")
sys.path.append(str(Path(__file__).parent))

# Import analyzers
from traffic_analyzer import (
    TrafficPatternAnalyzer,
    PredictiveMaintenance,
    TrendAnalyzer,
    TrafficPattern,
    MaintenancePrediction
)

# Kafka imports
try:
    from aiokafka import AIOKafkaConsumer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logging.warning("Kafka not available")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

class TrafficMetricsInput(BaseModel):
    """Input for traffic metrics"""
    intersection_id: str
    vehicle_count: int
    average_speed: float
    congestion_level: float
    timestamp: Optional[datetime] = None


class ComponentMetricInput(BaseModel):
    """Input for component metrics"""
    component: str
    error: bool
    error_count: int
    uptime: float
    timestamp: Optional[datetime] = None


# ============================================================================
# Analytics Service
# ============================================================================

class AnalyticsService:
    """Main analytics service"""
    
    def __init__(self):
        self.pattern_analyzer = TrafficPatternAnalyzer()
        self.maintenance_predictor = PredictiveMaintenance()
        self.trend_analyzer = TrendAnalyzer()
        self.kafka_consumer: Optional[AIOKafkaConsumer] = None
    
    async def initialize_kafka(self):
        """Initialize Kafka consumer"""
        runtime_cfg = get_atms_runtime_config()
        if not runtime_cfg.enable_kafka:
            logger.info(
                f"ATMS run mode: {runtime_cfg.run_mode.value} -> Kafka disabled (offline mode)"
            )
            return False

        if not KAFKA_AVAILABLE:
            return False
        
        try:
            import os
            kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
            
            self.kafka_consumer = AIOKafkaConsumer(
                'traffic-metrics',
                'detections',
                bootstrap_servers=kafka_servers,
                group_id='analytics-service',
                value_deserializer=lambda m: m.decode('utf-8') if isinstance(m, bytes) else m
            )
            await self.kafka_consumer.start()
            logger.info("✅ Kafka consumer initialized")
            
            # Start consuming
            asyncio.create_task(self._consume_metrics())
            return True
        except Exception as e:
            logger.error(f"❌ Kafka initialization failed: {e}")
            return False
    
    async def _consume_metrics(self):
        """Consume metrics from Kafka"""
        if not self.kafka_consumer:
            return
        
        try:
            async for message in self.kafka_consumer:
                try:
                    import json
                    data = json.loads(message.value) if isinstance(message.value, str) else message.value
                    
                    # Process traffic metrics
                    if message.topic == 'traffic-metrics':
                        await self.process_traffic_metrics(data)
                    elif message.topic == 'detections':
                        await self.process_detections(data)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
        except Exception as e:
            logger.error(f"Error consuming metrics: {e}")
    
    async def process_traffic_metrics(self, data: Dict):
        """Process traffic metrics data"""
        try:
            timestamp = datetime.fromisoformat(data.get('timestamp', datetime.utcnow().isoformat()))
            hour = timestamp.hour
            day_of_week = timestamp.weekday()
            
            pattern = TrafficPattern(
                time_of_day=hour,
                day_of_week=day_of_week,
                vehicle_count=data.get('vehicle_count', 0),
                average_speed=data.get('average_speed', 0.0),
                congestion_level=data.get('congestion_level', 0.0),
                peak_hour=(hour in [7, 8, 17, 18])  # Rush hours
            )
            
            self.pattern_analyzer.add_pattern(pattern)
            
            # Add to trend analyzer
            self.trend_analyzer.add_data_point(
                timestamp,
                data.get('vehicle_count', 0),
                'vehicle_count'
            )
        except Exception as e:
            logger.error(f"Error processing traffic metrics: {e}")
    
    async def process_detections(self, data: Dict):
        """Process detection data"""
        # Extract component health metrics if available
        if 'component_health' in data:
            for component, metrics in data['component_health'].items():
                self.maintenance_predictor.add_component_metric(component, metrics)


# ============================================================================
# FastAPI Application
# ============================================================================

analytics_service = AnalyticsService()
app = FastAPI(
    title="Analytics Service",
    version="1.0.0",
    description="Traffic analytics, predictive maintenance, and BI dashboards"
)
instrument_fastapi(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    """Initialize on startup"""
    await analytics_service.initialize_kafka()
    logger.info("✅ Analytics Service started")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    if analytics_service.kafka_consumer:
        await analytics_service.kafka_consumer.stop()
    logger.info("Analytics Service stopped")


@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "service": "analytics",
        "kafka_available": KAFKA_AVAILABLE
    }


@app.post("/metrics/traffic")
async def add_traffic_metrics(metrics: TrafficMetricsInput):
    """Add traffic metrics"""
    if not metrics.timestamp:
        metrics.timestamp = datetime.utcnow()
    
    await analytics_service.process_traffic_metrics(metrics.dict())
    return {"status": "added"}


@app.post("/metrics/component")
async def add_component_metrics(metrics: ComponentMetricInput):
    """Add component metrics"""
    if not metrics.timestamp:
        metrics.timestamp = datetime.utcnow()
    
    analytics_service.maintenance_predictor.add_component_metric(
        metrics.component,
        metrics.dict()
    )
    return {"status": "added"}


@app.get("/analytics/daily-patterns")
async def get_daily_patterns():
    """Get daily traffic patterns"""
    return analytics_service.pattern_analyzer.analyze_daily_patterns()


@app.get("/analytics/weekly-patterns")
async def get_weekly_patterns():
    """Get weekly traffic patterns"""
    return analytics_service.pattern_analyzer.analyze_weekly_patterns()


@app.get("/analytics/predict/{day_of_week}/{hour}")
async def predict_traffic(day_of_week: int, hour: int):
    """Predict traffic for specific time"""
    if day_of_week < 0 or day_of_week > 6:
        raise HTTPException(status_code=400, detail="day_of_week must be 0-6")
    if hour < 0 or hour > 23:
        raise HTTPException(status_code=400, detail="hour must be 0-23")
    
    return analytics_service.pattern_analyzer.predict_traffic(day_of_week, hour)


@app.get("/maintenance/predictions")
async def get_maintenance_predictions():
    """Get all maintenance predictions"""
    predictions = analytics_service.maintenance_predictor.get_all_predictions()
    return {
        "predictions": [
            {
                "component": p.component,
                "predicted_failure_date": p.predicted_failure_date.isoformat(),
                "confidence": p.confidence,
                "maintenance_type": p.maintenance_type,
                "priority": p.priority
            }
            for p in predictions
        ]
    }


@app.get("/maintenance/predictions/{component}")
async def get_component_prediction(component: str):
    """Get maintenance prediction for specific component"""
    prediction = analytics_service.maintenance_predictor.predict_maintenance(component)
    if not prediction:
        raise HTTPException(status_code=404, detail="No prediction available")
    
    return {
        "component": prediction.component,
        "predicted_failure_date": prediction.predicted_failure_date.isoformat(),
        "confidence": prediction.confidence,
        "maintenance_type": prediction.maintenance_type,
        "priority": prediction.priority
    }


@app.get("/trends/{metric}")
async def get_trend(metric: str, days: int = 7):
    """Get trend analysis for a metric"""
    return analytics_service.trend_analyzer.calculate_trend(metric, days)


@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    """Get BI dashboard HTML"""
    dashboard_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Traffic Analytics Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .dashboard { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }
            .card { border: 1px solid #ddd; padding: 20px; border-radius: 8px; }
            h1, h2 { color: #333; }
        </style>
    </head>
    <body>
        <h1>Traffic Analytics Dashboard</h1>
        <div class="dashboard">
            <div class="card">
                <h2>Daily Patterns</h2>
                <canvas id="dailyChart"></canvas>
            </div>
            <div class="card">
                <h2>Weekly Patterns</h2>
                <canvas id="weeklyChart"></canvas>
            </div>
            <div class="card">
                <h2>Maintenance Predictions</h2>
                <div id="maintenance"></div>
            </div>
            <div class="card">
                <h2>Trends</h2>
                <canvas id="trendChart"></canvas>
            </div>
        </div>
        <script>
            // Load dashboard data
            fetch('/analytics/daily-patterns')
                .then(r => r.json())
                .then(data => {
                    // Render daily patterns chart
                    const ctx = document.getElementById('dailyChart').getContext('2d');
                    new Chart(ctx, {
                        type: 'line',
                        data: {
                            labels: Object.keys(data.hourly_statistics || {}),
                            datasets: [{
                                label: 'Average Vehicles',
                                data: Object.values(data.hourly_statistics || {}).map(s => s.average)
                            }]
                        }
                    });
                });
            
            // Load maintenance predictions
            fetch('/maintenance/predictions')
                .then(r => r.json())
                .then(data => {
                    const div = document.getElementById('maintenance');
                    data.predictions.forEach(p => {
                        div.innerHTML += `<p><strong>${p.component}</strong>: ${p.priority} priority (${(p.confidence*100).toFixed(0)}% confidence)</p>`;
                    });
                });
        </script>
    </body>
    </html>
    """
    return dashboard_html


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8009,
        reload=True,
        log_level="info"
    )
