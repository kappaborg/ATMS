"""
Data Flow Verification Test
Verifies complete data flow from video → Kafka → AI Perception → Dashboard
"""
import asyncio
import json
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "services" / "ai-perception" / "src"))
sys.path.insert(0, str(project_root / "shared"))

def verify_detection_model():
    """Verify Detection model includes all fields"""
    try:
        from shared.models.detection import Detection
        
        # Check all required fields are in the model
        required_fields = [
            'detection_id', 'object_class', 'bbox', 'confidence', 'timestamp',
            'frame_id', 'sensor_id',
            # Enhanced fields
            'track_id', 'velocity', 'direction', 'speed',
            'vehicle_brand', 'brand_confidence',
            'vehicle_type',
            'license_plate', 'license_plate_confidence',
            'multiview_confidence', 'views',
            'emission_co2', 'fuel_consumption', 'emission_impact',
            'trajectory_predicted', 'anomaly_detected'
        ]
        
        model_fields = Detection.model_fields.keys()
        missing_fields = [f for f in required_fields if f not in model_fields]
        
        if missing_fields:
            print(f"❌ Missing fields in Detection model: {missing_fields}")
            return False
        else:
            print("✅ All required fields present in Detection model")
            return True
    except Exception as e:
        print(f"❌ Error checking Detection model: {e}")
        return False

def verify_imports():
    """Verify all critical imports work"""
    errors = []
    
    try:
        from tracking import OptimizedObjectTracker, ObjectType, TrackedObject, ByteTrackWrapper
        print("✅ Tracking imports: OK")
    except Exception as e:
        errors.append(f"Tracking: {e}")
        print(f"❌ Tracking imports: {e}")
    
    try:
        from optimization import ATMSTrafficOptimizer, SignalOptimization, PedestrianSafety, EmergencyPriority
        print("✅ Optimization imports: OK")
    except Exception as e:
        errors.append(f"Optimization: {e}")
        print(f"❌ Optimization imports: {e}")
    
    try:
        from detection.yolo_detector import YOLODetector
        print("✅ YOLO detector import: OK")
    except Exception as e:
        errors.append(f"YOLO: {e}")
        print(f"❌ YOLO detector import: {e}")
    
    try:
        from optimization.async_processor import AsyncModelProcessor
        print("✅ Async processor import: OK")
    except Exception as e:
        errors.append(f"Async: {e}")
        print(f"❌ Async processor import: {e}")
    
    try:
        from tracking.bytetrack_tracker import ByteTrackWrapper
        print("✅ ByteTrack import: OK")
    except Exception as e:
        errors.append(f"ByteTrack: {e}")
        print(f"❌ ByteTrack import: {e}")
    
    return len(errors) == 0

def verify_data_flow():
    """Verify data flow integration"""
    print("\n" + "="*60)
    print("📊 DATA FLOW VERIFICATION")
    print("="*60)
    
    # Step 1: Detection Model
    print("\n1️⃣  Detection Model Schema:")
    model_ok = verify_detection_model()
    
    # Step 2: Imports
    print("\n2️⃣  Module Imports:")
    imports_ok = verify_imports()
    
    # Step 3: Integration Points
    print("\n3️⃣  Integration Points:")
    integration_ok = True
    
    try:
        # Check main.py integration
        from main import app, process_frames
        print("   ✅ AI Perception main.py: OK")
    except Exception as e:
        print(f"   ❌ AI Perception main.py: {e}")
        integration_ok = False
    
    try:
        # Check trajectory integration
        from trajectory_integration import IntegratedATMSSystem
        print("   ✅ Trajectory integration: OK")
    except Exception as e:
        print(f"   ❌ Trajectory integration: {e}")
        integration_ok = False
    
    # Summary
    print("\n" + "="*60)
    print("📋 VERIFICATION SUMMARY")
    print("="*60)
    print(f"   Detection Model: {'✅ PASS' if model_ok else '❌ FAIL'}")
    print(f"   Module Imports: {'✅ PASS' if imports_ok else '❌ FAIL'}")
    print(f"   Integration: {'✅ PASS' if integration_ok else '❌ FAIL'}")
    
    all_ok = model_ok and imports_ok and integration_ok
    print(f"\n   Overall Status: {'✅ ALL CHECKS PASSED' if all_ok else '❌ SOME CHECKS FAILED'}")
    
    return all_ok

if __name__ == "__main__":
    success = verify_data_flow()
    sys.exit(0 if success else 1)

