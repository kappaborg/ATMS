#!/usr/bin/env python3
"""
Test Professional OCR System
Tests the new multi-method fusion OCR for 65-70%+ accuracy
"""
import sys
import os
import cv2
from pathlib import Path

# Add project paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "services" / "ai-perception" / "src"))

def test_professional_ocr(plate_image_path: str):
    """Test professional OCR on plate image"""
    print("=" * 60)
    print("Professional OCR Test (Target: 65-70%+ Accuracy)")
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
        from license_plate.ocr.professional_ocr_adapter import ProfessionalOCRAdapter
        
        print("\n🔍 Running Professional OCR (Multi-method fusion)...")
        ocr = ProfessionalOCRAdapter()
        
        result = ocr.recognize_text(img)
        
        print(f"\n📊 Results:")
        print(f"  Text: '{result.text}'")
        print(f"  Confidence: {result.confidence:.3f}")
        print(f"  Method: {result.method_used.value}")
        print(f"  Raw Text: '{result.raw_text}'")
        print(f"  Cleaned Text: '{result.cleaned_text}'")
        
        if result.text and len(result.text) >= 2:
            if result.confidence >= 0.65:
                print(f"\n✅ EXCELLENT! Confidence >= 65% (Target achieved!)")
            elif result.confidence >= 0.50:
                print(f"\n✅ GOOD! Confidence >= 50%")
            elif result.confidence >= 0.30:
                print(f"\n⚠️ MODERATE: Confidence >= 30% (Below target)")
            else:
                print(f"\n❌ LOW: Confidence < 30% (Needs improvement)")
        else:
            print(f"\n❌ FAILED: No text recognized")
            
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("\nMake sure all dependencies are installed:")
        print("  pip install paddleocr easyocr pytesseract")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_professional_ocr.py <plate_image>")
        print("\nExample:")
        print("  python test_professional_ocr.py plate_1_80x22.jpg")
        sys.exit(1)
    
    test_professional_ocr(sys.argv[1])

