"""
MJPEG Camera Adapter for HTTP streams
Uses requests library instead of OpenCV for better compatibility
"""
import asyncio
import cv2
from datetime import datetime
import numpy as np
from typing import Optional, Tuple
import sys
from pathlib import Path
import requests
from threading import Thread
import time
import traceback

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))
from shared.utils.logger import get_logger
from shared.models.base import CameraFrame

logger = get_logger(__name__)


class MJPEGCameraAdapter:
    """
    MJPEG Camera Adapter using requests library
    
    More reliable than OpenCV for HTTP MJPEG streams,
    especially on macOS
    """
    
    def __init__(
        self,
        camera_id: str,
        mjpeg_url: str,
        resolution: Tuple[int, int] = (1920, 1080),
        fps: int = 30,
        reconnect_delay: int = 5,
        max_reconnect_attempts: int = 3,
        rotation: int = 0,
        auth: Optional[Tuple[str, str]] = None  # (username, password)
    ):
        self.camera_id = camera_id
        self.mjpeg_url = mjpeg_url
        self.resolution = resolution
        self.target_fps = fps
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        self.rotation = rotation
        self.auth = auth
        
        self.is_connected = False
        self.frame_count = 0
        self.error_count = 0
        self.last_frame_time: Optional[datetime] = None
        
        # Frame buffer
        self.current_frame: Optional[np.ndarray] = None
        self.stream_thread: Optional[Thread] = None
        self.stop_stream = False
        
        self.logger = logger.bind(
            camera_id=camera_id,
            mjpeg_url=mjpeg_url
        )
    
    async def connect(self) -> bool:
        """Connect to MJPEG stream"""
        self.logger.info("Connecting to MJPEG camera")
        
        for attempt in range(1, self.max_reconnect_attempts + 1):
            try:
                self.logger.info(
                    "Attempting to connect to MJPEG stream",
                    attempt=attempt,
                    max_attempts=self.max_reconnect_attempts
                )
                
                # Test connection with a simple GET request
                request_kwargs = {'stream': True, 'timeout': 5}
                if self.auth and self.auth[0] and self.auth[1]:
                    from requests.auth import HTTPBasicAuth
                    request_kwargs['auth'] = HTTPBasicAuth(self.auth[0], self.auth[1])
                
                response = requests.get(self.mjpeg_url, **request_kwargs)
                
                if response.status_code == 200:
                    response.close()
                    
                    # Start streaming thread
                    self.stop_stream = False
                    self.stream_thread = Thread(target=self._stream_frames, daemon=True)
                    self.stream_thread.start()
                    
                    # Wait longer for first frame (MJPEG streams can be slow to start)
                    for wait_attempt in range(10):  # Wait up to 5 seconds
                        await asyncio.sleep(0.5)
                        if self.current_frame is not None:
                            self.is_connected = True
                            self.logger.info(
                                "MJPEG camera connected successfully",
                                resolution=f"{self.current_frame.shape[1]}x{self.current_frame.shape[0]}"
                            )
                            return True
                    
                    # If no frame after waiting, stop the thread and try again
                    self.stop_stream = True
                    if self.stream_thread:
                        self.stream_thread.join(timeout=1)
                    
            except Exception as e:
                self.logger.error(
                    f"Failed to connect to MJPEG stream: {e}",
                    attempt=attempt
                )
                
            if attempt < self.max_reconnect_attempts:
                delay = self.reconnect_delay
                self.logger.info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
        
        self.is_connected = False
        self.logger.error("Failed to connect after all attempts")
        return False
    
    def _stream_frames(self):
        """Background thread to continuously fetch frames from MJPEG stream"""
        try:
            # Print to stdout to ensure we see it even if logger fails
            print(f"[MJPEG Thread] Starting for {self.mjpeg_url}")
            self.logger.info("Starting MJPEG stream thread...")
            
            while not self.stop_stream:
                try:
                    # Open stream connection
                    print(f"[MJPEG Thread] Opening stream...")
                    self.logger.info(f"Opening MJPEG stream: {self.mjpeg_url}")
                    
                    # Prepare request kwargs
                    request_kwargs = {
                        'stream': True,
                        'timeout': 10
                    }
                    
                    # Add authentication if provided
                    if self.auth and self.auth[0] and self.auth[1]:
                        from requests.auth import HTTPBasicAuth
                        request_kwargs['auth'] = HTTPBasicAuth(self.auth[0], self.auth[1])
                        print(f"[MJPEG Thread] Using Basic Auth with username: {self.auth[0]}")
                    
                    response = requests.get(self.mjpeg_url, **request_kwargs)
                    
                    print(f"[MJPEG Thread] Response status: {response.status_code}")
                    
                    if response.status_code != 200:
                        self.logger.error(f"HTTP error: {response.status_code}")
                        time.sleep(self.reconnect_delay)
                        continue
                    
                    print("[MJPEG Thread] Stream opened, reading frames...")
                    self.logger.info("MJPEG stream opened, reading frames...")
                    
                    # Read MJPEG stream
                    bytes_data = bytes()
                    frame_count = 0
                    
                    for chunk in response.iter_content(chunk_size=1024):
                        if self.stop_stream:
                            print("[MJPEG Thread] Stop requested")
                            break
                        
                        bytes_data += chunk
                        
                        # Find JPEG boundaries
                        a = bytes_data.find(b'\xff\xd8')  # JPEG start
                        b = bytes_data.find(b'\xff\xd9')  # JPEG end
                        
                        if a != -1 and b != -1:
                            jpg = bytes_data[a:b+2]
                            bytes_data = bytes_data[b+2:]
                            
                            # Decode JPEG
                            frame = cv2.imdecode(
                                np.frombuffer(jpg, dtype=np.uint8),
                                cv2.IMREAD_COLOR
                            )
                            
                            if frame is not None:
                                # Apply rotation if needed
                                if self.rotation != 0:
                                    frame = self._rotate_frame(frame, self.rotation)
                                
                                self.current_frame = frame
                                self.error_count = 0
                                frame_count += 1
                                
                                if frame_count == 1:
                                    print(f"[MJPEG Thread] First frame! Size: {frame.shape}")
                                    self.logger.info(f"First frame received! Size: {frame.shape}")
                                elif frame_count % 100 == 0:
                                    self.logger.debug(f"Received {frame_count} frames")
                            
                except Exception as e:
                    print(f"[MJPEG Thread] Error in stream: {e}")
                    print(f"[MJPEG Thread] Traceback: {traceback.format_exc()}")
                    self.logger.error(f"Stream error: {e}\n{traceback.format_exc()}")
                    self.error_count += 1
                    time.sleep(self.reconnect_delay)
                    
        except Exception as e:
            print(f"[MJPEG Thread] Fatal error: {e}")
            print(f"[MJPEG Thread] Traceback: {traceback.format_exc()}")
            self.logger.error(f"Fatal stream error: {e}\n{traceback.format_exc()}")
    
    def _rotate_frame(self, frame: np.ndarray, rotation: int) -> np.ndarray:
        """Rotate frame by specified degrees"""
        if rotation == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif rotation == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        elif rotation == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        else:
            return frame
    
    async def disconnect(self):
        """Disconnect from camera"""
        self.stop_stream = True
        if self.stream_thread and self.stream_thread.is_alive():
            self.stream_thread.join(timeout=2)
        self.is_connected = False
        self.logger.info("MJPEG camera disconnected")
    
    async def read_frame(self, intersection_id: int) -> Optional[CameraFrame]:
        """Read a single frame from the camera"""
        if not self.is_connected or self.current_frame is None:
            return None
        
        try:
            # Get current frame
            frame = self.current_frame.copy()
            
            self.frame_count += 1
            current_time = datetime.utcnow()
            
            # Calculate FPS
            actual_fps = self.target_fps
            if self.last_frame_time:
                time_diff = (current_time - self.last_frame_time).total_seconds()
                if time_diff > 0:
                    actual_fps = 1.0 / time_diff
            
            self.last_frame_time = current_time
            
            # Convert frame to JPEG bytes
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ret:
                self.logger.error("Failed to encode frame to JPG")
                return None
            
            return CameraFrame(
                message_id=f"{self.camera_id}-{self.frame_count}-{current_time.isoformat()}",
                timestamp=current_time,
                sensor_id=self.camera_id,
                frame_id=str(self.frame_count),
                width=frame.shape[1],
                height=frame.shape[0],
                format="jpeg",
                fps=actual_fps,
                frame_data=buffer.tobytes()
            )
            
        except Exception as e:
            self.logger.error(f"Error reading frame: {e}")
            return None

