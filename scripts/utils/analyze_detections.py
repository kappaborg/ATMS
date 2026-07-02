#!/usr/bin/env python3
"""
Detection Data Analysis Tool
Analyzes saved detection data and generates statistics
"""

import json
import sys
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
from typing import List, Dict
import statistics


def load_detections(jsonl_file: Path) -> List[Dict]:
    """Load detections from JSONL file"""
    detections = []
    
    with open(jsonl_file, 'r') as f:
        for line in f:
            try:
                detection = json.loads(line.strip())
                detections.append(detection)
            except json.JSONDecodeError as e:
                print(f"⚠️  Skipping invalid line: {e}")
                continue
    
    return detections


def analyze_detections(detections: List[Dict]):
    """Analyze detection data and print statistics"""
    
    if not detections:
        print("❌ No detections found!")
        return
    
    # Extract data
    total_frames = len(detections)
    all_objects = []
    objects_by_class = defaultdict(list)
    confidences = []
    processing_times = []
    timestamps = []
    
    for det_msg in detections:
        dets = det_msg.get('detections', [])
        all_objects.extend(dets)
        
        for det in dets:
            obj_class = det.get('object_class', 'unknown')
            confidence = det.get('confidence', 0)
            
            objects_by_class[obj_class].append(det)
            confidences.append(confidence)
        
        processing_time = det_msg.get('processing_time_ms', 0)
        processing_times.append(processing_time)
        
        try:
            ts = datetime.fromisoformat(det_msg.get('timestamp', ''))
            timestamps.append(ts)
        except:
            pass
    
    total_objects = len(all_objects)
    
    # Calculate time range
    if timestamps:
        start_time = min(timestamps)
        end_time = max(timestamps)
        duration = (end_time - start_time).total_seconds()
    else:
        duration = 0
    
    # Calculate FPS
    avg_fps = total_frames / max(duration, 1)
    
    # Calculate averages
    avg_confidence = statistics.mean(confidences) if confidences else 0
    avg_processing_time = statistics.mean(processing_times) if processing_times else 0
    
    avg_objects_per_frame = total_objects / max(total_frames, 1)
    
    # Print report
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║                                                                       ║")
    print("║     📊 DETECTION DATA ANALYSIS REPORT                                ║")
    print("║                                                                       ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print()
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("⏱️  COLLECTION SUMMARY")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    if timestamps:
        print(f"  Start Time:             {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  End Time:               {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        hours = int(duration // 3600)
        minutes = int((duration % 3600) // 60)
        seconds = int(duration % 60)
        print(f"  Duration:               {hours:02d}:{minutes:02d}:{seconds:02d} ({duration:.0f}s)")
    
    print()
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("📹 FRAME STATISTICS")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  Total Frames:           {total_frames:,}")
    print(f"  Average FPS:            {avg_fps:.2f}")
    print(f"  Avg Processing Time:    {avg_processing_time:.2f} ms")
    print()
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🚗 DETECTION STATISTICS")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  Total Objects:          {total_objects:,}")
    print(f"  Objects/Frame:          {avg_objects_per_frame:.2f}")
    print(f"  Average Confidence:     {avg_confidence:.1%}")
    print()
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("📊 DETECTIONS BY CLASS")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # Sort by count
    sorted_classes = sorted(
        objects_by_class.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )
    
    print(f"  {'Class':<15s} │ {'Count':>8s} │ {'%':>6s} │ {'Avg Conf':>9s} │ Bar")
    print(f"  {'─'*15}─┼─{'─'*8}─┼─{'─'*6}─┼─{'─'*9}─┼─{'─'*30}")
    
    for obj_class, objects in sorted_classes:
        count = len(objects)
        percentage = (count / max(total_objects, 1)) * 100
        avg_conf = statistics.mean([o['confidence'] for o in objects])
        
        bar_length = int((count / max(total_objects, 1)) * 30)
        bar = "█" * bar_length
        
        print(f"  {obj_class:<15s} │ {count:8,d} │ {percentage:5.1f}% │ {avg_conf:8.1%} │ {bar}")
    
    print()
    
    # Confidence distribution
    if confidences:
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("🎯 CONFIDENCE DISTRIBUTION")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        ranges = [
            ("0-25%", 0.0, 0.25),
            ("25-50%", 0.25, 0.50),
            ("50-75%", 0.50, 0.75),
            ("75-90%", 0.75, 0.90),
            ("90-100%", 0.90, 1.0)
        ]
        
        for label, low, high in ranges:
            count = sum(1 for c in confidences if low <= c < high)
            percentage = (count / len(confidences)) * 100
            bar_length = int(percentage / 2)
            bar = "█" * bar_length
            print(f"  {label:<10s} │ {count:6,d} │ {percentage:5.1f}% │ {bar}")
        
        print()
        print(f"  Minimum:  {min(confidences):.1%}")
        print(f"  Maximum:  {max(confidences):.1%}")
        print(f"  Median:   {statistics.median(confidences):.1%}")
        print(f"  StdDev:   {statistics.stdev(confidences) if len(confidences) > 1 else 0:.1%}")
        print()
    
    # Traffic insights
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🚦 TRAFFIC INSIGHTS")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # Vehicles
    vehicle_classes = ['car', 'truck', 'bus', 'motorcycle']
    total_vehicles = sum(len(objects_by_class[c]) for c in vehicle_classes)
    
    # Pedestrians
    total_pedestrians = len(objects_by_class['pedestrian'])
    
    # Bicycles
    total_bicycles = len(objects_by_class['bicycle'])
    
    print(f"  Total Vehicles:         {total_vehicles:,}")
    print(f"  Total Pedestrians:      {total_pedestrians:,}")
    print(f"  Total Bicycles:         {total_bicycles:,}")
    
    if duration > 0:
        vehicles_per_minute = (total_vehicles / duration) * 60
        pedestrians_per_minute = (total_pedestrians / duration) * 60
        print(f"  Vehicles/Minute:        {vehicles_per_minute:.2f}")
        print(f"  Pedestrians/Minute:     {pedestrians_per_minute:.2f}")
    
    print()
    
    # Recommendations
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("💡 RECOMMENDATIONS")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    if avg_fps < 15:
        print("  ⚠️  FPS is below 15 - consider model optimization (TensorRT, FP16)")
    else:
        print("  ✅ FPS is good!")
    
    if avg_confidence < 0.5:
        print("  ⚠️  Average confidence is low - check camera positioning/quality")
    elif avg_confidence < 0.7:
        print("  ⚡ Average confidence is moderate - room for improvement")
    else:
        print("  ✅ Average confidence is excellent!")
    
    if total_objects < 100:
        print("  ⚠️  Low detection count - ensure camera has good traffic view")
    else:
        print("  ✅ Good detection count!")
    
    print()


def main():
    """Main entry point"""
    
    if len(sys.argv) < 2:
        print("Usage: python analyze_detections.py <detections_file.jsonl>")
        print()
        print("Example:")
        print("  python analyze_detections.py data/detections/detections_20231002_143000.jsonl")
        sys.exit(1)
    
    jsonl_file = Path(sys.argv[1])
    
    if not jsonl_file.exists():
        print(f"❌ File not found: {jsonl_file}")
        sys.exit(1)
    
    print(f"📂 Loading detections from: {jsonl_file}")
    print()
    
    detections = load_detections(jsonl_file)
    
    print(f"✅ Loaded {len(detections):,} detection frames")
    print()
    
    analyze_detections(detections)


if __name__ == "__main__":
    main()


