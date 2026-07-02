"""
Integrated License Plate Recognition System for ATMS
Complete pipeline for plate detection, OCR, and validation
"""

import asyncio
import time
import logging
from typing import List, Dict, Optional, Tuple, Union
from dataclasses import dataclass
from collections import defaultdict, deque
import numpy as np

from license_plate import (
    HybridPlateDetector, HybridOCR, LicensePlateValidator, PlateAnonymizer,
    PlateDetection, PlateText, PlateValidation
)

logger = logging.getLogger(__name__)

@dataclass
class PlateRecognitionResult:
    """Complete license plate recognition result"""
    plate_detection: PlateDetection
    plate_text: PlateText
    plate_validation: PlateValidation
    anonymized_text: str
    processing_time_ms: float
    confidence_score: float
    timestamp: float

class LicensePlateProcessor:
    """
    Integrated license plate recognition processor
    Combines detection, OCR, and validation into a single pipeline
    """
    
    def __init__(self, 
                 yolo_model_path: str = "/Users/kappasutra/Traffic/models/license_plate_training/outputs/license_plate_model_mps/weights/best.mlpackage",
                 ocr_primary_method: str = "easyocr",
                 ocr_fallback_methods: List[str] = None,
                 supported_countries: List[str] = None,
                 anonymization_level: str = "partial",
                 confidence_threshold: float = 0.5):
        """
        Initialize license plate processor
        
        Args:
            yolo_model_path: Path to YOLO model for detection
            ocr_primary_method: Primary OCR method
            ocr_fallback_methods: Fallback OCR methods
            supported_countries: Supported countries for validation
            anonymization_level: Level of anonymization
            confidence_threshold: Minimum confidence threshold
        """
        self.confidence_threshold = confidence_threshold
        
        # Initialize components
        # Try SAHI first (30-50% better detection for small objects), fallback to Hybrid
        try:
            from license_plate.detection.sahi_plate_detector import SAHIPlateDetector, SAHIConfig
            
            # Configure SAHI for optimal license plate detection
            sahi_config = SAHIConfig(
                slice_height=640,
                slice_width=640,
                overlap_height_ratio=0.1,  # 10% overlap for better boundary detection
                overlap_width_ratio=0.1,
                postprocess_type="NMS",
                postprocess_match_threshold=0.5
            )
            
            self.plate_detector = SAHIPlateDetector(
                model_path=yolo_model_path,
                confidence_threshold=0.15,  # Lowered to 0.15 to catch more plates (was 0.25)
                device="cpu",  # Will auto-detect MPS if available
                use_sahi=True,  # Enable SAHI sliced inference
                sahi_config=sahi_config
            )
            
            logger.info("✅ Using SAHI-enhanced license plate detector (30-50% better detection)")
            
        except (ImportError, Exception) as e:
            logger.warning(f"SAHI not available or failed to initialize: {e}")
            logger.info("Falling back to HybridPlateDetector")
            
            # Fallback to HybridPlateDetector
            self.plate_detector = HybridPlateDetector(
                yolo_model_path=yolo_model_path,
                yolo_confidence=0.15,  # Lowered from 0.25 to 0.15 for better distance detection
                traditional_fallback=True
            )
        
        # Use Professional OCR (Multi-method fusion) for 65-70%+ accuracy
        try:
            from license_plate.ocr.professional_ocr_adapter import ProfessionalOCRAdapter
            self.ocr_engine = ProfessionalOCRAdapter()
            logger.info("✅ Using Professional OCR (Multi-method fusion) - Target: 65-70%+ accuracy")
        except (ImportError, Exception) as e:
            logger.warning(f"⚠️ Professional OCR not available, trying Advanced OCR: {e}")
            try:
                from license_plate.ocr.ocr_adapter import AdvancedOCRAdapter
                from license_plate.ocr.advanced_ocr import OCRMethod as AdvancedOCRMethod
                self.ocr_engine = AdvancedOCRAdapter(primary_method=AdvancedOCRMethod.PADDLEOCR)
                logger.info("✅ Using Advanced OCR (PaddleOCR)")
            except (ImportError, Exception) as e2:
                logger.warning(f"⚠️ Advanced OCR not available, using HybridOCR: {e2}")
                from license_plate.ocr.plate_ocr import OCRMethod
                self.ocr_engine = HybridOCR(
                    primary_method=OCRMethod.EASYOCR if ocr_primary_method == "easyocr" else OCRMethod.TESSERACT,
                    fallback_methods=[OCRMethod.EASYOCR],
                    confidence_threshold=0.10
                )
        
        self.validator = LicensePlateValidator(
            supported_countries=supported_countries or ["US", "UK", "EU"],
            strict_validation=True
        )
        
        self.anonymizer = PlateAnonymizer(
            anonymization_level=anonymization_level
        )
        
        # Performance tracking
        self.processing_times = deque(maxlen=100)
        self.total_processed = 0
        self.successful_recognitions = 0
        self.detection_success_rate = 0.0
        self.ocr_success_rate = 0.0
        self.validation_success_rate = 0.0
        
        logger.info("License Plate Processor initialized")
    
    async def process_frame(self, frame: np.ndarray, 
                          frame_id: str = None,
                          context: Optional[Dict] = None) -> List[PlateRecognitionResult]:
        """
        Process frame for license plate recognition
        
        Args:
            frame: Input frame (BGR format)
            frame_id: Unique frame identifier
            context: Additional context information
        
        Returns:
            List of plate recognition results
        """
        start_time = time.time()
        
        if frame_id is None:
            frame_id = f"frame_{int(time.time() * 1000)}"
        
        try:
            # Step 1: Detect license plates
            logger.info(f"🔍 Detecting license plates in frame {frame_id} (frame shape: {frame.shape})")
            plate_detections = self.plate_detector.detect_plates(frame)
            
            logger.info(f"📊 Detected {len(plate_detections)} license plates in frame {frame_id}")
            
            if not plate_detections:
                logger.debug(f"No license plates detected in frame {frame_id}")
                return []
            
            # Step 2: Process each detected plate
            recognition_results = []
            
            for detection in plate_detections:
                try:
                    # Get plate image dimensions
                    plate_height, plate_width = detection.plate_image.shape[:2]
                    
                    # CRITICAL: Only filter extremely small plates (likely false positives)
                    # Lowered threshold to process more plates
                    if plate_height < 8 or plate_width < 15:  # Only reject extremely small (was 10x20)
                        logger.debug(f"Skipping extremely small plate detection: {plate_width}x{plate_height}")
                        continue
                    
                    # Log plate size for debugging
                    if plate_height < 50 or plate_width < 100:
                        logger.debug(f"⚠️ Small plate detected: {plate_width}x{plate_height} - will try OCR anyway")
                    
                    # NOTE: Don't filter by confidence here - SAHI already filtered at 0.25
                    # Process ALL detected plates for OCR (even if confidence is lower)
                    # This ensures we try OCR on all reasonable detections
                    
                    # CRITICAL: Ensure plate image is valid before OCR
                    if detection.plate_image is None or detection.plate_image.size == 0:
                        logger.warning(f"Invalid plate image for detection (confidence: {detection.confidence:.3f})")
                        continue
                    
                    # OCR on plate image
                    logger.info(f"🔍 Running OCR on plate: {plate_width}x{plate_height}, detection_confidence: {detection.confidence:.3f}")
                    logger.info(f"   Plate image shape: {detection.plate_image.shape}, dtype: {detection.plate_image.dtype}, min: {detection.plate_image.min()}, max: {detection.plate_image.max()}")
                    
                    try:
                        plate_text = self.ocr_engine.recognize_text(detection.plate_image)
                        
                        # Log OCR outcome WITHOUT plate text — raw plates are
                        # PII and must never reach application logs (ADR-0014:
                        # anonymisation-by-default; logs have their own retention).
                        if not plate_text.text or plate_text.text.strip() == '':
                            logger.warning(f"❌ OCR failed for plate (detection_conf: {detection.confidence:.3f}, ocr_conf: {plate_text.confidence:.3f}, size: {plate_width}x{plate_height})")
                        else:
                            logger.info(f"✅ OCR success: {len(plate_text.text)} chars (confidence: {plate_text.confidence:.3f})")
                    except Exception as ocr_error:
                        logger.error(f"❌ OCR exception: {ocr_error}", exc_info=True)
                        # Create empty result
                        from license_plate.ocr.plate_ocr import PlateText, OCRMethod
                        plate_text = PlateText(
                            text="",
                            confidence=0.0,
                            method_used=OCRMethod.EASYOCR,
                            raw_text="",
                            cleaned_text="",
                            timestamp=time.time()
                        )
                    
                    # Validate plate text
                    plate_validation = self.validator.validate_plate(plate_text.text)
                    
                    # Anonymize for privacy
                    anonymized_text = self.anonymizer.anonymize_plate(plate_text.text)
                    
                    # Calculate overall confidence
                    overall_confidence = self._calculate_overall_confidence(
                        detection.confidence,
                        plate_text.confidence,
                        plate_validation.confidence
                    )
                    
                    # Create result
                    result = PlateRecognitionResult(
                        plate_detection=detection,
                        plate_text=plate_text,
                        plate_validation=plate_validation,
                        anonymized_text=anonymized_text,
                        processing_time_ms=(time.time() - start_time) * 1000,
                        confidence_score=overall_confidence,
                        timestamp=time.time()
                    )
                    
                    recognition_results.append(result)
                    
                    logger.debug(f"Plate recognized: '{anonymized_text}' (confidence: {overall_confidence:.2f})")
                    
                except Exception as e:
                    import traceback
                    logger.error(f"Error processing plate detection: {e}\n{traceback.format_exc()}")
                    continue
            
            # Update performance metrics
            processing_time = time.time() - start_time
            self.processing_times.append(processing_time)
            self.total_processed += 1
            
            if recognition_results:
                self.successful_recognitions += 1
            
            # Update success rates
            self._update_success_rates(plate_detections, recognition_results)
            
            logger.debug(f"Frame {frame_id} processed: {len(plate_detections)} detections, "
                        f"{len(recognition_results)} successful recognitions in {processing_time*1000:.2f}ms")
            
            return recognition_results
            
        except Exception as e:
            logger.error(f"License plate processing failed for frame {frame_id}: {e}")
            return []
    
    def _calculate_overall_confidence(self, detection_conf: float, 
                                    ocr_conf: float, validation_conf: float) -> float:
        """Calculate overall confidence score"""
        # Weighted average of all confidence scores
        weights = [0.3, 0.4, 0.3]  # Detection, OCR, Validation
        confidences = [detection_conf, ocr_conf, validation_conf]
        
        overall_conf = sum(w * c for w, c in zip(weights, confidences))
        return min(1.0, max(0.0, overall_conf))
    
    def _update_success_rates(self, detections: List[PlateDetection], 
                            results: List[PlateRecognitionResult]):
        """Update success rates for performance tracking"""
        if not detections:
            return
        
        # Detection success rate
        detection_success = len(detections) / max(1, len(detections))
        self.detection_success_rate = (self.detection_success_rate + detection_success) / 2
        
        # OCR success rate
        if results:
            ocr_success = sum(1 for r in results if r.plate_text.text) / len(results)
            self.ocr_success_rate = (self.ocr_success_rate + ocr_success) / 2
        
        # Validation success rate
        if results:
            validation_success = sum(1 for r in results if r.plate_validation.is_valid) / len(results)
            self.validation_success_rate = (self.validation_success_rate + validation_success) / 2
    
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics"""
        avg_processing_time = np.mean(self.processing_times) if self.processing_times else 0
        
        return {
            'total_processed': self.total_processed,
            'successful_recognitions': self.successful_recognitions,
            'recognition_rate': self.successful_recognitions / max(1, self.total_processed),
            'detection_success_rate': self.detection_success_rate,
            'ocr_success_rate': self.ocr_success_rate,
            'validation_success_rate': self.validation_success_rate,
            'avg_processing_time_ms': avg_processing_time * 1000,
            'max_processing_time_ms': max(self.processing_times) * 1000 if self.processing_times else 0,
            'detector_metrics': self.plate_detector.get_performance_metrics(),
            'ocr_metrics': self.ocr_engine.get_performance_metrics(),
            'validator_metrics': self.validator.get_performance_metrics(),
            'anonymizer_metrics': self.anonymizer.get_performance_metrics()
        }
    
    def reset_metrics(self):
        """Reset performance metrics"""
        self.processing_times.clear()
        self.total_processed = 0
        self.successful_recognitions = 0
        self.detection_success_rate = 0.0
        self.ocr_success_rate = 0.0
        self.validation_success_rate = 0.0
        
        logger.info("License plate processor metrics reset")

class PlateAnalytics:
    """
    License plate analytics and reporting
    Provides insights into plate recognition performance
    """
    
    def __init__(self, max_records: int = 10000):
        """
        Initialize plate analytics
        
        Args:
            max_records: Maximum number of records to keep
        """
        self.max_records = max_records
        self.recognition_records = deque(maxlen=max_records)
        self.performance_records = deque(maxlen=max_records)
        
        logger.info("Plate Analytics initialized")
    
    def record_recognition(self, result: PlateRecognitionResult):
        """Record a plate recognition result"""
        # ADR-0014: only the anonymized form is retained — raw plate text
        # must not reach analytics storage or the export files built from it.
        record = {
            'timestamp': result.timestamp,
            'anonymized_text': result.anonymized_text,
            'confidence': result.confidence_score,
            'detection_confidence': result.plate_detection.confidence,
            'ocr_confidence': result.plate_text.confidence,
            'validation_confidence': result.plate_validation.confidence,
            'is_valid': result.plate_validation.is_valid,
            'format_detected': result.plate_validation.format_detected.value if hasattr(result.plate_validation.format_detected, 'value') else str(result.plate_validation.format_detected),
            'country': result.plate_validation.country,
            'region': result.plate_validation.region,
            'processing_time_ms': result.processing_time_ms
        }
        
        self.recognition_records.append(record)
    
    def record_performance(self, frame_id: str, processing_time: float, 
                         detections: int, recognitions: int):
        """Record performance metrics"""
        record = {
            'timestamp': time.time(),
            'frame_id': frame_id,
            'processing_time_ms': processing_time * 1000,
            'detections': detections,
            'recognitions': recognitions,
            'success_rate': recognitions / max(1, detections)
        }
        
        self.performance_records.append(record)
    
    def get_analytics_summary(self) -> Dict:
        """Get analytics summary"""
        if not self.recognition_records:
            return {}
        
        # Recognition analytics
        total_recognitions = len(self.recognition_records)
        valid_recognitions = sum(1 for r in self.recognition_records if r['is_valid'])
        avg_confidence = np.mean([r['confidence'] for r in self.recognition_records])
        
        # Country distribution
        country_dist = defaultdict(int)
        for record in self.recognition_records:
            country_dist[record['country']] += 1
        
        # Format distribution
        format_dist = defaultdict(int)
        for record in self.recognition_records:
            format_dist[record['format_detected']] += 1
        
        # Performance analytics
        if self.performance_records:
            avg_processing_time = np.mean([r['processing_time_ms'] for r in self.performance_records])
            avg_success_rate = np.mean([r['success_rate'] for r in self.performance_records])
        else:
            avg_processing_time = 0
            avg_success_rate = 0
        
        return {
            'total_recognitions': total_recognitions,
            'valid_recognitions': valid_recognitions,
            'validation_rate': valid_recognitions / max(1, total_recognitions),
            'avg_confidence': avg_confidence,
            'country_distribution': dict(country_dist),
            'format_distribution': dict(format_dist),
            'avg_processing_time_ms': avg_processing_time,
            'avg_success_rate': avg_success_rate,
            'data_period': {
                'start': min(r['timestamp'] for r in self.recognition_records),
                'end': max(r['timestamp'] for r in self.recognition_records)
            }
        }
    
    def export_data(self, filepath: str):
        """Export analytics data to file"""
        import json
        
        data = {
            'recognition_records': list(self.recognition_records),
            'performance_records': list(self.performance_records),
            'analytics_summary': self.get_analytics_summary()
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Plate analytics data exported to {filepath}")
    
    def clear_data(self):
        """Clear all analytics data"""
        self.recognition_records.clear()
        self.performance_records.clear()
        logger.info("Plate analytics data cleared")
