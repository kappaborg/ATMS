#!/usr/bin/env python3
"""
Camera Calibration Script
Helps calibrate pixel-to-meter ratio for accurate speed calculations
"""
import cv2
import numpy as np
import sys
from pathlib import Path

# Add project paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "services" / "ai-perception" / "src"))

from calculations.speed_calculator import CameraCalibrator

def calibrate_from_video(video_path: str, frame_idx: int = 0):
    """
    Calibrate camera from a video frame
    
    Args:
        video_path: Path to video file
        frame_idx: Frame index to use for calibration
    """
    print("=" * 70)
    print("Camera Calibration Tool")
    print("=" * 70)
    print()
    
    # Load video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ Cannot open video: {video_path}")
        return None
    
    # Seek to frame
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        print(f"❌ Cannot read frame {frame_idx}")
        return None
    
    print(f"✅ Loaded frame {frame_idx} from {video_path}")
    print(f"   Frame size: {frame.shape[1]}x{frame.shape[0]}")
    print()
    
    # Display frame
    display_frame = frame.copy()
    cv2.imshow("Calibration Frame - Click two points to measure distance", display_frame)
    
    print("Instructions:")
    print("1. Click two points on a known object (e.g., lane width, vehicle length)")
    print("2. Press 'Enter' to confirm")
    print("3. Enter the real-world distance in meters")
    print("4. Press 'q' to quit")
    print()
    
    points = []
    
    def mouse_callback(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x, y))
            cv2.circle(display_frame, (x, y), 5, (0, 255, 0), -1)
            if len(points) == 2:
                cv2.line(display_frame, points[0], points[1], (0, 255, 0), 2)
            cv2.imshow("Calibration Frame - Click two points to measure distance", display_frame)
    
    cv2.setMouseCallback("Calibration Frame - Click two points to measure distance", mouse_callback)
    
    while True:
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        if key == 13 and len(points) == 2:  # Enter key
            break
    
    cv2.destroyAllWindows()
    
    if len(points) != 2:
        print("❌ Need exactly 2 points")
        return None
    
    # Calculate pixel distance
    p1, p2 = points
    pixel_distance = np.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
    
    print(f"✅ Measured pixel distance: {pixel_distance:.1f} pixels")
    print()
    
    # Get real-world distance
    real_distance = float(input("Enter real-world distance in meters: "))
    
    if real_distance <= 0:
        print("❌ Invalid distance")
        return None
    
    # Calculate ratio
    pixel_to_meter = real_distance / pixel_distance
    
    print()
    print("=" * 70)
    print("CALIBRATION RESULT")
    print("=" * 70)
    print(f"Pixel distance: {pixel_distance:.1f} pixels")
    print(f"Real distance: {real_distance:.3f} meters")
    print(f"Pixel-to-meter ratio: {pixel_to_meter:.6f} m/pixel")
    print()
    print("📝 Add this to your SpeedCalculator initialization:")
    print(f'   pixel_to_meter_ratio={pixel_to_meter:.6f}')
    print()
    
    return pixel_to_meter

def estimate_from_road_type(frame_shape: tuple, road_type: str = "city"):
    """
    Estimate pixel-to-meter ratio from road type
    
    Args:
        frame_shape: (height, width) of frame
        road_type: "highway", "city", "parking"
    """
    calibrator = CameraCalibrator()
    ratio = calibrator.estimate_pixel_to_meter_ratio(frame_shape, road_type)
    
    print("=" * 70)
    print("Estimated Calibration (Road Type)")
    print("=" * 70)
    print(f"Road type: {road_type}")
    print(f"Frame size: {frame_shape[1]}x{frame_shape[0]}")
    print(f"Estimated pixel-to-meter ratio: {ratio:.6f} m/pixel")
    print()
    print("⚠️  This is an ESTIMATE. For accurate speed, calibrate manually!")
    print()
    
    return ratio

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Camera Calibration Tool")
    parser.add_argument("--video", type=str, help="Video file path")
    parser.add_argument("--frame", type=int, default=0, help="Frame index (default: 0)")
    parser.add_argument("--estimate", action="store_true", help="Estimate from road type")
    parser.add_argument("--road-type", type=str, default="city", choices=["highway", "city", "parking"], help="Road type for estimation")
    parser.add_argument("--width", type=int, default=1920, help="Frame width for estimation")
    parser.add_argument("--height", type=int, default=1080, help="Frame height for estimation")
    
    args = parser.parse_args()
    
    if args.estimate:
        estimate_from_road_type((args.height, args.width), args.road_type)
    elif args.video:
        calibrate_from_video(args.video, args.frame)
    else:
        print("Usage:")
        print("  python calibrate_camera.py --video path/to/video.mp4 --frame 0")
        print("  python calibrate_camera.py --estimate --road-type city --width 1920 --height 1080")

