"""
Advanced OCR Module for License Plates
Implements multiple state-of-the-art OCR methods with intelligent selection
"""
import cv2
import numpy as np
from typing import Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum
import time
import logging
import re

logger = logging.getLogger(__name__)

class OCRMethod(Enum):
    """OCR methods available"""
    PADDLEOCR = "paddleocr"
    EASYOCR = "easyocr"
    TESSERACT = "tesseract"
    TROCR = "trocr"  # Transformer-based OCR
    MMOCR = "mmocr"

@dataclass
class OCRResult:
    """OCR recognition result"""
    text: str
    confidence: float
    method: OCRMethod
    raw_text: str
    processing_time_ms: float
    bbox: Optional[Tuple[float, float, float, float]] = None
    
    def to_plate_text(self):
        """Convert to PlateText format for compatibility"""
        try:
            from license_plate.ocr.plate_ocr import PlateText, OCRMethod as OldOCRMethod
            
            # Map new OCRMethod to old OCRMethod enum
            method_map = {
                OCRMethod.PADDLEOCR: OldOCRMethod.PADDLEOCR,
                OCRMethod.EASYOCR: OldOCRMethod.EASYOCR,
                OCRMethod.TESSERACT: OldOCRMethod.TESSERACT,
            }
            
            old_method = method_map.get(self.method, OldOCRMethod.EASYOCR)
            
            return PlateText(
                text=self.text,
                confidence=self.confidence,
                method_used=old_method,
                raw_text=self.raw_text,
                cleaned_text=self.text,
                timestamp=time.time()
            )
        except Exception as e:
            logger.error(f"Error converting to PlateText: {e}")
            # Return minimal PlateText if conversion fails
            from license_plate.ocr.plate_ocr import PlateText, OCRMethod as OldOCRMethod
            return PlateText(
                text=self.text,
                confidence=self.confidence,
                method_used=OldOCRMethod.EASYOCR,
                raw_text=self.raw_text,
                cleaned_text=self.text,
                timestamp=time.time()
            )

class AdvancedPlateOCR:
    """
    Advanced OCR system with multiple methods and intelligent selection
    Optimized for small, blurry license plates
    """
    
    def __init__(self, 
                 primary_method: OCRMethod = OCRMethod.PADDLEOCR,
                 enable_fallback: bool = True):
        """
        Initialize Advanced OCR
        
        Args:
            primary_method: Primary OCR method to use
            enable_fallback: Enable fallback to other methods if primary fails
        """
        self.primary_method = primary_method
        self.enable_fallback = enable_fallback
        self.methods = {}
        
        # Initialize available methods
        self._initialize_methods()
        
        logger.info(f"Advanced OCR initialized: primary={primary_method.value}")
    
    def _initialize_methods(self):
        """Initialize all available OCR methods"""
        
        # 1. PaddleOCR (Best for license plates - high accuracy on small/blurry images)
        try:
            from paddleocr import PaddleOCR
            self.methods[OCRMethod.PADDLEOCR] = PaddleOCR(
                use_angle_cls=True,  # Use angle classification
                lang='en',
                use_gpu=False,  # Set to True if GPU available
                show_log=False
            )
            logger.info("✅ PaddleOCR initialized (BEST for license plates)")
        except ImportError:
            logger.warning("⚠️ PaddleOCR not installed. Install with: pip install paddleocr")
            self.methods[OCRMethod.PADDLEOCR] = None
        except Exception as e:
            logger.error(f"Failed to initialize PaddleOCR: {e}")
            self.methods[OCRMethod.PADDLEOCR] = None
        
        # 2. EasyOCR (Current method - keep as fallback)
        try:
            import easyocr
            self.methods[OCRMethod.EASYOCR] = easyocr.Reader(['en'], gpu=False)
            logger.info("✅ EasyOCR initialized")
        except ImportError:
            logger.warning("⚠️ EasyOCR not installed")
            self.methods[OCRMethod.EASYOCR] = None
        except Exception as e:
            logger.error(f"Failed to initialize EasyOCR: {e}")
            self.methods[OCRMethod.EASYOCR] = None
        
        # 3. Tesseract (Fallback)
        try:
            import pytesseract
            self.methods[OCRMethod.TESSERACT] = pytesseract
            logger.info("✅ Tesseract initialized")
        except ImportError:
            logger.warning("⚠️ Tesseract not installed")
            self.methods[OCRMethod.TESSERACT] = None
        except Exception as e:
            logger.error(f"Failed to initialize Tesseract: {e}")
            self.methods[OCRMethod.TESSERACT] = None
    
    def _enhance_image_for_ocr(self, image: np.ndarray) -> List[np.ndarray]:
        """
        Create multiple enhanced versions of the image for OCR
        Returns list of enhanced images to try
        """
        enhanced_images = []
        
        h, w = image.shape[:2]
        
        # Version 1: Aggressive upscaling (for very small plates)
        if h < 200 or w < 400:
            scale = max(200 / h, 400 / w, 5.0)  # Minimum 5x upscale
            scale = min(scale, 12.0)  # Max 12x
            upscaled = cv2.resize(image, (int(w * scale), int(h * scale)), 
                                 interpolation=cv2.INTER_LANCZOS4)
            enhanced_images.append(('upscaled_lanczos', upscaled))
        
        # Version 2: Grayscale with contrast enhancement
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # CLAHE for contrast
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
        enhanced_gray = clahe.apply(gray)
        
        # Upscale grayscale if small
        if h < 200 or w < 400:
            scale = max(200 / h, 400 / w, 5.0)
            scale = min(scale, 12.0)
            enhanced_gray = cv2.resize(enhanced_gray, (int(w * scale), int(h * scale)),
                                      interpolation=cv2.INTER_LANCZOS4)
        
        enhanced_images.append(('grayscale_enhanced', enhanced_gray))
        
        # Version 3: Sharpened version
        kernel = np.array([[-1, -1, -1],
                          [-1,  9, -1],
                          [-1, -1, -1]])
        sharpened = cv2.filter2D(enhanced_gray, -1, kernel)
        enhanced_images.append(('sharpened', sharpened))
        
        # Version 4: Denoised version
        denoised = cv2.fastNlMeansDenoising(enhanced_gray, None, h=3, 
                                           templateWindowSize=7, searchWindowSize=21)
        enhanced_images.append(('denoised', denoised))
        
        # Version 5: Adaptive threshold (binary)
        if enhanced_gray.shape[0] > 50:  # Only for larger images
            adaptive = cv2.adaptiveThreshold(enhanced_gray, 255, 
                                           cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                           cv2.THRESH_BINARY, 11, 2)
            enhanced_images.append(('adaptive_threshold', adaptive))
        
        return enhanced_images
    
    def _paddleocr_recognize(self, image: np.ndarray) -> Optional[OCRResult]:
        """Recognize text using PaddleOCR"""
        if OCRMethod.PADDLEOCR not in self.methods or self.methods[OCRMethod.PADDLEOCR] is None:
            return None
        
        try:
            start_time = time.time()
            result = self.methods[OCRMethod.PADDLEOCR].ocr(image, cls=True)
            
            processing_time = (time.time() - start_time) * 1000
            
            if not result or not result[0]:
                return None
            
            # PaddleOCR returns: [[[bbox, (text, confidence)], ...]]
            best_result = None
            best_confidence = 0.0
            
            for line in result[0]:
                if line and len(line) >= 2:
                    text_info = line[1]
                    if isinstance(text_info, tuple) and len(text_info) >= 2:
                        text, confidence = text_info[0], text_info[1]
                        if confidence > best_confidence:
                            best_confidence = confidence
                            best_result = (text, confidence, line[0] if len(line) > 0 else None)
            
            if best_result:
                text, confidence, bbox = best_result
                cleaned = self._clean_plate_text(text)
                
                return OCRResult(
                    text=cleaned,
                    confidence=float(confidence),
                    method=OCRMethod.PADDLEOCR,
                    raw_text=text,
                    processing_time_ms=processing_time,
                    bbox=bbox
                )
        except Exception as e:
            logger.debug(f"PaddleOCR error: {e}")
        
        return None
    
    def _easyocr_recognize(self, image: np.ndarray) -> Optional[OCRResult]:
        """Recognize text using EasyOCR"""
        if OCRMethod.EASYOCR not in self.methods or self.methods[OCRMethod.EASYOCR] is None:
            return None
        
        try:
            start_time = time.time()
            results = self.methods[OCRMethod.EASYOCR].readtext(
                image,
                detail=1,
                paragraph=False,
                width_ths=0.1,  # Very permissive
                height_ths=0.1,
                allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            )
            
            processing_time = (time.time() - start_time) * 1000
            
            if not results:
                return None
            
            # Get best result
            best = max(results, key=lambda x: x[2])
            bbox, text, confidence = best[0], best[1], best[2]
            
            cleaned = self._clean_plate_text(text)
            
            return OCRResult(
                text=cleaned,
                confidence=float(confidence),
                method=OCRMethod.EASYOCR,
                raw_text=text,
                processing_time_ms=processing_time,
                bbox=bbox
            )
        except Exception as e:
            logger.debug(f"EasyOCR error: {e}")
        
        return None
    
    def _tesseract_recognize(self, image: np.ndarray) -> Optional[OCRResult]:
        """Recognize text using Tesseract"""
        if OCRMethod.TESSERACT not in self.methods or self.methods[OCRMethod.TESSERACT] is None:
            return None
        
        try:
            start_time = time.time()
            text = self.methods[OCRMethod.TESSERACT].image_to_string(
                image,
                lang='eng',
                config='--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            )
            
            processing_time = (time.time() - start_time) * 1000
            
            if not text or len(text.strip()) == 0:
                return None
            
            cleaned = self._clean_plate_text(text)
            
            # Get confidence
            data = self.methods[OCRMethod.TESSERACT].image_to_data(
                image, lang='eng', output_type=self.methods[OCRMethod.TESSERACT].Output.DICT
            )
            confidences = [int(c) for c in data['conf'] if int(c) > 0]
            avg_confidence = np.mean(confidences) / 100.0 if confidences else 0.5
            
            return OCRResult(
                text=cleaned,
                confidence=float(avg_confidence),
                method=OCRMethod.TESSERACT,
                raw_text=text,
                processing_time_ms=processing_time
            )
        except Exception as e:
            logger.debug(f"Tesseract error: {e}")
        
        return None
    
    def _clean_plate_text(self, text: str) -> str:
        """Clean and validate license plate text"""
        if not text:
            return ""
        
        # Remove whitespace and special characters
        cleaned = re.sub(r'[^A-Z0-9]', '', text.upper())
        
        # Don't do aggressive character replacement - let OCR be more accurate
        # Only fix obvious errors
        if len(cleaned) >= 2:
            return cleaned
        
        return ""
    
    def recognize_text(self, plate_image: np.ndarray) -> OCRResult:
        """
        Recognize text from license plate image using best available method
        
        Args:
            plate_image: License plate image (BGR format)
        
        Returns:
            OCRResult with recognized text
        """
        h, w = plate_image.shape[:2]
        logger.info(f"🔍 OCR on {w}x{h} plate image")
        
        # Get enhanced versions
        enhanced_images = self._enhance_image_for_ocr(plate_image)
        
        # Try primary method first on all enhanced versions
        best_result = None
        best_confidence = 0.0
        
        # Method priority: PaddleOCR > EasyOCR > Tesseract
        methods_to_try = [self.primary_method]
        if self.enable_fallback:
            if self.primary_method != OCRMethod.PADDLEOCR:
                methods_to_try.append(OCRMethod.PADDLEOCR)
            if self.primary_method != OCRMethod.EASYOCR:
                methods_to_try.append(OCRMethod.EASYOCR)
            if self.primary_method != OCRMethod.TESSERACT:
                methods_to_try.append(OCRMethod.TESSERACT)
        
        # Try each method on each enhanced image
        for method in methods_to_try:
            if method not in self.methods or self.methods[method] is None:
                continue
            
            # Try original image first
            if method == OCRMethod.PADDLEOCR:
                result = self._paddleocr_recognize(plate_image)
            elif method == OCRMethod.EASYOCR:
                result = self._easyocr_recognize(plate_image)
            elif method == OCRMethod.TESSERACT:
                result = self._tesseract_recognize(plate_image)
            else:
                continue
            
            if result and result.confidence > best_confidence:
                best_result = result
                best_confidence = result.confidence
            
            # Try enhanced versions
            for name, enhanced_img in enhanced_images:
                if method == OCRMethod.PADDLEOCR:
                    result = self._paddleocr_recognize(enhanced_img)
                elif method == OCRMethod.EASYOCR:
                    result = self._easyocr_recognize(enhanced_img)
                elif method == OCRMethod.TESSERACT:
                    result = self._tesseract_recognize(enhanced_img)
                else:
                    continue
                
                if result and result.confidence > best_confidence:
                    best_result = result
                    best_confidence = result.confidence
                    logger.debug(f"✅ Better result from {method.value} on {name}: '{result.text}' (conf: {result.confidence:.3f})")
        
        # Return best result or empty result
        if best_result and best_result.text:
            logger.info(f"✅ OCR Success: '{best_result.text}' (conf: {best_result.confidence:.3f}, method: {best_result.method.value})")
            return best_result
        else:
            logger.warning(f"❌ OCR Failed: No text recognized")
            return OCRResult(
                text="",
                confidence=0.0,
                method=self.primary_method,
                raw_text="",
                processing_time_ms=0.0
            )

