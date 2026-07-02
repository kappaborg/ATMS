#!/usr/bin/env python3
"""
Detection Data Saver
Continuously saves all detections to JSONL file for analysis
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path
import asyncio

try:
    from aiokafka import AIOKafkaConsumer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    print("⚠️  aiokafka not available. Install with: pip install aiokafka")
    sys.exit(1)


async def save_detections_to_file(output_dir: str = "data/detections"):
    """
    Save all detections from Kafka to JSONL file
    
    Args:
        output_dir: Directory to save detection files
    """
    
    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Create timestamped filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_path / f"detections_{timestamp}.jsonl"
    
    print(f"📁 Saving detections to: {output_file}")
    print(f"🔄 Connecting to Kafka...")
    
    # Create Kafka consumer
    consumer = AIOKafkaConsumer(
        'detections',
        bootstrap_servers='localhost:9092',
        group_id='detection-saver',
        auto_offset_reset='latest',  # Only save new detections
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )
    
    saved_count = 0
    error_count = 0
    
    try:
        await consumer.start()
        print(f"✅ Connected! Saving to {output_file}")
        print(f"💡 Press Ctrl+C to stop")
        print()
        
        with open(output_file, 'a') as f:
            async for msg in consumer:
                try:
                    detection_msg = msg.value
                    
                    # Write to file (JSONL format - one JSON per line)
                    f.write(json.dumps(detection_msg) + '\n')
                    f.flush()  # Ensure data is written immediately
                    
                    saved_count += 1
                    
                    # Progress indicator
                    if saved_count % 10 == 0:
                        num_detections = len(detection_msg.get('detections', []))
                        timestamp = detection_msg.get('timestamp', 'N/A')
                        print(f"💾 Saved: {saved_count:,} frames | Latest: {num_detections} objects @ {timestamp}")
                    
                except Exception as e:
                    error_count += 1
                    print(f"❌ Error saving detection: {e}")
                    
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping data saver...")
        
    finally:
        await consumer.stop()
        
        # Final summary
        print()
        print("╔══════════════════════════════════════════════════════════════════════╗")
        print("║                                                                       ║")
        print("║     💾 DATA SAVE SUMMARY                                             ║")
        print("║                                                                       ║")
        print("╚══════════════════════════════════════════════════════════════════════╝")
        print()
        print(f"  File:           {output_file}")
        print(f"  Frames Saved:   {saved_count:,}")
        print(f"  Errors:         {error_count}")
        
        # File size
        if output_file.exists():
            file_size = output_file.stat().st_size
            if file_size > 1024 * 1024:
                size_str = f"{file_size / (1024 * 1024):.1f} MB"
            else:
                size_str = f"{file_size / 1024:.1f} KB"
            print(f"  File Size:      {size_str}")
        
        print()
        print(f"  ✅ Data saved successfully!")
        print()


def main():
    """Main entry point"""
    
    if not KAFKA_AVAILABLE:
        print("❌ aiokafka is not installed")
        print("   Install with: pip install aiokafka")
        sys.exit(1)
    
    # Get output directory from args or use default
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "/Users/kappasutra/Traffic/data/detections"
    
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║                                                                       ║")
    print("║     💾 DETECTION DATA SAVER                                          ║")
    print("║                                                                       ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print()
    
    try:
        asyncio.run(save_detections_to_file(output_dir))
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


