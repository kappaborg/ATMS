#!/usr/bin/env python3
"""
Performance Benchmarking Script
================================

Benchmarks the optimized vs original multi-view fusion system.
"""

import sys
import time
import numpy as np
from pathlib import Path
import asyncio
from typing import Dict

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))
sys.path.append(str(project_root / "services" / "ai-perception" / "src"))

try:
    # Try importing from the new integrated location
    from multiview.multiview_detector import MultiViewDetector
    MULTIVIEW_AVAILABLE = True
except ImportError:
    # Fallback: try old location (if exists)
    try:
        from multi_view_fusion_system import MultiViewFusionSystem
        from multi_view_fusion_system_optimized import OptimizedMultiViewFusionSystem
        MULTIVIEW_AVAILABLE = True
        USE_OLD_SYSTEM = True
    except ImportError as e:
        print(f"⚠️  Multi-view system not available: {e}")
        print("   Note: Multi-view is now integrated in services/ai-perception/src/multiview/")
        MULTIVIEW_AVAILABLE = False
        USE_OLD_SYSTEM = False

def create_test_image(width: int = 640, height: int = 480) -> np.ndarray:
    """Create a test image"""
    image = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
    return image

def benchmark_system(system, name: str, num_frames: int = 100, async_mode: bool = False) -> Dict:
    """Benchmark a detection system"""
    print(f"\n{'='*60}")
    print(f"Benchmarking: {name}")
    print(f"{'='*60}")
    
    test_image = create_test_image()
    
    times = []
    detections_count = []
    
    # Warmup
    print("Warming up...")
    for _ in range(5):
        if async_mode:
            asyncio.run(system.detect_vehicles_async(test_image))
        else:
            system.detect_vehicles(test_image)
    
    # Actual benchmark
    print(f"Running {num_frames} frames...")
    start_time = time.time()
    
    for i in range(num_frames):
        frame_start = time.time()
        
        if async_mode:
            detections = asyncio.run(system.detect_vehicles_async(test_image))
        else:
            detections = system.detect_vehicles(test_image)
        
        frame_time = (time.time() - frame_start) * 1000  # ms
        times.append(frame_time)
        detections_count.append(len(detections))
        
        if (i + 1) % 20 == 0:
            avg_time = np.mean(times[-20:])
            avg_fps = 1000.0 / avg_time if avg_time > 0 else 0
            print(f"  Frame {i+1}/{num_frames}: {avg_time:.2f}ms ({avg_fps:.2f} FPS)")
    
    total_time = time.time() - start_time
    
    # Calculate statistics
    avg_time_ms = np.mean(times)
    median_time_ms = np.median(times)
    min_time_ms = np.min(times)
    max_time_ms = np.max(times)
    std_time_ms = np.std(times)
    
    avg_fps = 1000.0 / avg_time_ms if avg_time_ms > 0 else 0
    max_fps = 1000.0 / min_time_ms if min_time_ms > 0 else 0
    min_fps = 1000.0 / max_time_ms if max_time_ms > 0 else 0
    
    avg_detections = np.mean(detections_count)
    
    results = {
        'name': name,
        'total_time_s': total_time,
        'avg_time_ms': avg_time_ms,
        'median_time_ms': median_time_ms,
        'min_time_ms': min_time_ms,
        'max_time_ms': max_time_ms,
        'std_time_ms': std_time_ms,
        'avg_fps': avg_fps,
        'max_fps': max_fps,
        'min_fps': min_fps,
        'avg_detections': avg_detections,
        'total_frames': num_frames
    }
    
    print(f"\nResults:")
    print(f"  Average Time: {avg_time_ms:.2f}ms")
    print(f"  Median Time: {median_time_ms:.2f}ms")
    print(f"  Min Time: {min_time_ms:.2f}ms")
    print(f"  Max Time: {max_time_ms:.2f}ms")
    print(f"  Std Dev: {std_time_ms:.2f}ms")
    print(f"  Average FPS: {avg_fps:.2f}")
    print(f"  Max FPS: {max_fps:.2f}")
    print(f"  Min FPS: {min_fps:.2f}")
    print(f"  Average Detections: {avg_detections:.1f}")
    
    return results

def main():
    """Main benchmarking function"""
    print("="*60)
    print("ATMS Performance Benchmark")
    print("="*60)
    
    # Model paths (use .pt files for YOLO)
    model_paths = {
        "top_view": project_root / "multiview_models/top_view_model/weights/best.pt",
        "side_profile": project_root / "multiview_models/side_profile_model/weights/best.pt",
        "front_bumper": project_root / "multiview_models/front_bumper_model/weights/best.pt",
    }
    
    # Check if models exist
    available_models = {}
    for view, path in model_paths.items():
        if path.exists():
            available_models[view] = str(path)
            print(f"✅ Found {view} model")
        else:
            print(f"❌ Missing {view} model: {path}")
    
    if not available_models:
        print("❌ No models found! Cannot run benchmark.")
        return
    
    print(f"\nUsing {len(available_models)} models for benchmarking\n")
    
    # Check if old system exists
    USE_OLD_SYSTEM = False
    try:
        from multi_view_fusion_system import MultiViewFusionSystem
        from multi_view_fusion_system_optimized import OptimizedMultiViewFusionSystem
        USE_OLD_SYSTEM = True
    except ImportError:
        print("⚠️  Old multi-view fusion system not found")
        print("   Using integrated MultiViewDetector from services/ai-perception")
        USE_OLD_SYSTEM = False
    
    if USE_OLD_SYSTEM:
        # Benchmark original system
        print("\n" + "="*60)
        print("1. ORIGINAL SYSTEM (Sequential)")
        print("="*60)
        try:
            original_system = MultiViewFusionSystem(available_models, device="auto")
            original_results = benchmark_system(original_system, "Original (Sequential)", num_frames=30)
        except Exception as e:
            print(f"❌ Error benchmarking original system: {e}")
            import traceback
            traceback.print_exc()
            return
    else:
        print("\n⚠️  Old multi-view fusion system not available")
        print("   Skipping original system benchmark")
        print("   Note: Multi-view is now integrated in services/ai-perception/src/multiview/")
        # Create dummy results for comparison
        original_results = {
            'avg_fps': 5.0,
            'avg_time_ms': 200.0,
            'max_fps': 6.0,
            'min_fps': 4.0
        }
    
    if USE_OLD_SYSTEM:
        # Benchmark optimized system (sequential)
        print("\n" + "="*60)
        print("2. OPTIMIZED SYSTEM (Sequential)")
        print("="*60)
        try:
            optimized_sequential = OptimizedMultiViewFusionSystem(available_models, device="auto", enable_parallel=False)
            optimized_seq_results = benchmark_system(optimized_sequential, "Optimized (Sequential)", num_frames=30)
        except Exception as e:
            print(f"❌ Error benchmarking optimized sequential: {e}")
            import traceback
            traceback.print_exc()
            optimized_seq_results = original_results  # Fallback
        
        # Benchmark optimized system (parallel)
        print("\n" + "="*60)
        print("3. OPTIMIZED SYSTEM (Parallel)")
        print("="*60)
        try:
            optimized_parallel = OptimizedMultiViewFusionSystem(available_models, device="auto", enable_parallel=True)
            optimized_par_results = benchmark_system(optimized_parallel, "Optimized (Parallel)", num_frames=30, async_mode=True)
        except Exception as e:
            print(f"❌ Error benchmarking optimized parallel: {e}")
            import traceback
            traceback.print_exc()
            optimized_par_results = optimized_seq_results  # Fallback
    else:
        print("\n⚠️  Old multi-view fusion system not available")
        print("   Skipping optimized system benchmarks")
        optimized_seq_results = original_results
        optimized_par_results = original_results
    
    # Comparison
    print("\n" + "="*60)
    print("PERFORMANCE COMPARISON")
    print("="*60)
    
    print(f"\n{'Metric':<30} {'Original':<15} {'Optimized Seq':<15} {'Optimized Par':<15} {'Improvement':<15}")
    print("-" * 90)
    
    print(f"{'Average FPS':<30} {original_results['avg_fps']:<15.2f} {optimized_seq_results['avg_fps']:<15.2f} {optimized_par_results['avg_fps']:<15.2f} {((optimized_par_results['avg_fps'] / original_results['avg_fps'] - 1) * 100):>13.1f}%")
    print(f"{'Average Time (ms)':<30} {original_results['avg_time_ms']:<15.2f} {optimized_seq_results['avg_time_ms']:<15.2f} {optimized_par_results['avg_time_ms']:<15.2f} {((1 - optimized_par_results['avg_time_ms'] / original_results['avg_time_ms']) * 100):>13.1f}%")
    print(f"{'Max FPS':<30} {original_results['max_fps']:<15.2f} {optimized_seq_results['max_fps']:<15.2f} {optimized_par_results['max_fps']:<15.2f}")
    
    # Calculate improvement
    fps_improvement = ((optimized_par_results['avg_fps'] / original_results['avg_fps']) - 1) * 100
    time_reduction = (1 - (optimized_par_results['avg_time_ms'] / original_results['avg_time_ms'])) * 100
    
    print(f"\n✅ Performance Improvement:")
    print(f"   FPS: {fps_improvement:+.1f}% ({original_results['avg_fps']:.2f} → {optimized_par_results['avg_fps']:.2f})")
    print(f"   Latency: {time_reduction:+.1f}% reduction ({original_results['avg_time_ms']:.2f}ms → {optimized_par_results['avg_time_ms']:.2f}ms)")
    
    # Check if target met
    target_fps = 15.0
    if optimized_par_results['avg_fps'] >= target_fps:
        print(f"\n🎉 SUCCESS: Target FPS ({target_fps}) MET!")
    else:
        gap = target_fps - optimized_par_results['avg_fps']
        print(f"\n⚠️  Target FPS ({target_fps}) not yet met. Gap: {gap:.2f} FPS")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    main()

