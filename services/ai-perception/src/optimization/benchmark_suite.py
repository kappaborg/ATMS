"""
Performance Benchmark Suite
Week 11: Performance Optimization

Comprehensive benchmarking for:
- FPS (frames per second)
- Latency (processing time)
- Throughput (frames processed per second)
- Memory usage
- Model inference time
"""

import time
import statistics
import logging
from typing import List, Dict, Optional, Callable
import numpy as np
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import psutil
    import os
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class BenchmarkSuite:
    """
    Comprehensive performance benchmark suite
    """
    
    def __init__(self):
        """Initialize benchmark suite"""
        self.results: Dict[str, List[float]] = {}
        self.metadata: Dict[str, any] = {}
    
    def benchmark_detection(
        self,
        detector_func: Callable,
        test_images: List[np.ndarray],
        num_iterations: int = 100,
        warmup_iterations: int = 10
    ) -> Dict[str, float]:
        """
        Benchmark object detection performance
        
        Args:
            detector_func: Function that takes image and returns detections
            test_images: List of test images
            num_iterations: Number of benchmark iterations
            warmup_iterations: Number of warmup iterations
            
        Returns:
            Benchmark results dictionary
        """
        logger.info(f"Starting detection benchmark: {num_iterations} iterations")
        
        # Warmup
        logger.info(f"Warmup: {warmup_iterations} iterations")
        for _ in range(warmup_iterations):
            img = test_images[0] if test_images else np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
            try:
                detector_func(img)
            except Exception as e:
                logger.warning(f"Warmup error: {e}")
        
        # Benchmark
        inference_times = []
        total_times = []
        
        process = None
        if PSUTIL_AVAILABLE:
            process = psutil.Process(os.getpid())
            initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        for i in range(num_iterations):
            img = test_images[i % len(test_images)] if test_images else np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
            
            start_time = time.perf_counter()
            try:
                detections = detector_func(img)
                inference_time = time.perf_counter() - start_time
                inference_times.append(inference_time)
                total_times.append(inference_time)
            except Exception as e:
                logger.error(f"Benchmark iteration {i} failed: {e}")
                continue
            
            if (i + 1) % 10 == 0:
                logger.info(f"Completed {i + 1}/{num_iterations} iterations")
        
        # Calculate statistics
        if not inference_times:
            logger.error("No successful benchmark iterations")
            return {}
        
        results = {
            'num_iterations': num_iterations,
            'successful_iterations': len(inference_times),
            'avg_inference_time_ms': statistics.mean(inference_times) * 1000,
            'min_inference_time_ms': min(inference_times) * 1000,
            'max_inference_time_ms': max(inference_times) * 1000,
            'median_inference_time_ms': statistics.median(inference_times) * 1000,
            'std_inference_time_ms': statistics.stdev(inference_times) * 1000 if len(inference_times) > 1 else 0,
            'fps': 1.0 / statistics.mean(inference_times),
            'p50_latency_ms': np.percentile([t * 1000 for t in inference_times], 50),
            'p95_latency_ms': np.percentile([t * 1000 for t in inference_times], 95),
            'p99_latency_ms': np.percentile([t * 1000 for t in inference_times], 99),
        }
        
        # Memory usage
        if PSUTIL_AVAILABLE and process:
            final_memory = process.memory_info().rss / 1024 / 1024  # MB
            results['memory_usage_mb'] = final_memory - initial_memory
            results['peak_memory_mb'] = final_memory
        
        logger.info(f"Benchmark complete: {results['fps']:.2f} FPS, {results['avg_inference_time_ms']:.2f}ms avg")
        
        return results
    
    def benchmark_throughput(
        self,
        processor_func: Callable,
        test_images: List[np.ndarray],
        duration_seconds: int = 30
    ) -> Dict[str, float]:
        """
        Benchmark throughput (frames processed per second)
        
        Args:
            processor_func: Function that processes images
            test_images: List of test images
            duration_seconds: Benchmark duration
            
        Returns:
            Throughput results
        """
        logger.info(f"Starting throughput benchmark: {duration_seconds}s")
        
        frames_processed = 0
        start_time = time.time()
        end_time = start_time + duration_seconds
        
        while time.time() < end_time:
            img = test_images[frames_processed % len(test_images)] if test_images else np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
            
            try:
                processor_func(img)
                frames_processed += 1
            except Exception as e:
                logger.error(f"Throughput benchmark error: {e}")
                break
        
        elapsed = time.time() - start_time
        throughput = frames_processed / elapsed if elapsed > 0 else 0
        
        results = {
            'duration_seconds': elapsed,
            'frames_processed': frames_processed,
            'throughput_fps': throughput,
            'avg_time_per_frame_ms': (elapsed / frames_processed * 1000) if frames_processed > 0 else 0
        }
        
        logger.info(f"Throughput benchmark complete: {throughput:.2f} FPS")
        
        return results
    
    def compare_models(
        self,
        models: Dict[str, Callable],
        test_images: List[np.ndarray],
        num_iterations: int = 50
    ) -> Dict[str, Dict]:
        """
        Compare multiple models
        
        Args:
            models: Dictionary of model_name -> detector_function
            test_images: List of test images
            num_iterations: Number of iterations per model
            
        Returns:
            Comparison results
        """
        logger.info(f"Starting model comparison: {len(models)} models")
        
        comparison = {}
        
        for model_name, detector_func in models.items():
            logger.info(f"Benchmarking {model_name}...")
            results = self.benchmark_detection(
                detector_func,
                test_images,
                num_iterations=num_iterations
            )
            comparison[model_name] = results
        
        # Find best model
        if comparison:
            best_model = max(comparison.items(), key=lambda x: x[1].get('fps', 0))
            logger.info(f"Best model: {best_model[0]} ({best_model[1].get('fps', 0):.2f} FPS)")
        
        return comparison
    
    def generate_report(self, output_path: Optional[str] = None) -> str:
        """
        Generate benchmark report
        
        Args:
            output_path: Path to save report (optional)
            
        Returns:
            Report string
        """
        report_lines = [
            "=" * 80,
            "Performance Benchmark Report",
            "=" * 80,
            ""
        ]
        
        for benchmark_name, results in self.results.items():
            report_lines.append(f"Benchmark: {benchmark_name}")
            report_lines.append("-" * 80)
            
            if isinstance(results, dict):
                for key, value in results.items():
                    if isinstance(value, float):
                        report_lines.append(f"  {key}: {value:.2f}")
                    else:
                        report_lines.append(f"  {key}: {value}")
            else:
                report_lines.append(f"  Results: {results}")
            
            report_lines.append("")
        
        report = "\n".join(report_lines)
        
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as f:
                f.write(report)
            logger.info(f"Report saved to: {output_path}")
        
        return report

