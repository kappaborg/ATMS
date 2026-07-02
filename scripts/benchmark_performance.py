#!/usr/bin/env python3
"""
Performance Benchmark Script
Week 11: Performance Optimization

Benchmarks detection performance with and without optimizations
"""

import sys
import asyncio
import numpy as np
from pathlib import Path
import time
import json

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "services" / "ai-perception" / "src"))

from optimization.benchmark_suite import BenchmarkSuite
from detection.yolo_detector import YOLODetector
from config import model_config, perception_config


async def generate_test_images(num_images: int = 50) -> list:
    """Generate test images"""
    print(f"Generating {num_images} test images...")
    images = []
    for i in range(num_images):
        # Generate random image (simulating camera frames)
        img = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
        images.append(img)
    return images


async def benchmark_detector(detector: YOLODetector, test_images: list, name: str):
    """Benchmark a detector"""
    print(f"\n{'='*60}")
    print(f"Benchmarking: {name}")
    print(f"{'='*60}")
    
    latencies = []
    total_detections = 0
    num_iterations = min(50, len(test_images))
    warmup_iterations = 5
    
    # Warmup phase
    print(f"Running {warmup_iterations} warmup iterations...")
    for i in range(warmup_iterations):
        img = test_images[i % len(test_images)]
        frame_id = f"warmup_{i}"
        await detector.detect(img, frame_id, "benchmark")
    
    print("Warmup complete. Starting benchmark...")
    
    # Benchmark phase
    start_time = time.time()
    for i in range(num_iterations):
        img = test_images[i % len(test_images)]
        frame_id = f"bench_{i}"
        
        iteration_start = time.time()
        detections, metrics = await detector.detect(img, frame_id, "benchmark")
        iteration_end = time.time()
        
        latency_ms = (iteration_end - iteration_start) * 1000
        latencies.append(latency_ms)
        total_detections += len(detections)
        
        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{num_iterations} frames...")
    
    end_time = time.time()
    total_time = end_time - start_time
    
    # Calculate statistics
    avg_latency = np.mean(latencies) if latencies else 0
    min_latency = np.min(latencies) if latencies else 0
    max_latency = np.max(latencies) if latencies else 0
    p95_latency = np.percentile(latencies, 95) if latencies else 0
    fps = num_iterations / total_time if total_time > 0 else 0
    
    results = {
        'test_name': name,
        'num_iterations': num_iterations,
        'total_time_s': round(total_time, 2),
        'fps': round(fps, 2),
        'avg_inference_time_ms': round(avg_latency, 2),
        'min_latency_ms': round(min_latency, 2),
        'max_latency_ms': round(max_latency, 2),
        'p95_latency_ms': round(p95_latency, 2),
        'total_detections': total_detections,
        'avg_detections_per_frame': round(total_detections / num_iterations, 2) if num_iterations > 0 else 0
    }
    
    return results


async def main():
    """Main benchmark function"""
    print("="*60)
    print("Performance Benchmark Suite")
    print("Week 11: Performance Optimization")
    print("="*60)
    
    # Generate test images
    test_images = await generate_test_images(50)
    
    # Initialize detectors
    print("\nInitializing detectors...")
    
    # Standard detector (without optimizations)
    print("\nInitializing standard detector (no optimizations)...")
    standard_detector = YOLODetector(
        model_path=model_config.MODEL_PATH,
        device=model_config.DEVICE,
        confidence_threshold=model_config.CONFIDENCE_THRESHOLD,
        iou_threshold=model_config.IOU_THRESHOLD,
        input_size=model_config.INPUT_SIZE,
        half_precision=model_config.HALF_PRECISION,
        enable_memory_pool=False,
        enable_caching=False,
        enable_profiling=False
    )
    
    if not standard_detector.load_model():
        print("ERROR: Failed to load standard detector")
        return
    
    print("✅ Standard detector loaded")
    
    # Optimized detector (with all optimizations)
    print("\nInitializing optimized detector (with all optimizations)...")
    optimized_detector = YOLODetector(
        model_path=model_config.MODEL_PATH,
        device=model_config.DEVICE,
        confidence_threshold=model_config.CONFIDENCE_THRESHOLD,
        iou_threshold=model_config.IOU_THRESHOLD,
        input_size=model_config.INPUT_SIZE,
        half_precision=model_config.HALF_PRECISION,
        enable_memory_pool=True,
        enable_caching=True,
        enable_profiling=True
    )
    
    if not optimized_detector.load_model():
        print("ERROR: Failed to load optimized detector")
        return
    
    print("✅ Optimized detector loaded")
    
    # Run benchmarks
    print("\nRunning benchmarks...")
    
    standard_results = await benchmark_detector(standard_detector, test_images, "Standard Detector")
    optimized_results = await benchmark_detector(optimized_detector, test_images, "Optimized Detector")
    
    # Compare results
    print("\n" + "="*60)
    print("Comparison Results")
    print("="*60)
    
    if standard_results and optimized_results:
        speedup = standard_results.get('avg_inference_time_ms', 0) / optimized_results.get('avg_inference_time_ms', 1)
        fps_improvement = optimized_results.get('fps', 0) / standard_results.get('fps', 1) if standard_results.get('fps', 0) > 0 else 0
        
        print(f"\nStandard Detector:")
        print(f"  FPS: {standard_results.get('fps', 0):.2f}")
        print(f"  Avg Latency: {standard_results.get('avg_inference_time_ms', 0):.2f}ms")
        print(f"  P95 Latency: {standard_results.get('p95_latency_ms', 0):.2f}ms")
        
        print(f"\nOptimized Detector:")
        print(f"  FPS: {optimized_results.get('fps', 0):.2f}")
        print(f"  Avg Latency: {optimized_results.get('avg_inference_time_ms', 0):.2f}ms")
        print(f"  P95 Latency: {optimized_results.get('p95_latency_ms', 0):.2f}ms")
        
        print(f"\nImprovement:")
        print(f"  Speedup: {speedup:.2f}x")
        print(f"  FPS Improvement: {fps_improvement:.2f}x")
        
        # Save results
        results = {
            'standard': standard_results,
            'optimized': optimized_results,
            'improvement': {
                'speedup': speedup,
                'fps_improvement': fps_improvement
            }
        }
        
        output_file = project_root / "benchmark_results.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"\nResults saved to: {output_file}")
    
    # Get detector stats
    print("\n" + "="*60)
    print("Detector Statistics")
    print("="*60)
    
    standard_stats = standard_detector.get_stats()
    optimized_stats = optimized_detector.get_stats()
    
    print(f"\nStandard Detector Stats:")
    for key, value in standard_stats.items():
        if key not in ['memory_pool', 'cache', 'fps_monitor', 'profiler']:
            print(f"  {key}: {value}")
    
    print(f"\nOptimized Detector Stats:")
    for key, value in optimized_stats.items():
        print(f"  {key}: {value}")
    
    print("\n" + "="*60)
    print("Benchmark Complete!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())

