"""
License Plate OCR Module for ATMS
High-accuracy text recognition for license plates
"""

import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
import time
import logging
from collections import deque
import re
import string

logger = logging.getLogger(__name__)

class OCRMethod(Enum):
    """OCR methods available"""
    TESSERACT = "tesseract"
    EASYOCR = "easyocr"
    PADDLEOCR = "paddleocr"
    TRADITIONAL = "traditional"

@dataclass
class PlateText:
    """License plate text recognition result"""
    text: str
    confidence: float
    method_used: OCRMethod
    raw_text: str
    cleaned_text: str
    timestamp: float
    region: Optional[str] = None

class TesseractOCR:
    """
    Tesseract-based OCR for license plates
    Reliable and widely used
    """
    
    def __init__(self, 
                 language: str = "eng",
                 config: str = "--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"):
        """
        Initialize Tesseract OCR
        
        Args:
            language: OCR language
            config: Tesseract configuration
        """
        self.language = language
        self.config = config
        
        # Performance tracking
        self.ocr_times = deque(maxlen=100)
        self.total_ocrs = 0
        self.successful_ocrs = 0
        
        # Initialize Tesseract
        self.tesseract = None
        self._initialize_tesseract()
        
        logger.info(f"Tesseract OCR initialized: {language}")
    
    def _initialize_tesseract(self):
        """Initialize Tesseract"""
        try:
            import pytesseract
            self.tesseract = pytesseract
            logger.info("Tesseract initialized successfully")
        except ImportError:
            logger.error("pytesseract not installed. Install with: pip install pytesseract")
            self.tesseract = None
        except Exception as e:
            logger.error(f"Failed to initialize Tesseract: {e}")
            self.tesseract = None
    
    def recognize_text(self, plate_image: np.ndarray) -> PlateText:
        """
        Recognize text in license plate image
        
        Args:
            plate_image: License plate image (BGR format)
        
        Returns:
            Plate text recognition result
        """
        if self.tesseract is None:
            return PlateText(
                text="",
                confidence=0.0,
                method_used=OCRMethod.TESSERACT,
                raw_text="",
                cleaned_text="",
                timestamp=time.time()
            )
        
        start_time = time.time()
        
        try:
            # Preprocess image for better OCR
            processed_image = self._preprocess_for_ocr(plate_image)
            
            # Run OCR
            raw_text = self.tesseract.image_to_string(
                processed_image, 
                lang=self.language, 
                config=self.config
            )
            
            # Get confidence
            data = self.tesseract.image_to_data(
                processed_image, 
                lang=self.language, 
                config=self.config, 
                output_type=self.tesseract.Output.DICT
            )
            
            # Calculate average confidence
            confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]
            avg_confidence = np.mean(confidences) / 100.0 if confidences else 0.0
            
            # Clean and validate text
            cleaned_text = self._clean_plate_text(raw_text)
            
            # Update metrics
            processing_time = time.time() - start_time
            self.ocr_times.append(processing_time)
            self.total_ocrs += 1
            
            if cleaned_text:
                self.successful_ocrs += 1
            
            logger.debug(f"Tesseract OCR: '{cleaned_text}' (confidence: {avg_confidence:.2f}) in {processing_time*1000:.2f}ms")
            
            return PlateText(
                text=cleaned_text,
                confidence=avg_confidence,
                method_used=OCRMethod.TESSERACT,
                raw_text=raw_text,
                cleaned_text=cleaned_text,
                timestamp=time.time()
            )
            
        except Exception as e:
            logger.error(f"Tesseract OCR failed: {e}")
            return PlateText(
                text="",
                confidence=0.0,
                method_used=OCRMethod.TESSERACT,
                raw_text="",
                cleaned_text="",
                timestamp=time.time()
            )
    
    def _preprocess_for_ocr(self, image: np.ndarray) -> np.ndarray:
        """Preprocess image for better OCR results"""
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Resize if too small
        height, width = gray.shape
        if height < 30 or width < 100:
            scale_factor = max(30 / height, 100 / width)
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            gray = cv2.resize(gray, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
        
        # Apply Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        
        # Apply adaptive threshold
        binary = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        
        # Morphological operations to clean up
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        
        return binary
    
    def _clean_plate_text(self, text: str) -> str:
        """Clean and validate license plate text"""
        if not text:
            return ""
        
        # Remove whitespace and special characters
        cleaned = re.sub(r'[^A-Z0-9]', '', text.upper())
        
        # Remove common OCR errors
        cleaned = cleaned.replace('O', '0')  # Replace O with 0
        cleaned = cleaned.replace('I', '1')  # Replace I with 1
        cleaned = cleaned.replace('S', '5')  # Replace S with 5
        
        # Validate length (typical license plates are 6-8 characters)
        if len(cleaned) < 3 or len(cleaned) > 10:
            return ""
        
        return cleaned
    
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics"""
        avg_processing_time = np.mean(self.ocr_times) if self.ocr_times else 0
        success_rate = self.successful_ocrs / self.total_ocrs if self.total_ocrs > 0 else 0
        
        return {
            'total_ocrs': self.total_ocrs,
            'successful_ocrs': self.successful_ocrs,
            'success_rate': success_rate,
            'avg_processing_time_ms': avg_processing_time * 1000,
            'max_processing_time_ms': max(self.ocr_times) * 1000 if self.ocr_times else 0,
            'tesseract_available': self.tesseract is not None
        }

class EasyOCR:
    """
    EasyOCR-based OCR for license plates
    High accuracy for various languages
    """
    
    def __init__(self, 
                 languages: List[str] = ['en'],
                 gpu: bool = False):
        """
        Initialize EasyOCR
        
        Args:
            languages: List of languages to support
            gpu: Use GPU acceleration
        """
        self.languages = languages
        self.gpu = gpu
        
        # Performance tracking
        self.ocr_times = deque(maxlen=100)
        self.total_ocrs = 0
        self.successful_ocrs = 0
        
        # Initialize EasyOCR
        self.easyocr = None
        self._initialize_easyocr()
        
        logger.info(f"EasyOCR initialized: {languages}")
    
    def _initialize_easyocr(self):
        """Initialize EasyOCR"""
        try:
            import easyocr
            self.easyocr = easyocr.Reader(self.languages, gpu=self.gpu)
            logger.info("EasyOCR initialized successfully")
        except ImportError:
            logger.error("easyocr not installed. Install with: pip install easyocr")
            self.easyocr = None
        except Exception as e:
            logger.error(f"Failed to initialize EasyOCR: {e}")
            self.easyocr = None
    
    def _preprocess_for_ocr(self, image: np.ndarray) -> np.ndarray:
        """Preprocess image for better OCR results - GENTLE ENHANCEMENT (don't destroy text)"""
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        original_height, original_width = gray.shape
        
        # Strategy 1: Aggressive upscaling for small plates (EasyOCR needs larger images)
        # Minimum 120x300 for good OCR (increased from 80x200)
        height, width = gray.shape
        if height < 120 or width < 300:
            # More aggressive upscaling (3-6x) for very small plates
            scale_factor = max(120 / height, 300 / width, 3.0)
            scale_factor = min(scale_factor, 6.0)  # Cap at 6x (was 4x)
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            gray = cv2.resize(gray, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)  # Better quality than CUBIC
            logger.debug(f"Upscaled plate from {original_width}x{original_height} to {new_width}x{new_height} ({scale_factor:.1f}x)")
        
        # Strategy 2: Stronger contrast enhancement for blurry plates
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))  # Increased from 2.0
        enhanced = clahe.apply(gray)
        
        # Strategy 3: Light denoising (keep h=5 to preserve text)
        denoised = cv2.fastNlMeansDenoising(enhanced, None, h=5, templateWindowSize=7, searchWindowSize=21)
        
        # Strategy 4: Gentle sharpening for blurry plates (reduced intensity)
        # Less aggressive sharpening to avoid artifacts
        kernel = np.array([[-0.5, -0.5, -0.5],
                          [-0.5,  5.0, -0.5],
                          [-0.5, -0.5, -0.5]])
        sharpened = cv2.filter2D(denoised, -1, kernel)
        
        # Strategy 5: Return grayscale (NOT binary) - EasyOCR works better on grayscale
        # CRITICAL: Don't over-process - EasyOCR often works better on less processed images
        return sharpened
    
    def _clean_plate_text(self, text: str) -> str:
        """Clean and validate license plate text"""
        if not text:
            return ""
        
        # Remove whitespace and special characters
        cleaned = re.sub(r'[^A-Z0-9]', '', text.upper())
        
        # Remove common OCR errors
        cleaned = cleaned.replace('O', '0')  # Replace O with 0
        cleaned = cleaned.replace('I', '1')  # Replace I with 1
        cleaned = cleaned.replace('S', '5')  # Replace S with 5
        
        # Validate length (typical license plates are 6-8 characters)
        if len(cleaned) < 3 or len(cleaned) > 10:
            return ""
        
        return cleaned
    
    def recognize_text(self, plate_image: np.ndarray) -> PlateText:
        """
        Recognize text in license plate image
        
        Args:
            plate_image: License plate image (BGR format)
        
        Returns:
            Plate text recognition result
        """
        if self.easyocr is None:
            return PlateText(
                text="",
                confidence=0.0,
                method_used=OCRMethod.EASYOCR,
                raw_text="",
                cleaned_text="",
                timestamp=time.time()
            )
        
        start_time = time.time()
        
        try:
            # Preprocess plate image for better OCR results
            # CRITICAL: Process ALL plates, no matter how small - upscaling will handle it
            height, width = plate_image.shape[:2]
            
            # Log plate image info for debugging
            logger.info(f"📸 OCR Input: {width}x{height}, dtype={plate_image.dtype}, min={plate_image.min()}, max={plate_image.max()}")
            
            # Only reject if completely invalid
            if height < 5 or width < 10:  # Only reject extremely tiny (was 15x40)
                logger.warning(f"❌ Plate image too small for OCR: {width}x{height}")
                return PlateText(
                    text="",
                    confidence=0.0,
                    method_used=OCRMethod.EASYOCR,
                    raw_text="",
                    cleaned_text="",
                    timestamp=time.time()
                )
            
            # Log small plates - we'll upscale them
            if height < 50 or width < 100:
                logger.warning(f"⚠️ Small plate detected: {width}x{height} - will upscale aggressively (may affect OCR accuracy)")
            
            # Enhance image for OCR (more aggressive preprocessing)
            processed_image = self._preprocess_for_ocr(plate_image)
            
            # Run OCR with multiple attempts - try different preprocessing strategies
            results = None
            
            # CRITICAL: Try original image FIRST (before preprocessing) - EasyOCR often works better on original
            # Attempt 1: Original color image (BEST for EasyOCR)
            try:
                orig_color = plate_image.copy()
                orig_h, orig_w = orig_color.shape[:2]
                # CRITICAL: More aggressive upscaling for small plates
                # Minimum 150x300 for good OCR (increased from 100x200)
                if orig_h < 150 or orig_w < 300:
                    scale = max(150 / orig_h, 300 / orig_w, 3.0)  # Start at 3x minimum
                    scale = min(scale, 8.0)  # Allow up to 8x upscaling (was 4x)
                    orig_color = cv2.resize(orig_color, (int(orig_w * scale), int(orig_h * scale)), interpolation=cv2.INTER_LANCZOS4)
                    logger.debug(f"Upscaled original color from {orig_w}x{orig_h} to {int(orig_w*scale)}x{int(orig_h*scale)} ({scale:.1f}x)")
                
                # CRITICAL: Use simpler, more permissive parameters (inspired by GitHub repo)
                # The repository uses default EasyOCR parameters which work better
                # Try simple call first (like GitHub repo), then fallback to permissive parameters
                try:
                    # Attempt 1: Simple call without restrictions (like GitHub repo)
                    results = self.easyocr.readtext(
                        orig_color, 
                        detail=1, 
                        paragraph=False
                    )
                    if not results:
                        # Attempt 2: With permissive parameters
                        results = self.easyocr.readtext(
                            orig_color, 
                            detail=1, 
                            paragraph=False, 
                            width_ths=0.3,  # Very permissive (was 0.5)
                            height_ths=0.3,  # Very permissive (was 0.5)
                            allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                            decoder='beamsearch',
                            beamWidth=5
                        )
                except Exception as e:
                    logger.debug(f"OCR call failed: {e}, trying fallback...")
                    # Fallback: Most permissive settings
                    try:
                        results = self.easyocr.readtext(
                            orig_color, 
                            detail=1, 
                            paragraph=False,
                            width_ths=0.1,  # Extremely permissive
                            height_ths=0.1  # Extremely permissive
                        )
                    except Exception as e2:
                        logger.debug(f"Fallback OCR also failed: {e2}")
                        results = None
                if results:
                    logger.debug(f"✅ OCR success on original color image")
            except Exception as e:
                logger.debug(f"OCR attempt 1 (original color) failed: {e}")
            
            # Attempt 2: Original grayscale (upscaled if needed)
            if not results:
                logger.debug(f"Trying original grayscale...")
                if len(plate_image.shape) == 3:
                    orig_gray = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
                else:
                    orig_gray = plate_image.copy()
                
                # Upscale if small (same aggressive upscaling as color)
                orig_h, orig_w = orig_gray.shape
                if orig_h < 200 or orig_w < 400:
                    scale = max(200 / orig_h, 400 / orig_w, 4.0)  # Match color upscaling
                    scale = min(scale, 10.0)
                    orig_gray = cv2.resize(orig_gray, (int(orig_w * scale), int(orig_h * scale)), interpolation=cv2.INTER_LANCZOS4)
                    logger.info(f"📏 Upscaled grayscale from {orig_w}x{orig_h} to {int(orig_w*scale)}x{int(orig_h*scale)} ({scale:.1f}x)")
                
                try:
                    # Try simple call first (like GitHub repo)
                    results = self.easyocr.readtext(
                        orig_gray, 
                        detail=1, 
                        paragraph=False
                    )
                    if not results:
                        # Fallback to permissive parameters
                        results = self.easyocr.readtext(
                            orig_gray, 
                            detail=1, 
                            paragraph=False, 
                            width_ths=0.3,
                            height_ths=0.3,
                            allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                            decoder='beamsearch',
                            beamWidth=5
                        )
                    if results:
                        logger.debug(f"✅ OCR success on original grayscale")
                except Exception as e:
                    logger.debug(f"OCR attempt 2 failed: {e}")
                    results = None
            
            # Attempt 3: Processed grayscale (gentle enhancement) - LAST RESORT
            if not results:
                logger.debug(f"Trying processed grayscale (last resort)...")
                try:
                    # Try simple call first (like GitHub repo)
                    results = self.easyocr.readtext(
                        processed_image, 
                        detail=1, 
                        paragraph=False
                    )
                    if not results:
                        # Fallback to permissive parameters
                        results = self.easyocr.readtext(
                            processed_image, 
                            detail=1, 
                            paragraph=False, 
                            width_ths=0.3,
                            height_ths=0.3,
                            allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                            decoder='beamsearch',
                            beamWidth=5
                        )
                    if results:
                        logger.debug(f"✅ OCR success on processed grayscale")
                except Exception as e:
                    logger.debug(f"OCR attempt 3 failed: {e}")
                    results = None
            
            if not results:
                logger.debug(f"EasyOCR found no text in plate image ({width}x{height}) after all attempts")
                return PlateText(
                    text="",
                    confidence=0.0,
                    method_used=OCRMethod.EASYOCR,
                    raw_text="",
                    cleaned_text="",
                    timestamp=time.time()
                )
            
            # Get best result
            best_result = max(results, key=lambda x: x[2])  # Highest confidence
            raw_text = best_result[1]
            confidence = best_result[2]
            
            # CRITICAL FIX: Accept ANY text result from EasyOCR, even with very low confidence
            # EasyOCR often returns correct text with low confidence, especially for blurry/distant plates
            # We'll let the validator decide if it's a valid plate format
            
            # Clean and validate text
            cleaned_preview = re.sub(r'[^A-Z0-9]', '', raw_text.upper())
            is_plate_like = (
                len(cleaned_preview) >= 2 and  # Lowered from 3 to 2 (some plates might be partially visible)
                len(cleaned_preview) <= 12 and  # Increased from 10 to 12 (some plates are longer)
                (any(c.isdigit() for c in cleaned_preview) or any(c.isalpha() for c in cleaned_preview))
            )
            
            # ACCEPT ALL RESULTS from EasyOCR (even confidence 0.01)
            # Only reject if:
            # 1. Text is completely empty
            # 2. Text is too short (< 2 chars after cleaning)
            # 3. Text doesn't look like a plate at all (no alphanumeric)
            
            if not raw_text or len(raw_text.strip()) == 0:
                logger.debug(f"EasyOCR returned empty text")
                return PlateText(
                    text="",
                    confidence=0.0,
                    method_used=OCRMethod.EASYOCR,
                    raw_text="",
                    cleaned_text="",
                    timestamp=time.time()
                )
            
            # CRITICAL: Accept ANY text result from EasyOCR (GitHub repo approach)
            # EasyOCR is generally accurate, so trust its output
            # Only reject if completely empty or obviously invalid
            
            # Clean and validate text FIRST (before rejecting)
            cleaned_text = self._clean_plate_text(raw_text)
            
            # If cleaned text is empty, try using raw_text (might be valid but filtered)
            if not cleaned_text and raw_text:
                # Check if raw_text has any alphanumeric characters
                raw_alnum = re.sub(r'[^A-Z0-9]', '', raw_text.upper())
                if len(raw_alnum) >= 2:  # At least 2 alphanumeric characters
                    cleaned_text = raw_alnum
                    logger.debug(f"Using raw text after cleaning failed: '{raw_text}' -> '{cleaned_text}'")
            
            # If it looks like a plate (even slightly), accept it
            if is_plate_like:
                logger.info(f"✅ Accepting plate-like text '{raw_text}' (confidence: {confidence:.3f}, cleaned: '{cleaned_preview}')")
            elif cleaned_text:
                # Even if not plate-like but we have cleaned text, accept it
                logger.info(f"✅ Accepting text '{raw_text}' (confidence: {confidence:.3f}, cleaned: '{cleaned_text}')")
            else:
                # Only reject if we have no cleaned text AND confidence is very low
                if confidence < 0.01:
                    logger.debug(f"Rejecting text '{raw_text}' (confidence: {confidence:.3f} too low, no valid text)")
                    return PlateText(
                        text="",
                        confidence=0.0,
                        method_used=OCRMethod.EASYOCR,
                        raw_text=raw_text,
                        cleaned_text="",
                        timestamp=time.time()
                    )
                else:
                    # Accept even with low confidence if we have some text
                    logger.info(f"✅ Accepting text '{raw_text}' (confidence: {confidence:.3f}, low but above threshold)")
                    cleaned_text = cleaned_preview if cleaned_preview else raw_text.strip()
            
            # Update metrics
            processing_time = time.time() - start_time
            self.ocr_times.append(processing_time)
            self.total_ocrs += 1
            
            if cleaned_text:
                self.successful_ocrs += 1
            
            logger.debug(f"EasyOCR: '{cleaned_text}' (confidence: {confidence:.2f}) in {processing_time*1000:.2f}ms")
            
            return PlateText(
                text=cleaned_text,
                confidence=confidence,
                method_used=OCRMethod.EASYOCR,
                raw_text=raw_text,
                cleaned_text=cleaned_text,
                timestamp=time.time()
            )
            
        except Exception as e:
            logger.error(f"EasyOCR failed: {e}")
            return PlateText(
                text="",
                confidence=0.0,
                method_used=OCRMethod.EASYOCR,
                raw_text="",
                cleaned_text="",
                timestamp=time.time()
            )
    
    def _clean_plate_text(self, text: str) -> str:
        """Clean and validate license plate text"""
        if not text:
            return ""
        
        # Remove whitespace and special characters
        cleaned = re.sub(r'[^A-Z0-9]', '', text.upper())
        
        # Remove common OCR errors
        cleaned = cleaned.replace('O', '0')
        cleaned = cleaned.replace('I', '1')
        cleaned = cleaned.replace('S', '5')
        
        # Validate length
        if len(cleaned) < 3 or len(cleaned) > 10:
            return ""
        
        return cleaned
    
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics"""
        avg_processing_time = np.mean(self.ocr_times) if self.ocr_times else 0
        success_rate = self.successful_ocrs / self.total_ocrs if self.total_ocrs > 0 else 0
        
        return {
            'total_ocrs': self.total_ocrs,
            'successful_ocrs': self.successful_ocrs,
            'success_rate': success_rate,
            'avg_processing_time_ms': avg_processing_time * 1000,
            'max_processing_time_ms': max(self.ocr_times) * 1000 if self.ocr_times else 0,
            'easyocr_available': self.easyocr is not None
        }

class HybridOCR:
    """
    Hybrid OCR combining multiple methods
    Provides best accuracy and reliability
    """
    
    def __init__(self, 
                 primary_method: OCRMethod = OCRMethod.TESSERACT,
                 fallback_methods: List[OCRMethod] = None,
                 confidence_threshold: float = 0.7):
        """
        Initialize hybrid OCR
        
        Args:
            primary_method: Primary OCR method
            fallback_methods: Fallback methods
            confidence_threshold: Confidence threshold for method selection
        """
        self.primary_method = primary_method
        self.fallback_methods = fallback_methods or [OCRMethod.EASYOCR]
        self.confidence_threshold = confidence_threshold
        
        # Initialize OCR methods
        self.ocr_methods = {}
        self._initialize_methods()
        
        # Performance tracking
        self.ocr_times = deque(maxlen=100)
        self.total_ocrs = 0
        self.successful_ocrs = 0
        self.method_usage = {}
        
        logger.info(f"Hybrid OCR initialized: primary={primary_method}, fallbacks={fallback_methods}")
    
    def _initialize_methods(self):
        """Initialize OCR methods"""
        # Initialize Tesseract
        if self.primary_method == OCRMethod.TESSERACT or OCRMethod.TESSERACT in self.fallback_methods:
            self.ocr_methods[OCRMethod.TESSERACT] = TesseractOCR()
        
        # Initialize EasyOCR
        if self.primary_method == OCRMethod.EASYOCR or OCRMethod.EASYOCR in self.fallback_methods:
            self.ocr_methods[OCRMethod.EASYOCR] = EasyOCR()
    
    def recognize_text(self, plate_image: np.ndarray) -> PlateText:
        """
        Recognize text using hybrid approach
        
        Args:
            plate_image: License plate image (BGR format)
        
        Returns:
            Plate text recognition result
        """
        start_time = time.time()
        
        # Try primary method first
        primary_result = self._try_method(self.primary_method, plate_image)
        
        if primary_result.confidence >= self.confidence_threshold:
            result = primary_result
        else:
            # Try fallback methods
            best_result = primary_result
            
            for method in self.fallback_methods:
                if method in self.ocr_methods:
                    fallback_result = self._try_method(method, plate_image)
                    
                    if fallback_result.confidence > best_result.confidence:
                        best_result = fallback_result
            
            result = best_result
        
        # Update metrics
        processing_time = time.time() - start_time
        self.ocr_times.append(processing_time)
        self.total_ocrs += 1
        
        if result.text:
            self.successful_ocrs += 1
        
        # Track method usage
        method_name = result.method_used.value if hasattr(result.method_used, 'value') else str(result.method_used)
        self.method_usage[method_name] = self.method_usage.get(method_name, 0) + 1
        
        method_display = result.method_used.value if hasattr(result.method_used, 'value') else str(result.method_used)
        logger.debug(f"Hybrid OCR: {len(result.text)} chars (confidence: {result.confidence:.2f}, method: {method_display}) in {processing_time*1000:.2f}ms")
        
        return result
    
    def _try_method(self, method: OCRMethod, plate_image: np.ndarray) -> PlateText:
        """Try specific OCR method"""
        if method not in self.ocr_methods:
            return PlateText(
                text="",
                confidence=0.0,
                method_used=method,
                raw_text="",
                cleaned_text="",
                timestamp=time.time()
            )
        
        try:
            return self.ocr_methods[method].recognize_text(plate_image)
        except Exception as e:
            method_name = method.value if hasattr(method, 'value') else str(method)
            logger.error(f"OCR method {method_name} failed: {e}")
            return PlateText(
                text="",
                confidence=0.0,
                method_used=method,
                raw_text="",
                cleaned_text="",
                timestamp=time.time()
            )
    
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics"""
        avg_processing_time = np.mean(self.ocr_times) if self.ocr_times else 0
        success_rate = self.successful_ocrs / self.total_ocrs if self.total_ocrs > 0 else 0
        
        # Get metrics from individual methods
        method_metrics = {}
        for method_name, method in self.ocr_methods.items():
            method_key = method_name.value if hasattr(method_name, 'value') else str(method_name)
            method_metrics[method_key] = method.get_performance_metrics()
        
        return {
            'total_ocrs': self.total_ocrs,
            'successful_ocrs': self.successful_ocrs,
            'success_rate': success_rate,
            'avg_processing_time_ms': avg_processing_time * 1000,
            'max_processing_time_ms': max(self.ocr_times) * 1000 if self.ocr_times else 0,
            'method_usage': self.method_usage,
            'method_metrics': method_metrics
        }
