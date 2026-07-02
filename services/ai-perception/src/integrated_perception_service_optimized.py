#!/usr/bin/env python3
"""
Optimized Integrated AI Perception Service
==========================================

Enhanced version with:
- Batch frame processing
- Optimized data conversions
- Improved async operations
- Better memory management
"""

import asyncio
import cv2
import json
import logging
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Deque
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import deque

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn
import numpy as np

# Import optimized components
try:
    from frame_batch_processor import FrameBatchProcessor, FrameBatch
    BATCH_PROCESSING_AVAILABLE = True
except ImportError:
    BATCH_PROCESSING_AVAILABLE = False
    logging.warning("Batch processor not available")

try:
    from optimized_trajectory_converter import convert_numpy_types_optimized, optimize_trajectory_dict
    OPTIMIZED_CONVERTER_AVAILABLE = True
except ImportError:
    OPTIMIZED_CONVERTER_AVAILABLE = False
    logging.warning("Optimized converter not available")

# Import base service components
from integrated_perception_service import (
    IntegratedPerceptionService,
    convert_numpy_types,
    MULTIVIEW_AVAILABLE,
    TRAJECTORY_AVAILABLE,
    EMISSION_AVAILABLE,
    ANOMALY_AVAILABLE,
    KAFKA_AVAILABLE,
    DATABASE_AVAILABLE,
    CACHE_AVAILABLE
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OptimizedIntegratedPerceptionService(IntegratedPerceptionService):
    """Optimized version of IntegratedPerceptionService with batch processing"""
    
    def __init__(self, batch_size: int = 2, enable_batch: bool = True):
        """
        Initialize optimized perception service
        
        Args:
            batch_size: Number of frames to process in batch
            enable_batch: Enable batch processing
        """
        super().__init__()
        
        self.batch_size = batch_size if enable_batch and BATCH_PROCESSING_AVAILABLE else 1
        self.enable_batch = enable_batch and BATCH_PROCESSING_AVAILABLE
        self.batch_processor = FrameBatchProcessor(batch_size=self.batch_size) if self.enable_batch else None
        
        # Performance tracking
        self.batch_processing_stats = {
            'total_batches': 0,
            'frames_in_batches': 0,
            'batch_time_saved': 0.0
        }
        
        logger.info(f"Optimized perception service initialized (batch_size={self.batch_size}, enabled={self.enable_batch})")
    
    async def process_frame_batch(self, frames: List[np.ndarray], frame_ids: List[int]) -> List[Dict]:
        """
        Process a batch of frames together (optimized)
        
        Args:
            frames: List of frame images
            frame_ids: List of frame IDs
            
        Returns:
            List of processing results
        """
        if not frames:
            return []
        
        start_time = time.time()
        results = []
        
        # Process all frames in parallel
        tasks = []
        for frame, frame_id in zip(frames, frame_ids):
            task = self.process_frame(frame, frame_id)
            tasks.append(task)
        
        # Run all frames in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions
        valid_results = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error in batch processing: {result}")
            else:
                valid_results.append(result)
        
        processing_time = time.time() - start_time
        avg_time_per_frame = processing_time / len(frames) if frames else 0
        
        # Track batch statistics
        if self.enable_batch:
            self.batch_processing_stats['total_batches'] += 1
            self.batch_processing_stats['frames_in_batches'] += len(frames)
            # Estimate time saved vs sequential
            sequential_time = avg_time_per_frame * len(frames) if avg_time_per_frame > 0 else 0
            if sequential_time > 0:
                self.batch_processing_stats['batch_time_saved'] += (sequential_time - processing_time)
        
        logger.debug(f"Batch processed: {len(frames)} frames in {processing_time*1000:.2f}ms ({avg_time_per_frame*1000:.2f}ms/frame)")
        
        return valid_results
    
    async def process_stream_optimized(self):
        """Optimized stream processing with batch support"""
        if not self.camera:
            logger.error("Camera not initialized")
            return
        
        self.is_running = True
        self.start_time = time.time()
        frame_id = 0
        
        logger.info("🚀 Starting optimized stream processing...")
        logger.info(f"Batch processing: {'ENABLED' if self.enable_batch else 'DISABLED'} (size={self.batch_size})")
        
        try:
            while self.is_running:
                # Read frame
                ret, frame = self.camera.read()
                if not ret:
                    logger.warning("Failed to read frame")
                    break
                
                frame_id += 1
                
                if self.enable_batch and self.batch_processor:
                    # Add to batch queue
                    batch_ready = self.batch_processor.add_frame(frame, frame_id)
                    
                    if batch_ready:
                        # Get batch
                        batch = self.batch_processor.get_batch()
                        if batch:
                            # Process batch
                            results = await self.process_frame_batch(batch.frames, batch.frame_ids)
                            
                            # Publish all results
                            for result in results:
                                await self._publish_result(result)
                else:
                    # Process single frame (original method)
                    result = await self.process_frame(frame, frame_id)
                    await self._publish_result(result)
                
                # Small sleep to prevent CPU spinning
                await asyncio.sleep(0.001)
                
        except KeyboardInterrupt:
            logger.info("Stream processing interrupted")
        except Exception as e:
            logger.error(f"Error in stream processing: {e}", exc_info=True)
        finally:
            self.is_running = False
            logger.info("Stream processing stopped")
    
    async def _publish_result(self, result: Dict):
        """Publish single result to Kafka/database"""
        try:
            # Publish to Kafka
            if result.get('detections'):
                await self.publish_to_kafka(result, 'detections')
            
            if result.get('trajectories'):
                await self.publish_to_kafka(
                    {'trajectories': result['trajectories'], 'timestamp': result['timestamp']},
                    'trajectory-data'
                )
            
            if result.get('anomalies'):
                await self.publish_to_kafka(
                    {'anomalies': result['anomalies'], 'timestamp': result['timestamp']},
                    'trajectory-anomalies'
                )
                
                # Persist anomalies
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
                        logger.warning(f"Failed to insert anomaly: {e}")
            
            if result.get('emissions'):
                await self.publish_to_kafka(
                    {'emissions': result['emissions'], 'timestamp': result['timestamp']},
                    'emission-data'
                )
            
            # Async database save (non-blocking)
            asyncio.create_task(self.save_to_database(result))
            
            # Async cache (non-blocking)
            asyncio.create_task(self.cache_results(result))
            
        except Exception as e:
            logger.error(f"Error publishing result: {e}")
    
    def get_optimization_stats(self) -> Dict:
        """Get optimization statistics"""
        base_stats = self.stats.copy()
        
        if self.enable_batch:
            base_stats['batch_processing'] = {
                'enabled': True,
                'batch_size': self.batch_size,
                'total_batches': self.batch_processing_stats['total_batches'],
                'frames_in_batches': self.batch_processing_stats['frames_in_batches'],
                'avg_batch_size': self.batch_processing_stats['frames_in_batches'] / max(1, self.batch_processing_stats['total_batches']),
                'time_saved_seconds': self.batch_processing_stats['batch_time_saved']
            }
        else:
            base_stats['batch_processing'] = {'enabled': False}
        
        base_stats['optimizations'] = {
            'optimized_converter': OPTIMIZED_CONVERTER_AVAILABLE,
            'batch_processing': BATCH_PROCESSING_AVAILABLE
        }
        
        return base_stats


