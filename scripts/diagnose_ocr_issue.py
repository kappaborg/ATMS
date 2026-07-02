#!/usr/bin/env python3
"""
Diagnostic script to check why OCR is failing
Tests OCR on actual detected plate images
"""
import sys
import os
import cv2
import numpy as np
from pathlib import Path
import logging

# Add project paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "services" / "ai-perception" / "src"))

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def extract_and_test_plates(frame_path: str):
    """Extract detected plates and test OCR on each"""
    logger.info("=" * 60)
    logger.info("OCR Diagnostic Test")
    logger.info("=" * 60)
    
    try:
        from license_plate_processor import LicensePlateProcessor
        from license_plate.ocr.plate_ocr import HybridOCR
        
        # Load image
        if not os.path.exists(frame_path):
            logger.error(f"❌ Image not found: {frame_path}")
            return
        
        frame = cv2.imread(frame_path)
        if frame is None:
            logger.error(f"❌ Failed to load image: {frame_path}")
            return
        
        logger.info(f"✅ Loaded image: {frame_path} ({frame.shape[1]}x{frame.shape[0]})")
        
        # Initialize processor
        processor = LicensePlateProcessor()
        logger.info("✅ LicensePlateProcessor initialized")
        
        # Detect plates
        logger.info("🔍 Detecting plates...")
        if hasattr(processor.plate_detector, 'detect_plates'):
            plate_detections = processor.plate_detector.detect_plates(frame)
        elif hasattr(processor.plate_detector, 'detect'):
            plate_detections = processor.plate_detector.detect(frame)
        else:
            logger.error("❌ No detection method found")
            return
        
        logger.info(f"📊 Detected {len(plate_detections)} plates")
        
        if len(plate_detections) == 0:
            logger.warning("⚠️ No plates detected!")
            return
        
        # Initialize OCR
        ocr_engine = HybridOCR()
        logger.info("✅ OCR engine initialized")
        
        # Test each detected plate
        for idx, detection in enumerate(plate_detections):
            logger.info(f"\n{'='*60}")
            logger.info(f"Plate {idx + 1} Analysis")
            logger.info(f"{'='*60}")
            
            # Get plate image
            plate_img = None
            if hasattr(detection, 'plate_image') and detection.plate_image is not None:
                plate_img = detection.plate_image
            elif isinstance(detection, dict) and 'plate_image' in detection:
                plate_img = detection['plate_image']
            
            if plate_img is None:
                logger.warning(f"  ❌ No plate image available")
                continue
            
            # Get bbox
            bbox = None
            if hasattr(detection, 'bbox'):
                bbox = detection.bbox
            elif isinstance(detection, dict) and 'bbox' in detection:
                bbox = detection['bbox']
            
            if bbox:
                if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                    x1, y1, x2, y2 = bbox[:4]
                elif hasattr(bbox, 'x1'):
                    x1, y1, x2, y2 = bbox.x1, bbox.y1, bbox.x2, bbox.y2
                else:
                    x1, y1, x2, y2 = 0, 0, 0, 0
                logger.info(f"  BBox: ({x1:.1f}, {y1:.1f}, {x2:.1f}, {y2:.1f})")
            
            # Get confidence
            conf = 0.0
            if hasattr(detection, 'confidence'):
                conf = detection.confidence
            elif isinstance(detection, dict) and 'confidence' in detection:
                conf = detection['confidence']
            logger.info(f"  Detection Confidence: {conf:.3f}")
            
            # Analyze plate image
            if isinstance(plate_img, np.ndarray):
                h, w = plate_img.shape[:2]
                logger.info(f"  Plate Image Size: {w}x{h} pixels")
                logger.info(f"  Image dtype: {plate_img.dtype}")
                logger.info(f"  Image min/max: {plate_img.min()}/{plate_img.max()}")
                
                # Check if too small
                if h < 30 or w < 60:
                    logger.warning(f"  ⚠️ Plate is VERY SMALL - OCR will likely fail!")
                    logger.warning(f"     Recommended minimum: 50x100 pixels")
                    logger.warning(f"     Current size: {w}x{h} pixels")
                
                # Save plate image for inspection
                plate_filename = f"plate_{idx+1}_{w}x{h}.jpg"
                cv2.imwrite(plate_filename, plate_img)
                logger.info(f"  💾 Saved plate image: {plate_filename}")
                
                # Test OCR
                logger.info(f"  🔍 Running OCR...")
                try:
                    result = ocr_engine.recognize_text(plate_img)
                    
                    logger.info(f"  📝 OCR Results:")
                    logger.info(f"     Text: '{result.text}'")
                    logger.info(f"     Confidence: {result.confidence:.3f}")
                    logger.info(f"     Method: {result.method_used}")
                    logger.info(f"     Raw Text: '{result.raw_text}'")
                    logger.info(f"     Cleaned Text: '{result.cleaned_text}'")
                    
                    if result.text and len(result.text) > 0:
                        logger.info(f"  ✅ OCR SUCCESS!")
                    else:
                        logger.warning(f"  ❌ OCR FAILED - No text extracted")
                        
                        # Try to diagnose why
                        logger.info(f"  🔬 Diagnosis:")
                        if h < 30 or w < 60:
                            logger.info(f"     - Plate too small ({w}x{h})")
                        if result.confidence == 0.0:
                            logger.info(f"     - EasyOCR returned 0 confidence")
                        if not result.raw_text:
                            logger.info(f"     - EasyOCR found no text at all")
                        else:
                            logger.info(f"     - EasyOCR found text but it was filtered: '{result.raw_text}'")
                            
                except Exception as ocr_error:
                    logger.error(f"  ❌ OCR Error: {ocr_error}")
                    import traceback
                    traceback.print_exc()
            else:
                logger.warning(f"  ❌ Invalid plate image format")
        
        logger.info(f"\n{'='*60}")
        logger.info("Diagnostic Complete")
        logger.info(f"{'='*60}")
        logger.info("Check the saved plate images to see what OCR is trying to read")
        
    except Exception as e:
        logger.error(f"❌ Diagnostic failed: {e}", exc_info=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python diagnose_ocr_issue.py <frame_image>")
        print("\nExample:")
        print("  python diagnose_ocr_issue.py test_frame.jpg")
        sys.exit(1)
    
    extract_and_test_plates(sys.argv[1])

