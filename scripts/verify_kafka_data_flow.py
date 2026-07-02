#!/usr/bin/env python3
"""
Kafka Data Flow Verification Script
Checks that all data is flowing correctly through Kafka topics
"""
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Add project paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from aiokafka import AIOKafkaConsumer
    from kafka import KafkaConsumer
except ImportError:
    print("❌ aiokafka not installed. Install with: pip install aiokafka")
    sys.exit(1)

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
TOPICS = [
    "camera-frames",
    "detections",
    "license-plates",
    "emission-data",
    "trajectory-data",
    "traffic-metrics"
]

def check_topic_messages_sync(topic: str, max_messages: int = 5) -> List[Dict]:
    """Check messages in a topic synchronously"""
    try:
        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')) if m else None,
            consumer_timeout_ms=5000
        )
        
        messages = []
        for i, message in enumerate(consumer):
            if i >= max_messages:
                break
            try:
                value = message.value
                if value:
                    messages.append({
                        'offset': message.offset,
                        'partition': message.partition,
                        'timestamp': datetime.fromtimestamp(message.timestamp / 1000).isoformat() if message.timestamp else None,
                        'data': value
                    })
            except Exception as e:
                print(f"  ⚠️  Error parsing message: {e}")
        
        consumer.close()
        return messages
    except Exception as e:
        print(f"  ❌ Error reading topic {topic}: {e}")
        return []

def analyze_detection_message(data: Dict) -> Dict:
    """Analyze a detection message"""
    analysis = {
        'has_bbox': 'bbox' in data or any(k.startswith('x') or k.startswith('y') for k in data.keys()),
        'has_class': 'object_class' in data or 'class' in data,
        'has_confidence': 'confidence' in data,
        'has_track_id': 'track_id' in data,
        'has_speed': 'speed' in data,
        'has_brand': 'vehicle_brand' in data or 'brand' in data,
        'has_plate': 'license_plate' in data or 'plate_text' in data,
        'has_emission': 'emission_co2' in data or 'co2_g_km' in data,
        'has_multiview': 'multiview_confidence' in data or 'views' in data,
    }
    return analysis

def analyze_license_plate_message(data: Dict) -> Dict:
    """Analyze a license plate message"""
    analysis = {
        'has_plate_text': 'plate_text' in data and data.get('plate_text') is not None,
        'has_ocr_confidence': 'ocr_confidence' in data,
        'ocr_confidence_value': data.get('ocr_confidence', 0.0),
        'has_detection_confidence': 'detection_confidence' in data,
        'has_bbox': 'bbox' in data,
        'plate_text_value': data.get('plate_text'),
    }
    return analysis

def analyze_emission_message(data: Dict) -> Dict:
    """Analyze an emission data message"""
    analysis = {
        'has_co2': 'co2_g_km' in data,
        'has_fuel': 'fuel_l_100km' in data,
        'has_impact': 'emission_impact' in data,
        'has_vehicle_type': 'vehicle_type' in data,
        'has_speed': 'speed_kmh' in data,
    }
    return analysis

def main():
    print("=" * 70)
    print("Kafka Data Flow Verification")
    print("=" * 70)
    print()
    
    results = {}
    
    for topic in TOPICS:
        print(f"📊 Checking topic: {topic}")
        messages = check_topic_messages_sync(topic, max_messages=10)
        
        if not messages:
            print(f"  ⚠️  No messages found in {topic}")
            results[topic] = {'count': 0, 'status': 'empty'}
        else:
            print(f"  ✅ Found {len(messages)} recent messages")
            
            # Analyze first message
            if messages:
                first_msg = messages[0].get('data', {})
                
                if topic == 'detections':
                    analysis = analyze_detection_message(first_msg)
                    print(f"  📋 Detection Analysis:")
                    for key, value in analysis.items():
                        icon = "✅" if value else "❌"
                        print(f"     {icon} {key}: {value}")
                
                elif topic == 'license-plates':
                    analysis = analyze_license_plate_message(first_msg)
                    print(f"  📋 License Plate Analysis:")
                    for key, value in analysis.items():
                        if key == 'plate_text_value':
                            if value:
                                print(f"     ✅ Plate Text: '{value}'")
                            else:
                                print(f"     ❌ Plate Text: null")
                        elif key == 'ocr_confidence_value':
                            print(f"     {'✅' if value > 0 else '❌'} OCR Confidence: {value:.3f}")
                        else:
                            icon = "✅" if value else "❌"
                            print(f"     {icon} {key}: {value}")
                
                elif topic == 'emission-data':
                    analysis = analyze_emission_message(first_msg)
                    print(f"  📋 Emission Data Analysis:")
                    for key, value in analysis.items():
                        icon = "✅" if value else "❌"
                        print(f"     {icon} {key}: {value}")
                
                # Show sample data keys
                if first_msg:
                    print(f"  📝 Sample keys: {list(first_msg.keys())[:10]}")
            
            results[topic] = {'count': len(messages), 'status': 'ok'}
        
        print()
    
    # Summary
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print()
    
    for topic, result in results.items():
        status_icon = "✅" if result['count'] > 0 else "⚠️"
        print(f"{status_icon} {topic}: {result['count']} messages")
    
    print()
    
    # Check for critical issues
    critical_issues = []
    
    if results.get('detections', {}).get('count', 0) == 0:
        critical_issues.append("No detections in Kafka")
    
    if results.get('license-plates', {}).get('count', 0) == 0:
        critical_issues.append("No license plates in Kafka")
    
    # Check license plate OCR
    license_plates = check_topic_messages_sync('license-plates', max_messages=50)
    if license_plates:
        plates_with_text = sum(1 for msg in license_plates 
                             if msg.get('data', {}).get('plate_text') is not None 
                             and msg.get('data', {}).get('plate_text') not in ['', 'null', None])
        total_plates = len(license_plates)
        ocr_rate = (plates_with_text / total_plates * 100) if total_plates > 0 else 0
        
        print(f"📊 License Plate OCR Rate: {plates_with_text}/{total_plates} ({ocr_rate:.1f}%)")
        
        if ocr_rate < 50:
            critical_issues.append(f"Low OCR rate: {ocr_rate:.1f}% (expected ~68%)")
    
    if critical_issues:
        print()
        print("⚠️  Critical Issues Found:")
        for issue in critical_issues:
            print(f"   • {issue}")
    else:
        print()
        print("✅ All systems operational!")
    
    print()

if __name__ == "__main__":
    main()

