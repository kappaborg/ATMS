#!/usr/bin/env python3
"""
ATMS Video Processor - Real-Time Video Display
Full-screen real-time video with all AI model outputs
"""

import asyncio
import json
import base64
import logging
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
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
    logging.warning("aiokafka not available - Kafka features disabled")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# Data Models
# ============================================================================

class VideoUploadResponse(BaseModel):
    """Response model for video upload"""
    video_id: str
    filename: str
    duration_seconds: float
    fps: float
    frame_count: int
    resolution: Dict[str, int]
    status: str
    message: str

# ============================================================================
# Video Processor Service with Real-Time Display
# ============================================================================

class RealTimeVideoProcessor:
    """Service for processing videos with real-time detection display"""
    
    def __init__(self):
        self.kafka_producer: Optional[AIOKafkaProducer] = None
        self.kafka_consumer: Optional[AIOKafkaConsumer] = None
        self.kafka_license_consumer: Optional[AIOKafkaConsumer] = None  # Consumer for license plates
        self.websocket_connections: List[WebSocket] = []
        self.upload_dir = Path("/tmp/atms_videos")
        self.upload_dir.mkdir(exist_ok=True, parents=True)
        
        # Real-time direct processor (NEW - no Kafka round-trip)
        self.realtime_processor = None
        self._realtime_processor_initialized = False
        
        # Real-time display - store frames by frame_id for matching
        self.frame_buffer: Dict[str, np.ndarray] = {}  # frame_id -> frame
        self.latest_frame: Optional[np.ndarray] = None
        self.latest_detections: List[Dict] = []
        self.active_video_id: Optional[str] = None
        self.frame_buffer_max_size = 200  # Keep last 200 frames for better matching
        
        # Tracking persistence - maintain boxes across frames
        self.track_buffer: Dict[int, Dict] = {}  # track_id -> {bbox, class, data, last_seen_frame, age}
        self.frame_counter = 0
        self.track_max_age = 15  # Keep tracks for 15 frames even if not detected (smoother persistence)
        self.track_smoothing_alpha = 0.7  # Smoothing factor for box positions
        
        # Trajectory heatmap - store path history for each track
        self.trajectory_history: Dict[int, List[tuple]] = {}  # track_id -> [(x, y), (x, y), ...]
        self.trajectory_max_length = 60  # Keep last 60 points (about 2-3 seconds at 25fps)
        
        # Processed videos storage (for batch processing)
        self.processed_videos: Dict[str, str] = {}  # video_id -> output_path
        self.processing_status: Dict[str, str] = {}  # video_id -> status
        
        # Store detections by frame_id for batch processing
        self.detections_by_frame: Dict[str, List[Dict]] = {}  # frame_id -> [detections]
    
    async def initialize_realtime_processor(self):
        """Initialize real-time direct processor (no Kafka round-trip)"""
        if self._realtime_processor_initialized:
            return True
        
        try:
            # Import here to avoid circular dependencies
            import sys
            from pathlib import Path
            
            # Add current directory to Python path for imports
            current_dir = Path(__file__).parent
            if str(current_dir) not in sys.path:
                sys.path.insert(0, str(current_dir))
            
            processor_path = current_dir / "realtime_direct_processing.py"
            if not processor_path.exists():
                logger.warning(f"⚠️ Real-time processor not found at {processor_path}")
                return False
            
            # Use absolute import with path
            import importlib.util
            spec = importlib.util.spec_from_file_location("realtime_direct_processing", processor_path)
            if spec is None or spec.loader is None:
                logger.warning(f"⚠️ Could not load realtime_direct_processing module")
                return False
            
            realtime_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(realtime_module)
            DirectVideoProcessor = realtime_module.DirectVideoProcessor
            
            logger.info(f"✅ Successfully loaded DirectVideoProcessor from {processor_path}")
            
            self.realtime_processor = DirectVideoProcessor(
                websocket_connections=self.websocket_connections,
                kafka_producer=self.kafka_producer
            )
            
            logger.info("✅ DirectVideoProcessor instance created, initializing models...")
            
            if await self.realtime_processor.initialize_models():
                logger.info("✅ Real-Time Direct Processor initialized (no Kafka round-trip)")
                self._realtime_processor_initialized = True
                return True
            else:
                logger.warning("⚠️ Real-Time Direct Processor failed to initialize, using Kafka mode")
                self.realtime_processor = None
                return False
        except Exception as e:
            logger.warning(f"⚠️ Real-Time Direct Processor not available: {e}, using Kafka mode", exc_info=True)
            self.realtime_processor = None
            return False
    
    async def initialize_kafka(self, bootstrap_servers: List[str]):
        """Initialize Kafka producer and consumer with better error handling"""
        runtime_cfg = get_atms_runtime_config()
        if not runtime_cfg.enable_kafka:
            logger.info(
                f"ATMS run mode: {runtime_cfg.run_mode.value} -> Kafka disabled (offline mode)"
            )
            return False

        if not KAFKA_AVAILABLE:
            logger.warning("⚠️ Kafka not available (aiokafka not installed)")
            return False
        
        # Validate and clean bootstrap servers
        if not bootstrap_servers or len(bootstrap_servers) == 0:
            logger.error("❌ No Kafka bootstrap servers provided")
            return False
        
        cleaned_servers = [s.strip() for s in bootstrap_servers if s and s.strip()]
        if not cleaned_servers:
            logger.error("❌ No valid Kafka bootstrap servers after cleaning")
            return False
        
        logger.info(f"🔌 Connecting to Kafka at: {', '.join(cleaned_servers)}")
        
        # Retry initialization up to 3 times
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # Producer with timeout and retry settings
                self.kafka_producer = AIOKafkaProducer(
                    bootstrap_servers=cleaned_servers,
                    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                    compression_type='gzip',
                    request_timeout_ms=30000,  # 30 second timeout
                    retry_backoff_ms=100
                )
                await self.kafka_producer.start()
                logger.info("✅ Kafka producer initialized")
                break  # Success, exit retry loop
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Kafka producer initialization failed (attempt {attempt + 1}/{max_retries}): {e}")
                    logger.info(f"⏳ Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"❌ Kafka producer initialization failed after {max_retries} attempts: {e}")
                    self.kafka_producer = None
                    return False
        
        # Verify producer is actually initialized
        if not self.kafka_producer:
            logger.error("❌ Kafka producer is None after initialization")
            return False
        
        try:
            
            # Consumer for detections
            # CRITICAL: Use fixed group_id for batch processing
            group_id = 'video-processor-batch-group'
            self.kafka_consumer = AIOKafkaConsumer(
                'detections',
                bootstrap_servers=cleaned_servers,
                group_id=group_id,
                auto_offset_reset='earliest',  # CRITICAL: Start from earliest for batch processing
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                enable_auto_commit=True,
                auto_commit_interval_ms=1000,
                request_timeout_ms=30000,
                session_timeout_ms=30000,
                heartbeat_interval_ms=10000
            )
            await self.kafka_consumer.start()
            logger.info("✅ Kafka consumer initialized")
            
            # Start processing detections (CRITICAL: Store task reference)
            self.detection_task = asyncio.create_task(self.process_detections())
            logger.info("✅ Detection processing task started (will run continuously)")
            
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize Kafka: {e}", exc_info=True)
            logger.error(f"   Bootstrap servers: {cleaned_servers}")
            logger.error(f"   Check Kafka: docker ps | grep kafka")
            return False
    
    async def save_uploaded_video(self, file: UploadFile) -> tuple[str, Path]:
        """Save uploaded video file"""
        video_id = str(uuid.uuid4())
        filename = f"{video_id}_{file.filename}"
        filepath = self.upload_dir / filename
        
        contents = await file.read()
        with open(filepath, 'wb') as f:
            f.write(contents)
        
        logger.info(f"Video saved: {filepath}")
        return video_id, filepath
    
    def get_video_info(self, filepath: Path) -> Dict:
        """Extract video information"""
        cap = cv2.VideoCapture(str(filepath))
        
        if not cap.isOpened():
            raise ValueError("Cannot open video file")
        
        info = {
            'fps': cap.get(cv2.CAP_PROP_FPS),
            'frame_count': int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
            'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            'duration': 0.0
        }
        
        if info['fps'] > 0:
            info['duration'] = info['frame_count'] / info['fps']
        
        cap.release()
        return info
    
    async def process_video(self, video_id: str, filepath: Path):
        """Process video batch mode: process all frames, then generate output video"""
        try:
            logger.info(f"🎬 Starting BATCH video processing: {video_id}")
            
            # CRITICAL: Ensure Kafka is initialized before processing
            if not self.kafka_producer:
                logger.warning("⚠️ Kafka producer not initialized. Attempting to initialize...")
                import os
                kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
                initialized = await self.initialize_kafka(kafka_servers)
                if not initialized:
                    logger.error("❌ Failed to initialize Kafka. Cannot process video.")
                    self.processing_status[video_id] = "failed"
                    return
                logger.info("✅ Kafka initialized successfully")
            
            # Reset tracking when starting new video
            self.track_buffer.clear()
            self.trajectory_history.clear()
            self.frame_counter = 0
            self.detections_by_frame.clear()  # Clear previous video's detections
            self.active_video_id = video_id  # Set active video BEFORE sending frames
            logger.info(f"📹 Set active video to: {video_id} (will collect all detections for this video)")
            
            # Get video info
            info = self.get_video_info(filepath)
            self.active_video_id = video_id
            logger.info(f"📹 Video info: {info['frame_count']} frames, {info['width']}x{info['height']}, {info['fps']:.2f} FPS")
            
            # Open video
            cap = cv2.VideoCapture(str(filepath))
            if not cap.isOpened():
                logger.error(f"❌ Cannot open video file: {filepath}")
                return
            
            # Prepare output video writer
            output_dir = self.upload_dir / "processed"
            output_dir.mkdir(exist_ok=True, parents=True)
            output_path = output_dir / f"{video_id}_processed.mp4"
            
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            fps = info.get('fps', 25.0)
            width = info['width']
            height = info['height']
            out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
            
            if not out.isOpened():
                logger.error(f"❌ Cannot create output video: {output_path}")
                cap.release()
                return
            
            frame_idx = 0
            frames_sent = 0
            frames_processed = 0
            
            # Store all frames and their detections for batch processing
            frame_data_list = []
            
            logger.info(f"📤 Sending all frames to Kafka for processing...")
            
            # PHASE 1: Send all frames to Kafka for processing
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    logger.info(f"📹 Reached end of video at frame {frame_idx}")
                    break
                
                # Validate frame
                if frame is None or frame.size == 0:
                    logger.warning(f"⚠️ Invalid frame at index {frame_idx}, skipping")
                    frame_idx += 1
                    continue
                
                # Store frame in buffer with frame_id as key
                frame_id = f"video_{video_id}_frame_{frame_idx}"
                
                # Store frame in buffer (limit size to prevent memory issues)
                if len(self.frame_buffer) >= self.frame_buffer_max_size:
                    # Remove oldest frame (FIFO)
                    oldest_key = next(iter(self.frame_buffer))
                    del self.frame_buffer[oldest_key]
                
                self.frame_buffer[frame_id] = frame.copy()
                self.latest_frame = frame.copy()
                
                # Store frame data for later processing (unlimited, for batch processing)
                frame_data_list.append({
                    'frame_id': frame_id,
                    'frame_idx': frame_idx,
                    'frame': frame.copy()
                })
                
                # Send frame to Kafka for AI processing
                asyncio.create_task(self._send_frame_to_kafka_async(video_id, frame_idx, frame_id, frame.copy(), info))
                frames_sent += 1
                
                if frames_sent % 50 == 0:
                    logger.info(f"📤 Sent {frames_sent}/{info['frame_count']} frames to Kafka")
                
                frame_idx += 1
                
                # Optimized: Batch send frames to reduce Kafka overhead
                # Send frames in batches of 10, then small delay
                if frames_sent % 10 == 0:
                    await asyncio.sleep(0.05)  # Slightly longer delay every 10 frames
                else:
                    await asyncio.sleep(0.001)  # Minimal delay for batch
            
            cap.release()
            logger.info(f"✅ All {frames_sent} frames sent to Kafka. Waiting for detections...")
            
            # PHASE 2: Wait for detections and process frames
            logger.info(f"⏳ Waiting for detections to arrive...")
            
            # CRITICAL FIX: Wait for ALL frames, not just stability
            # Calculate wait time based on processing time per frame
            # AI Perception processes ~2-5 frames/second, so for 864 frames, need ~3-5 minutes
            # Use more conservative estimate: 0.5s per frame (accounts for all 7 models)
            base_wait_time = max(30, frames_sent * 0.5)  # At least 30s, or 0.5s per frame
            max_wait_time = min(base_wait_time, 600)  # Cap at 10 minutes
            logger.info(f"⏳ Waiting up to {max_wait_time:.1f} seconds for detections (processing ~{frames_sent} frames)...")
            
            # Wait in chunks and check progress
            check_interval = 10  # Check every 10 seconds
            waited = 0
            last_frame_count = 0
            no_progress_count = 0
            max_no_progress = 6  # Stop if no progress for 60 seconds (6 checks)
            
            while waited < max_wait_time:
                await asyncio.sleep(check_interval)
                waited += check_interval
                
                # Check detection count
                detections_count = sum(len(dets) for dets in self.detections_by_frame.values())
                frames_with_detections = len(self.detections_by_frame)
                
                # Calculate progress percentage
                progress_pct = (frames_with_detections / frames_sent * 100) if frames_sent > 0 else 0
                
                logger.info(f"⏳ Progress: {waited:.0f}s/{max_wait_time:.0f}s - {frames_with_detections}/{frames_sent} frames ({progress_pct:.1f}%) - {detections_count} total detections")
                
                # Check if we're making progress
                if frames_with_detections > last_frame_count:
                    no_progress_count = 0
                    last_frame_count = frames_with_detections
                else:
                    no_progress_count += 1
                
                # Stop conditions:
                # 1. We have 95%+ of frames (very high coverage)
                if frames_with_detections >= frames_sent * 0.95:
                    logger.info(f"✅ Collected detections for {frames_with_detections}/{frames_sent} frames (95%+), proceeding")
                    break
                
                # 2. No progress for 60 seconds AND we have at least 80% coverage
                if no_progress_count >= max_no_progress and frames_with_detections >= frames_sent * 0.8:
                    logger.info(f"✅ No progress for 60s, but have {frames_with_detections}/{frames_sent} frames (80%+), proceeding")
                    break
                
                # 3. No progress for 90 seconds (regardless of coverage - something is wrong)
                if no_progress_count >= 9:
                    logger.warning(f"⚠️ No progress for 90s, proceeding with {frames_with_detections}/{frames_sent} frames ({progress_pct:.1f}%)")
                    break
            
            # Final check
            detections_count = sum(len(dets) for dets in self.detections_by_frame.values())
            frames_with_detections = len(self.detections_by_frame)
            progress_pct = (frames_with_detections / frames_sent * 100) if frames_sent > 0 else 0
            logger.info(f"📊 Final: Collected {detections_count} detections across {frames_with_detections}/{frames_sent} frames ({progress_pct:.1f}% coverage)")
            
            # Log missing frames for debugging
            if frames_with_detections < frames_sent:
                missing_count = frames_sent - frames_with_detections
                logger.warning(f"⚠️ Missing detections for {missing_count} frames ({100-progress_pct:.1f}%)")
                
                # Find missing frame ranges
                detected_frame_indices = set()
                for frame_id in self.detections_by_frame.keys():
                    if '_frame_' in frame_id:
                        try:
                            idx_str = frame_id.split('_frame_')[1]
                            detected_frame_indices.add(int(idx_str))
                        except:
                            pass
                
                if detected_frame_indices:
                    all_indices = set(range(frames_sent))
                    missing_indices = sorted(all_indices - detected_frame_indices)
                    if missing_indices:
                        gap_start = min(missing_indices)
                        gap_end = max(missing_indices)
                        logger.warning(f"⚠️ Missing frame range: {gap_start}-{gap_end} ({len(missing_indices)} frames)")
            
            # Re-read video to process frames with detections
            cap2 = cv2.VideoCapture(str(filepath))
            
            frame_idx = 0
            frames_processed = 0
            
            # Color map for visualization
            color_map = {
                'car': (0, 255, 0),
                'truck': (255, 165, 0),
                'bus': (255, 0, 255),
                'motorcycle': (255, 255, 0),
                'bicycle': (0, 255, 255),
                'person': (255, 0, 0),
                'pedestrian': (255, 0, 0)
            }
            
            logger.info(f"🎨 Processing frames with annotations...")
            
            # Process each frame with its detections
            while cap2.isOpened():
                ret, frame = cap2.read()
                if not ret:
                    break
                
                # Get detections for this specific frame
                frame_id = f"video_{video_id}_frame_{frame_idx}"
                
                # Get frame-specific detections (stored during process_detections)
                frame_detections = self.detections_by_frame.get(frame_id, [])
                
                # If no detections for this frame, try to get from frame_data_list (fallback)
                if not frame_detections and frame_idx < len(frame_data_list):
                    frame_data = frame_data_list[frame_idx]
                    frame_detections = self.detections_by_frame.get(frame_data['frame_id'], [])
                
                # Also get active tracks for trajectory heatmap (all tracks for context)
                active_tracks = self.get_active_tracks()
                
                # Create annotated frame
                annotated_frame = frame.copy()
                
                # Draw trajectory heatmap FIRST (behind boxes)
                self._draw_trajectory_heatmap(annotated_frame, color_map)
                
                # Draw bounding boxes and labels for THIS FRAME's detections
                annotated_frame = self._draw_detections_on_frame(annotated_frame, frame_detections, color_map)
                
                if len(frame_detections) > 0:
                    logger.debug(f"📹 Frame {frame_idx}: Drawing {len(frame_detections)} detections")
                
                # Write frame to output video
                out.write(annotated_frame)
                frames_processed += 1
                
                if frames_processed % 50 == 0:
                    logger.info(f"📹 Processed {frames_processed}/{info['frame_count']} frames")
                
                frame_idx += 1
                
                # Update frame counter for tracking
                self.frame_counter = frame_idx
            
            cap2.release()
            out.release()
            
            logger.info(f"✅ Video processing complete: {frames_processed} frames processed, output saved to {output_path}")
            
            # Store output path for download
            self.processed_videos[video_id] = str(output_path)
            self.processing_status[video_id] = "completed"
            
        except Exception as e:
            logger.error(f"❌ Error processing video {video_id}: {e}", exc_info=True)
    
    async def _send_frame_to_kafka_async(self, video_id: str, frame_idx: int, frame_id: str, frame: np.ndarray, info: Dict):
        """Send frame to Kafka asynchronously (non-blocking)"""
        try:
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])  # Reduced quality for speed
            if buffer is None or len(buffer) == 0:
                logger.warning(f"⚠️ Failed to encode frame {frame_idx}")
                return
            
            frame_hex = buffer.tobytes().hex()
            
            message = {
                'message_id': f"{video_id}_{frame_idx}",
                'service_name': 'video-processor',
                'sensor_id': f"video_{video_id}",
                'sensor_type': 'camera',
                'timestamp': datetime.utcnow().isoformat(),
                'sequence_number': frame_idx,
                'frame_id': frame_id,  # Use consistent frame_id
                'intersection_id': 1,
                'status': 'pending',
                'data': {
                    'frame_data': frame_hex,
                    'width': info['width'],
                    'height': info['height'],
                    'video_id': video_id,
                    'video_frame_idx': frame_idx
                }
            }
            
            if self.kafka_producer:
                try:
                    await self.kafka_producer.send('camera-frames', message)
                    if frame_idx % 30 == 0:
                        logger.debug(f"📹 Sent frame {frame_idx} to Kafka")
                except Exception as e:
                    logger.error(f"❌ Error sending frame {frame_idx} to Kafka: {e}")
                    # Try to reinitialize if connection lost
                    if "not connected" in str(e).lower() or "connection" in str(e).lower() or "closed" in str(e).lower():
                        logger.warning("⚠️ Kafka connection lost, attempting to reinitialize...")
                        import os
                        kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
                        await self.initialize_kafka(kafka_servers)
            else:
                logger.error(f"❌ Kafka producer not available, skipping frame {frame_idx}")
                logger.error(f"   This should not happen - Kafka should be initialized before processing")
                # Try to initialize on the fly (only once)
                if frame_idx == 0:
                    logger.info("🔄 Attempting to initialize Kafka now...")
                    import os
                    kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
                    await self.initialize_kafka(kafka_servers)
        except Exception as e:
            logger.error(f"❌ Error sending frame {frame_idx} to Kafka: {e}")
    
    async def process_detections(self):
        """Process detections from Kafka and visualize - RUNS CONTINUOUSLY"""
        if not self.kafka_consumer:
            logger.warning("Kafka consumer not available")
            return
        
        logger.info("✅ Starting detection consumer (running continuously)...")
        logger.info(f"✅ Consumer subscribed to 'detections' topic")
        
        try:
            message_count = 0
            last_log_time = time.time()
            
            async for message in self.kafka_consumer:
                message_count += 1
                current_time = time.time()
                
                # Log every 10 messages or every 5 seconds (whichever comes first)
                if message_count % 10 == 0 or (current_time - last_log_time) >= 5:
                    logger.info(f"📦 Processed {message_count} detection messages from Kafka (running continuously...)")
                    last_log_time = current_time
                try:
                    data = message.value
                    
                    # Log raw message structure for debugging
                    if message_count == 1 or message_count % 50 == 0:
                        logger.info(f"📦 Received Kafka message #{message_count}, keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
                    
                    detections_raw = data.get('detections', [])
                    sensor_id = data.get('sensor_id', '')
                    frame_id = data.get('frame_id', '')
                    
                    # CRITICAL: Log frame_id format for debugging
                    if message_count == 1 or message_count % 100 == 0:
                        logger.info(f"🔍 Detection message #{message_count}: sensor_id={sensor_id}, frame_id={frame_id}, detections={len(detections_raw)}")
                    
                    if not sensor_id.startswith('video_'):
                        logger.debug(f"Skipping non-video sensor: {sensor_id}")
                        continue
                    
                    video_id = sensor_id.replace('video_', '')
                    # Only filter if we have an active video AND it doesn't match
                    # During batch processing, we want to collect ALL detections
                    if self.active_video_id and video_id != self.active_video_id:
                        logger.debug(f"Skipping detection for inactive video: {video_id} (active: {self.active_video_id})")
                        continue
                    
                    # If no active video set, set it to this one (for batch processing)
                    if not self.active_video_id:
                        self.active_video_id = video_id
                        logger.info(f"📹 Setting active video to: {video_id}")
                    
                    # CRITICAL: Verify frame_id format matches expected format
                    # Expected: video_{video_id}_frame_{frame_idx}
                    expected_prefix = f"video_{video_id}_frame_"
                    if frame_id and not frame_id.startswith(expected_prefix):
                        logger.warning(f"⚠️ Frame ID mismatch! Expected format: {expected_prefix}*, got: {frame_id}")
                        # Try to extract frame_idx from frame_id if it's in a different format
                        # This is a fallback to handle different frame_id formats
                        if '_frame_' in frame_id:
                            # Try to extract: video_xxx_frame_yyy -> use as is
                            pass
                        elif frame_id.isdigit() or (frame_id.startswith('frame_') and frame_id[6:].isdigit()):
                            # If frame_id is just a number or "frame_123", construct proper format
                            frame_idx_str = frame_id.replace('frame_', '') if 'frame_' in frame_id else frame_id
                            try:
                                frame_idx = int(frame_idx_str)
                                frame_id = f"video_{video_id}_frame_{frame_idx}"
                                logger.info(f"🔧 Fixed frame_id format: {frame_id}")
                            except ValueError:
                                logger.warning(f"⚠️ Cannot parse frame_id: {frame_id}")
                                continue
                        else:
                            logger.warning(f"⚠️ Unknown frame_id format: {frame_id}, skipping")
                            continue
                    
                    # Get frame for this detection (match by frame_id)
                    frame_to_use = None
                    if frame_id and frame_id in self.frame_buffer:
                        frame_to_use = self.frame_buffer[frame_id]
                        logger.debug(f"Found matching frame for {frame_id}")
                    elif self.latest_frame is not None:
                        frame_to_use = self.latest_frame
                        logger.debug(f"Using latest frame (frame_id not found in buffer)")
                    else:
                        logger.warning(f"No frame available for {frame_id}")
                        continue
                    
                    # Update frame counter for tracking
                    self.frame_counter += 1
                    
                    # Extract detections with LOWER confidence threshold to detect more
                    detections = []
                    for det in detections_raw:
                        # Handle both Pydantic model and dict formats
                        if hasattr(det, 'bbox'):
                            # Pydantic Detection model
                            bbox_obj = det.bbox
                            if hasattr(bbox_obj, 'x1'):
                                bbox_dict = {'x1': bbox_obj.x1, 'y1': bbox_obj.y1, 'x2': bbox_obj.x2, 'y2': bbox_obj.y2}
                            else:
                                continue
                            obj_class = det.object_class
                            if hasattr(obj_class, 'value'):
                                obj_class = obj_class.value
                            else:
                                obj_class = str(obj_class)
                            confidence = det.confidence
                            speed = det.speed
                            license_plate = det.license_plate
                            vehicle_brand = det.vehicle_brand
                            brand_confidence = det.brand_confidence
                            multiview_confidence = det.multiview_confidence
                            views = det.views
                            emission_co2 = det.emission_co2
                            fuel_consumption = det.fuel_consumption
                            track_id = det.track_id
                            anomaly_detected = det.anomaly_detected
                        else:
                            # Dict format
                            bbox = det.get('bbox', {})
                            if hasattr(bbox, 'x1'):
                                bbox_dict = {'x1': bbox.x1, 'y1': bbox.y1, 'x2': bbox.x2, 'y2': bbox.y2}
                            elif isinstance(bbox, dict):
                                bbox_dict = bbox
                            else:
                                continue
                            obj_class = det.get('object_class')
                            confidence = det.get('confidence')
                            speed = det.get('speed')
                            license_plate = det.get('license_plate')
                            vehicle_brand = det.get('vehicle_brand')
                            brand_confidence = det.get('brand_confidence')
                            multiview_confidence = det.get('multiview_confidence')
                            views = det.get('views')
                            emission_co2 = det.get('emission_co2')
                            fuel_consumption = det.get('fuel_consumption')
                            track_id = det.get('track_id')
                            anomaly_detected = det.get('anomaly_detected')
                        
                        # Safe float conversion helper
                        def safe_float(value, default=0.0):
                            if value is None:
                                return default
                            try:
                                return float(value)
                            except (ValueError, TypeError):
                                return default
                        
                        # Ensure obj_class is set
                        if 'obj_class' not in locals() or obj_class is None:
                            if isinstance(det, dict):
                                obj_class = det.get('object_class') or det.get('class', 'unknown')
                            else:
                                obj_class = getattr(det, 'object_class', 'unknown')
                            
                            if hasattr(obj_class, 'value'):
                                obj_class = obj_class.value
                            obj_class = str(obj_class)
                        
                        detection_data = {
                            'bbox': bbox_dict,
                            'confidence': safe_float(confidence, 0.0),
                            'class': obj_class,
                            'speed': safe_float(speed, 0.0),
                            'license_plate': license_plate or (det.get('plate_text') if isinstance(det, dict) else None),
                            'vehicle_brand': vehicle_brand or (det.get('brand') if isinstance(det, dict) else None),
                            'brand_confidence': safe_float(brand_confidence, 0.0),
                            'multiview_confidence': safe_float(multiview_confidence, 0.0),
                            'views': views or [],
                            'emission_co2': safe_float(emission_co2, 0.0),
                            'fuel_consumption': safe_float(fuel_consumption, 0.0),
                            'track_id': track_id,
                            'anomaly_detected': bool(anomaly_detected or False)
                        }
                        
                        # LOWER confidence threshold (0.3) to show more detections in video
                        # SAHI already filters at 0.35, so this should catch most real detections
                        if detection_data['confidence'] > 0.3:
                            detections.append(detection_data)
                    
                    # Always broadcast frame (even without detections) so user sees video
                    if frame_to_use is None:
                        logger.warning(f"No frame available for {frame_id}, skipping")
                        continue
                    
                    # Store detections by frame_id for batch processing
                    if frame_id:
                        # Apply NMS to reduce duplicates
                        if detections:
                            detections = self.apply_nms(detections, iou_threshold=0.4)
                            # Limit max detections per frame (increased from 50 to 100)
                            if len(detections) > 100:
                                detections = sorted(detections, key=lambda d: d.get('confidence', 0), reverse=True)[:100]
                        
                        # Store detections for this frame (for batch processing)
                        self.detections_by_frame[frame_id] = detections.copy()
                        logger.info(f"💾 Stored {len(detections)} detections for {frame_id} (total frames with detections: {len(self.detections_by_frame)})")
                        
                        # Log first few detections for debugging
                        if len(detections) > 0 and message_count <= 5:
                            logger.info(f"   Sample detection: class={detections[0].get('class')}, conf={detections[0].get('confidence'):.3f}, bbox={detections[0].get('bbox')}")
                    
                    # Update track buffer with new detections
                    self.update_track_buffer(detections)
                    
                    # Get all active tracks (including persisted ones)
                    active_tracks = self.get_active_tracks()
                    
                    if len(active_tracks) == 0 and len(detections) == 0:
                        logger.debug(f"No detections or tracks for {frame_id}")
                        # Broadcast frame without detections
                        await self.visualize_and_broadcast([], frame_to_use)
                        continue
                    
                    logger.info(f"✅ Extracted {len(detections)} new detections, {len(active_tracks)} active tracks for {frame_id}")
                    
                    # Filter active tracks by confidence for display (but keep all in buffer)
                    display_tracks = [t for t in active_tracks if t.get('confidence', 0) > 0.3]  # Show only confident detections
                    
                    # Use active tracks (which include persisted boxes) for visualization
                    self.latest_detections = active_tracks  # Store all for reference
                    logger.info(f"✅ Processing {len(active_tracks)} total tracks, {len(display_tracks)} high-confidence for display (frame {frame_id})")
                    
                    # Visualize and broadcast with the matched frame (use display_tracks for cleaner output)
                    await self.visualize_and_broadcast(display_tracks, frame_to_use)
                    
                except Exception as e:
                    logger.error(f"Error processing detection: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Kafka consumer error: {e}", exc_info=True)
    
    def apply_nms(self, detections, iou_threshold=0.25):
        """Apply Non-Maximum Suppression"""
        if not detections:
            return []
        
        boxes = np.array([[d['bbox']['x1'], d['bbox']['y1'], d['bbox']['x2'], d['bbox']['y2']] 
                         for d in detections], dtype=np.float32)
        scores = np.array([d['confidence'] for d in detections], dtype=np.float32)
        
        indices = cv2.dnn.NMSBoxes(
            boxes.tolist(),
            scores.tolist(),
            0.5,
            iou_threshold
        )
        
        if len(indices) > 0:
            indices = indices.flatten()
            return [detections[i] for i in indices]
        return []
    
    def _calculate_iou(self, box1: tuple, box2: tuple) -> float:
        """Calculate Intersection over Union (IoU) between two bounding boxes
        
        Args:
            box1: (x1, y1, x2, y2)
            box2: (x1, y1, x2, y2)
        
        Returns:
            IoU value between 0 and 1
        """
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        
        if x2 <= x1 or y2 <= y1:
            return 0.0
        
        intersection = (x2 - x1) * (y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - intersection
        
        return intersection / union if union > 0 else 0.0
    
    def update_track_buffer(self, new_detections: List[Dict]):
        """Update track buffer with new detections, maintaining persistence"""
        # Mark all existing tracks as not seen this frame
        for track_id in self.track_buffer:
            self.track_buffer[track_id]['seen_this_frame'] = False
        
        # Update or create tracks from new detections
        for det in new_detections:
            track_id = det.get('track_id')
            
            # Try to get track_id from detection (from ByteTrack/ATMS)
            if track_id is None or track_id == 'N/A' or track_id == 'null' or track_id == 0:
                # If no track_id from AI Perception, try to match with existing tracks using IoU
                bbox = det.get('bbox', {})
                det_center_x = (bbox.get('x1', 0) + bbox.get('x2', 0)) / 2
                det_center_y = (bbox.get('y1', 0) + bbox.get('y2', 0)) / 2
                obj_class = det.get('class', 'unknown')
                
                # Try to match with existing tracks by IoU and proximity
                best_match_id = None
                best_iou = 0.0
                max_distance = 100  # pixels
                
                for existing_track_id, existing_track in self.track_buffer.items():
                    existing_bbox = existing_track.get('bbox', {})
                    existing_class = existing_track.get('class', 'unknown')
                    
                    # Only match same class
                    if existing_class != obj_class:
                        continue
                    
                    # Calculate IoU
                    iou = self._calculate_iou(
                        (bbox.get('x1', 0), bbox.get('y1', 0), bbox.get('x2', 0), bbox.get('y2', 0)),
                        (existing_bbox.get('x1', 0), existing_bbox.get('y1', 0), existing_bbox.get('x2', 0), existing_bbox.get('y2', 0))
                    )
                    
                    # Calculate center distance
                    existing_center_x = (existing_bbox.get('x1', 0) + existing_bbox.get('x2', 0)) / 2
                    existing_center_y = (existing_bbox.get('y1', 0) + existing_bbox.get('y2', 0)) / 2
                    distance = ((det_center_x - existing_center_x)**2 + (det_center_y - existing_center_y)**2)**0.5
                    
                    # Match if IoU > 0.3 and distance is reasonable
                    if iou > best_iou and iou > 0.3 and distance < max_distance:
                        best_iou = iou
                        best_match_id = existing_track_id
                
                # Use matched track_id or generate new one
                if best_match_id is not None:
                    track_id = best_match_id
                    logger.debug(f"✅ Matched detection to existing track {track_id} (IoU: {best_iou:.2f})")
                else:
                    # Generate a stable ID from bbox center and class (more stable than full bbox)
                    # Use quantized position for stability (round to nearest 10 pixels)
                    track_id = hash((int(det_center_x/10), int(det_center_y/10), obj_class)) % 100000
                    logger.debug(f"🆕 Generated new track_id {track_id} for {obj_class}")
                
                det['track_id'] = track_id  # Store it back in detection
            
            # Calculate bbox center for trajectory
            bbox = det.get('bbox', {})
            center_x = int((bbox.get('x1', 0) + bbox.get('x2', 0)) / 2)
            center_y = int((bbox.get('y1', 0) + bbox.get('y2', 0)) / 2)
            
            if track_id in self.track_buffer:
                # Update existing track with smoothing
                old_track = self.track_buffer[track_id]
                old_bbox = old_track['bbox']
                new_bbox = det['bbox']
                
                # Smooth box position
                smoothed_bbox = {
                    'x1': old_bbox['x1'] * (1 - self.track_smoothing_alpha) + new_bbox['x1'] * self.track_smoothing_alpha,
                    'y1': old_bbox['y1'] * (1 - self.track_smoothing_alpha) + new_bbox['y1'] * self.track_smoothing_alpha,
                    'x2': old_bbox['x2'] * (1 - self.track_smoothing_alpha) + new_bbox['x2'] * self.track_smoothing_alpha,
                    'y2': old_bbox['y2'] * (1 - self.track_smoothing_alpha) + new_bbox['y2'] * self.track_smoothing_alpha,
                }
                
                # Update trajectory history
                if track_id not in self.trajectory_history:
                    self.trajectory_history[track_id] = []
                self.trajectory_history[track_id].append((center_x, center_y))
                # Limit trajectory length
                if len(self.trajectory_history[track_id]) > self.trajectory_max_length:
                    self.trajectory_history[track_id] = self.trajectory_history[track_id][-self.trajectory_max_length:]
                
                # Update track data
                self.track_buffer[track_id].update({
                    'bbox': smoothed_bbox,
                    'confidence': det.get('confidence', old_track.get('confidence', 0)),
                    'class': det.get('class', old_track.get('class', 'unknown')),
                    'speed': det.get('speed', old_track.get('speed', 0)),
                    'license_plate': det.get('license_plate') or old_track.get('license_plate'),
                    'vehicle_brand': det.get('vehicle_brand') or old_track.get('vehicle_brand'),
                    'brand_confidence': det.get('brand_confidence', old_track.get('brand_confidence', 0)),
                    'multiview_confidence': det.get('multiview_confidence', old_track.get('multiview_confidence', 0)),
                    'views': det.get('views') or old_track.get('views', []),
                    'emission_co2': det.get('emission_co2', old_track.get('emission_co2', 0)),
                    'fuel_consumption': det.get('fuel_consumption', old_track.get('fuel_consumption', 0)),
                    'anomaly_detected': det.get('anomaly_detected', old_track.get('anomaly_detected', False)),
                    'last_seen_frame': self.frame_counter,
                    'age': 0,  # Reset age when seen
                    'seen_this_frame': True
                })
            else:
                # Create new track
                self.track_buffer[track_id] = {
                    'bbox': det['bbox'],
                    'confidence': det.get('confidence', 0),
                    'class': det.get('class', 'unknown'),
                    'speed': det.get('speed', 0),
                    'license_plate': det.get('license_plate'),
                    'vehicle_brand': det.get('vehicle_brand'),
                    'brand_confidence': det.get('brand_confidence', 0),
                    'multiview_confidence': det.get('multiview_confidence', 0),
                    'views': det.get('views', []),
                    'emission_co2': det.get('emission_co2', 0),
                    'fuel_consumption': det.get('fuel_consumption', 0),
                    'anomaly_detected': det.get('anomaly_detected', False),
                    'track_id': track_id,
                    'last_seen_frame': self.frame_counter,
                    'age': 0,
                    'seen_this_frame': True
                }
                # Initialize trajectory history
                self.trajectory_history[track_id] = [(center_x, center_y)]
        
        # Age tracks that weren't seen this frame
        tracks_to_remove = []
        for track_id, track in self.track_buffer.items():
            if not track.get('seen_this_frame', False):
                track['age'] += 1
                # Remove tracks that are too old
                if track['age'] > self.track_max_age:
                    tracks_to_remove.append(track_id)
        
        for track_id in tracks_to_remove:
            del self.track_buffer[track_id]
            # Clean up trajectory history
            if track_id in self.trajectory_history:
                del self.trajectory_history[track_id]
    
    def get_active_tracks(self) -> List[Dict]:
        """Get all active tracks (including persisted ones) as detection format"""
        active_tracks = []
        for track_id, track in self.track_buffer.items():
            # Include track even if age > 0 (persisted)
            track_data = {
                'bbox': track['bbox'],
                'confidence': track.get('confidence', 0),
                'class': track.get('class', 'unknown'),
                'speed': track.get('speed', 0),
                'license_plate': track.get('license_plate'),
                'vehicle_brand': track.get('vehicle_brand'),
                'brand_confidence': track.get('brand_confidence', 0),
                'multiview_confidence': track.get('multiview_confidence', 0),
                'views': track.get('views', []),
                'emission_co2': track.get('emission_co2', 0),
                'fuel_consumption': track.get('fuel_consumption', 0),
                'track_id': track_id,
                'anomaly_detected': track.get('anomaly_detected', False),
                'age': track.get('age', 0)  # Include age for visualization
            }
            active_tracks.append(track_data)
        
        return active_tracks
    
    def _check_label_overlap(self, label_rect, occupied_rects, margin=5):
        """Check if label rectangle overlaps with any occupied rectangles"""
        x1, y1, x2, y2 = label_rect
        for ox1, oy1, ox2, oy2 in occupied_rects:
            if not (x2 + margin < ox1 or x1 - margin > ox2 or y2 + margin < oy1 or y1 - margin > oy2):
                return True
        return False
    
    def _draw_trajectory_heatmap(self, frame: np.ndarray, color_map: Dict):
        """Draw trajectory heatmap showing paths of all tracked objects - ENHANCED VISIBILITY"""
        if not self.trajectory_history:
            return
        
        # Create overlay for heatmap with transparency
        overlay = frame.copy()
        
        for track_id, trajectory in self.trajectory_history.items():
            if len(trajectory) < 2:
                continue
            
            # Get color for this track (based on class if available)
            track = self.track_buffer.get(track_id, {})
            obj_class = track.get('class', 'car').lower()
            base_color = color_map.get(obj_class, (0, 255, 0))
            
            # Draw trajectory path with fading (recent = bright, old = faint)
            # Make lines thicker and more visible
            for i in range(len(trajectory) - 1):
                pt1 = trajectory[i]
                pt2 = trajectory[i + 1]
                
                # Calculate alpha based on position in history (0.0 = old, 1.0 = recent)
                alpha = (i + 1) / len(trajectory)
                # Make it MORE visible (increased range)
                alpha = 0.5 + (alpha * 0.5)  # Range: 0.5 to 1.0 (was 0.3 to 0.8)
                
                # Calculate color with alpha
                color = tuple(int(c * alpha) for c in base_color)
                
                # Draw thicker line for better visibility
                cv2.line(overlay, pt1, pt2, color, 3)  # Increased from 2 to 3
                
                # Draw point at each position (larger for better visibility)
                point_size = max(2, int(4 * alpha))  # Increased from 3 to 4
                cv2.circle(overlay, pt2, point_size, color, -1)
            
            # Draw arrow at the end to show direction (more visible)
            if len(trajectory) >= 2:
                # Get last two points for direction
                pt1 = trajectory[-2]
                pt2 = trajectory[-1]
                
                # Calculate angle
                dx = pt2[0] - pt1[0]
                dy = pt2[1] - pt1[1]
                angle = np.arctan2(dy, dx)
                
                # Draw arrow (thicker and more visible)
                arrow_length = 15
                arrow_tip = (
                    int(pt2[0] + arrow_length * np.cos(angle)),
                    int(pt2[1] + arrow_length * np.sin(angle))
                )
                cv2.arrowedLine(overlay, pt1, arrow_tip, base_color, 2, tipLength=0.3)
        
        # Blend overlay with frame
        cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)
    
    def _find_label_position(self, bbox, label_height, label_width, frame_shape, occupied_rects):
        """Find best position for label to avoid overlap"""
        x1, y1, x2, y2 = bbox
        frame_h, frame_w = frame_shape[:2]
        margin = 5
        
        # Try positions in order of preference
        positions = [
            (x1, y1 - label_height - margin, x1 + label_width, y1 - margin),  # Above box
            (x1, y2 + margin, x1 + label_width, y2 + label_height + margin),  # Below box
            (x2 + margin, y1, x2 + label_width + margin, y1 + label_height),  # Right of box
            (x1 - label_width - margin, y1, x1 - margin, y1 + label_height),  # Left of box
        ]
        
        for pos in positions:
            px1, py1, px2, py2 = pos
            # Check bounds
            if px1 >= 0 and py1 >= 0 and px2 <= frame_w and py2 <= frame_h:
                # Check overlap
                if not self._check_label_overlap(pos, occupied_rects, margin):
                    return (px1, py1, px2, py2)
        
        # If all positions overlap, use above box anyway (will overlap but at least visible)
        return (x1, max(0, y1 - label_height - margin), x1 + label_width, max(0, y1 - margin))
    
    def _draw_detections_on_frame(self, frame: np.ndarray, detections: List[Dict], color_map: Dict) -> np.ndarray:
        """Draw detections on frame (for batch processing)"""
        if not detections:
            return frame
        
        # Sort detections by confidence (draw high confidence first to get better positions)
        sorted_detections = sorted(detections, key=lambda d: d.get('confidence', 0), reverse=True)
        
        # Limit to top 100 detections to prevent overcrowding (increased from 50)
        if len(sorted_detections) > 100:
            sorted_detections = sorted_detections[:100]
            logger.debug(f"Limited detections to 100 (had {len(detections)})")
        
        # Track occupied label areas to prevent overlap
        occupied_label_rects = []
        
        # Draw boxes with all model outputs
        for det in sorted_detections:
            bbox = det['bbox']
            x1 = int(max(0, min(bbox['x1'], frame.shape[1] - 1)))
            y1 = int(max(0, min(bbox['y1'], frame.shape[0] - 1)))
            x2 = int(max(0, min(bbox['x2'], frame.shape[1])))
            y2 = int(max(0, min(bbox['y2'], frame.shape[0])))
            
            if x2 <= x1 or y2 <= y1:
                continue
            
            obj_class = det['class'].lower()
            color = color_map.get(obj_class, (0, 255, 0))
            
            # Draw bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
            
            # Generate or use track ID
            track_id = det.get('track_id')
            if track_id is None or track_id == 'N/A' or track_id == 'null':
                track_id = hash((int(x1/10), int(y1/10), obj_class)) % 10000
                det['track_id'] = track_id
            
            # Build comprehensive label with ALL model outputs
            label_lines = []
            label_lines.append(f"ID:{track_id}")  # Line 1: Track ID
            label_lines.append(f"{det['class']}")  # Line 2: Class
            
            # Line 3: Speed
            if det.get('speed') and det['speed'] > 0:
                label_lines.append(f"{det['speed']:.0f}km/h")
            
            # Line 4: Brand (if available)
            if det.get('vehicle_brand') and det['vehicle_brand'] not in [None, 'N/A', 'null', '']:
                brand_conf = det.get('brand_confidence', 0)
                if brand_conf > 0.3:  # Only show if confident
                    label_lines.append(f"Brand: {det['vehicle_brand']}")
            
            # Line 5: License Plate (if available)
            if det.get('license_plate') and det['license_plate'] not in [None, 'N/A', 'null', '']:
                label_lines.append(f"Plate: {det['license_plate']}")
            
            # Line 6: CO2 Emission (if available)
            if det.get('emission_co2') and det['emission_co2'] > 0:
                label_lines.append(f"CO2: {det['emission_co2']:.1f}g/km")
            
            # Limit to 6 lines max to avoid clutter
            label_lines = label_lines[:6]
            
            # Calculate label dimensions
            font_scale = 0.6
            font_thickness = 2
            line_height = 22
            max_width = 0
            for line in label_lines:
                (text_width, text_height), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thickness)
                max_width = max(max_width, text_width)
            
            label_width = max_width + 10
            label_height = len(label_lines) * line_height + 10
            
            # Find best position for label
            label_rect = self._find_label_position(
                (x1, y1, x2, y2),
                label_height,
                label_width,
                frame.shape,
                occupied_label_rects
            )
            
            label_x1, label_y1, label_x2, label_y2 = label_rect
            
            # Draw semi-transparent background for label
            overlay = frame.copy()
            cv2.rectangle(overlay, (label_x1, label_y1), (label_x2, label_y2), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
            
            # Draw text
            current_y = label_y1 + 20
            for i, line in enumerate(label_lines):
                if i == 0:  # Track ID - make it prominent
                    font_scale_id = 0.8
                    thickness_id = 3
                    (text_width_id, text_height_id), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, font_scale_id, thickness_id)
                    cv2.rectangle(frame, (label_x1 + 2, current_y - text_height_id - 5), 
                                (label_x1 + text_width_id + 8, current_y + 5), color, -1)
                    cv2.putText(frame, line, (label_x1 + 5, current_y), 
                               cv2.FONT_HERSHEY_SIMPLEX, font_scale_id, (255, 255, 255), thickness_id)
                    current_y += line_height + 5
                else:
                    cv2.putText(frame, line, (label_x1 + 5, current_y), 
                               cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), 3)
                    cv2.putText(frame, line, (label_x1 + 5, current_y), 
                               cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), font_thickness)
                    current_y += line_height
            
            # Record this label's position
            occupied_label_rects.append(label_rect)
        
        return frame
    
    async def visualize_and_broadcast(self, detections, frame: Optional[np.ndarray] = None):
        """Draw bounding boxes with all model outputs and broadcast - WITH OVERLAP PREVENTION"""
        if frame is None:
            frame = self.latest_frame
        
        if frame is None:
            logger.warning("No frame available for visualization")
            return
        
        try:
            frame = frame.copy()
            
            # Color map
            color_map = {
                'car': (0, 255, 0),
                'truck': (255, 165, 0),
                'bus': (255, 0, 255),
                'motorcycle': (255, 255, 0),
                'bicycle': (0, 255, 255),
                'person': (255, 0, 0),
                'pedestrian': (255, 0, 0)
            }
            
            # Draw trajectory heatmap FIRST (behind boxes)
            self._draw_trajectory_heatmap(frame, color_map)
            
            # Sort detections by confidence (draw high confidence first to get better positions)
            sorted_detections = sorted(detections, key=lambda d: d.get('confidence', 0), reverse=True)
            
            # Track occupied label areas to prevent overlap
            occupied_label_rects = []
            
            # Draw boxes with all model outputs
            for det in sorted_detections:
                bbox = det['bbox']
                x1 = int(max(0, min(bbox['x1'], frame.shape[1] - 1)))
                y1 = int(max(0, min(bbox['y1'], frame.shape[0] - 1)))
                x2 = int(max(0, min(bbox['x2'], frame.shape[1])))
                y2 = int(max(0, min(bbox['y2'], frame.shape[0])))
                
                if x2 <= x1 or y2 <= y1:
                    continue
                
                obj_class = det['class'].lower()
                color = color_map.get(obj_class, (0, 255, 0))
                
                # Adjust opacity for persisted tracks (age > 0)
                track_age = det.get('age', 0)
                if track_age > 0:
                    # Fade persisted tracks slightly
                    alpha = max(0.5, 1.0 - (track_age / self.track_max_age) * 0.3)
                    overlay = frame.copy()
                    cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 3)
                    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
                else:
                    # Fresh detection - full opacity
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
                
                # Generate or use track ID (CRITICAL - must have unique ID)
                track_id = det.get('track_id')
                if track_id is None or track_id == 'N/A' or track_id == 'null':
                    # Generate a stable ID from bbox position (fallback)
                    track_id = hash((int(x1/10), int(y1/10), obj_class)) % 10000
                    det['track_id'] = track_id
                
                # Build comprehensive label with ALL model outputs
                label_lines = []
                label_lines.append(f"ID:{track_id}")  # Line 1: Track ID
                label_lines.append(f"{det['class']}")  # Line 2: Class
                
                # Line 3: Speed
                if det.get('speed') and det['speed'] > 0:
                    label_lines.append(f"{det['speed']:.0f}km/h")
                
                # Line 4: Brand (if available)
                if det.get('vehicle_brand') and det['vehicle_brand'] not in [None, 'N/A', 'null', '']:
                    brand_conf = det.get('brand_confidence', 0)
                    if brand_conf > 0.3:  # Only show if confident
                        label_lines.append(f"Brand: {det['vehicle_brand']}")
                
                # Line 5: License Plate (if available)
                if det.get('license_plate') and det['license_plate'] not in [None, 'N/A', 'null', '']:
                    label_lines.append(f"Plate: {det['license_plate']}")
                
                # Line 6: CO2 Emission (if available)
                if det.get('emission_co2') and det['emission_co2'] > 0:
                    label_lines.append(f"CO2: {det['emission_co2']:.1f}g/km")
                
                # Limit to 6 lines max
                label_lines = label_lines[:6]
                
                # Calculate label dimensions
                font_scale = 0.6
                font_thickness = 2
                line_height = 22
                max_width = 0
                for line in label_lines:
                    (text_width, text_height), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thickness)
                    max_width = max(max_width, text_width)
                
                label_width = max_width + 10
                label_height = len(label_lines) * line_height + 10
                
                # Find best position for label (avoid overlap)
                label_rect = self._find_label_position(
                    (x1, y1, x2, y2),
                    label_height,
                    label_width,
                    frame.shape,
                    occupied_label_rects
                )
                
                label_x1, label_y1, label_x2, label_y2 = label_rect
                
                # Draw semi-transparent background for label
                overlay = frame.copy()
                cv2.rectangle(overlay, (label_x1, label_y1), (label_x2, label_y2), (0, 0, 0), -1)
                cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
                
                # Draw text - ID line is BIGGER and BOLDER
                current_y = label_y1 + 20
                for i, line in enumerate(label_lines):
                    if i == 0:  # Track ID - make it prominent
                        font_scale_id = 0.8
                        thickness_id = 3
                        # Draw ID with colored background
                        (text_width_id, text_height_id), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, font_scale_id, thickness_id)
                        cv2.rectangle(frame, (label_x1 + 2, current_y - text_height_id - 5), 
                                    (label_x1 + text_width_id + 8, current_y + 5), color, -1)
                        cv2.putText(frame, line, (label_x1 + 5, current_y), 
                                   cv2.FONT_HERSHEY_SIMPLEX, font_scale_id, (255, 255, 255), thickness_id)
                        current_y += line_height + 5
                    else:
                        # Other lines - normal size
                        cv2.putText(frame, line, (label_x1 + 5, current_y), 
                                   cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), 3)  # Black outline
                        cv2.putText(frame, line, (label_x1 + 5, current_y), 
                                   cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), font_thickness)  # White text
                        current_y += line_height
                
                # Record this label's position to prevent future overlaps
                occupied_label_rects.append(label_rect)
            
            # Encode frame with optimized quality for speed
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            frame_base64 = base64.b64encode(buffer).decode('utf-8')
            
            # Broadcast to all WebSocket clients (non-blocking)
            try:
                await self.broadcast({
                    'type': 'frame_update',
                    'frame': frame_base64,
                    'detections': len(detections),
                    'timestamp': time.time()
                })
                
                if len(detections) > 0:
                    logger.debug(f"✅ Broadcasted frame with {len(detections)} detections to {len(self.websocket_connections)} clients")
            except Exception as e:
                logger.warning(f"⚠️ Broadcast error: {e}")
            
        except Exception as e:
            logger.error(f"Visualization error: {e}", exc_info=True)
    
    async def broadcast(self, message: Dict):
        """Broadcast message to all WebSocket connections"""
        if not self.websocket_connections:
            logger.debug("No WebSocket connections to broadcast to")
            return
        
        disconnected = []
        for ws in self.websocket_connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug(f"WebSocket send error: {e}")
                disconnected.append(ws)
        
        for ws in disconnected:
            if ws in self.websocket_connections:
                self.websocket_connections.remove(ws)
        
        if len(self.websocket_connections) > 0:
            logger.debug(f"✅ Broadcasted to {len(self.websocket_connections)} WebSocket clients")
    
    async def add_websocket(self, websocket: WebSocket):
        """Add WebSocket connection"""
        await websocket.accept()
        self.websocket_connections.append(websocket)
        logger.info(f"✅ WebSocket connected. Total: {len(self.websocket_connections)}")
        
        # Send initial status
        try:
            await websocket.send_json({
                'type': 'status',
                'active_video': self.active_video_id,
                'has_frame': self.latest_frame is not None,
                'detections_count': len(self.latest_detections)
            })
        except:
            pass
    
    async def remove_websocket(self, websocket: WebSocket):
        """Remove WebSocket connection"""
        if websocket in self.websocket_connections:
            self.websocket_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.websocket_connections)}")

# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(title="ATMS Real-Time Video Processor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

video_service = RealTimeVideoProcessor()

@app.on_event("startup")
async def startup():
    """Initialize service"""
    import os
    kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
    await video_service.initialize_kafka(kafka_servers)
    logger.info("🚀 Real-Time Video Processor started")

@app.on_event("shutdown")
async def shutdown():
    """Cleanup"""
    if video_service.kafka_producer:
        await video_service.kafka_producer.stop()
    if video_service.kafka_consumer:
        await video_service.kafka_consumer.stop()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time video stream"""
    await video_service.add_websocket(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await video_service.remove_websocket(websocket)

@app.get("/", response_class=HTMLResponse)
async def root():
    """Full-screen real-time video display"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ATMS Real-Time Video Analysis</title>
        <meta charset="utf-8">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', Tahoma, sans-serif;
                background: #000;
                overflow: hidden;
                height: 100vh;
            }
            .header {
                position: fixed;
                top: 20px;
                left: 50%;
                transform: translateX(-50%);
                z-index: 100;
                background: rgba(0,0,0,0.7);
                color: white;
                padding: 15px 30px;
                border-radius: 10px;
                text-align: center;
            }
            .header h1 {
                font-size: 1.5em;
                margin-bottom: 5px;
            }
            .video-container {
                width: 100vw;
                height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                background: #000;
            }
            #videoFrame {
                max-width: 100%;
                max-height: 100%;
                width: auto;
                height: auto;
                image-rendering: -webkit-optimize-contrast;
                image-rendering: crisp-edges;
                transform: translateZ(0);
                will-change: contents;
            }
            .upload-controls {
                position: fixed;
                bottom: 20px;
                left: 50%;
                transform: translateX(-50%);
                z-index: 100;
                background: rgba(255,255,255,0.95);
                padding: 20px 30px;
                border-radius: 15px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.5);
            }
            .upload-area {
                border: 2px dashed #667eea;
                border-radius: 10px;
                padding: 20px;
                text-align: center;
                cursor: pointer;
                transition: all 0.3s;
            }
            .upload-area:hover {
                border-color: #764ba2;
                background: #f8f9ff;
            }
            input[type="file"] {
                display: none;
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
                margin-top: 10px;
            }
            .btn:hover {
                transform: scale(1.05);
            }
            .btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            .placeholder {
                color: white;
                text-align: center;
                font-size: 1.5em;
            }
            .placeholder-icon {
                font-size: 4em;
                margin-bottom: 20px;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🚦 ATMS Video Processing System</h1>
            <p>Upload Video • Automatic Processing • Auto-Download</p>
        </div>
        
        <div class="video-container">
            <div id="placeholder" class="placeholder">
                <div class="placeholder-icon">🎥</div>
                <div>Upload a video to start automatic processing</div>
                <div style="font-size: 0.8em; margin-top: 10px; color: #888;">
                    All AI models will process: Detection, Tracking, License Plates, Emissions, Trajectory
                </div>
            </div>
        </div>
        
        <div class="upload-controls">
            <div class="upload-area" id="uploadArea">
                <div>📹 Drag & Drop Video Here</div>
                <div style="font-size: 0.9em; color: #666; margin-top: 5px;">or click to browse</div>
                <input type="file" id="fileInput" accept="video/*" style="display: none;">
                <div id="status" style="margin-top: 20px; font-size: 1em; color: #667eea; font-weight: bold;"></div>
                <div id="progress" style="margin-top: 10px; font-size: 0.9em; color: #888;"></div>
            </div>
        </div>
        
        <script>
            let currentVideoId = null;
            let statusCheckInterval = null;
            
            const fileInput = document.getElementById('fileInput');
            const uploadArea = document.getElementById('uploadArea');
            const status = document.getElementById('status');
            const progress = document.getElementById('progress');
            
            // Create Processed_Videos folder if it doesn't exist (client-side)
            function ensureProcessedVideosFolder() {
                // This will be handled by the download function
                // Browser will prompt user for download location
            }
            
            // Download video to Processed_Videos folder
            async function downloadVideo(videoId, filename) {
                try {
                    const response = await fetch(`/api/download/${videoId}`);
                    if (!response.ok) {
                        throw new Error('Download failed');
                    }
                    
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename || `${videoId}_processed.mp4`;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    document.body.removeChild(a);
                    
                    status.textContent = `✅ Video downloaded successfully!`;
                    status.style.color = '#4ade80';
                    progress.textContent = `Saved to: ${a.download}`;
                } catch (error) {
                    console.error('Download error:', error);
                    status.textContent = `❌ Download failed: ${error.message}`;
                    status.style.color = '#ef4444';
                }
            }
            
            // Check processing status
            async function checkStatus(videoId) {
                try {
                    const response = await fetch(`/api/status/${videoId}`);
                    const data = await response.json();
                    
                    if (data.status === 'processing') {
                        status.textContent = '⏳ Processing video...';
                        status.style.color = '#fbbf24';
                        progress.textContent = 'Running all AI models: Detection, Tracking, License Plates, Emissions, Trajectory...';
                    } else if (data.status === 'completed' && data.ready) {
                        status.textContent = '✅ Processing complete! Downloading video...';
                        status.style.color = '#4ade80';
                        progress.textContent = 'Preparing download...';
                        
                        // Stop status checking
                        if (statusCheckInterval) {
                            clearInterval(statusCheckInterval);
                            statusCheckInterval = null;
                        }
                        
                        // Download video
                        await downloadVideo(videoId, `${data.video_id}_processed.mp4`);
                    } else if (data.status === 'unknown') {
                        status.textContent = '❌ Video not found';
                        status.style.color = '#ef4444';
                        if (statusCheckInterval) {
                            clearInterval(statusCheckInterval);
                            statusCheckInterval = null;
                        }
                    }
                } catch (error) {
                    console.error('Status check error:', error);
                    progress.textContent = `Error checking status: ${error.message}`;
                }
            }
            
            // Upload and process video
            async function uploadAndProcess(file) {
                if (!file || !file.type.startsWith('video/')) {
                    alert('Please select a valid video file');
                    return;
                }
                
                status.textContent = '⏳ Uploading video...';
                status.style.color = '#fbbf24';
                progress.textContent = 'Preparing upload...';
                uploadArea.style.pointerEvents = 'none';
                uploadArea.style.opacity = '0.6';
                
                const formData = new FormData();
                formData.append('file', file);
                
                try {
                    const response = await fetch('/api/upload', {
                        method: 'POST',
                        body: formData
                    });
                    
                    if (!response.ok) {
                        throw new Error(`Upload failed: ${response.statusText}`);
                    }
                    
                    const result = await response.json();
                    currentVideoId = result.video_id;
                    
                    status.textContent = '✅ Upload successful! Processing started...';
                    status.style.color = '#4ade80';
                    progress.textContent = `Video ID: ${currentVideoId}`;
                    
                    // Start checking status every 2 seconds
                    statusCheckInterval = setInterval(() => {
                        checkStatus(currentVideoId);
                    }, 2000);
                    
                    // Check immediately
                    checkStatus(currentVideoId);
                    
                } catch (error) {
                    console.error('Upload failed:', error);
                    status.textContent = `❌ Upload failed: ${error.message}`;
                    status.style.color = '#ef4444';
                    progress.textContent = '';
                    uploadArea.style.pointerEvents = 'auto';
                    uploadArea.style.opacity = '1';
                }
            }
            
            // Smooth frame rendering with requestAnimationFrame
            function renderFrame() {
                if (frameQueue.length === 0) {
                    isRendering = false;
                    return;
                }
                
                const now = performance.now();
                if (now - lastFrameTime < FRAME_INTERVAL) {
                    requestAnimationFrame(renderFrame);
                    return;
                }
                
                const frameData = frameQueue.shift();
                if (frameData && frameData.frame) {
                    videoFrame.src = 'data:image/jpeg;base64,' + frameData.frame;
                    videoFrame.style.display = 'block';
                    placeholder.style.display = 'none';
                    
                    if (frameData.detections !== undefined) {
                        status.textContent = `✅ ${frameData.detections} detections`;
                    }
                }
                
                lastFrameTime = now;
                
                // Limit queue size to prevent memory buildup
                if (frameQueue.length > 3) {
                    frameQueue = frameQueue.slice(-3);
                }
                
                requestAnimationFrame(renderFrame);
            }
            
            // Connect WebSocket
            function connectWebSocket() {
                ws = new WebSocket('ws://localhost:8008/ws');
                
                ws.onopen = () => {
                    console.log('✅ WebSocket connected');
                };
                
                ws.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        
                        if (data.type === 'frame_update' && data.frame) {
                            // Add to queue instead of directly updating
                            frameQueue.push(data);
                            
                            // Start rendering loop if not already running
                            if (!isRendering) {
                                isRendering = true;
                                requestAnimationFrame(renderFrame);
                            }
                        } else if (data.type === 'status') {
                            console.log('Status:', data);
                            if (data.active_video) {
                                status.textContent = `✅ Video active: ${data.active_video}`;
                            }
                        }
                    } catch (error) {
                        console.error('Error parsing WebSocket message:', error);
                    }
                };
                
                ws.onerror = (error) => {
                    console.error('❌ WebSocket error:', error);
                };
                
                ws.onclose = () => {
                    console.log('🔌 WebSocket closed, reconnecting...');
                    setTimeout(connectWebSocket, 3000);
                };
            }
            
            // Drag and drop
            uploadArea.addEventListener('dragover', (e) => {
                e.preventDefault();
                uploadArea.style.borderColor = '#764ba2';
            });
            
            uploadArea.addEventListener('dragleave', () => {
                uploadArea.style.borderColor = '#667eea';
            });
            
            uploadArea.addEventListener('drop', (e) => {
                e.preventDefault();
                uploadArea.style.borderColor = '#667eea';
                const file = e.dataTransfer.files[0];
                if (file && file.type.startsWith('video/')) {
                    uploadAndProcess(file);
                } else {
                    alert('Please drop a valid video file');
                }
            });
            
            uploadArea.addEventListener('click', () => {
                if (!currentVideoId || status.textContent.includes('complete')) {
                    fileInput.click();
                }
            });
            
            fileInput.addEventListener('change', (e) => {
                const file = e.target.files[0];
                if (file) {
                    uploadAndProcess(file);
                }
            });
            
            // Reset on page load
            status.textContent = '📹 Select or drop a video to start processing';
            status.style.color = '#667eea';
            progress.textContent = '';
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...), mode: str = "realtime"):
    """
    Upload video for processing
    
    Args:
        file: Video file to upload
        mode: Processing mode - "realtime" (direct processing, immediate display) or "batch" (Kafka round-trip)
    """
    try:
        if not file.content_type or not file.content_type.startswith('video/'):
            raise HTTPException(status_code=400, detail="File must be a video")
        
        video_id, filepath = await video_service.save_uploaded_video(file)
        info = video_service.get_video_info(filepath)
        
        # Set processing status
        video_service.processing_status[video_id] = "processing"
        
        # Initialize real-time processor if not already done
        if mode == "realtime" and not video_service._realtime_processor_initialized:
            await video_service.initialize_realtime_processor()
        
        # Choose processing mode
        if mode == "realtime" and video_service.realtime_processor:
            # REAL-TIME MODE: Process directly, display immediately, then send to Kafka
            logger.info(f"🚀 Starting REAL-TIME processing for video {video_id}")
            asyncio.create_task(
                video_service.realtime_processor.process_video_realtime(filepath, video_id)
            )
            message = "Video upload successful, REAL-TIME processing started. Results displayed immediately on screen, then sent to Kafka."
        else:
            # BATCH MODE: Send to Kafka, wait for processing, then display
            logger.info(f"📦 Starting BATCH processing for video {video_id}")
            asyncio.create_task(video_service.process_video(video_id, filepath))
            message = "Video upload successful, batch processing started. Check /api/status/{video_id} for progress."
        
        return VideoUploadResponse(
            video_id=video_id,
            filename=file.filename,
            duration_seconds=info['duration'],
            fps=info['fps'],
            frame_count=info['frame_count'],
            resolution={'width': info['width'], 'height': info['height']},
            status="processing",
            message=message
        )
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@app.get("/api/status/{video_id}")
async def get_video_status(video_id: str):
    """Get processing status and download link"""
    status = video_service.processing_status.get(video_id, "unknown")
    output_path = video_service.processed_videos.get(video_id)
    
    return {
        "video_id": video_id,
        "status": status,
        "download_url": f"/api/download/{video_id}" if output_path else None,
        "ready": status == "completed"
    }

@app.get("/api/download/{video_id}")
async def download_processed_video(video_id: str):
    """Download processed video"""
    output_path = video_service.processed_videos.get(video_id)
    if not output_path or not Path(output_path).exists():
        raise HTTPException(status_code=404, detail="Processed video not found")
    
    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=f"{video_id}_processed.mp4"
    )

@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "kafka": video_service.kafka_producer is not None,
        "active_video": video_service.active_video_id
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8008)

