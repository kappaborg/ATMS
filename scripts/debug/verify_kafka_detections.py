#!/usr/bin/env python3
"""
Verify Kafka Detection Messages
Checks that all detection fields are properly included in Kafka messages
"""
import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

try:
    from kafka import KafkaConsumer
    from kafka.errors import KafkaError
except ImportError:
    print("❌ kafka-python not installed. Install with: pip install kafka-python")
    sys.exit(1)

def verify_detection_message(message_value: dict):
    """Verify a detection message has all required fields"""
    issues = []
    warnings = []
    
    # Check top-level fields
    required_fields = ['detections', 'frame_id', 'sensor_id', 'frame_width', 'frame_height']
    for field in required_fields:
        if field not in message_value:
            issues.append(f"Missing required field: {field}")
    
    # Check detections array
    detections = message_value.get('detections', [])
    if not detections:
        warnings.append("No detections in message")
        return issues, warnings
    
    # Check first detection
    first_det = detections[0]
    
    # Required detection fields
    det_required = ['detection_id', 'object_class', 'bbox', 'confidence', 'timestamp', 'frame_id', 'sensor_id']
    for field in det_required:
        if field not in first_det:
            issues.append(f"Detection missing required field: {field}")
    
    # Check bbox structure
    bbox = first_det.get('bbox', {})
    if isinstance(bbox, dict):
        bbox_required = ['x1', 'y1', 'x2', 'y2']
        for field in bbox_required:
            if field not in bbox:
                issues.append(f"Bbox missing field: {field}")
    else:
        issues.append("Bbox is not a dict")
    
    # Check optional fields (should be present even if None)
    optional_fields = [
        'track_id', 'speed', 'vehicle_brand', 'brand_confidence',
        'license_plate', 'license_plate_confidence',
        'multiview_confidence', 'views',
        'emission_co2', 'fuel_consumption', 'emission_impact',
        'anomaly_detected'
    ]
    
    for field in optional_fields:
        if field not in first_det:
            warnings.append(f"Optional field missing: {field}")
    
    # Check if values are populated
    if first_det.get('vehicle_brand'):
        print(f"  ✅ Brand: {first_det['vehicle_brand']} (conf: {first_det.get('brand_confidence', 0):.2f})")
    else:
        warnings.append("No vehicle_brand in detection")
    
    if first_det.get('license_plate'):
        print(f"  ✅ License Plate: {first_det['license_plate']}")
    else:
        warnings.append("No license_plate in detection")
    
    if first_det.get('speed') and first_det['speed'] > 0:
        print(f"  ✅ Speed: {first_det['speed']} km/h")
    else:
        warnings.append("No speed in detection")
    
    if first_det.get('emission_co2') and first_det['emission_co2'] > 0:
        print(f"  ✅ CO2: {first_det['emission_co2']} g/km")
    else:
        warnings.append("No emission_co2 in detection")
    
    if first_det.get('track_id'):
        print(f"  ✅ Track ID: {first_det['track_id']}")
    else:
        warnings.append("No track_id in detection")
    
    return issues, warnings

def main():
    print("🔍 Verifying Kafka Detection Messages")
    print("=" * 60)
    
    try:
        consumer = KafkaConsumer(
            'detections',
            bootstrap_servers=['localhost:9092'],
            auto_offset_reset='earliest',  # Read from beginning to see existing messages
            consumer_timeout_ms=10000,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id='verification-group-temp'  # Use temporary group to read all messages
        )
        
        print("✅ Connected to Kafka")
        print("📥 Reading existing messages from detections topic...")
        print("   (Reading from earliest offset to see all messages)")
        print()
        
        message_count = 0
        for message in consumer:
            message_count += 1
            message_value = message.value
            
            print(f"📦 Message #{message_count}")
            print(f"  Key: {message.key.decode('utf-8') if message.key else 'None'}")
            print(f"  Partition: {message.partition}, Offset: {message.offset}")
            print(f"  Frame ID: {message_value.get('frame_id', 'N/A')}")
            print(f"  Sensor ID: {message_value.get('sensor_id', 'N/A')}")
            print(f"  Detections: {len(message_value.get('detections', []))}")
            print()
            
            issues, warnings = verify_detection_message(message_value)
            
            if issues:
                print("  ❌ ISSUES FOUND:")
                for issue in issues:
                    print(f"    - {issue}")
                print()
            
            if warnings:
                print("  ⚠️  WARNINGS:")
                for warning in warnings:
                    print(f"    - {warning}")
                print()
            
            if not issues and not warnings:
                print("  ✅ All fields present and valid!")
                print()
            
            # Show full detection structure
            if message_value.get('detections'):
                print("  📋 First Detection Structure:")
                first_det = message_value['detections'][0]
                print(f"    Keys: {list(first_det.keys())}")
                if 'bbox' in first_det:
                    print(f"    Bbox keys: {list(first_det['bbox'].keys()) if isinstance(first_det['bbox'], dict) else 'N/A'}")
                print()
            
            # Limit to 5 messages for readability
            if message_count >= 5:
                break
        
        if message_count == 0:
            print("⚠️  No messages found in detections topic")
            print("   This could mean:")
            print("   - AI Perception is not running")
            print("   - No videos have been processed")
            print("   - Messages are in a different format")
        else:
            print(f"✅ Verified {message_count} message(s) from detections topic")
        
        consumer.close()
        
    except KafkaError as e:
        print(f"❌ Kafka error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n✅ Verification stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

