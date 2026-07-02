#!/usr/bin/env python3
"""
Real-time Detection Monitoring Dashboard
Displays live statistics during data collection
"""

import json
import sys
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, List
import asyncio

try:
    from aiokafka import AIOKafkaConsumer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    print("⚠️  aiokafka not available. Install with: pip install aiokafka")
    sys.exit(1)


class DetectionMonitor:
    """Real-time detection monitoring"""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.total_frames = 0
        self.total_detections = 0
        self.detections_by_class: Dict[str, int] = defaultdict(int)
        self.fps_history: deque = deque(maxlen=30)
        self.last_frame_time = None
        self.errors = 0
        self.last_update = datetime.now()
        
    def update_from_detection(self, detection_msg: dict):
        """Update stats from a detection message"""
        self.total_frames += 1
        
        # Update detection counts
        detections = detection_msg.get('detections', [])
        self.total_detections += len(detections)
        
        # Count by class
        for det in detections:
            obj_class = det.get('object_class', 'unknown')
            self.detections_by_class[obj_class] += 1
        
        # Calculate FPS
        now = datetime.now()
        if self.last_frame_time:
            time_diff = (now - self.last_frame_time).total_seconds()
            if time_diff > 0:
                fps = 1.0 / time_diff
                self.fps_history.append(fps)
        
        self.last_frame_time = now
        self.last_update = now
    
    def get_avg_fps(self) -> float:
        """Get average FPS"""
        if not self.fps_history:
            return 0.0
        return sum(self.fps_history) / len(self.fps_history)
    
    def get_runtime(self) -> str:
        """Get formatted runtime"""
        elapsed = datetime.now() - self.start_time
        hours = int(elapsed.total_seconds() // 3600)
        minutes = int((elapsed.total_seconds() % 3600) // 60)
        seconds = int(elapsed.total_seconds() % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def display_dashboard(self):
        """Display the monitoring dashboard"""
        # Clear screen
        print("\033[2J\033[H", end="")
        
        runtime = self.get_runtime()
        avg_fps = self.get_avg_fps()
        detections_per_frame = self.total_detections / max(self.total_frames, 1)
        
        print("╔══════════════════════════════════════════════════════════════════════╗")
        print("║                                                                       ║")
        print("║     📊 REAL-TIME DETECTION MONITORING DASHBOARD                      ║")
        print("║                                                                       ║")
        print("╚══════════════════════════════════════════════════════════════════════╝")
        print()
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("⏱️  RUNTIME & PERFORMANCE")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  Runtime:                {runtime}")
        print(f"  Last Update:            {self.last_update.strftime('%H:%M:%S')}")
        print(f"  Average FPS:            {avg_fps:.1f}")
        print(f"  Errors:                 {self.errors}")
        print()
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("📹 FRAME STATISTICS")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  Total Frames:           {self.total_frames:,}")
        print(f"  Total Detections:       {self.total_detections:,}")
        print(f"  Detections/Frame:       {detections_per_frame:.2f}")
        print()
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("🚗 DETECTIONS BY CLASS")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        if self.detections_by_class:
            # Sort by count (descending)
            sorted_classes = sorted(
                self.detections_by_class.items(),
                key=lambda x: x[1],
                reverse=True
            )
            
            for obj_class, count in sorted_classes:
                percentage = (count / max(self.total_detections, 1)) * 100
                bar_length = int(percentage / 2)  # Scale to fit screen
                bar = "█" * bar_length
                print(f"  {obj_class:15s} │ {count:6,d} │ {percentage:5.1f}% │ {bar}")
        else:
            print("  No detections yet...")
        
        print()
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("💡 TIPS")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("  • Dashboard updates every second")
        print("  • Press Ctrl+C to stop monitoring")
        print("  • Kafka UI: http://localhost:8080")
        print("  • Target: 2 hours = 7,200 seconds")
        
        elapsed_seconds = (datetime.now() - self.start_time).total_seconds()
        progress = (elapsed_seconds / 7200) * 100
        print(f"  • Progress: {progress:.1f}% of 2-hour target")
        print()


async def monitor_kafka_detections():
    """Monitor Kafka detections topic in real-time"""
    
    monitor = DetectionMonitor()
    
    # Create Kafka consumer
    consumer = AIOKafkaConsumer(
        'detections',
        bootstrap_servers='localhost:9092',
        group_id='monitoring-dashboard',
        auto_offset_reset='latest',  # Only show new messages
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )
    
    try:
        # Start consumer
        await consumer.start()
        print("🔄 Connecting to Kafka...")
        print("📊 Starting monitoring dashboard...")
        time.sleep(2)
        
        # Display initial dashboard
        monitor.display_dashboard()
        
        # Consume messages
        last_display_time = time.time()
        
        async for msg in consumer:
            try:
                detection_msg = msg.value
                monitor.update_from_detection(detection_msg)
                
                # Update display every second
                current_time = time.time()
                if current_time - last_display_time >= 1.0:
                    monitor.display_dashboard()
                    last_display_time = current_time
                    
            except Exception as e:
                monitor.errors += 1
                print(f"❌ Error processing message: {e}")
                
    except KeyboardInterrupt:
        print("\n\n🛑 Monitoring stopped by user")
        
    finally:
        await consumer.stop()
        
        # Final summary
        print("\n")
        print("╔══════════════════════════════════════════════════════════════════════╗")
        print("║                                                                       ║")
        print("║     📊 FINAL SUMMARY                                                 ║")
        print("║                                                                       ║")
        print("╚══════════════════════════════════════════════════════════════════════╝")
        print()
        print(f"  Total Runtime:          {monitor.get_runtime()}")
        print(f"  Total Frames:           {monitor.total_frames:,}")
        print(f"  Total Detections:       {monitor.total_detections:,}")
        print(f"  Average FPS:            {monitor.get_avg_fps():.1f}")
        print(f"  Detections/Frame:       {monitor.total_detections / max(monitor.total_frames, 1):.2f}")
        print()
        print("  Object Breakdown:")
        for obj_class, count in sorted(monitor.detections_by_class.items(), key=lambda x: x[1], reverse=True):
            print(f"    • {obj_class:15s}: {count:6,d}")
        print()


def main():
    """Main entry point"""
    
    if not KAFKA_AVAILABLE:
        print("❌ aiokafka is not installed")
        print("   Install with: pip install aiokafka")
        sys.exit(1)
    
    print("Starting Real-Time Detection Monitor...")
    print("This will display live statistics from the detections topic")
    print()
    
    try:
        asyncio.run(monitor_kafka_detections())
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()


