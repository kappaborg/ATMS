#!/usr/bin/env python3
"""
Performance Configuration
=========================

Centralized performance tuning parameters.
"""

from pydantic import BaseSettings
from typing import Optional

class PerformanceConfig(BaseSettings):
    """Performance optimization settings"""
    
    # Batch processing
    enable_batch_processing: bool = True
    batch_size: int = 2
    max_batch_wait_time: float = 0.05  # seconds
    
    # Parallel processing
    enable_parallel_inference: bool = True
    max_parallel_workers: int = 3
    
    # Device optimization
    auto_select_device: bool = True
    preferred_device: Optional[str] = None  # 'mps', 'cuda', 'cpu'
    
    # Data conversion
    enable_optimized_converter: bool = True
    lazy_array_conversion: bool = True
    array_size_threshold: int = 1000  # Arrays smaller than this converted immediately
    
    # Database operations
    async_database_operations: bool = True
    batch_database_writes: bool = True
    database_write_batch_size: int = 10
    
    # Caching
    enable_result_caching: bool = True
    cache_ttl_seconds: int = 60
    
    # Memory management
    max_trajectory_history: int = 100
    cleanup_interval_seconds: int = 30
    
    class Config:
        env_prefix = "PERF_"
        case_sensitive = False

# Global performance config
perf_config = PerformanceConfig()


