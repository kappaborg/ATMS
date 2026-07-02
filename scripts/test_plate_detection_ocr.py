#!/usr/bin/env python3
"""
Standalone Test Script for License Plate Detection and OCR
Tests the complete pipeline: Detection → OCR → Validation
"""
import sys
import os
import cv2
import numpy as np
from pathlib import Path
import time
import logging

# Add project paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "services" / "ai-perception" / "src"))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_plate_detection(frame_path: str):
    """Test license plate detection only"""
    logger.info("=" * 60)
    logger.info("TEST 1: License Plate Detection")
    logger.info("=" * 60)
    
    try:
        from license_plate_processor import LicensePlateProcessor
        
        # Load test image
        if not os.path.exists(frame_path):
            logger.error(f"❌ Test image not found: {frame_path}")
            return False
        
        frame = cv2.imread(frame_path)
        if frame is None:
            logger.error(f"❌ Failed to load image: {frame_path}")
            return False
        
        logger.info(f"✅ Loaded test image: {frame_path} ({frame.shape[1]}x{frame.shape[0]})")
        
        # Initialize processor
        processor = LicensePlateProcessor()
        logger.info("✅ LicensePlateProcessor initialized")
        
        # Test detection only (no OCR)
        logger.info("🔍 Running plate detection...")
        start_time = time.time()
        
        # Access the plate detector directly - check which method exists
        if hasattr(processor.plate_detector, 'detect_plates'):
            plate_detections = processor.plate_detector.detect_plates(frame)
        elif hasattr(processor.plate_detector, 'detect'):
            plate_detections = processor.plate_detector.detect(frame)
        else:
            logger.error("❌ Plate detector doesn't have detect_plates() or detect() method")
            logger.error(f"   Available methods: {[m for m in dir(processor.plate_detector) if not m.startswith('_')]}")
            return False
        
        detection_time = time.time() - start_time
        logger.info(f"⏱️ Detection time: {detection_time*1000:.2f}ms")
        logger.info(f"📊 Detected {len(plate_detections)} license plates")
        
        if len(plate_detections) == 0:
            logger.warning("⚠️ No plates detected!")
            return False
        
        # Display detection results
        for idx, detection in enumerate(plate_detections):
            logger.info(f"\n  Plate {idx + 1}:")
            
            # Handle different detection formats
            if hasattr(detection, 'confidence'):
                logger.info(f"    Confidence: {detection.confidence:.3f}")
            elif isinstance(detection, dict) and 'confidence' in detection:
                logger.info(f"    Confidence: {detection['confidence']:.3f}")
            
            # Handle bbox
            bbox = None
            if hasattr(detection, 'bbox'):
                bbox = detection.bbox
            elif isinstance(detection, dict) and 'bbox' in detection:
                bbox = detection['bbox']
            
            if bbox:
                if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                    logger.info(f"    BBox: ({bbox[0]:.1f}, {bbox[1]:.1f}, {bbox[2]:.1f}, {bbox[3]:.1f})")
                elif hasattr(bbox, 'x1'):
                    logger.info(f"    BBox: ({bbox.x1:.1f}, {bbox.y1:.1f}, {bbox.x2:.1f}, {bbox.y2:.1f})")
            
            # Get plate image
            plate_img = None
            if hasattr(detection, 'plate_image') and detection.plate_image is not None:
                plate_img = detection.plate_image
            elif isinstance(detection, dict) and 'plate_image' in detection:
                plate_img = detection['plate_image']
            
            if plate_img is not None:
                if isinstance(plate_img, np.ndarray):
                    h, w = plate_img.shape[:2]
                    logger.info(f"    Plate Image Size: {w}x{h}")
                    logger.info(f"    Plate Image Valid: ✅")
                else:
                    logger.warning(f"    Plate Image: ⚠️ Invalid format")
            else:
                logger.warning(f"    Plate Image: ❌ Not available")
        
        # Save visualization
        vis_frame = frame.copy()
        for idx, detection in enumerate(plate_detections):
            # Extract bbox
            bbox = None
            if hasattr(detection, 'bbox'):
                bbox = detection.bbox
            elif isinstance(detection, dict) and 'bbox' in detection:
                bbox = detection['bbox']
            
            if bbox:
                if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                    x1, y1, x2, y2 = map(int, bbox[:4])
                elif hasattr(bbox, 'x1'):
                    x1, y1, x2, y2 = int(bbox.x1), int(bbox.y1), int(bbox.x2), int(bbox.y2)
                else:
                    continue
                
                # Get confidence
                conf = 0.0
                if hasattr(detection, 'confidence'):
                    conf = detection.confidence
                elif isinstance(detection, dict) and 'confidence' in detection:
                    conf = detection['confidence']
                
                cv2.rectangle(vis_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(vis_frame, f"Plate {idx+1}: {conf:.2f}", 
                           (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        
        output_path = "test_detection_result.jpg"
        cv2.imwrite(output_path, vis_frame)
        logger.info(f"✅ Saved detection visualization: {output_path}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Detection test failed: {e}", exc_info=True)
        return False


def test_ocr_only(plate_image_path: str):
    """Test OCR on a single plate image"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: OCR Only (on plate image)")
    logger.info("=" * 60)
    
    try:
        from license_plate.ocr.plate_ocr import HybridOCR
        
        # Load plate image
        if not os.path.exists(plate_image_path):
            logger.error(f"❌ Plate image not found: {plate_image_path}")
            return False
        
        plate_img = cv2.imread(plate_image_path)
        if plate_img is None:
            logger.error(f"❌ Failed to load plate image: {plate_image_path}")
            return False
        
        h, w = plate_img.shape[:2]
        logger.info(f"✅ Loaded plate image: {plate_image_path} ({w}x{h})")
        
        # Initialize OCR
        ocr_engine = HybridOCR()
        logger.info("✅ HybridOCR initialized")
        
        # Test OCR
        logger.info("🔍 Running OCR...")
        start_time = time.time()
        
        plate_text = ocr_engine.recognize_text(plate_img)
        
        ocr_time = time.time() - start_time
        logger.info(f"⏱️ OCR time: {ocr_time*1000:.2f}ms")
        
        # Display results
        logger.info(f"\n📝 OCR Results:")
        logger.info(f"    Text: '{plate_text.text}'")
        logger.info(f"    Confidence: {plate_text.confidence:.3f}")
        logger.info(f"    Method: {plate_text.method_used}")
        logger.info(f"    Raw Text: '{plate_text.raw_text}'")
        logger.info(f"    Cleaned Text: '{plate_text.cleaned_text}'")
        
        if plate_text.text and len(plate_text.text) > 0:
            logger.info(f"✅ OCR Success!")
            return True
        else:
            logger.warning(f"⚠️ OCR returned empty text")
            return False
        
    except Exception as e:
        logger.error(f"❌ OCR test failed: {e}", exc_info=True)
        return False


async def test_full_pipeline(frame_path: str):
    """Test complete pipeline: Detection + OCR"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: Full Pipeline (Detection + OCR)")
    logger.info("=" * 60)
    
    try:
        from license_plate_processor import LicensePlateProcessor
        
        # Load test image
        if not os.path.exists(frame_path):
            logger.error(f"❌ Test image not found: {frame_path}")
            return False
        
        frame = cv2.imread(frame_path)
        if frame is None:
            logger.error(f"❌ Failed to load image: {frame_path}")
            return False
        
        logger.info(f"✅ Loaded test image: {frame_path} ({frame.shape[1]}x{frame.shape[0]})")
        
        # Initialize processor
        processor = LicensePlateProcessor()
        logger.info("✅ LicensePlateProcessor initialized")
        
        # Test full pipeline
        logger.info("🔍 Running full pipeline (detection + OCR)...")
        start_time = time.time()
        
        # CRITICAL FIX: process_frame is async, must use await
        results = await processor.process_frame(
            frame=frame,
            frame_id="test_frame_001",
            context={'intersection_id': 1, 'sensor_id': 'test_camera'}
        )
        
        processing_time = time.time() - start_time
        logger.info(f"⏱️ Total processing time: {processing_time*1000:.2f}ms")
        logger.info(f"📊 Processed {len(results)} plate results")
        
        if len(results) == 0:
            logger.warning("⚠️ No plate results!")
            return False
        
        # Display results
        plates_with_text = 0
        plates_detected_only = 0
        
        for idx, result in enumerate(results):
            logger.info(f"\n  Result {idx + 1}:")
            
            # Get plate text
            plate_text = None
            plate_confidence = 0.0
            if hasattr(result, 'plate_text') and result.plate_text:
                if hasattr(result.plate_text, 'text'):
                    plate_text = result.plate_text.text
                    plate_confidence = result.plate_text.confidence if hasattr(result.plate_text, 'confidence') else 0.0
                elif isinstance(result.plate_text, str):
                    plate_text = result.plate_text
            
            # Get detection info
            detection_conf = 0.0
            bbox = None
            if hasattr(result, 'plate_detection') and result.plate_detection:
                detection_conf = result.plate_detection.confidence if hasattr(result.plate_detection, 'confidence') else 0.0
                if hasattr(result.plate_detection, 'bbox'):
                    bbox = result.plate_detection.bbox
            
            logger.info(f"    Detection Confidence: {detection_conf:.3f}")
            if bbox:
                logger.info(f"    BBox: ({bbox[0]:.1f}, {bbox[1]:.1f}, {bbox[2]:.1f}, {bbox[3]:.1f})")
            logger.info(f"    OCR Text: '{plate_text}'")
            logger.info(f"    OCR Confidence: {plate_confidence:.3f}")
            
            if plate_text and len(plate_text) > 0:
                plates_with_text += 1
                logger.info(f"    Status: ✅ Text recognized")
            else:
                plates_detected_only += 1
                logger.info(f"    Status: ⚠️ Detection only (no text)")
        
        logger.info(f"\n📊 Summary:")
        logger.info(f"    Plates with text: {plates_with_text}")
        logger.info(f"    Plates detected only: {plates_detected_only}")
        logger.info(f"    Total: {len(results)}")
        
        # Save visualization
        vis_frame = frame.copy()
        for idx, result in enumerate(results):
            # Get bbox
            if hasattr(result, 'plate_detection') and result.plate_detection:
                if hasattr(result.plate_detection, 'bbox'):
                    bbox = result.plate_detection.bbox
                    x1, y1, x2, y2 = map(int, bbox[:4])
                    
                    # Get text
                    plate_text = None
                    if hasattr(result, 'plate_text') and result.plate_text:
                        if hasattr(result.plate_text, 'text'):
                            plate_text = result.plate_text.text
                    
                    # Draw box
                    color = (0, 255, 0) if plate_text else (0, 165, 255)  # Green if text, orange if no text
                    cv2.rectangle(vis_frame, (x1, y1), (x2, y2), color, 2)
                    
                    # Draw label
                    label = f"{idx+1}: {plate_text}" if plate_text else f"{idx+1}: No text"
                    cv2.putText(vis_frame, label, (x1, y1-10), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        
        output_path = "test_full_pipeline_result.jpg"
        cv2.imwrite(output_path, vis_frame)
        logger.info(f"✅ Saved full pipeline visualization: {output_path}")
        
        return plates_with_text > 0 or plates_detected_only > 0
        
    except Exception as e:
        logger.error(f"❌ Full pipeline test failed: {e}", exc_info=True)
        return False


async def main_async():
    """Main test function (async version)"""
    logger.info("🚀 Starting License Plate Detection & OCR Tests")
    logger.info("=" * 60)
    
    # Check for test image
    test_image = None
    test_plate_image = None
    
    # Look for test images in common locations
    possible_locations = [
        "videos/LPDT.mp4",  # User mentioned this video
        "test_images/test_plate.jpg",
        "test_images/test_frame.jpg",
        "test.jpg",
        "test.png"
    ]
    
    # Check if user provided image path
    if len(sys.argv) > 1:
        test_image = sys.argv[1]
        if not os.path.exists(test_image):
            logger.error(f"❌ Provided image not found: {test_image}")
            return
    else:
        # Try to find test image
        for loc in possible_locations:
            if os.path.exists(loc):
                test_image = loc
                break
    
    if not test_image:
        logger.error("❌ No test image found!")
        logger.info("\nUsage:")
        logger.info("  python test_plate_detection_ocr.py <image_path>")
        logger.info("\nOr place a test image at one of these locations:")
        for loc in possible_locations:
            logger.info(f"  - {loc}")
        return
    
    logger.info(f"📸 Using test image: {test_image}")
    
    # Run tests
    results = {}
    
    # Test 1: Detection only
    results['detection'] = test_plate_detection(test_image)
    
    # Test 2: OCR only (if we have a plate image)
    if len(sys.argv) > 2:
        test_plate_image = sys.argv[2]
        results['ocr'] = test_ocr_only(test_plate_image)
    else:
        logger.info("\n⚠️ Skipping OCR-only test (no plate image provided)")
        logger.info("   Usage: python test_plate_detection_ocr.py <frame_image> <plate_image>")
        results['ocr'] = None
    
    # Test 3: Full pipeline (async)
    results['full_pipeline'] = await test_full_pipeline(test_image)
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("📊 TEST SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Detection Test: {'✅ PASSED' if results['detection'] else '❌ FAILED'}")
    if results['ocr'] is not None:
        logger.info(f"OCR Test: {'✅ PASSED' if results['ocr'] else '❌ FAILED'}")
    logger.info(f"Full Pipeline Test: {'✅ PASSED' if results['full_pipeline'] else '❌ FAILED'}")
    
    if all(r for r in results.values() if r is not None):
        logger.info("\n✅ All tests passed!")
    else:
        logger.warning("\n⚠️ Some tests failed. Check logs above for details.")


async def main_async():
    """Main test function (async version)"""
    logger.info("🚀 Starting License Plate Detection & OCR Tests")
    logger.info("=" * 60)
    
    # Check for test image
    test_image = None
    test_plate_image = None
    
    # Look for test images in common locations
    possible_locations = [
        "videos/LPDT.mp4",  # User mentioned this video
        "test_images/test_plate.jpg",
        "test_images/test_frame.jpg",
        "test.jpg",
        "test.png"
    ]
    
    # Check if user provided image path
    if len(sys.argv) > 1:
        test_image = sys.argv[1]
        if not os.path.exists(test_image):
            logger.error(f"❌ Provided image not found: {test_image}")
            return
    else:
        # Try to find test image
        for loc in possible_locations:
            if os.path.exists(loc):
                test_image = loc
                break
    
    if not test_image:
        logger.error("❌ No test image found!")
        logger.info("\nUsage:")
        logger.info("  python test_plate_detection_ocr.py <image_path>")
        logger.info("\nOr place a test image at one of these locations:")
        for loc in possible_locations:
            logger.info(f"  - {loc}")
        return
    
    logger.info(f"📸 Using test image: {test_image}")
    
    # Run tests
    results = {}
    
    # Test 1: Detection only
    results['detection'] = test_plate_detection(test_image)
    
    # Test 2: OCR only (if we have a plate image)
    if len(sys.argv) > 2:
        test_plate_image = sys.argv[2]
        results['ocr'] = test_ocr_only(test_plate_image)
    else:
        logger.info("\n⚠️ Skipping OCR-only test (no plate image provided)")
        logger.info("   Usage: python test_plate_detection_ocr.py <frame_image> <plate_image>")
        results['ocr'] = None
    
    # Test 3: Full pipeline (async)
    results['full_pipeline'] = await test_full_pipeline(test_image)
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("📊 TEST SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Detection Test: {'✅ PASSED' if results['detection'] else '❌ FAILED'}")
    if results['ocr'] is not None:
        logger.info(f"OCR Test: {'✅ PASSED' if results['ocr'] else '❌ FAILED'}")
    logger.info(f"Full Pipeline Test: {'✅ PASSED' if results['full_pipeline'] else '❌ FAILED'}")
    
    if all(r for r in results.values() if r is not None):
        logger.info("\n✅ All tests passed!")
    else:
        logger.warning("\n⚠️ Some tests failed. Check logs above for details.")


def main():
    """Synchronous wrapper for async main"""
    import asyncio
    asyncio.run(main_async())

if __name__ == "__main__":
    main()

