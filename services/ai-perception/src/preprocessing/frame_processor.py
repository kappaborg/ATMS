"""
AI Perception Service - Frame Preprocessor
Week 2: Professional Image Preprocessing Pipeline
"""
import cv2
import numpy as np
from typing import Tuple, Optional
import sys
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent.parent))
from shared.utils.logger import get_logger

logger = get_logger(__name__)


class FrameProcessor:
    """
    Professional Frame Preprocessing Pipeline
    
    Features:
    - Multiple resize methods (letterbox, resize, crop)
    - Normalization
    - Color space conversion
    - Quality validation
    - Batch processing
    """
    
    def __init__(
        self,
        target_size: Tuple[int, int] = (640, 640),
        resize_method: str = "letterbox",
        normalize: bool = True,
        mean: Tuple[float, float, float] = (0.485, 0.456, 0.406),
        std: Tuple[float, float, float] = (0.229, 0.224, 0.225),
        bgr_to_rgb: bool = False
    ):
        """
        Initialize frame processor
        
        Args:
            target_size: Target image size (width, height)
            resize_method: Resize method (letterbox/resize/crop)
            normalize: Whether to normalize pixel values
            mean: Mean values for normalization
            std: Standard deviation for normalization
            bgr_to_rgb: Convert BGR to RGB
        """
        self.target_size = target_size
        self.resize_method = resize_method
        self.normalize = normalize
        self.mean = np.array(mean).reshape(1, 1, 3)
        self.std = np.array(std).reshape(1, 1, 3)
        self.bgr_to_rgb = bgr_to_rgb
        
        self.processed_count = 0
        
        self.logger = logger.bind(
            target_size=target_size,
            resize_method=resize_method
        )
    
    def process(self, frame: np.ndarray) -> Tuple[np.ndarray, dict]:
        """
        Process a single frame
        
        Args:
            frame: Input frame (numpy array)
            
        Returns:
            Tuple of (processed_frame, metadata)
        """
        if frame is None or frame.size == 0:
            self.logger.warning("Empty frame received")
            return None, {}
        
        try:
            original_size = (frame.shape[1], frame.shape[0])  # (width, height)
            
            # Color space conversion
            if self.bgr_to_rgb:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Resize
            if self.resize_method == "letterbox":
                processed, scale, pad = self._letterbox_resize(frame)
                metadata = {
                    "original_size": original_size,
                    "processed_size": self.target_size,
                    "scale": scale,
                    "padding": pad,
                    "resize_method": "letterbox"
                }
            elif self.resize_method == "resize":
                processed = cv2.resize(frame, self.target_size)
                metadata = {
                    "original_size": original_size,
                    "processed_size": self.target_size,
                    "scale": (
                        self.target_size[0] / original_size[0],
                        self.target_size[1] / original_size[1]
                    ),
                    "resize_method": "resize"
                }
            elif self.resize_method == "crop":
                processed = self._center_crop(frame)
                metadata = {
                    "original_size": original_size,
                    "processed_size": self.target_size,
                    "resize_method": "crop"
                }
            else:
                processed = frame
                metadata = {
                    "original_size": original_size,
                    "resize_method": "none"
                }
            
            # Normalize
            if self.normalize:
                processed = self._normalize(processed)
                metadata["normalized"] = True
            
            self.processed_count += 1
            
            return processed, metadata
            
        except Exception as e:
            self.logger.error(f"Error processing frame: {e}", exc_info=True)
            return None, {}
    
    def _letterbox_resize(
        self,
        frame: np.ndarray
    ) -> Tuple[np.ndarray, float, Tuple[int, int]]:
        """
        Letterbox resize - maintain aspect ratio with padding
        
        Args:
            frame: Input frame
            
        Returns:
            Tuple of (resized_frame, scale, padding)
        """
        h, w = frame.shape[:2]
        target_w, target_h = self.target_size
        
        # Calculate scaling factor
        scale = min(target_w / w, target_h / h)
        
        # New size
        new_w = int(w * scale)
        new_h = int(h * scale)
        
        # Resize
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        
        # Create canvas with padding
        canvas = np.full((target_h, target_w, 3), 114, dtype=np.uint8)  # Gray padding
        
        # Calculate padding
        pad_w = (target_w - new_w) // 2
        pad_h = (target_h - new_h) // 2
        
        # Place resized image on canvas
        canvas[pad_h:pad_h + new_h, pad_w:pad_w + new_w] = resized
        
        return canvas, scale, (pad_w, pad_h)
    
    def _center_crop(self, frame: np.ndarray) -> np.ndarray:
        """
        Center crop to target size
        
        Args:
            frame: Input frame
            
        Returns:
            Cropped frame
        """
        h, w = frame.shape[:2]
        target_w, target_h = self.target_size
        
        # Calculate crop coordinates
        start_x = max(0, (w - target_w) // 2)
        start_y = max(0, (h - target_h) // 2)
        end_x = start_x + target_w
        end_y = start_y + target_h
        
        # Crop
        cropped = frame[start_y:end_y, start_x:end_x]
        
        # If cropped size doesn't match target, resize
        if cropped.shape[:2] != (target_h, target_w):
            cropped = cv2.resize(cropped, self.target_size)
        
        return cropped
    
    def _normalize(self, frame: np.ndarray) -> np.ndarray:
        """
        Normalize frame using mean and std
        
        Args:
            frame: Input frame (0-255)
            
        Returns:
            Normalized frame
        """
        # Convert to float and scale to [0, 1]
        frame = frame.astype(np.float32) / 255.0
        
        # Normalize using mean and std
        frame = (frame - self.mean) / self.std
        
        return frame
    
    def denormalize(self, frame: np.ndarray) -> np.ndarray:
        """
        Denormalize frame back to [0, 255]
        
        Args:
            frame: Normalized frame
            
        Returns:
            Denormalized frame
        """
        # Denormalize
        frame = (frame * self.std) + self.mean
        
        # Scale to [0, 255]
        frame = (frame * 255.0).clip(0, 255).astype(np.uint8)
        
        return frame
    
    def process_batch(self, frames: list) -> Tuple[list, list]:
        """
        Process batch of frames
        
        Args:
            frames: List of input frames
            
        Returns:
            Tuple of (processed_frames, metadata_list)
        """
        processed_frames = []
        metadata_list = []
        
        for frame in frames:
            processed, metadata = self.process(frame)
            if processed is not None:
                processed_frames.append(processed)
                metadata_list.append(metadata)
        
        return processed_frames, metadata_list
    
    def validate_frame(self, frame: np.ndarray) -> bool:
        """
        Validate frame quality
        
        Args:
            frame: Input frame
            
        Returns:
            bool: True if frame is valid
        """
        if frame is None or frame.size == 0:
            return False
        
        # Check dimensions
        if len(frame.shape) != 3 or frame.shape[2] != 3:
            return False
        
        # Check size
        h, w = frame.shape[:2]
        if h < 100 or w < 100:  # Minimum size
            return False
        
        # Check if frame is too dark or too bright
        mean_brightness = np.mean(frame)
        if mean_brightness < 10 or mean_brightness > 250:
            return False
        
        # Check variance (avoid blank frames)
        variance = np.var(frame)
        if variance < 100:
            return False
        
        return True
    
    def get_stats(self) -> dict:
        """Get processor statistics"""
        return {
            "processed_count": self.processed_count,
            "target_size": self.target_size,
            "resize_method": self.resize_method,
            "normalize": self.normalize
        }
    
    @staticmethod
    def decode_jpeg(jpeg_bytes: bytes) -> Optional[np.ndarray]:
        """
        Decode JPEG bytes to numpy array
        
        Args:
            jpeg_bytes: JPEG encoded bytes
            
        Returns:
            Decoded frame or None
        """
        try:
            # Convert bytes to numpy array
            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            
            # Decode image
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            return frame
        except Exception as e:
            logger.error(f"Error decoding JPEG: {e}")
            return None
    
    @staticmethod
    def encode_jpeg(frame: np.ndarray, quality: int = 85) -> Optional[bytes]:
        """
        Encode frame to JPEG bytes
        
        Args:
            frame: Input frame
            quality: JPEG quality (0-100)
            
        Returns:
            JPEG encoded bytes or None
        """
        try:
            # Encode image
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            
            return buffer.tobytes()
        except Exception as e:
            logger.error(f"Error encoding JPEG: {e}")
            return None

