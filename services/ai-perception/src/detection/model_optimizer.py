"""
AI Perception Service - Model Optimization
Supports ONNX export, TensorRT optimization, and FP16 precision
"""
import os
from pathlib import Path
from typing import Optional, Tuple
import torch
import numpy as np

try:
    import onnx
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False

try:
    import tensorrt as trt
    TENSORRT_AVAILABLE = True
except ImportError:
    TENSORRT_AVAILABLE = False

from shared.utils.logger import get_logger

logger = get_logger(__name__)


class ModelOptimizer:
    """
    Model Optimization Utility
    
    Features:
    - ONNX export for cross-platform deployment
    - TensorRT optimization for NVIDIA GPUs
    - FP16 half-precision conversion
    - Batch inference optimization
    - Model quantization (INT8)
    """
    
    def __init__(
        self,
        model_path: str,
        output_dir: str = "./optimized_models"
    ):
        """
        Initialize model optimizer
        
        Args:
            model_path: Path to PyTorch model
            output_dir: Directory to save optimized models
        """
        self.model_path = model_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = logger.bind(
            model_path=model_path,
            output_dir=str(output_dir)
        )
    
    def export_to_onnx(
        self,
        model: torch.nn.Module,
        input_shape: Tuple[int, int, int, int] = (1, 3, 640, 640),
        opset_version: int = 12,
        dynamic_axes: bool = True
    ) -> Optional[str]:
        """
        Export PyTorch model to ONNX format
        
        Args:
            model: PyTorch model
            input_shape: Input tensor shape (batch, channels, height, width)
            opset_version: ONNX opset version
            dynamic_axes: Enable dynamic batch size
            
        Returns:
            Path to ONNX model or None if failed
        """
        if not ONNX_AVAILABLE:
            self.logger.warning("ONNX not available, skipping export")
            return None
        
        try:
            onnx_path = self.output_dir / "model.onnx"
            
            # Create dummy input
            dummy_input = torch.randn(*input_shape)
            
            # Set dynamic axes for batch size
            dynamic_config = None
            if dynamic_axes:
                dynamic_config = {
                    'input': {0: 'batch_size'},
                    'output': {0: 'batch_size'}
                }
            
            # Export model
            torch.onnx.export(
                model,
                dummy_input,
                str(onnx_path),
                opset_version=opset_version,
                input_names=['input'],
                output_names=['output'],
                dynamic_axes=dynamic_config,
                do_constant_folding=True,
                export_params=True
            )
            
            # Verify ONNX model
            onnx_model = onnx.load(str(onnx_path))
            onnx.checker.check_model(onnx_model)
            
            self.logger.info(f"ONNX export successful: {onnx_path}")
            return str(onnx_path)
            
        except Exception as e:
            self.logger.error(f"ONNX export failed: {e}")
            return None
    
    def optimize_onnx(
        self,
        onnx_path: str,
        optimization_level: int = 2
    ) -> Optional[str]:
        """
        Optimize ONNX model using ONNX Runtime
        
        Args:
            onnx_path: Path to ONNX model
            optimization_level: 0=none, 1=basic, 2=extended, 99=all
            
        Returns:
            Path to optimized ONNX model or None if failed
        """
        if not ONNX_AVAILABLE:
            return None
        
        try:
            optimized_path = self.output_dir / "model_optimized.onnx"
            
            # Create session options
            sess_options = ort.SessionOptions()
            sess_options.optimized_model_filepath = str(optimized_path)
            sess_options.graph_optimization_level = getattr(
                ort.GraphOptimizationLevel,
                f'ORT_ENABLE_{"ALL" if optimization_level == 99 else "EXTENDED" if optimization_level == 2 else "BASIC"}'
            )
            
            # Create session (triggers optimization)
            _ = ort.InferenceSession(onnx_path, sess_options)
            
            self.logger.info(f"ONNX optimization successful: {optimized_path}")
            return str(optimized_path)
            
        except Exception as e:
            self.logger.error(f"ONNX optimization failed: {e}")
            return None
    
    def convert_to_fp16(
        self,
        model: torch.nn.Module,
        device: str = "cuda"
    ) -> torch.nn.Module:
        """
        Convert model to FP16 half precision
        
        Args:
            model: PyTorch model
            device: Device to use ('cuda' or 'cpu')
            
        Returns:
            FP16 model
        """
        try:
            if device == "cuda" and torch.cuda.is_available():
                model = model.half()
                model = model.to(device)
                self.logger.info("Model converted to FP16")
            else:
                self.logger.warning("CUDA not available, keeping FP32")
            
            return model
            
        except Exception as e:
            self.logger.error(f"FP16 conversion failed: {e}")
            return model
    
    def export_to_tensorrt(
        self,
        onnx_path: str,
        precision: str = "fp16",
        max_batch_size: int = 16,
        workspace_size: int = 1 << 30  # 1GB
    ) -> Optional[str]:
        """
        Convert ONNX model to TensorRT engine
        
        Args:
            onnx_path: Path to ONNX model
            precision: 'fp32', 'fp16', or 'int8'
            max_batch_size: Maximum batch size
            workspace_size: Max workspace size in bytes
            
        Returns:
            Path to TensorRT engine or None if failed
        """
        if not TENSORRT_AVAILABLE:
            self.logger.warning("TensorRT not available")
            return None
        
        try:
            trt_path = self.output_dir / f"model_{precision}.trt"
            
            # Create TensorRT logger
            TRT_LOGGER = trt.Logger(trt.Logger.WARNING)
            
            # Create builder and network
            builder = trt.Builder(TRT_LOGGER)
            network = builder.create_network(
                1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
            )
            parser = trt.OnnxParser(network, TRT_LOGGER)
            
            # Parse ONNX
            with open(onnx_path, 'rb') as model_file:
                if not parser.parse(model_file.read()):
                    self.logger.error("Failed to parse ONNX file")
                    return None
            
            # Create builder config
            config = builder.create_builder_config()
            config.max_workspace_size = workspace_size
            
            # Set precision
            if precision == "fp16" and builder.platform_has_fast_fp16:
                config.set_flag(trt.BuilderFlag.FP16)
            elif precision == "int8" and builder.platform_has_fast_int8:
                config.set_flag(trt.BuilderFlag.INT8)
                # Note: INT8 calibration would be needed here
            
            # Build engine
            engine = builder.build_engine(network, config)
            
            if engine is None:
                self.logger.error("Failed to build TensorRT engine")
                return None
            
            # Serialize engine
            with open(trt_path, 'wb') as f:
                f.write(engine.serialize())
            
            self.logger.info(f"TensorRT export successful: {trt_path}")
            return str(trt_path)
            
        except Exception as e:
            self.logger.error(f"TensorRT export failed: {e}")
            return None
    
    def benchmark_model(
        self,
        model: torch.nn.Module,
        input_shape: Tuple[int, int, int, int] = (1, 3, 640, 640),
        num_iterations: int = 100,
        warmup_iterations: int = 10,
        device: str = "cuda"
    ) -> dict:
        """
        Benchmark model performance
        
        Args:
            model: PyTorch model
            input_shape: Input tensor shape
            num_iterations: Number of iterations for benchmarking
            warmup_iterations: Number of warmup iterations
            device: Device to use
            
        Returns:
            Dictionary with benchmark results
        """
        import time
        
        try:
            model.eval()
            model = model.to(device)
            
            # Create dummy input
            dummy_input = torch.randn(*input_shape).to(device)
            
            # Warmup
            with torch.no_grad():
                for _ in range(warmup_iterations):
                    _ = model(dummy_input)
            
            # Synchronize if using CUDA
            if device == "cuda":
                torch.cuda.synchronize()
            
            # Benchmark
            times = []
            with torch.no_grad():
                for _ in range(num_iterations):
                    start = time.perf_counter()
                    _ = model(dummy_input)
                    
                    if device == "cuda":
                        torch.cuda.synchronize()
                    
                    end = time.perf_counter()
                    times.append((end - start) * 1000)  # Convert to ms
            
            # Calculate statistics
            times = np.array(times)
            results = {
                "mean_ms": float(np.mean(times)),
                "std_ms": float(np.std(times)),
                "min_ms": float(np.min(times)),
                "max_ms": float(np.max(times)),
                "median_ms": float(np.median(times)),
                "fps": 1000.0 / float(np.mean(times)),
                "device": device,
                "input_shape": input_shape,
                "num_iterations": num_iterations
            }
            
            self.logger.info(f"Benchmark results: {results['mean_ms']:.2f}ms ({results['fps']:.1f} FPS)")
            return results
            
        except Exception as e:
            self.logger.error(f"Benchmarking failed: {e}")
            return {}
    
    def optimize_batch_inference(
        self,
        model: torch.nn.Module,
        batch_sizes: list = [1, 4, 8, 16],
        input_shape: Tuple[int, int, int] = (3, 640, 640),
        device: str = "cuda"
    ) -> dict:
        """
        Find optimal batch size for inference
        
        Args:
            model: PyTorch model
            batch_sizes: List of batch sizes to test
            input_shape: Input tensor shape (without batch)
            device: Device to use
            
        Returns:
            Dictionary with optimal batch size and performance metrics
        """
        results = {}
        
        for batch_size in batch_sizes:
            try:
                input_tensor_shape = (batch_size, *input_shape)
                benchmark = self.benchmark_model(
                    model,
                    input_tensor_shape,
                    num_iterations=50,
                    device=device
                )
                
                if benchmark:
                    results[batch_size] = {
                        "throughput": benchmark["fps"] * batch_size,
                        "latency_ms": benchmark["mean_ms"],
                        "fps": benchmark["fps"]
                    }
                
            except RuntimeError as e:
                if "out of memory" in str(e):
                    self.logger.warning(f"Batch size {batch_size} exceeds memory")
                    break
                else:
                    raise
        
        # Find optimal batch size (highest throughput)
        if results:
            optimal_batch = max(results.items(), key=lambda x: x[1]["throughput"])
            self.logger.info(f"Optimal batch size: {optimal_batch[0]} (throughput: {optimal_batch[1]['throughput']:.1f} img/s)")
            
            return {
                "optimal_batch_size": optimal_batch[0],
                "all_results": results,
                "recommendation": f"Use batch size {optimal_batch[0]} for best throughput"
            }
        
        return {}


def create_optimization_report(
    model_path: str,
    output_formats: list = ["onnx", "fp16"],
    save_path: str = "optimization_report.json"
) -> dict:
    """
    Create comprehensive optimization report
    
    Args:
        model_path: Path to model
        output_formats: Formats to export ('onnx', 'tensorrt', 'fp16')
        save_path: Path to save report
        
    Returns:
        Optimization report dictionary
    """
    import json
    from datetime import datetime
    
    optimizer = ModelOptimizer(model_path)
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "model_path": model_path,
        "optimizations": {},
        "recommendations": []
    }
    
    # Add optimization results based on requested formats
    if "onnx" in output_formats and ONNX_AVAILABLE:
        report["optimizations"]["onnx"] = {
            "available": True,
            "recommended": True,
            "benefits": "Cross-platform deployment, reduced model size"
        }
    
    if "tensorrt" in output_formats and TENSORRT_AVAILABLE:
        report["optimizations"]["tensorrt"] = {
            "available": True,
            "recommended": True,
            "benefits": "Up to 3-5x faster inference on NVIDIA GPUs"
        }
    
    if "fp16" in output_formats:
        report["optimizations"]["fp16"] = {
            "available": torch.cuda.is_available(),
            "recommended": torch.cuda.is_available(),
            "benefits": "2x faster inference, 50% memory reduction"
        }
    
    # Save report
    with open(save_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"Optimization report saved: {save_path}")
    return report


