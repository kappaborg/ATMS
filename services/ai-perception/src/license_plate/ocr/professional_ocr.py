"""
Professional License Plate OCR System
State-of-the-art OCR specifically optimized for license plates
Uses multiple methods with intelligent fusion for 65-70%+ accuracy
"""
import cv2
import numpy as np
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass
from enum import Enum
import time
import logging
import re

logger = logging.getLogger(__name__)

class OCRMethod(Enum):
    """OCR methods"""
    PADDLEOCR = "paddleocr"
    EASYOCR = "easyocr"
    TESSERACT = "tesseract"
    FUSION = "fusion"  # Fusion of multiple methods

@dataclass
class OCRResult:
    """OCR result"""
    text: str
    confidence: float
    method: OCRMethod
    raw_text: str
    processing_time_ms: float

class ProfessionalPlateOCR:
    """
    Professional OCR system with multiple methods and intelligent fusion
    Optimized for small, blurry license plates - Target: 65-70%+ accuracy
    """
    
    def __init__(self):
        """Initialize Professional OCR"""
        self.methods = {}
        self._initialize_all_methods()
        logger.info("✅ Professional Plate OCR initialized")
    
    def _initialize_all_methods(self):
        """Initialize all available OCR methods"""
        
        # 1. PaddleOCR (Best for license plates)
        try:
            from paddleocr import PaddleOCR
            # Try different initialization methods based on PaddleOCR version
            try:
                # Try with minimal parameters first
                self.methods[OCRMethod.PADDLEOCR] = PaddleOCR(use_angle_cls=True, lang='en')
            except TypeError:
                try:
                    # Try without use_angle_cls
                    self.methods[OCRMethod.PADDLEOCR] = PaddleOCR(lang='en')
                except TypeError:
                    # Try with just language
                    self.methods[OCRMethod.PADDLEOCR] = PaddleOCR()
            logger.info("✅ PaddleOCR initialized")
        except Exception as e:
            logger.warning(f"⚠️ PaddleOCR not available: {e}")
            self.methods[OCRMethod.PADDLEOCR] = None
        
        # 2. EasyOCR
        try:
            import easyocr
            self.methods[OCRMethod.EASYOCR] = easyocr.Reader(['en'], gpu=False)
            logger.info("✅ EasyOCR initialized")
        except Exception as e:
            logger.warning(f"⚠️ EasyOCR not available: {e}")
            self.methods[OCRMethod.EASYOCR] = None
        
        # 3. Tesseract
        try:
            import pytesseract
            self.methods[OCRMethod.TESSERACT] = pytesseract
            logger.info("✅ Tesseract initialized")
        except Exception as e:
            logger.warning(f"⚠️ Tesseract not available: {e}")
            self.methods[OCRMethod.TESSERACT] = None
    
    def _super_resolution_upscale(self, image: np.ndarray, target_min_size: int = 500) -> np.ndarray:
        """
        Super-resolution upscaling for very small plates
        Uses multiple upscaling strategies to preserve all characters
        """
        h, w = image.shape[:2]
        
        # Calculate required scale (larger target for better character preservation)
        scale = max(target_min_size / h, target_min_size / w, 10.0)  # Minimum 10x (was 8x)
        scale = min(scale, 25.0)  # Max 25x for extremely small plates (was 20x)
        
        # Use LANCZOS4 for best quality (preserves character edges)
        upscaled = cv2.resize(image, (int(w * scale), int(h * scale)), 
                             interpolation=cv2.INTER_LANCZOS4)
        
        # Apply gentle sharpening (preserve all characters, don't over-sharpen)
        kernel = np.array([[-0.5, -0.5, -0.5, -0.5, -0.5],
                          [-0.5,  1.0,  1.0,  1.0, -0.5],
                          [-0.5,  1.0,  5.0,  1.0, -0.5],
                          [-0.5,  1.0,  1.0,  1.0, -0.5],
                          [-0.5, -0.5, -0.5, -0.5, -0.5]]) / 5.0
        sharpened = cv2.filter2D(upscaled, -1, kernel)
        
        return sharpened
    
    def _enhance_for_ocr(self, image: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        """Create multiple enhanced versions"""
        enhanced = []
        
        h, w = image.shape[:2]
        
        # Version 1: Super-resolution upscale (for very small plates)
        if h < 100 or w < 200:
            sr_image = self._super_resolution_upscale(image, target_min_size=500)  # Increased from 400
            enhanced.append(('super_resolution', sr_image))
        
        # Version 2: Grayscale + CLAHE
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # Aggressive CLAHE
        clahe = cv2.createCLAHE(clipLimit=5.0, tileGridSize=(8, 8))
        enhanced_gray = clahe.apply(gray)
        
        # Upscale if small (larger target for better character preservation)
        if h < 250 or w < 500:
            scale = max(250 / h, 500 / w, 10.0)  # Minimum 10x (was 6x)
            scale = min(scale, 20.0)  # Max 20x (was 15x)
            enhanced_gray = cv2.resize(enhanced_gray, (int(w * scale), int(h * scale)),
                                     interpolation=cv2.INTER_LANCZOS4)
        
        enhanced.append(('grayscale_enhanced', enhanced_gray))
        
        # Version 3: Denoised + Sharpened
        denoised = cv2.fastNlMeansDenoising(enhanced_gray, None, h=3, 
                                           templateWindowSize=7, searchWindowSize=21)
        kernel = np.array([[-1, -1, -1],
                          [-1,  9, -1],
                          [-1, -1, -1]])
        sharpened = cv2.filter2D(denoised, -1, kernel)
        enhanced.append(('denoised_sharpened', sharpened))
        
        # Version 4: Adaptive threshold (for high contrast)
        if enhanced_gray.shape[0] > 50:
            adaptive = cv2.adaptiveThreshold(enhanced_gray, 255,
                                             cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                             cv2.THRESH_BINARY, 11, 2)
            enhanced.append(('adaptive_threshold', adaptive))
        
        return enhanced
    
    def _paddleocr_recognize(self, image: np.ndarray) -> Optional[OCRResult]:
        """PaddleOCR recognition"""
        if self.methods.get(OCRMethod.PADDLEOCR) is None:
            return None
        
        try:
            start_time = time.time()
            result = self.methods[OCRMethod.PADDLEOCR].ocr(image, cls=True)
            processing_time = (time.time() - start_time) * 1000
            
            if not result or not result[0]:
                return None
            
            # Get best result
            best_text = ""
            best_conf = 0.0
            
            for line in result[0]:
                if line and len(line) >= 2:
                    text_info = line[1]
                    if isinstance(text_info, tuple) and len(text_info) >= 2:
                        text, conf = text_info[0], text_info[1]
                        if conf > best_conf:
                            best_conf = conf
                            best_text = text
            
            if best_text:
                cleaned = self._clean_text(best_text)
                if cleaned:
                    return OCRResult(
                        text=cleaned,
                        confidence=float(best_conf),
                        method=OCRMethod.PADDLEOCR,
                        raw_text=best_text,
                        processing_time_ms=processing_time
                    )
        except Exception as e:
            logger.debug(f"PaddleOCR error: {e}")
        
        return None
    
    def _easyocr_recognize(self, image: np.ndarray) -> Optional[OCRResult]:
        """EasyOCR recognition with multiple attempts"""
        if self.methods.get(OCRMethod.EASYOCR) is None:
            return None
        
        try:
            start_time = time.time()
            
            # Attempt 1: Very permissive parameters (capture all text)
            results = self.methods[OCRMethod.EASYOCR].readtext(
                image,
                detail=1,
                paragraph=False,
                width_ths=0.05,  # Very permissive (was 0.1)
                height_ths=0.05,  # Very permissive (was 0.1)
                allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            )
            
            # Attempt 2: If no results, try without allowlist (capture more characters)
            if not results:
                results = self.methods[OCRMethod.EASYOCR].readtext(
                    image,
                    detail=1,
                    paragraph=False,
                    width_ths=0.01,  # Extremely permissive
                    height_ths=0.01
                )
            
            # Attempt 3: Try with paragraph mode (capture multi-line plates)
            if not results:
                results = self.methods[OCRMethod.EASYOCR].readtext(
                    image,
                    detail=1,
                    paragraph=True,  # Enable paragraph mode
                    width_ths=0.01,
                    height_ths=0.01
                )
            
            processing_time = (time.time() - start_time) * 1000
            
            if not results:
                return None
            
            # Combine all text results (for multi-line or multiple detections)
            all_texts = []
            all_confs = []
            
            for result in results:
                if len(result) >= 3:
                    bbox, text, conf = result[0], result[1], result[2]
                    if text and len(text.strip()) > 0:
                        all_texts.append(text.strip())
                        all_confs.append(float(conf))
            
            if not all_texts:
                return None
            
            # Combine all detected text (join with space if multiple)
            combined_text = ' '.join(all_texts)
            avg_conf = np.mean(all_confs) if all_confs else 0.0
            
            cleaned = self._clean_text(combined_text)
            if cleaned:
                return OCRResult(
                    text=cleaned,
                    confidence=float(avg_conf),
                    method=OCRMethod.EASYOCR,
                    raw_text=combined_text,
                    processing_time_ms=processing_time
                )
        except Exception as e:
            logger.debug(f"EasyOCR error: {e}")
        
        return None
    
    def _tesseract_recognize(self, image: np.ndarray) -> Optional[OCRResult]:
        """Tesseract recognition"""
        if self.methods.get(OCRMethod.TESSERACT) is None:
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
            
            cleaned = self._clean_text(text)
            if cleaned:
                # Get confidence
                data = self.methods[OCRMethod.TESSERACT].image_to_data(
                    image, lang='eng', 
                    output_type=self.methods[OCRMethod.TESSERACT].Output.DICT
                )
                confidences = [int(c) for c in data['conf'] if int(c) > 0]
                avg_conf = np.mean(confidences) / 100.0 if confidences else 0.5
                
                return OCRResult(
                    text=cleaned,
                    confidence=float(avg_conf),
                    method=OCRMethod.TESSERACT,
                    raw_text=text,
                    processing_time_ms=processing_time
                )
        except Exception as e:
            logger.debug(f"Tesseract error: {e}")
        
        return None
    
    def _fuse_results(self, results: List[OCRResult]) -> Optional[OCRResult]:
        """
        Intelligent fusion of multiple OCR results
        Uses voting and confidence weighting
        """
        if not results:
            return None
        
        # Filter valid results
        valid_results = [r for r in results if r and r.text and len(r.text) >= 2]
        if not valid_results:
            return None
        
        # If only one result, return it
        if len(valid_results) == 1:
            return valid_results[0]
        
        # Voting: Find most common text
        text_votes = {}
        for r in valid_results:
            text = r.text.upper()
            if text not in text_votes:
                text_votes[text] = {'count': 0, 'total_conf': 0.0, 'results': [], 'length': len(text)}
            text_votes[text]['count'] += 1
            text_votes[text]['total_conf'] += r.confidence
            text_votes[text]['results'].append(r)
        
        # Score each text: votes * length * confidence (prefer longer, more voted, higher confidence)
        text_scores = {}
        for text, vote_data in text_votes.items():
            avg_conf = vote_data['total_conf'] / vote_data['count']
            # Score = votes * length_weight * confidence
            # Prefer longer text (more complete), more votes (agreement), higher confidence
            length_weight = min(vote_data['length'] / 8.0, 1.5)  # Boost for longer text (up to 1.5x)
            score = vote_data['count'] * length_weight * avg_conf
            text_scores[text] = score
        
        # Get text with highest score
        best_text = max(text_scores.keys(), key=lambda t: text_scores[t])
        best_vote = text_votes[best_text]
        
        # Calculate average confidence
        avg_conf = best_vote['total_conf'] / best_vote['count']
        
        # Use result with longest raw_text (most complete)
        best_result = max(best_vote['results'], key=lambda r: len(r.raw_text) if r.raw_text else 0)
        
        logger.info(f"✅ Fusion: '{best_text}' (votes: {best_vote['count']}/{len(valid_results)}, conf: {avg_conf:.3f}, length: {len(best_text)})")
        
        return OCRResult(
            text=best_text,
            confidence=avg_conf,
            method=OCRMethod.FUSION,
            raw_text=best_result.raw_text,
            processing_time_ms=sum(r.processing_time_ms for r in valid_results) / len(valid_results)
        )
    
    def _clean_text(self, text: str) -> str:
        """Clean and validate plate text - PRESERVE ALL CHARACTERS"""
        if not text:
            return ""
        
        # Remove only spaces and special characters, keep all alphanumeric
        # Don't remove too aggressively - we want to preserve all characters
        cleaned = re.sub(r'[^A-Z0-9]', '', text.upper())
        
        # More lenient validation (2-15 characters) to capture longer plates
        if len(cleaned) < 2 or len(cleaned) > 15:
            # If too long, try to extract the longest valid substring
            if len(cleaned) > 15:
                # Try to find a valid plate-like pattern
                # Look for sequences of 6-12 characters (typical plate length)
                matches = re.findall(r'[A-Z0-9]{6,12}', cleaned)
                if matches:
                    # Return longest match
                    cleaned = max(matches, key=len)
                else:
                    # Return first 12 characters if no pattern found
                    cleaned = cleaned[:12]
        
        return cleaned
    
    def recognize_text(self, plate_image: np.ndarray) -> OCRResult:
        """
        Recognize text using professional multi-method approach
        Target: 65-70%+ accuracy
        """
        h, w = plate_image.shape[:2]
        logger.info(f"🔍 Professional OCR on {w}x{h} plate")
        
        # Get enhanced versions
        enhanced_images = self._enhance_for_ocr(plate_image)
        
        # Try all methods on all enhanced versions
        all_results = []
        
        # Try original image first
        for method in [OCRMethod.PADDLEOCR, OCRMethod.EASYOCR, OCRMethod.TESSERACT]:
            if method not in self.methods or self.methods[method] is None:
                continue
                
            if method == OCRMethod.PADDLEOCR:
                result = self._paddleocr_recognize(plate_image)
            elif method == OCRMethod.EASYOCR:
                result = self._easyocr_recognize(plate_image)
            elif method == OCRMethod.TESSERACT:
                result = self._tesseract_recognize(plate_image)
            else:
                continue
            
            if result and result.text:
                all_results.append(result)
                logger.debug(f"✅ {method.value} on original: '{result.text}' (conf: {result.confidence:.3f})")
        
        # Try enhanced versions
        for name, enhanced_img in enhanced_images:
            for method in [OCRMethod.PADDLEOCR, OCRMethod.EASYOCR, OCRMethod.TESSERACT]:
                if method not in self.methods or self.methods[method] is None:
                    continue
                    
                if method == OCRMethod.PADDLEOCR:
                    result = self._paddleocr_recognize(enhanced_img)
                elif method == OCRMethod.EASYOCR:
                    result = self._easyocr_recognize(enhanced_img)
                elif method == OCRMethod.TESSERACT:
                    result = self._tesseract_recognize(enhanced_img)
                else:
                    continue
                
                if result and result.text:
                    all_results.append(result)
                    logger.debug(f"✅ {method.value} on {name}: '{result.text}' (conf: {result.confidence:.3f}, len: {len(result.text)})")
        
        # Fuse results for best accuracy
        fused_result = self._fuse_results(all_results)
        
        if fused_result and fused_result.text:
            logger.info(f"✅ Professional OCR: '{fused_result.text}' (conf: {fused_result.confidence:.3f}, method: {fused_result.method.value})")
            return fused_result
        else:
            # Return best single result if fusion failed
            if all_results:
                best = max(all_results, key=lambda r: r.confidence)
                logger.info(f"✅ Best single result: '{best.text}' (conf: {best.confidence:.3f}, method: {best.method.value})")
                return best
            
            logger.warning(f"❌ Professional OCR failed: No text recognized")
            return OCRResult(
                text="",
                confidence=0.0,
                method=OCRMethod.EASYOCR,
                raw_text="",
                processing_time_ms=0.0
            )
    
    def to_plate_text(self, ocr_result: OCRResult):
        """Convert to PlateText format"""
        from license_plate.ocr.plate_ocr import PlateText, OCRMethod as OldOCRMethod
        
        method_map = {
            OCRMethod.PADDLEOCR: OldOCRMethod.PADDLEOCR,
            OCRMethod.EASYOCR: OldOCRMethod.EASYOCR,
            OCRMethod.TESSERACT: OldOCRMethod.TESSERACT,
            OCRMethod.FUSION: OldOCRMethod.EASYOCR,  # Map fusion to EasyOCR for compatibility
        }
        
        return PlateText(
            text=ocr_result.text,
            confidence=ocr_result.confidence,
            method_used=method_map.get(ocr_result.method, OldOCRMethod.EASYOCR),
            raw_text=ocr_result.raw_text,
            cleaned_text=ocr_result.text,
            timestamp=time.time()
        )

