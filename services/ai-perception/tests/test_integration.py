#!/usr/bin/env python3
"""
Integration Test Script
======================

Tests all services working simultaneously with low latency.
"""

import asyncio
import time
import httpx
import json
from datetime import datetime, timedelta
from typing import Dict, List

# Service URLs
SERVICES = {
    "api-gateway": "http://localhost:8000",
    "ai-perception": "http://localhost:8004",
    "analytics": "http://localhost:8005",
    "dashboard": "http://localhost:8006",
    "sensor-fusion": "http://localhost:8003",
    "decision-engine": "http://localhost:8007"
}

async def test_service_health(client: httpx.AsyncClient, service_name: str, url: str) -> Dict:
    """Test service health"""
    try:
        start_time = time.time()
        response = await client.get(f"{url}/health", timeout=5.0)
        latency = (time.time() - start_time) * 1000  # ms
        
        return {
            "service": service_name,
            "status": "healthy" if response.status_code == 200 else "unhealthy",
            "latency_ms": round(latency, 2),
            "response": response.json() if response.status_code == 200 else None
        }
    except Exception as e:
        return {
            "service": service_name,
            "status": "error",
            "latency_ms": None,
            "error": str(e)
        }

async def test_api_gateway_routing(client: httpx.AsyncClient) -> Dict:
    """Test API Gateway routing"""
    try:
        # Test routing to analytics service
        start_time = time.time()
        response = await client.get(
            f"{SERVICES['api-gateway']}/api/v1/analytics/health",
            headers={"Authorization": "Bearer test-key-123"},
            timeout=5.0
        )
        latency = (time.time() - start_time) * 1000
        
        return {
            "test": "api_gateway_routing",
            "status": "success" if response.status_code == 200 else "failed",
            "latency_ms": round(latency, 2),
            "response_code": response.status_code
        }
    except Exception as e:
        return {
            "test": "api_gateway_routing",
            "status": "error",
            "error": str(e)
        }

async def test_concurrent_requests(client: httpx.AsyncClient, num_requests: int = 10) -> Dict:
    """Test concurrent requests to multiple services"""
    tasks = []
    
    for i in range(num_requests):
        # Mix of different service calls
        if i % 3 == 0:
            tasks.append(client.get(f"{SERVICES['analytics']}/health", timeout=5.0))
        elif i % 3 == 1:
            tasks.append(client.get(f"{SERVICES['dashboard']}/health", timeout=5.0))
        else:
            tasks.append(client.get(f"{SERVICES['ai-perception']}/health", timeout=5.0))
    
    start_time = time.time()
    responses = await asyncio.gather(*tasks, return_exceptions=True)
    total_time = (time.time() - start_time) * 1000
    
    successful = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 200)
    avg_latency = total_time / num_requests
    
    return {
        "test": "concurrent_requests",
        "total_requests": num_requests,
        "successful": successful,
        "failed": num_requests - successful,
        "total_time_ms": round(total_time, 2),
        "avg_latency_ms": round(avg_latency, 2),
        "throughput_rps": round(num_requests / (total_time / 1000), 2)
    }

async def main():
    """Run integration tests"""
    print("="*60)
    print("ATMS Integration Test - All Services")
    print("="*60)
    
    async with httpx.AsyncClient() as client:
        # Test 1: Health checks for all services
        print("\n1. Testing Service Health Checks...")
        health_tasks = [
            test_service_health(client, name, url)
            for name, url in SERVICES.items()
        ]
        health_results = await asyncio.gather(*health_tasks)
        
        print("\nHealth Check Results:")
        for result in health_results:
            status_icon = "✅" if result["status"] == "healthy" else "❌"
            latency_str = f"{result['latency_ms']}ms" if result.get("latency_ms") else "N/A"
            print(f"  {status_icon} {result['service']:20} - {result['status']:10} - Latency: {latency_str}")
        
        # Test 2: API Gateway routing
        print("\n2. Testing API Gateway Routing...")
        routing_result = await test_api_gateway_routing(client)
        status_icon = "✅" if routing_result["status"] == "success" else "❌"
        print(f"  {status_icon} {routing_result['test']} - {routing_result['status']}")
        if routing_result.get("latency_ms"):
            print(f"     Latency: {routing_result['latency_ms']}ms")
        
        # Test 3: Concurrent requests
        print("\n3. Testing Concurrent Requests...")
        concurrent_result = await test_concurrent_requests(client, num_requests=20)
        print(f"  Total Requests: {concurrent_result['total_requests']}")
        print(f"  Successful: {concurrent_result['successful']}")
        print(f"  Failed: {concurrent_result['failed']}")
        print(f"  Average Latency: {concurrent_result['avg_latency_ms']}ms")
        print(f"  Throughput: {concurrent_result['throughput_rps']} req/s")
        
        # Summary
        print("\n" + "="*60)
        print("Test Summary")
        print("="*60)
        
        all_healthy = all(r["status"] == "healthy" for r in health_results)
        avg_latency = sum(r.get("latency_ms", 0) for r in health_results if r.get("latency_ms")) / len([r for r in health_results if r.get("latency_ms")])
        
        print(f"All Services Healthy: {'✅ YES' if all_healthy else '❌ NO'}")
        print(f"Average Latency: {avg_latency:.2f}ms")
        print(f"Concurrent Throughput: {concurrent_result['throughput_rps']} req/s")
        
        # Latency check
        if avg_latency < 100:
            print("✅ Low latency requirement MET (<100ms)")
        else:
            print("⚠️  Latency above target (>100ms)")
        
        if concurrent_result['throughput_rps'] > 10:
            print("✅ High throughput requirement MET (>10 req/s)")
        else:
            print("⚠️  Throughput below target (<10 req/s)")

if __name__ == "__main__":
    asyncio.run(main())

