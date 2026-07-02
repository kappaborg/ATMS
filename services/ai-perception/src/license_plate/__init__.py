"""
License Plate Recognition Module for ATMS
Complete license plate detection, OCR, and validation system
"""

from .detection.plate_detector import (
    PlateRegion,
    PlateDetection,
    YOLOPlateDetector,
    TraditionalPlateDetector,
    HybridPlateDetector
)

# SAHI detector (optional, requires sahi package)
try:
    from .detection.sahi_plate_detector import SAHIPlateDetector, SAHIConfig
    SAHI_AVAILABLE = True
except ImportError:
    SAHI_AVAILABLE = False
    SAHIPlateDetector = None
    SAHIConfig = None

from .ocr.plate_ocr import (
    OCRMethod,
    PlateText,
    TesseractOCR,
    EasyOCR,
    HybridOCR
)

# Professional OCR (best accuracy)
try:
    from .ocr.professional_ocr import ProfessionalPlateOCR, OCRResult as ProfessionalOCRResult
    from .ocr.professional_ocr_adapter import ProfessionalOCRAdapter
    PROFESSIONAL_OCR_AVAILABLE = True
except ImportError:
    PROFESSIONAL_OCR_AVAILABLE = False
    ProfessionalPlateOCR = None
    ProfessionalOCRAdapter = None
    ProfessionalOCRResult = None

from .validation.plate_validator import (
    PlateFormat,
    ValidationResult,
    PlateValidation,
    LicensePlateValidator,
    PlateAnonymizer
)

__all__ = [
    # Detection
    'PlateRegion',
    'PlateDetection',
    'YOLOPlateDetector',
    'TraditionalPlateDetector',
    'HybridPlateDetector',
    'SAHIPlateDetector',  # SAHI detector (if available)
    'SAHIConfig',  # SAHI configuration (if available)
    'SAHI_AVAILABLE',  # Flag indicating SAHI availability
    
    # OCR
    'OCRMethod',
    'PlateText',
    'TesseractOCR',
    'EasyOCR',
    'HybridOCR',
    'ProfessionalPlateOCR',  # Professional OCR (if available)
    'ProfessionalOCRAdapter',  # Professional OCR adapter (if available)
    'ProfessionalOCRResult',  # Professional OCR result (if available)
    'PROFESSIONAL_OCR_AVAILABLE',  # Flag indicating Professional OCR availability
    
    # Validation
    'PlateFormat',
    'ValidationResult',
    'PlateValidation',
    'LicensePlateValidator',
    'PlateAnonymizer'
]
