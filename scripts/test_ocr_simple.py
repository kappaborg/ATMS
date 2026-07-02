#!/usr/bin/env python3
"""
Simple OCR Test - Just test EasyOCR on a plate image
"""
import sys
import os
import cv2
from pathlib import Path

# Add project paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "services" / "ai-perception" / "src"))

def test_easyocr_direct(image_path: str):
    """Test EasyOCR directly"""
    print("=" * 60)
    print("Simple EasyOCR Test")
    print("=" * 60)
    
    # Load image
    if not os.path.exists(image_path):
        print(f"❌ Image not found: {image_path}")
        return
    
    img = cv2.imread(image_path)
    if img is None:
        print(f"❌ Failed to load image: {image_path}")
        return
    
    h, w = img.shape[:2]
    print(f"✅ Loaded image: {w}x{h}")
    
    # Test EasyOCR
    try:
        import easyocr
        print("✅ EasyOCR imported")
        
        # Initialize reader
        print("🔍 Initializing EasyOCR reader...")
        reader = easyocr.Reader(['en'], gpu=False)
        print("✅ EasyOCR reader initialized")
        
        # Run OCR
        print("🔍 Running OCR...")
        results = reader.readtext(img, detail=1, paragraph=False)
        
        print(f"\n📊 Found {len(results)} text regions:")
        for idx, (bbox, text, confidence) in enumerate(results):
            print(f"\n  Region {idx + 1}:")
            print(f"    Text: '{text}'")
            print(f"    Confidence: {confidence:.3f}")
            print(f"    BBox: {bbox}")
        
        if len(results) > 0:
            # Get best result
            best = max(results, key=lambda x: x[2])
            print(f"\n✅ Best result: '{best[1]}' (confidence: {best[2]:.3f})")
        else:
            print("\n⚠️ No text detected")
            
    except ImportError as e:
        print(f"❌ EasyOCR not installed: {e}")
        print("   Install with: pip install easyocr")
    except Exception as e:
        print(f"❌ OCR failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_ocr_simple.py <image_path>")
        print("\nExample:")
        print("  python test_ocr_simple.py test_plate.jpg")
        sys.exit(1)
    
    test_easyocr_direct(sys.argv[1])

