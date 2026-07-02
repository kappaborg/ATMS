"""
Sensor Fusion Service - Camera Adapter
Week 1: Professional RTSP Camera Interface with Error Handling & Optimization
"""
import asyncio
import cv2
import numpy as np
from typing import Optional, Tuple, AsyncGenerator
from datetime import datetime
import sys
from pathlib import Path
from contextlib import asynccontextmanager

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent.parent))
from shared.utils.logger import get_logger
from shared.models.base import CameraFrame, SensorType

logger = get_logger(__name__)


class CameraAdapter:
    """
    Professional Camera Adapter with RTSP streaming support
    
    Features:
    - Async RTSP streaming
    - Auto-reconnection with exponential backoff
    - Frame quality validation
    - Performance optimization
    - Comprehensive error handling
    """
    
    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        resolution: Tuple[int, int] = (1920, 1080),
        fps: int = 30,
        buffer_size: int = 10,
        reconnect_delay: int = 5,
        max_reconnect_attempts: int = 3,
        rotation: int = 0  # 0, 90, 180, 270 degrees
    ):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.resolution = resolution
        self.target_fps = fps
        self.buffer_size = buffer_size
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        self.rotation = rotation
        
        self.capture: Optional[cv2.VideoCapture] = None
        self.is_connected = False
        self.frame_count = 0
        self.error_count = 0
        self.last_frame_time = None
        
        self.logger = logger.bind(
            camera_id=camera_id,
            rtsp_url=rtsp_url
        )
    
    async def connect(self) -> bool:
        """
        Connect to RTSP stream with retry logic
        
        Returns:
            bool: True if connected successfully
        """
        for attempt in range(1, self.max_reconnect_attempts + 1):
            try:
                self.logger.info(
                    "Connecting to camera",
                    attempt=attempt,
                    max_attempts=self.max_reconnect_attempts
                )
                
                # Open RTSP stream in a thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                self.capture = await loop.run_in_executor(
                    None,
                    self._open_capture
                )
                
                if self.capture and self.capture.isOpened():
                    self.is_connected = True
                    
                    # Configure capture settings
                    self.capture.set(cv2.CAP_PROP_BUFFERSIZE, self.buffer_size)
                    self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
                    self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
                    self.capture.set(cv2.CAP_PROP_FPS, self.target_fps)
                    
                    # Get actual settings
                    actual_width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
                    actual_height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    actual_fps = self.capture.get(cv2.CAP_PROP_FPS)
                    
                    self.logger.info(
                        "Camera connected successfully",
                        resolution=f"{actual_width}x{actual_height}",
                        fps=actual_fps
                    )
                    return True
                
            except Exception as e:
                self.logger.error(
                    "Failed to connect to camera",
                    attempt=attempt,
                    error=str(e)
                )
                
                if attempt < self.max_reconnect_attempts:
                    # Exponential backoff
                    delay = self.reconnect_delay * (2 ** (attempt - 1))
                    self.logger.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
        
        self.is_connected = False
        self.logger.error("Failed to connect after all attempts")
        return False
    
    def _open_capture(self) -> cv2.VideoCapture:
        """Open video capture (runs in thread pool)"""
        # For MJPEG streams, try multiple backends
        if self.rtsp_url.startswith('http'):
            # Try different backends for HTTP/MJPEG streams
            backends = [
                cv2.CAP_ANY,      # Auto-detect (usually works best on macOS)
                cv2.CAP_FFMPEG,   # FFmpeg backend
                cv2.CAP_GSTREAMER # GStreamer backend
            ]
            
            for backend in backends:
                try:
                    cap = cv2.VideoCapture(self.rtsp_url, backend)
                    if cap.isOpened():
                        # Test if we can actually read a frame
                        ret, frame = cap.read()
                        if ret and frame is not None:
                            return cap
                        cap.release()
                except:
                    continue
            
            # If all backends fail, return a failed capture
            return cv2.VideoCapture(self.rtsp_url)
        else:
            # RTSP or other streams
            cap = cv2.VideoCapture(self.rtsp_url)
        
        return cap
    
    def _rotate_frame(self, frame: np.ndarray, rotation: int) -> np.ndarray:
        """
        Rotate frame by specified degrees
        
        Args:
            frame: Input frame
            rotation: Rotation angle (0, 90, 180, 270)
            
        Returns:
            Rotated frame
        """
        if rotation == 90:
            # Rotate 90 degrees clockwise
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif rotation == 180:
            # Rotate 180 degrees
            return cv2.rotate(frame, cv2.ROTATE_180)
        elif rotation == 270:
            # Rotate 270 degrees clockwise (90 counter-clockwise)
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        else:
            return frame
    
    async def disconnect(self):
        """Disconnect from camera"""
        if self.capture:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.capture.release)
            self.capture = None
            self.is_connected = False
            self.logger.info("Camera disconnected")
    
    async def read_frame(self) -> Optional[CameraFrame]:
        """
        Read a single frame from camera
        
        Returns:
            CameraFrame or None if failed
        """
        if not self.is_connected or not self.capture:
            self.logger.warning("Camera not connected")
            return None
        
        try:
            # Read frame in thread pool
            loop = asyncio.get_event_loop()
            ret, frame = await loop.run_in_executor(
                None,
                self.capture.read
            )
            
            if not ret or frame is None:
                self.error_count += 1
                self.logger.warning(
                    "Failed to read frame",
                    error_count=self.error_count
                )
                
                # Auto-reconnect if too many errors
                if self.error_count > 10:
                    self.logger.warning("Too many errors, reconnecting...")
                    await self.disconnect()
                    await self.connect()
                    self.error_count = 0
                
                return None
            
            # Reset error count on success
            self.error_count = 0
            self.frame_count += 1
            current_time = datetime.utcnow()
            
            # Apply rotation if needed
            if self.rotation != 0:
                frame = self._rotate_frame(frame, self.rotation)
            
            # Calculate actual FPS
            actual_fps = self.target_fps
            if self.last_frame_time:
                time_diff = (current_time - self.last_frame_time).total_seconds()
                if time_diff > 0:
                    actual_fps = 1.0 / time_diff
            
            self.last_frame_time = current_time
            
            # Validate frame quality
            if not self._validate_frame(frame):
                self.logger.warning("Frame quality validation failed")
                return None
            
            # Encode frame to JPEG for transmission (optimization)
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            frame_bytes = buffer.tobytes()
            
            # Create CameraFrame object
            camera_frame = CameraFrame(
                frame_id=f"{self.camera_id}_{self.frame_count}",
                sensor_id=self.camera_id,
                timestamp=current_time,
                width=frame.shape[1],
                height=frame.shape[0],
                format="JPEG",
                fps=actual_fps,
                frame_data=frame_bytes
            )
            
            return camera_frame
            
        except Exception as e:
            self.error_count += 1
            self.logger.error(
                "Error reading frame",
                error=str(e),
                error_count=self.error_count
            )
            return None
    
    def _validate_frame(self, frame: np.ndarray) -> bool:
        """
        Validate frame quality
        
        Args:
            frame: OpenCV frame
            
        Returns:
            bool: True if frame is valid
        """
        if frame is None or frame.size == 0:
            return False
        
        # Check if frame is too dark or too bright
        mean_brightness = np.mean(frame)
        if mean_brightness < 10 or mean_brightness > 250:
            return False
        
        # Check if frame has enough variance (not a blank frame)
        variance = np.var(frame)
        if variance < 100:
            return False
        
        return True
    
    @asynccontextmanager
    async def stream(self) -> AsyncGenerator[CameraFrame, None]:
        """
        Async context manager for frame streaming
        
        Usage:
            async with camera.stream() as frames:
                async for frame in frames:
                    process(frame)
        """
        try:
            # Connect if not already connected
            if not self.is_connected:
                await self.connect()
            
            yield self._frame_generator()
            
        finally:
            # Cleanup handled by caller
            pass
    
    async def _frame_generator(self) -> AsyncGenerator[CameraFrame, None]:
        """Generate frames asynchronously"""
        while self.is_connected:
            frame = await self.read_frame()
            if frame:
                yield frame
            else:
                # Small delay on error to avoid tight loop
                await asyncio.sleep(0.1)
    
    async def get_stats(self) -> dict:
        """Get camera statistics"""
        return {
            "camera_id": self.camera_id,
            "is_connected": self.is_connected,
            "frame_count": self.frame_count,
            "error_count": self.error_count,
            "rtsp_url": self.rtsp_url,
            "resolution": f"{self.resolution[0]}x{self.resolution[1]}",
            "target_fps": self.target_fps
        }

