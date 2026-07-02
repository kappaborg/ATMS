#!/usr/bin/env python3
"""
Test Professional OCR on Multiple Frames from /Users/kappasutra/Traffic/videos/test2.mp4
Extracts frames at different timestamps and tests OCR on detected plates
"""
import sys
import os
import cv2
import numpy as np
from pathlib import Path
import asyncio

# Add project paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "services" / "ai-perception" / "src"))

def extract_frames(video_path: str, timestamps: list, output_dir: str = "test_frames"):
    """Extract frames at specific timestamps"""
    if not os.path.exists(video_path):
        print(f"❌ Video not found: {video_path}")
        return []
    
    os.makedirs(output_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    
    print(f"📹 Video Info:")
    print(f"   FPS: {fps:.2f}")
    print(f"   Total Frames: {total_frames}")
    print(f"   Duration: {duration:.2f}s")
    print()
    
    extracted_frames = []
    
    for timestamp in timestamps:
        frame_number = int(timestamp * fps)
        if frame_number >= total_frames:
            print(f"⚠️  Timestamp {timestamp}s (frame {frame_number}) exceeds video length")
            continue
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        
        if ret:
            frame_path = os.path.join(output_dir, f"frame_{timestamp}s.jpg")
            cv2.imwrite(frame_path, frame)
            extracted_frames.append((frame_path, timestamp, frame_number))
            print(f"✅ Extracted frame at {timestamp}s (frame {frame_number}) → {frame_path}")
        else:
            print(f"❌ Failed to extract frame at {timestamp}s")
    
    cap.release()
    return extracted_frames

async def test_ocr_on_frame(frame_path: str, timestamp: float):
    """Test Professional OCR on a frame"""
    print("\n" + "=" * 70)
    print(f"Testing Frame at {timestamp}s")
    print("=" * 70)
    
    frame = cv2.imread(frame_path)
    if frame is None:
        print(f"❌ Failed to load frame: {frame_path}")
        return None
    
    h, w = frame.shape[:2]
    print(f"📸 Frame: {w}x{h} pixels")
    
    try:
        # Import license plate processor
        from license_plate_processor import LicensePlateProcessor
        
        # Use default model path (no need for Config)
        model_path = str(project_root / "models" / "license_plate_training" / "outputs" / "license_plate_model_mps" / "weights" / "best.mlpackage")
        
        # Initialize processor (use yolo_model_path parameter)
        processor = LicensePlateProcessor(
            yolo_model_path=model_path,
            confidence_threshold=0.25,
            ocr_primary_method="professional"
        )
        
        print("\n🔍 Running Detection + OCR...")
        results = await processor.process_frame(frame, frame_id=f"test_{timestamp}s")
        
        if results and len(results) > 0:
            print(f"\n✅ Detected {len(results)} plate(s):")
            
            for i, plate_det in enumerate(results, 1):
                print(f"\n  Plate {i}:")
                print(f"    BBox: {plate_det.plate_detection.bbox}")
                print(f"    Detection Confidence: {plate_det.plate_detection.confidence:.3f}")
                
                if plate_det.plate_text:
                    ocr = plate_det.plate_text
                    print(f"    OCR Text: '{ocr.text}'")
                    print(f"    OCR Confidence: {ocr.confidence:.3f}")
                    print(f"    OCR Method: {ocr.method_used.value}")
                    print(f"    Raw Text: '{ocr.raw_text}'")
                    
                    if ocr.text and len(ocr.text) >= 5:
                        print(f"    ✅ GOOD: Complete text detected!")
                    elif ocr.text:
                        print(f"    ⚠️  PARTIAL: Only {len(ocr.text)} characters")
                    else:
                        print(f"    ❌ FAILED: No text recognized")
                else:
                    print(f"    ❌ No OCR result")
        else:
            print(f"\n❌ No plates detected in this frame")
        
        return results
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None

async def main():
    """Main test function"""
    print("=" * 70)
    print("Professional OCR Test - Multiple Frames from /Users/kappasutra/Traffic/videos/test2.mp4")
    print("=" * 70)
    
    video_path = project_root / "videos" / "/Users/kappasutra/Traffic/videos/test2.mp4"
    
    if not video_path.exists():
        print(f"❌ Video not found: {video_path}")
        print("\nLooking for video in common locations...")
        possible_paths = [
            project_root / "/Users/kappasutra/Traffic/videos/test2.mp4",
            project_root / "videos" / "/Users/kappasutra/Traffic/videos/test2.mp4",
            Path("/Users/kappasutra/Traffic/videos/test2.mp4"),
        ]
        for path in possible_paths:
            if path.exists():
                video_path = path
                print(f"✅ Found: {video_path}")
                break
        else:
            print("❌ Could not find /Users/kappasutra/Traffic/videos/test2.mp4")
            return
    
    # Extract frames at different timestamps (spread throughout video)
    print("\n📹 Extracting frames from video...")
    timestamps = [5, 10, 15, 20, 25, 30]  # Test at 5s intervals
    extracted = extract_frames(str(video_path), timestamps, "test_frames")
    
    if not extracted:
        print("❌ No frames extracted")
        return
    
    print(f"\n✅ Extracted {len(extracted)} frames")
    print("\n" + "=" * 70)
    print("Testing Professional OCR on Each Frame")
    print("=" * 70)
    
    results_summary = []
    
    for frame_path, timestamp, frame_num in extracted:
        results = await test_ocr_on_frame(frame_path, timestamp)
        
        if results and len(results) > 0:
            for plate_det in results:
                ocr_text = plate_det.plate_text.text if plate_det.plate_text else ""
                ocr_conf = plate_det.plate_text.confidence if plate_det.plate_text else 0.0
                results_summary.append({
                    'timestamp': timestamp,
                    'frame': frame_num,
                    'detection_conf': plate_det.plate_detection.confidence,
                    'ocr_text': ocr_text,
                    'ocr_conf': ocr_conf,
                    'text_length': len(ocr_text)
                })
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    if results_summary:
        print(f"\n✅ Total plates processed: {len(results_summary)}")
        print(f"\nResults by frame:")
        
        for r in results_summary:
            status = "✅" if r['text_length'] >= 5 else "⚠️" if r['text_length'] > 0 else "❌"
            print(f"  {status} {r['timestamp']}s: '{r['ocr_text']}' "
                  f"(OCR: {r['ocr_conf']:.3f}, len: {r['text_length']})")
        
        # Statistics
        successful = sum(1 for r in results_summary if r['text_length'] >= 5)
        partial = sum(1 for r in results_summary if 0 < r['text_length'] < 5)
        failed = sum(1 for r in results_summary if r['text_length'] == 0)
        
        print(f"\n📊 Statistics:")
        print(f"   ✅ Complete (≥5 chars): {successful}/{len(results_summary)} ({100*successful/len(results_summary):.1f}%)")
        print(f"   ⚠️  Partial (<5 chars): {partial}/{len(results_summary)} ({100*partial/len(results_summary):.1f}%)")
        print(f"   ❌ Failed (0 chars): {failed}/{len(results_summary)} ({100*failed/len(results_summary):.1f}%)")
        
        avg_conf = np.mean([r['ocr_conf'] for r in results_summary if r['ocr_conf'] > 0])
        print(f"   📈 Average OCR Confidence: {avg_conf:.3f}")
    else:
        print("\n❌ No plates detected in any frame")

if __name__ == "__main__":
    asyncio.run(main())

