"""
Sensor Fusion Service - Main Application
Week 1: Complete Implementation with FastAPI
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, List
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from fastapi.responses import Response
import time

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))
from shared.utils.logger import setup_logger
from shared.models.base import HealthResponse

from config import sensor_fusion_config, camera_config
from adapters.camera import CameraAdapter
from adapters.mjpeg_camera import MJPEGCameraAdapter
from kafka.producer import KafkaProducerManager
from sync.synchronizer import FrameSynchronizer

# Initialize logger
logger = setup_logger(
    service_name=sensor_fusion_config.SERVICE_NAME,
    level=sensor_fusion_config.LOG_LEVEL
)

# Prometheus metrics - using try/except to avoid duplicate registration during reload
try:
    frames_processed = Counter(
        'sensor_fusion_frames_processed_total',
        'Total frames processed',
        ['camera_id']
    )
    frames_synced = Counter(
        'sensor_fusion_frames_synced_total',
        'Total synchronized frame sets'
    )
    processing_time = Histogram(
        'sensor_fusion_processing_seconds',
        'Frame processing time'
    )
    active_cameras = Gauge(
        'sensor_fusion_active_cameras',
        'Number of active cameras'
    )
except ValueError:
    # Metrics already registered (happens with uvicorn reload)
    from prometheus_client import REGISTRY
    frames_processed = REGISTRY._names_to_collectors.get('sensor_fusion_frames_processed_total')
    frames_synced = REGISTRY._names_to_collectors.get('sensor_fusion_frames_synced_total')
    processing_time = REGISTRY._names_to_collectors.get('sensor_fusion_processing_seconds')
    active_cameras = REGISTRY._names_to_collectors.get('sensor_fusion_active_cameras')

# Global state
cameras: Dict[str, CameraAdapter] = {}
kafka_producer: KafkaProducerManager = None
synchronizer: FrameSynchronizer = None
processing_task: asyncio.Task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global cameras, kafka_producer, synchronizer, processing_task
    
    logger.info("Starting Sensor Fusion Service...")
    
    try:
        # Initialize Kafka producer
        kafka_producer = KafkaProducerManager(
            bootstrap_servers=sensor_fusion_config.KAFKA_BOOTSTRAP_SERVERS,
            client_id=sensor_fusion_config.SERVICE_NAME
        )
        try:
            await kafka_producer.start()
        except Exception as kafka_error:
            logger.warning(f"Kafka connection failed, continuing in mock mode: {kafka_error}")
            # Service continues to run in mock mode without Kafka
        
        # Initialize cameras
        if sensor_fusion_config.ENABLE_CAMERAS:
            for camera_id in camera_config.CAMERA_IDS:
                rtsp_url = camera_config.RTSP_URLS.get(camera_id)
                
                if rtsp_url:
                    # Get rotation setting for this camera (default to 0 if not specified)
                    rotation = camera_config.CAMERA_ROTATIONS.get(camera_id, 0)
                    
                    # Get auth credentials for this camera (default to empty tuple if not specified)
                    auth = camera_config.CAMERA_AUTH.get(camera_id, ("", ""))
                    
                    # Use MJPEGCameraAdapter for HTTP streams (more reliable on macOS)
                    if rtsp_url.startswith('http'):
                        camera = MJPEGCameraAdapter(
                            camera_id=camera_id,
                            mjpeg_url=rtsp_url,
                            resolution=camera_config.CAMERA_RESOLUTION,
                            fps=camera_config.CAMERA_FPS,
                            reconnect_delay=camera_config.RECONNECT_DELAY,
                            max_reconnect_attempts=camera_config.MAX_RECONNECT_ATTEMPTS,
                            rotation=rotation,
                            auth=auth if auth[0] and auth[1] else None
                        )
                    else:
                        # Use regular CameraAdapter for RTSP streams
                        camera = CameraAdapter(
                            camera_id=camera_id,
                            rtsp_url=rtsp_url,
                            resolution=camera_config.CAMERA_RESOLUTION,
                            fps=camera_config.CAMERA_FPS,
                            buffer_size=camera_config.FRAME_BUFFER_SIZE,
                            reconnect_delay=camera_config.RECONNECT_DELAY,
                            max_reconnect_attempts=camera_config.MAX_RECONNECT_ATTEMPTS,
                            rotation=rotation
                        )
                    
                    # Connect camera
                    if await camera.connect():
                        cameras[camera_id] = camera
                        active_cameras.inc()
                        logger.info(f"Camera {camera_id} initialized")
                    else:
                        logger.error(f"Failed to initialize camera {camera_id}")
        
        # Initialize synchronizer
        if cameras:
            synchronizer = FrameSynchronizer(
                camera_ids=list(cameras.keys()),
                sync_threshold_ms=100,
                buffer_size=30
            )
            logger.info("Frame synchronizer initialized")
        
        # Start background processing
        processing_task = asyncio.create_task(process_frames())
        
        logger.info("Sensor Fusion Service started successfully")
        
        yield
        
    finally:
        logger.info("Shutting down Sensor Fusion Service...")
        
        # Cancel processing task
        if processing_task:
            processing_task.cancel()
            try:
                await processing_task
            except asyncio.CancelledError:
                pass
        
        # Disconnect cameras
        for camera_id, camera in cameras.items():
            await camera.disconnect()
            logger.info(f"Camera {camera_id} disconnected")
        
        # Stop Kafka producer
        if kafka_producer:
            await kafka_producer.stop()
        
        logger.info("Sensor Fusion Service stopped")


# Create FastAPI app
app = FastAPI(
    title="ATMS Sensor Fusion Service",
    version=sensor_fusion_config.SERVICE_VERSION,
    lifespan=lifespan
)


async def process_frames():
    """Background task to process camera frames"""
    logger.info("Starting frame processing loop...")
    
    try:
        while True:
            start_time = time.time()
            
            # Read frames from all cameras
            for camera_id, camera in cameras.items():
                # TODO: Make intersection_id configurable per camera
                frame = await camera.read_frame(intersection_id=1)
                
                if frame:
                    # Add to synchronizer
                    synchronizer.add_frame(camera_id, frame)
                    frames_processed.labels(camera_id=camera_id).inc()
            
            # Get synchronized frames
            if synchronizer:
                synced_frames = synchronizer.get_synchronized_frames()
                
                if synced_frames:
                    # Send to Kafka
                    for camera_id, frame in synced_frames.items():
                        await kafka_producer.send_camera_frame(
                            topic=sensor_fusion_config.KAFKA_TOPIC_CAMERA_FRAMES,
                            camera_frame=frame,
                            intersection_id=1  # TODO: Make configurable
                        )
                    
                    frames_synced.inc()
                    
                    logger.debug(
                        "Synchronized frames sent",
                        camera_count=len(synced_frames)
                    )
                
                # Cleanup old frames
                synchronizer.cleanup_old_frames()
            
            # Record processing time
            processing_time.observe(time.time() - start_time)
            
            # Small delay to prevent tight loop
            await asyncio.sleep(0.01)
            
    except asyncio.CancelledError:
        logger.info("Frame processing task cancelled")
        raise
    except Exception as e:
        logger.error(f"Error in frame processing: {e}", exc_info=True)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": sensor_fusion_config.SERVICE_NAME,
        "version": sensor_fusion_config.SERVICE_VERSION,
        "status": "running"
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    # Check camera status
    camera_status = {
        camera_id: camera.is_connected
        for camera_id, camera in cameras.items()
    }
    
    # Check Kafka status
    kafka_status = kafka_producer.is_connected if kafka_producer else False
    
    # Determine overall status
    all_healthy = all(camera_status.values()) and kafka_status
    status = "healthy" if all_healthy else "degraded"
    
    return HealthResponse(
        status=status,
        service=sensor_fusion_config.SERVICE_NAME,
        version=sensor_fusion_config.SERVICE_VERSION,
        details={
            "cameras": camera_status,
            "kafka": kafka_status,
            "active_cameras": len([c for c in camera_status.values() if c])
        }
    )


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(
        content=generate_latest(),
        media_type="text/plain"
    )


@app.get("/cameras")
async def list_cameras():
    """List all cameras and their status"""
    camera_list = []
    
    for camera_id, camera in cameras.items():
        stats = await camera.get_stats()
        camera_list.append(stats)
    
    return {"cameras": camera_list}


@app.get("/cameras/{camera_id}")
async def get_camera_status(camera_id: str):
    """Get specific camera status"""
    if camera_id not in cameras:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    camera = cameras[camera_id]
    return await camera.get_stats()


@app.get("/sync/status")
async def get_sync_status():
    """Get synchronizer status"""
    if not synchronizer:
        raise HTTPException(status_code=503, detail="Synchronizer not initialized")
    
    return synchronizer.get_stats()


@app.get("/kafka/status")
async def get_kafka_status():
    """Get Kafka producer status"""
    if not kafka_producer:
        raise HTTPException(status_code=503, detail="Kafka producer not initialized")
    
    return await kafka_producer.get_stats()


@app.post("/cameras/{camera_id}/reconnect")
async def reconnect_camera(camera_id: str):
    """Reconnect a specific camera"""
    if camera_id not in cameras:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    camera = cameras[camera_id]
    
    # Disconnect and reconnect
    await camera.disconnect()
    success = await camera.connect()
    
    if success:
        return {"status": "reconnected", "camera_id": camera_id}
    else:
        raise HTTPException(status_code=500, detail="Failed to reconnect camera")


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=sensor_fusion_config.API_HOST,
        port=sensor_fusion_config.API_PORT,
        reload=True,
        log_level=sensor_fusion_config.LOG_LEVEL.lower()
    )

