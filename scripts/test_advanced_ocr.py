#!/usr/bin/env python3
"""
Test script for Advanced OCR system
Compares different OCR methods on actual plate images
"""
import sys
import os
import cv2
import numpy as np
from pathlib import Path

# Add project paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "services" / "ai-perception" / "src"))

def test_advanced_ocr(plate_image_path: str):
    """Test advanced OCR on a plate image"""
    print("=" * 60)
    print("Advanced OCR Test")
    print("=" * 60)
    
    if not os.path.exists(plate_image_path):
        print(f"❌ Image not found: {plate_image_path}")
        return
    
    img = cv2.imread(plate_image_path)
    if img is None:
        print(f"❌ Failed to load image: {plate_image_path}")
        return
    
    h, w = img.shape[:2]
    print(f"✅ Loaded image: {w}x{h} pixels")
    
    try:
        from license_plate.ocr.advanced_ocr import AdvancedPlateOCR, OCRMethod
        
        # Test with PaddleOCR (best for license plates)
        print("\n" + "-" * 60)
        print("Testing PaddleOCR (Recommended for License Plates)")
        print("-" * 60)
        ocr_paddle = AdvancedPlateOCR(primary_method=OCRMethod.PADDLEOCR)
        result_paddle = ocr_paddle.recognize_text(img)
        
        print(f"Text: '{result_paddle.text}'")
        print(f"Confidence: {result_paddle.confidence:.3f}")
        print(f"Method: {result_paddle.method.value}")
        print(f"Raw Text: '{result_paddle.raw_text}'")
        print(f"Processing Time: {result_paddle.processing_time_ms:.2f}ms")
        
        # Test with EasyOCR (current method)
        print("\n" + "-" * 60)
        print("Testing EasyOCR (Current Method)")
        print("-" * 60)
        ocr_easy = AdvancedPlateOCR(primary_method=OCRMethod.EASYOCR)
        result_easy = ocr_easy.recognize_text(img)
        
        print(f"Text: '{result_easy.text}'")
        print(f"Confidence: {result_easy.confidence:.3f}")
        print(f"Method: {result_easy.method.value}")
        print(f"Raw Text: '{result_easy.raw_text}'")
        print(f"Processing Time: {result_easy.processing_time_ms:.2f}ms")
        
        # Compare results
        print("\n" + "=" * 60)
        print("Comparison")
        print("=" * 60)
        print(f"PaddleOCR: '{result_paddle.text}' (conf: {result_paddle.confidence:.3f})")
        print(f"EasyOCR:   '{result_easy.text}' (conf: {result_easy.confidence:.3f})")
        
        if result_paddle.text and result_paddle.confidence > result_easy.confidence:
            print("✅ PaddleOCR performed better!")
        elif result_easy.text and result_easy.confidence > result_paddle.confidence:
            print("✅ EasyOCR performed better!")
        else:
            print("⚠️ Results are similar")
            
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("\nInstall missing dependencies:")
        print("  pip install paddleocr")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_advanced_ocr.py <plate_image>")
        print("\nExample:")
        print("  python test_advanced_ocr.py plate_1_80x22.jpg")
        sys.exit(1)
    
    test_advanced_ocr(sys.argv[1])

