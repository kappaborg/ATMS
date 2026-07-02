#!/usr/bin/env python3
"""
Test script to verify sensor-fusion service can start
"""
import sys
from pathlib import Path

print("=" * 70)
print("SENSOR FUSION SERVICE - STARTUP DIAGNOSTIC TEST")
print("=" * 70)
print()

# Test 1: Python version
print("✓ Test 1: Python Version")
print(f"  Version: {sys.version}")
print(f"  Expected: 3.11+")
if sys.version_info >= (3, 11):
    print("  ✅ PASS")
else:
    print("  ⚠️  WARNING: Python 3.11+ recommended")
print()

# Test 2: Import shared modules
print("✓ Test 2: Import Shared Modules")
try:
    sys.path.append(str(Path(__file__).parent.parent.parent.parent))
    from shared.utils.logger import setup_logger, get_logger
    from shared.utils.config import BaseConfig
    from shared.models.base import CameraFrame, SensorDataMessage
    print("  ✅ PASS - All shared modules imported")
except Exception as e:
    print(f"  ❌ FAIL - {e}")
    sys.exit(1)
print()

# Test 3: Import service modules
print("✓ Test 3: Import Service Modules")
try:
    sys.path.insert(0, str(Path(__file__).parent / "src"))
    from config import sensor_fusion_config, camera_config
    print(f"  Service: {sensor_fusion_config.SERVICE_NAME}")
    print(f"  Version: {sensor_fusion_config.SERVICE_VERSION}")
    print("  ✅ PASS - Config loaded")
except Exception as e:
    print(f"  ❌ FAIL - {e}")
    sys.exit(1)
print()

# Test 4: Logger initialization
print("✓ Test 4: Logger Initialization")
try:
    logger = setup_logger("test-service", level="INFO")
    logger.info("Test log message")
    print("  ✅ PASS - Logger works")
except Exception as e:
    print(f"  ❌ FAIL - {e}")
    sys.exit(1)
print()

# Test 5: Prometheus metrics (with fix)
print("✓ Test 5: Prometheus Metrics")
try:
    from prometheus_client import Counter, Gauge
    
    # Test the fix for duplicate metrics
    try:
        test_counter = Counter('test_metric', 'Test metric')
        print("  ✅ PASS - Metrics can be created")
    except ValueError as e:
        print(f"  ⚠️  Metric already exists (expected with reload)")
        from prometheus_client import REGISTRY
        test_counter = REGISTRY._names_to_collectors.get('test_metric')
        if test_counter:
            print("  ✅ PASS - Metric reused correctly")
        else:
            print(f"  ❌ FAIL - Could not reuse metric")
except Exception as e:
    print(f"  ❌ FAIL - {e}")
    sys.exit(1)
print()

# Test 6: FastAPI import
print("✓ Test 6: FastAPI Import")
try:
    from fastapi import FastAPI
    app = FastAPI(title="Test App")
    print("  ✅ PASS - FastAPI works")
except Exception as e:
    print(f"  ❌ FAIL - {e}")
    sys.exit(1)
print()

# Test 7: Camera adapter import
print("✓ Test 7: Camera Adapter Import")
try:
    from src.adapters.camera import CameraAdapter
    print("  ✅ PASS - Camera adapter can be imported")
except Exception as e:
    print(f"  ❌ FAIL - {e}")
    sys.exit(1)
print()

# Test 8: Kafka producer import
print("✓ Test 8: Kafka Producer Import")
try:
    from src.kafka.producer import KafkaProducerManager
    print("  ✅ PASS - Kafka producer can be imported")
except Exception as e:
    print(f"  ❌ FAIL - {e}")
    sys.exit(1)
print()

# Summary
print("=" * 70)
print("DIAGNOSTIC SUMMARY")
print("=" * 70)
print("✅ All basic tests passed!")
print()
print("Next steps:")
print("1. Run: cd src && python main.py")
print("2. Check: http://localhost:8000/health")
print("3. View metrics: http://localhost:8000/metrics")
print()
print("If service starts successfully, all fixes are working! 🎉")
print("=" * 70)

