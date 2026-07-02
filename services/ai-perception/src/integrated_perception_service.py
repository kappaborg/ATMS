#!/usr/bin/env python3
"""
Integrated AI Perception Service
================================

Complete perception service integrating all trained models with Kafka and FastAPI.

Features:
- Multi-view vehicle detection (top, side, front bumper)
- License plate recognition
- Real-time frame synchronization
- Kafka publishing
- Database integration
- Redis caching
- REST API endpoints
"""

import asyncio
import cv2
import json
import logging
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn
import numpy as np
import json as _json

def convert_numpy_types(obj):
    """
    Recursively convert numpy types to Python native types for JSON serialization
    """
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return [convert_numpy_types(item) for item in obj.tolist()]
    elif isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(convert_numpy_types(item) for item in obj)
    else:
        return obj

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

try:
    from multi_view_fusion_system import MultiViewFusionSystem
    MULTIVIEW_AVAILABLE = True
except ImportError:
    MULTIVIEW_AVAILABLE = False
    logging.warning("Multi-view fusion system not available")

# Try to import optimized version
try:
    from multi_view_fusion_system_optimized import MultiViewFusionSystem as OptimizedMultiViewFusionSystem
    USE_OPTIMIZED = True
    logging.info("✅ Optimized multi-view fusion system available.")
except ImportError:
    USE_OPTIMIZED = False
    logging.warning("Optimized multi-view fusion system not available, falling back to original.")

try:
    import sys
    import os
    # Add parent directories to path
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))
    from trajectory_tracking_system import TrajectoryTracker
    TRAJECTORY_AVAILABLE = True
except ImportError as e:
    TRAJECTORY_AVAILABLE = False
    logging.warning(f"Trajectory tracking system not available: {e}")

try:
    from emission_calculation_system import EmissionCalculator
    EMISSION_AVAILABLE = True
except ImportError:
    EMISSION_AVAILABLE = False
    logging.warning("Emission calculation system not available")

try:
    # Trajectory anomaly detection (rules + IsolationForest)
    from trajectory_anomaly_detection import (
        TrajectoryAnomalyDetector,
        RuleThresholds,
        LiveVideoAnomalyMonitor,
    )
    ANOMALY_AVAILABLE = True
except ImportError:
    ANOMALY_AVAILABLE = False
    logging.warning("Trajectory anomaly detection not available")

try:
    from aiokafka import AIOKafkaProducer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logging.warning("Kafka not available")

try:
    from database.database import db
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False
    logging.warning("Database not available")

try:
    from database.redis_cache import cache
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    logging.warning("Redis cache not available")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="AI Perception Service",
    description="Integrated AI perception with multi-view detection",
    version="3.0.0"
)

# Pydantic models
class CameraConfig(BaseModel):
    """Camera configuration"""
    camera_id: int = 0
    camera_url: Optional[str] = None
    width: int = 640
    height: int = 480
    fps: int = 30

class DetectionStats(BaseModel):
    """Detection statistics"""
    total_detections: int
    fps: float
    detections_by_class: Dict[str, int]
    average_confidence: float

class IntegratedPerceptionService:
    """Integrated AI perception service"""
    
    def __init__(self):
        """Initialize integrated perception service"""
        self.intersection_id = 1
        self.camera_id = 1
        
        # Model paths
        self.model_paths = {
            "top_view": "/Users/kappasutra/Traffic/multiview_models/top_view_model/weights/best.mlpackage",
            "side_profile": "/Users/kappasutra/Traffic/multiview_models/side_profile_model/weights/best.mlpackage",
            "front_bumper": "/Users/kappasutra/Traffic/multiview_models/front_bumper_model/weights/best.mlpackage",
            "license_plate": "/Users/kappasutra/Traffic/models/license_plate_training/outputs/license_plate_model_mps/weights/best.mlpackage"
        }
        
        # Initialize components
        self.fusion_system = None
        self.trajectory_tracker = None
        self.emission_calculator = None
        
        # Kafka producer
        self.kafka_producer: Optional[AIOKafkaProducer] = None
        
        # Camera
        self.camera = None
        self.is_running = False
        self.frame_count = 0
        self.start_time = time.time()
        
        # Statistics
        self.stats = {
            'total_detections': 0,
            'detections_by_class': {},
            'total_frames_processed': 0,
            'average_fps': 0.0,
            'average_confidence': 0.0
        }
        
        # Thread pool for async operations
        self.executor = ThreadPoolExecutor(max_workers=4)

        # Anomaly detection configuration
        self.enable_anomaly_detection = True
        # defaults; will be overridden by config if present
        self.anomaly_rule_thresholds = RuleThresholds(
            max_speed_mps=40.0,
            max_accel_mps2=6.0,
            max_heading_change_deg=60.0,
            max_jitter_px=30.0,
            min_stop_time_s=-1.0,
        )
        self.anomaly_detector = None
        self.anomaly_monitor = None
        self.pixels_per_meter: Optional[float] = None
        self.lane_polygons: Dict[str, List[List[float]]] = {}
        self.iforest_enabled = False
        self.iforest_warmup = 512

        # Load anomaly config JSON if exists
        try:
            cfg_path = Path('/Users/kappasutra/Traffic/config/anomaly_config.json')
            if cfg_path.exists():
                with open(cfg_path, 'r') as f:
                    cfg = _json.load(f)
                self.enable_anomaly_detection = bool(cfg.get('enabled', True))
                rt = cfg.get('rule_thresholds', {})
                self.anomaly_rule_thresholds = RuleThresholds(
                    max_speed_mps=float(rt.get('max_speed_mps', 40.0)),
                    max_accel_mps2=float(rt.get('max_accel_mps2', 6.0)),
                    max_heading_change_deg=float(rt.get('max_heading_change_deg', 60.0)),
                    max_jitter_px=float(rt.get('max_jitter_px', 30.0)),
                    min_stop_time_s=float(rt.get('min_stop_time_s', -1.0)),
                )
                self.iforest_enabled = bool(cfg.get('use_isolation_forest', False))
                self.iforest_warmup = int(cfg.get('iforest_warmup', 512))
                # camera-specific settings
                cam_cfg = cfg.get('cameras', {}).get(str(self.camera_id), {})
                self.pixels_per_meter = cam_cfg.get('pixels_per_meter')
                self.lane_polygons = cam_cfg.get('lane_polygons', {})
        except Exception as e:
            logger.warning(f"Failed to load anomaly config: {e}")
        
        logger.info("Integrated Perception Service initialized")

        # in-memory anomaly ring buffer for dashboard
        from collections import deque as _deque
        self._recent_anomalies = _deque(maxlen=500)
    
    async def initialize_models(self):
        """Initialize all AI models"""
        logger.info("Initializing AI models...")
        
        try:
            # Check which models exist
            available_models = {}
            for view_type, path in self.model_paths.items():
                if Path(path).exists():
                    available_models[view_type] = path
                    logger.info(f"✅ Found {view_type} model: {path}")
                else:
                    logger.warning(f"❌ Missing {view_type} model: {path}")
            
            if not available_models:
                logger.error("No models available!")
                return False
            
            # Initialize multi-view fusion (exclude license plate for now)
            multiview_models = {k: v for k, v in available_models.items() if k != 'license_plate'}
            
            if multiview_models and MULTIVIEW_AVAILABLE:
                if USE_OPTIMIZED:
                    # Use optimized version with parallel inference
                    self.fusion_system = OptimizedMultiViewFusionSystem(
                        multiview_models,
                        device="auto",
                        enable_parallel=True
                    )
                    logger.info(f"✅ Optimized multi-view fusion initialized with {len(multiview_models)} models (parallel mode)")
                else:
                    self.fusion_system = MultiViewFusionSystem(multiview_models)
                    logger.info(f"✅ Multi-view fusion initialized with {len(multiview_models)} models")
            
            # Initialize trajectory tracker
            if TRAJECTORY_AVAILABLE:
                self.trajectory_tracker = TrajectoryTracker()
                logger.info("✅ Trajectory tracker initialized")
            
            # Initialize emission calculator
            if EMISSION_AVAILABLE:
                self.emission_calculator = EmissionCalculator()
                logger.info("✅ Emission calculator initialized")

            # Initialize anomaly detector
            if ANOMALY_AVAILABLE and self.enable_anomaly_detection:
                self.anomaly_detector = TrajectoryAnomalyDetector(
                    rule_thresholds=self.anomaly_rule_thresholds,
                    use_isolation_forest=self.iforest_enabled,
                    warmup_size=self.iforest_warmup,
                    pixels_per_meter=self.pixels_per_meter,
                    lane_polygons=self.lane_polygons,
                )
                self.anomaly_monitor = LiveVideoAnomalyMonitor(self.anomaly_detector)
                logger.info("✅ Trajectory anomaly detector initialized")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize models: {e}")
            return False
    
    async def start_kafka(self, bootstrap_servers: str = "localhost:9092"):
        """Start Kafka producer"""
        if not KAFKA_AVAILABLE:
            logger.warning("Kafka not available")
            return
        
        try:
            self.kafka_producer = AIOKafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            await self.kafka_producer.start()
            logger.info("✅ Kafka producer started")
        except Exception as e:
            logger.error(f"Failed to start Kafka producer: {e}")
    
    async def stop_kafka(self):
        """Stop Kafka producer"""
        if self.kafka_producer:
            await self.kafka_producer.stop()
            logger.info("Kafka producer stopped")
    
    async def start_database(self):
        """Initialize database connections"""
        if DATABASE_AVAILABLE:
            try:
                await db.connect()
                logger.info("✅ Database connected")
            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
        
        if CACHE_AVAILABLE:
            try:
                await cache.connect()
                logger.info("✅ Redis cache connected")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
    
    async def stop_database(self):
        """Close database connections"""
        if DATABASE_AVAILABLE:
            await db.close()
        if CACHE_AVAILABLE:
            await cache.close()
    
    def initialize_camera(self, camera_id: int = 0, camera_url: Optional[str] = None):
        """Initialize camera"""
        try:
            if camera_url:
                self.camera = cv2.VideoCapture(camera_url)
            else:
                self.camera = cv2.VideoCapture(camera_id)
            
            if not self.camera.isOpened():
                logger.error("Failed to open camera")
                return False
            
            # Set camera properties
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.camera.set(cv2.CAP_PROP_FPS, 30)
            
            logger.info(f"✅ Camera initialized (ID: {camera_id})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize camera: {e}")
            return False
    
    def stop_camera(self):
        """Stop camera"""
        if self.camera:
            self.camera.release()
            logger.info("Camera stopped")
    
    async def process_frame(self, frame: np.ndarray, frame_id: int) -> Dict:
        """Process single frame with all models"""
        try:
            timestamp = datetime.now()
            
            # Run multi-view detection (use async if available)
            detections = []
            if self.fusion_system:
                # Try async version first (optimized)
                if hasattr(self.fusion_system, 'detect_vehicles_async'):
                    fused_detections = await self.fusion_system.detect_vehicles_async(frame)
                else:
                    fused_detections = self.fusion_system.detect_vehicles(frame)
                # Convert FusedDetection objects to dictionaries
                detections = [
                    {
                        'bbox': list(d.bbox),
                        'confidence': d.confidence,
                        'class_id': d.class_id,
                        'class_name': d.class_name,
                        'contributing_views': d.contributing_views,
                        'fusion_confidence': d.fusion_confidence,
                        'timestamp': d.timestamp.isoformat()
                    }
                    for d in fused_detections
                ]
            
            # Update trajectory tracking
            trajectory_objects = []
            if self.trajectory_tracker and detections:
                # Convert detections to tracking format with view_type
                tracking_detections = [
                    {
                        'bbox': d['bbox'],
                        'confidence': d['confidence'],
                        'class_name': d['class_name'],
                        'view_type': d.get('contributing_views', ['unknown'])[0] if d.get('contributing_views') else 'unknown'
                    }
                    for d in detections
                ]
                trajectory_objects = self.trajectory_tracker.update(tracking_detections)
            
            # Convert VehicleTrack objects to dictionaries (optimized conversion)
            trajectories = []
            if trajectory_objects:
                # Try optimized converter if available
                try:
                    from optimized_trajectory_converter import optimize_trajectory_dict, convert_numpy_types_optimized
                    use_optimized = True
                except ImportError:
                    use_optimized = False
                
                for t in trajectory_objects:
                    if use_optimized:
                        # Use optimized conversion (faster)
                        traj_dict = optimize_trajectory_dict(t)
                        traj_dict = convert_numpy_types_optimized(traj_dict)
                    else:
                        # Fallback to original conversion
                        velocity_vec = [0.0, 0.0]
                        if len(t.positions) >= 2:
                            dx = float(t.positions[-1][0] - t.positions[-2][0])
                            dy = float(t.positions[-1][1] - t.positions[-2][1])
                            velocity_vec = [dx, dy]
                        
                        traj_dict = {
                            'track_id': int(t.track_id),
                            'class_name': str(t.class_name),
                            'last_position': [float(x) for x in t.positions[-1]] if t.positions else None,
                            'velocity': velocity_vec,
                            'velocity_magnitude': float(t.velocities[-1]) if t.velocities else 0.0,
                            'confidence': float(t.confidences[-1]) if t.confidences else 0.0,
                            'views_seen': [str(v) for v in t.views_seen],
                            'frames_tracked': int(len(t.positions)),
                            'is_active': bool(t.is_active),
                            'first_seen': t.first_seen.isoformat(),
                            'last_seen': t.last_seen.isoformat(),
                            'total_detections': int(len(t.positions)),
                            'positions': [[float(x) for x in pos] for pos in t.positions] if t.positions else [],
                            'velocities': [float(vel) for vel in t.velocities] if t.velocities else []
                        }
                        traj_dict = convert_numpy_types(traj_dict)
                    trajectories.append(traj_dict)
            
            # Calculate emissions for trajectories (now they are dicts)
            emissions = []
            if self.emission_calculator and trajectories:
                for traj in trajectories:
                    # Convert trajectory to emission-compatible format
                    try:
                        # Extract velocity magnitude from last velocity
                        velocity = traj.get('velocity', [0, 0])
                        velocity_magnitude = float((velocity[0]**2 + velocity[1]**2)**0.5) if velocity else 0.0
                        
                        # Calculate distance from positions
                        positions = traj.get('positions', [])
                        distance_pixels = 0.0
                        if len(positions) > 1:
                            for i in range(1, len(positions)):
                                dx = positions[i][0] - positions[i-1][0]
                                dy = positions[i][1] - positions[i-1][1]
                                distance_pixels += (dx**2 + dy**2)**0.5
                        
                        # Calculate emissions using the correct method
                        emission_obj = self.emission_calculator.calculate_emissions(
                            vehicle_id=traj['track_id'],
                            vehicle_class=traj.get('class_name', 'sedan'),
                            distance_pixels=distance_pixels,
                            velocity_pixels_per_sec=velocity_magnitude,
                            idle_time_seconds=0.0  # Can be calculated from trajectory data
                        )
                        
                        # Convert to dictionary format for Kafka/database with explicit type conversion
                        emission_dict = {
                            'trajectory_id': int(traj['track_id']),
                            'vehicle_type': str(emission_obj.vehicle_class),
                            'co2_grams': float(emission_obj.co2),
                            'nox_grams': float(emission_obj.nox),
                            'pm_grams': float(emission_obj.pm),
                            'co_grams': float(emission_obj.co),
                            'hc_grams': float(emission_obj.hc),
                            'distance_meters': float(emission_obj.distance_traveled),
                            'average_speed_kmh': float(emission_obj.average_speed),
                            'idle_time_seconds': float(emission_obj.idle_time),
                            'environmental_impact_score': float(emission_obj.environmental_impact_score),
                            'timestamp': emission_obj.timestamp.isoformat()
                        }
                        # Convert any remaining numpy types
                        emission_dict = convert_numpy_types(emission_dict)
                        emissions.append(emission_dict)
                    except Exception as e:
                        logger.error(f"Failed to calculate emission for track {traj.get('track_id', 'unknown')}: {e}")
            
            # Update statistics
            self.stats['total_detections'] += len(detections)
            self.stats['total_frames_processed'] += 1
            
            for det in detections:
                class_name = det['class_name']
                self.stats['detections_by_class'][class_name] = \
                    self.stats['detections_by_class'].get(class_name, 0) + 1
            
            # Calculate FPS
            elapsed = time.time() - self.start_time
            self.stats['average_fps'] = self.stats['total_frames_processed'] / elapsed if elapsed > 0 else 0
            
            # Prepare result (trajectories are already dicts) with numpy type conversion
            result = {
                'frame_id': int(frame_id),
                'timestamp': timestamp.isoformat(),
                'detections': detections,
                'trajectories': trajectories,
                'emissions': emissions,
                'stats': {
                    'detection_count': int(len(detections)),
                    'trajectory_count': int(len(trajectories)),
                    'emission_count': int(len(emissions))
                }
            }

            # Run anomaly detection on trajectories (live)
            if self.anomaly_monitor and trajectories:
                tracked_objects = []
                now_s = time.time()
                for traj in trajectories:
                    lp = traj.get('last_position') or [0.0, 0.0]
                    tracked_objects.append({
                        'track_id': traj.get('track_id'),
                        'cx': lp[0],
                        'cy': lp[1],
                        'timestamp_s': now_s
                    })
                anomaly_events = self.anomaly_monitor.on_frame(tracked_objects)
                if anomaly_events:
                    result['anomalies'] = anomaly_events
                    # store for dashboard
                    for a in anomaly_events:
                        self._recent_anomalies.append({
                            'track_id': a.get('track_id'),
                            'reasons': a.get('reasons', []),
                            'scores': a.get('scores', {}),
                            'timestamp': timestamp.isoformat()
                        })
            
            # Convert all numpy types in the entire result before Kafka/DB (optimized)
            try:
                from optimized_trajectory_converter import convert_numpy_types_optimized
                result = convert_numpy_types_optimized(result)
            except ImportError:
                result = convert_numpy_types(result)
            
            return result
            
        except Exception as e:
            import traceback
            logger.error(f"Error processing frame {frame_id}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {'frame_id': frame_id, 'error': str(e), 'detections': [], 'trajectories': [], 'emissions': []}
    
    async def publish_to_kafka(self, data: Dict, topic: str):
        """Publish data to Kafka topic"""
        if not self.kafka_producer:
            return
        
        try:
            await self.kafka_producer.send(topic, value=data)
            logger.debug(f"Published to {topic}")
        except Exception as e:
            logger.error(f"Failed to publish to Kafka: {e}")
    
    async def save_to_database(self, data: Dict):
        """Save data to database"""
        if not DATABASE_AVAILABLE:
            return
        
        try:
            # Save detections
            for det in data.get('detections', []):
                await db.insert_detection(
                    intersection_id=self.intersection_id,
                    camera_id=self.camera_id,
                    frame_id=str(data['frame_id']),
                    object_class=det['class_name'],
                    confidence=det['confidence'],
                    bbox={
                        'x1': det['bbox'][0],
                        'y1': det['bbox'][1],
                        'x2': det['bbox'][2],
                        'y2': det['bbox'][3]
                    }
                )
            
            # Save trajectories
            for traj in data.get('trajectories', []):
                # Calculate average velocity magnitude
                velocity = traj.get('velocity', [0, 0])
                avg_velocity = float((velocity[0]**2 + velocity[1]**2)**0.5) if velocity else 0.0
                
                # Convert track_id (int) to UUID-compatible string
                track_uuid = str(traj['track_id'])
                
                await db.insert_trajectory(
                    track_id=track_uuid,
                    intersection_id=self.intersection_id,
                    vehicle_class=traj.get('class_name', 'unknown'),
                    start_timestamp=datetime.fromisoformat(traj['first_seen']),
                    end_timestamp=datetime.fromisoformat(traj['last_seen']),
                    total_frames=traj['total_detections'],
                    average_velocity=avg_velocity,
                    trajectory_path=traj['positions']
                )
            
            # Save emissions
            for emission in data.get('emissions', []):
                # Convert trajectory_id (int) to UUID-compatible string
                trajectory_uuid = str(emission.get('trajectory_id', 'unknown'))
                
                await db.insert_emission(
                    trajectory_id=trajectory_uuid,
                    intersection_id=self.intersection_id,
                    vehicle_class=emission['vehicle_type'],
                    emissions={
                        'co2': emission['co2_grams'],
                        'nox': emission['nox_grams'],
                        'pm': emission['pm_grams'],
                        'co': emission['co_grams'],
                        'hc': emission['hc_grams'],
                        'distance': emission['distance_meters'],
                        'speed': emission['average_speed_kmh'],
                        'idle_time': emission['idle_time_seconds'],
                        'impact_score': emission['environmental_impact_score']
                    }
                )
            
        except Exception as e:
            logger.error(f"Failed to save to database: {e}")
    
    async def cache_results(self, data: Dict):
        """Cache results in Redis"""
        if not CACHE_AVAILABLE:
            return
        
        try:
            # Cache detection counts
            await cache.cache_traffic_metrics(
                intersection_id=self.intersection_id,
                metrics={
                    'total_vehicles': len(data.get('detections', [])),
                    'total_trajectories': len(data.get('trajectories', [])),
                    'total_emissions': len(data.get('emissions', [])),
                    'frame_id': data.get('frame_id', 0),
                    'timestamp': str(data.get('timestamp', datetime.now().isoformat()))
                }
            )
        except Exception as e:
            logger.error(f"Failed to cache results: {e}")
            import traceback
            logger.error(f"Cache error traceback: {traceback.format_exc()}")
    
    async def process_stream(self):
        """Main processing loop"""
        if not self.camera:
            logger.error("Camera not initialized")
            return
        
        self.is_running = True
        self.start_time = time.time()
        frame_id = 0
        
        logger.info("🚀 Starting stream processing...")
        
        try:
            while self.is_running:
                ret, frame = self.camera.read()
                if not ret:
                    logger.warning("Failed to read frame")
                    break
                
                frame_id += 1
                
                # Process frame
                result = await self.process_frame(frame, frame_id)
                
                # Publish to Kafka
                if result.get('detections'):
                    await self.publish_to_kafka(result, 'detections')
                
                if result.get('trajectories'):
                    await self.publish_to_kafka(
                        {'trajectories': result['trajectories'], 'timestamp': result['timestamp']},
                        'trajectory-data'
                    )

                # Publish anomalies if any
                if result.get('anomalies'):
                    await self.publish_to_kafka(
                        {'anomalies': result['anomalies'], 'timestamp': result['timestamp']},
                        'trajectory-anomalies'
                    )
                    # Persist anomalies to DB if available
                    if DATABASE_AVAILABLE:
                        try:
                            for a in result['anomalies']:
                                await db.insert_anomaly(
                                    track_id=str(a.get('track_id')),
                                    intersection_id=self.intersection_id,
                                    camera_id=self.camera_id,
                                    reasons=a.get('reasons', []),
                                    scores=a.get('scores', {}),
                                    created_at=datetime.fromisoformat(result['timestamp'])
                                )
                        except Exception as e:
                            logger.warning(f"insert_anomaly not available or failed: {e}")
                
                if result.get('emissions'):
                    await self.publish_to_kafka(
                        {'emissions': result['emissions'], 'timestamp': result['timestamp']},
                        'emission-data'
                    )
                
                # Save to database (non-blocking with optimization)
                # Use fire-and-forget pattern to avoid blocking
                try:
                    asyncio.create_task(self.save_to_database(result))
                except Exception as e:
                    logger.debug(f"Database save task creation failed (non-critical): {e}")
                
                # Cache results (non-blocking with optimization)
                try:
                    asyncio.create_task(self.cache_results(result))
                except Exception as e:
                    logger.debug(f"Cache task creation failed (non-critical): {e}")
                
                # Log progress
                if frame_id % 30 == 0:
                    logger.info(
                        f"Processed {frame_id} frames | "
                        f"FPS: {self.stats['average_fps']:.2f} | "
                        f"Detections: {self.stats['total_detections']}"
                    )
                
                # Small delay to prevent overwhelming the system
                await asyncio.sleep(0.01)
                
        except Exception as e:
            logger.error(f"Error in processing loop: {e}")
        finally:
            self.is_running = False
            logger.info("Stream processing stopped")
    
    def get_stats(self) -> Dict:
        """Get current statistics"""
        return {
            **self.stats,
            'is_running': self.is_running,
            'frame_count': self.frame_count,
            'uptime_seconds': time.time() - self.start_time
        }

# Global service instance
service = IntegratedPerceptionService()

# FastAPI endpoints
@app.on_event("startup")
async def startup_event():
    """Startup event handler"""
    logger.info("Starting Integrated AI Perception Service...")
    
    # Initialize models
    await service.initialize_models()
    
    # Start Kafka
    await service.start_kafka()
    
    # Start database
    await service.start_database()
    
    logger.info("✅ Integrated AI Perception Service started")

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler"""
    logger.info("Stopping Integrated AI Perception Service...")
    
    service.is_running = False
    service.stop_camera()
    await service.stop_kafka()
    await service.stop_database()
    
    logger.info("Integrated AI Perception Service stopped")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Integrated AI Perception Service",
        "version": "3.0.0",
        "status": "operational",
        "models": {
            "multiview_fusion": service.fusion_system is not None,
            "trajectory_tracking": service.trajectory_tracker is not None,
            "emission_calculation": service.emission_calculator is not None
        },
        "integrations": {
            "kafka": KAFKA_AVAILABLE and service.kafka_producer is not None,
            "database": DATABASE_AVAILABLE,
            "cache": CACHE_AVAILABLE
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "is_running": service.is_running,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/stats")
async def get_stats():
    """Get service statistics"""
    return JSONResponse(content=service.get_stats())

@app.get("/anomalies")
async def get_anomalies(limit: int = 100):
    """Return recent trajectory anomalies for dashboard"""
    try:
        items = list(service._recent_anomalies)[-limit:]
        return JSONResponse(content={'count': len(items), 'items': items})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/start")
async def start_processing(
    background_tasks: BackgroundTasks,
    camera_id: int = 0,
    camera_url: Optional[str] = None
):
    """Start processing stream"""
    if service.is_running:
        raise HTTPException(status_code=400, detail="Already running")
    
    # Initialize camera
    if not service.initialize_camera(camera_id, camera_url):
        raise HTTPException(status_code=500, detail="Failed to initialize camera")
    
    # Start processing in background
    background_tasks.add_task(service.process_stream)
    
    return {
        "status": "started",
        "camera_id": camera_id,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/stop")
async def stop_processing():
    """Stop processing stream"""
    if not service.is_running:
        raise HTTPException(status_code=400, detail="Not running")
    
    service.is_running = False
    service.stop_camera()
    
    return {
        "status": "stopped",
        "timestamp": datetime.now().isoformat()
    }

def main():
    """Main entry point"""
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8004,
        log_level="info"
    )

if __name__ == "__main__":
    main()
