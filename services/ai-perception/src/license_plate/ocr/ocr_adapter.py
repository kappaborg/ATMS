"""
OCR Adapter - Bridges Advanced OCR with existing PlateText format
Allows seamless integration of new OCR methods
"""
import logging
from typing import Optional
import numpy as np

from license_plate.ocr.plate_ocr import PlateText, OCRMethod as OldOCRMethod
from license_plate.ocr.advanced_ocr import AdvancedPlateOCR, OCRMethod as NewOCRMethod, OCRResult

logger = logging.getLogger(__name__)

class AdvancedOCRAdapter:
    """
    Adapter to use Advanced OCR with existing PlateText interface
    """
    
    def __init__(self, primary_method: NewOCRMethod = NewOCRMethod.PADDLEOCR):
        """
        Initialize adapter
        
        Args:
            primary_method: Primary OCR method (PaddleOCR recommended)
        """
        self.advanced_ocr = AdvancedPlateOCR(primary_method=primary_method, enable_fallback=True)
        logger.info(f"Advanced OCR Adapter initialized with {primary_method.value}")
    
    def recognize_text(self, plate_image: np.ndarray) -> PlateText:
        """
        Recognize text - compatible with existing interface
        
        Args:
            plate_image: License plate image (BGR format)
        
        Returns:
            PlateText object (existing format)
        """
        # Use advanced OCR
        result: OCRResult = self.advanced_ocr.recognize_text(plate_image)
        
        # Convert to PlateText format
        return result.to_plate_text()

