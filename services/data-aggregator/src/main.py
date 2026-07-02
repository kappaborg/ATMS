#!/usr/bin/env python3
"""
Data Aggregator Service
======================

Aggregates detection data from multiple sources and generates analytics.

Features:
- Kafka consumer for detections
- Data aggregation and statistics
- Real-time analytics
- Kafka producer for aggregated data
"""

import asyncio
import json
import logging
import os
import sys
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

# Make `shared.*` importable.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logging.warning("Kafka not available - running in standalone mode")

# Phase B1/B2/B3 — shared observability bootstrap.
from shared.atms_common.logging import configure_logging  # noqa: E402
from shared.atms_common.tracing import configure_tracing, instrument_fastapi  # noqa: E402

configure_logging(
    service="data-aggregator",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    intersection_id=int(os.getenv("ATMS_INTERSECTION_ID", "1")),
    level=os.getenv("LOG_LEVEL", "INFO"),
    development=os.getenv("ATMS_LOG_DEV", "").lower() in ("1", "true", "yes"),
)
configure_tracing(
    service="data-aggregator",
    version=os.getenv("SERVICE_VERSION", "1.0.0"),
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    sample_ratio=float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")),
    development=os.getenv("ATMS_OTEL_DEV", "1").lower() in ("1", "true", "yes"),
)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="Data Aggregator Service",
    description="Aggregates and analyzes traffic detection data",
    version="1.0.0"
)
instrument_fastapi(app)

class DataAggregator:
    """Aggregates detection data and generates analytics"""
    
    def __init__(self, window_size: int = 100):
        """
        Initialize data aggregator
        
        Args:
            window_size: Number of recent detections to keep
        """
        self.window_size = window_size
        self.detections = deque(maxlen=window_size)
        self.statistics = {
            'total_detections': 0,
            'detections_by_class': defaultdict(int),
            'detections_by_intersection': defaultdict(int),
            'average_confidence': 0.0,
            'last_updated': None
        }
        self.kafka_consumer: Optional[AIOKafkaConsumer] = None
        self.kafka_producer: Optional[AIOKafkaProducer] = None
        
        logger.info("Data Aggregator initialized")
    
    async def start_kafka(self, bootstrap_servers: str = "localhost:9092"):
        """Start Kafka consumer and producer"""
        if not KAFKA_AVAILABLE:
            logger.warning("Kafka not available - skipping Kafka initialization")
            return
        
        try:
            # Initialize consumer
            self.kafka_consumer = AIOKafkaConsumer(
                'detections',
                'trajectory-data',
                'emission-data',
                bootstrap_servers=bootstrap_servers,
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                group_id='data-aggregator-group',
                auto_offset_reset='latest'
            )
            
            # Initialize producer
            self.kafka_producer = AIOKafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
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
        if not self.kafka_consumer:
            logger.warning("Kafka consumer not initialized")
            return
        
        try:
            async for message in self.kafka_consumer:
                await self.process_message(message.topic, message.value)
        except Exception as e:
            logger.error(f"Error consuming messages: {e}")
    
    async def process_message(self, topic: str, data: Dict):
        """Process incoming message"""
        try:
            if topic == 'detections':
                await self.process_detection(data)
            elif topic == 'trajectory-data':
                await self.process_trajectory(data)
            elif topic == 'emission-data':
                await self.process_emission(data)
        except Exception as e:
            logger.error(f"Error processing message from {topic}: {e}")
    
    async def process_detection(self, detection: Dict):
        """Process detection data"""
        # Add to recent detections
        self.detections.append({
            'timestamp': detection.get('timestamp', datetime.now().isoformat()),
            'class': detection.get('object_class', 'unknown'),
            'confidence': detection.get('confidence', 0.0),
            'intersection_id': detection.get('intersection_id', 0)
        })
        
        # Update statistics
        self.statistics['total_detections'] += 1
        self.statistics['detections_by_class'][detection.get('object_class', 'unknown')] += 1
        self.statistics['detections_by_intersection'][detection.get('intersection_id', 0)] += 1
        
        # Calculate average confidence
        if self.detections:
            total_conf = sum(d['confidence'] for d in self.detections)
            self.statistics['average_confidence'] = total_conf / len(self.detections)
        
        self.statistics['last_updated'] = datetime.now().isoformat()
        
        # Publish aggregated data periodically
        if self.statistics['total_detections'] % 10 == 0:
            await self.publish_analytics()
    
    async def process_trajectory(self, trajectory: Dict):
        """Process trajectory data"""
        logger.debug(f"Processing trajectory data: {trajectory.get('track_id')}")
    
    async def process_emission(self, emission: Dict):
        """Process emission data"""
        logger.debug(f"Processing emission data: {emission.get('vehicle_id')}")
    
    async def publish_analytics(self):
        """Publish aggregated analytics to Kafka"""
        if not self.kafka_producer:
            return
        
        try:
            analytics = {
                'timestamp': datetime.now().isoformat(),
                'statistics': dict(self.statistics),
                'recent_detections_count': len(self.detections)
            }
            
            await self.kafka_producer.send(
                'traffic-metrics',
                value=analytics
            )
            
            logger.info(f"Published analytics: {analytics['statistics']['total_detections']} total detections")
        except Exception as e:
            logger.error(f"Error publishing analytics: {e}")
    
    def get_statistics(self) -> Dict:
        """Get current statistics"""
        return {
            **self.statistics,
            'detections_by_class': dict(self.statistics['detections_by_class']),
            'detections_by_intersection': dict(self.statistics['detections_by_intersection']),
            'recent_detections_count': len(self.detections)
        }
    
    def get_recent_detections(self, limit: int = 10) -> List[Dict]:
        """Get recent detections"""
        return list(self.detections)[-limit:]

# Global aggregator instance
aggregator = DataAggregator()

# FastAPI endpoints
@app.on_event("startup")
async def startup_event():
    """Startup event handler"""
    logger.info("Starting Data Aggregator Service...")
    await aggregator.start_kafka()
    
    # Start background task for consuming messages
    if KAFKA_AVAILABLE and aggregator.kafka_consumer:
        asyncio.create_task(aggregator.consume_messages())
    
    logger.info("Data Aggregator Service started successfully")

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler"""
    logger.info("Stopping Data Aggregator Service...")
    await aggregator.stop_kafka()
    logger.info("Data Aggregator Service stopped")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Data Aggregator Service",
        "version": "1.0.0",
        "status": "operational",
        "kafka_available": KAFKA_AVAILABLE
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "kafka_connected": aggregator.kafka_consumer is not None
    }

@app.get("/statistics")
async def get_statistics():
    """Get current statistics"""
    return JSONResponse(content=aggregator.get_statistics())

@app.get("/detections/recent")
async def get_recent_detections(limit: int = 10):
    """Get recent detections"""
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 100")
    
    return JSONResponse(content={
        "detections": aggregator.get_recent_detections(limit),
        "count": len(aggregator.get_recent_detections(limit))
    })

@app.post("/aggregate/publish")
async def publish_analytics():
    """Manually trigger analytics publication"""
    await aggregator.publish_analytics()
    return {"status": "published", "timestamp": datetime.now().isoformat()}

def main():
    """Main entry point"""
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info"
    )

if __name__ == "__main__":
    main()
