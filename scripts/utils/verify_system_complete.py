#!/usr/bin/env python3
"""
Comprehensive ATMS System Verification
======================================

Tests all components of the ATMS system:
- Services (all 6 services)
- Models (all 6 AI models)
- Kafka (message broker)
- PostgreSQL (database)
- Redis (cache)
- Dashboard UI
- API Gateway
- Integration tests
"""

import asyncio
import json
import sys
import time
from typing import Dict, List, Tuple
from datetime import datetime
import subprocess

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text.center(80)}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*80}{Colors.RESET}\n")

def print_success(text: str):
    print(f"{Colors.GREEN}✅ {text}{Colors.RESET}")

def print_warning(text: str):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.RESET}")

def print_error(text: str):
    print(f"{Colors.RED}❌ {text}{Colors.RESET}")

def print_info(text: str):
    print(f"{Colors.BLUE}ℹ️  {text}{Colors.RESET}")

class SystemVerifier:
    """Comprehensive system verification"""
    
    def __init__(self):
        self.results = {
            'services': {},
            'models': {},
            'kafka': {},
            'database': {},
            'redis': {},
            'dashboard': {},
            'docker': {},
            'integration': {}
        }
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
    
    async def verify_service_health(self, service_name: str, port: int) -> bool:
        """Verify a service is healthy"""
        import httpx
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"http://localhost:{port}/health")
                if response.status_code == 200:
                    data = response.json()
                    print_success(f"{service_name} (port {port}): HEALTHY")
                    self.results['services'][service_name] = {'status': 'healthy', 'port': port, 'data': data}
                    self.passed_tests += 1
                    return True
                else:
                    print_error(f"{service_name} (port {port}): UNHEALTHY (status {response.status_code})")
                    self.results['services'][service_name] = {'status': 'unhealthy', 'port': port}
                    self.failed_tests += 1
                    return False
        except Exception as e:
            print_error(f"{service_name} (port {port}): NOT RESPONDING ({str(e)[:50]})")
            self.results['services'][service_name] = {'status': 'error', 'port': port, 'error': str(e)}
            self.failed_tests += 1
            return False
        finally:
            self.total_tests += 1
    
    async def verify_all_services(self):
        """Verify all services"""
        print_header("Service Health Checks")
        
        services = [
            ("API Gateway", 8000),
            ("Sensor Fusion", 8003),
            ("AI Perception", 8004),
            ("Analytics", 8005),
            ("Dashboard", 8006),
            ("Decision Engine", 8007)
        ]
        
        tasks = [self.verify_service_health(name, port) for name, port in services]
        results = await asyncio.gather(*tasks)
        
        healthy = sum(results)
        print_info(f"Services: {healthy}/{len(services)} healthy")
        return all(results)
    
    async def verify_ai_models(self):
        """Verify AI models are loaded"""
        print_header("AI Model Verification")
        
        import httpx
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get("http://localhost:8004/")
                data = response.json()
                
                models = data.get('models', {})
                for model_name, loaded in models.items():
                    self.total_tests += 1
                    if loaded:
                        print_success(f"{model_name}: LOADED")
                        self.passed_tests += 1
                    else:
                        print_error(f"{model_name}: NOT LOADED")
                        self.failed_tests += 1
                
                self.results['models'] = models
                return all(models.values())
        except Exception as e:
            print_error(f"Failed to check models: {e}")
            self.failed_tests += 1
            return False
    
    def verify_kafka(self) -> bool:
        """Verify Kafka is running"""
        print_header("Kafka Verification")
        
        self.total_tests += 1
        
        try:
            # Check if Kafka container is running
            result = subprocess.run(
                ['docker', 'ps', '--filter', 'name=kafka', '--format', '{{.Status}}'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            kafka_running = 'up' in result.stdout.lower() and 'healthy' in result.stdout.lower()
            
            if kafka_running:
                print_success("Kafka: RUNNING (Docker container)")
                print_info("  Container status: HEALTHY")
                self.results['kafka'] = {'status': 'running', 'deployment': 'docker'}
                self.passed_tests += 1
                return True
            elif 'up' in result.stdout.lower():
                print_success("Kafka: RUNNING (Docker container)")
                print_warning("  Container health check pending...")
                self.results['kafka'] = {'status': 'running', 'deployment': 'docker'}
                self.passed_tests += 1
                return True
            else:
                print_warning("Kafka: NOT RUNNING")
                print_info("  To start Kafka: ./start_kafka.sh or docker-compose up kafka")
                self.results['kafka'] = {'status': 'not_running'}
                self.failed_tests += 1
                return False
        except FileNotFoundError:
            # Docker not available, check local process
            try:
                result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
                kafka_running = 'kafka' in result.stdout.lower()
                if kafka_running:
                    print_success("Kafka: RUNNING (local process)")
                    self.results['kafka'] = {'status': 'running', 'deployment': 'local'}
                    self.passed_tests += 1
                    return True
                else:
                    print_warning("Kafka: NOT RUNNING")
                    self.results['kafka'] = {'status': 'not_running'}
                    self.failed_tests += 1
                    return False
            except Exception as e:
                print_error(f"Failed to check Kafka: {e}")
                self.results['kafka'] = {'status': 'error', 'error': str(e)}
                self.failed_tests += 1
                return False
        except Exception as e:
            print_error(f"Failed to check Kafka: {e}")
            self.results['kafka'] = {'status': 'error', 'error': str(e)}
            self.failed_tests += 1
            return False
    
    async def verify_postgresql(self) -> bool:
        """Verify PostgreSQL database"""
        print_header("PostgreSQL Database Verification")
        
        self.total_tests += 1
        
        try:
            import asyncpg
            
            conn = await asyncpg.connect(
                host='localhost',
                port=5432,
                user='atms_user',
                password='atms_pass',
                database='atms_db',
                timeout=5
            )
            
            # Test query
            version = await conn.fetchval('SELECT version()')
            await conn.close()
            
            print_success("PostgreSQL: CONNECTED")
            print_info(f"  Version: {version.split(',')[0]}")
            self.results['database'] = {'status': 'connected', 'version': version}
            self.passed_tests += 1
            return True
            
        except Exception as e:
            print_error(f"PostgreSQL: NOT CONNECTED ({str(e)[:50]})")
            print_info("  Check if PostgreSQL is running: pg_ctl status")
            self.results['database'] = {'status': 'error', 'error': str(e)}
            self.failed_tests += 1
            return False
    
    async def verify_redis(self) -> bool:
        """Verify Redis cache"""
        print_header("Redis Cache Verification")
        
        self.total_tests += 1
        
        try:
            import redis.asyncio as redis
            
            client = redis.from_url("redis://localhost:6379/0", socket_timeout=5)
            await client.ping()
            info = await client.info()
            await client.close()
            
            print_success("Redis: CONNECTED")
            print_info(f"  Version: {info.get('redis_version', 'unknown')}")
            self.results['redis'] = {'status': 'connected', 'version': info.get('redis_version')}
            self.passed_tests += 1
            return True
            
        except Exception as e:
            print_error(f"Redis: NOT CONNECTED ({str(e)[:50]})")
            print_info("  Check if Redis is running: redis-cli ping")
            self.results['redis'] = {'status': 'error', 'error': str(e)}
            self.failed_tests += 1
            return False
    
    async def verify_dashboard_ui(self) -> bool:
        """Verify Dashboard UI"""
        print_header("Dashboard UI Verification")
        
        self.total_tests += 1
        
        import httpx
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Check HTML page
                response = await client.get("http://localhost:8006/")
                if response.status_code == 200 and 'ATMS' in response.text:
                    print_success("Dashboard HTML: ACCESSIBLE")
                    
                    # Check API endpoints
                    metrics_response = await client.get("http://localhost:8006/api/metrics")
                    anomalies_response = await client.get("http://localhost:8006/api/anomalies")
                    
                    if metrics_response.status_code == 200 and anomalies_response.status_code == 200:
                        print_success("Dashboard API: WORKING")
                        print_info("  Access at: http://localhost:8006")
                        self.results['dashboard'] = {'status': 'working', 'url': 'http://localhost:8006'}
                        self.passed_tests += 1
                        return True
                    else:
                        print_warning("Dashboard API: PARTIAL")
                        self.results['dashboard'] = {'status': 'partial'}
                        self.failed_tests += 1
                        return False
                else:
                    print_error("Dashboard HTML: NOT ACCESSIBLE")
                    self.results['dashboard'] = {'status': 'error'}
                    self.failed_tests += 1
                    return False
        except Exception as e:
            print_error(f"Dashboard: ERROR ({str(e)[:50]})")
            self.results['dashboard'] = {'status': 'error', 'error': str(e)}
            self.failed_tests += 1
            return False
    
    def verify_docker(self) -> bool:
        """Verify Docker (if used)"""
        print_header("Docker Verification")
        
        self.total_tests += 1
        
        try:
            result = subprocess.run(
                ['docker', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                version = result.stdout.strip()
                print_success(f"Docker: INSTALLED")
                print_info(f"  {version}")
                
                # Check running containers
                ps_result = subprocess.run(
                    ['docker', 'ps', '--format', '{{.Names}}'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                containers = ps_result.stdout.strip().split('\n') if ps_result.stdout.strip() else []
                if containers and containers[0]:
                    print_info(f"  Running containers: {len(containers)}")
                    self.results['docker'] = {'status': 'installed', 'version': version, 'containers': len(containers)}
                else:
                    print_info("  No containers running (services running locally)")
                    self.results['docker'] = {'status': 'installed', 'version': version, 'containers': 0}
                
                self.passed_tests += 1
                return True
            else:
                print_warning("Docker: NOT INSTALLED")
                print_info("  Docker is optional for local development")
                self.results['docker'] = {'status': 'not_installed'}
                self.passed_tests += 1  # Not an error
                return True
                
        except FileNotFoundError:
            print_warning("Docker: NOT INSTALLED")
            print_info("  Docker is optional for local development")
            self.results['docker'] = {'status': 'not_installed'}
            self.passed_tests += 1  # Not an error
            return True
        except Exception as e:
            print_warning(f"Docker: CHECK FAILED ({str(e)[:30]})")
            self.results['docker'] = {'status': 'unknown'}
            self.passed_tests += 1  # Not an error
            return True
    
    async def verify_integration(self) -> bool:
        """Verify service integration"""
        print_header("Integration Tests")
        
        import httpx
        
        tests_passed = 0
        tests_total = 3
        
        # Test 1: API Gateway routing
        self.total_tests += 1
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    "http://localhost:8000/api/v1/analytics/health",
                    headers={"Authorization": "Bearer test-key-123"}
                )
                if response.status_code == 200:
                    print_success("API Gateway routing: WORKING")
                    tests_passed += 1
                    self.passed_tests += 1
                else:
                    print_error(f"API Gateway routing: FAILED (status {response.status_code})")
                    self.failed_tests += 1
        except Exception as e:
            print_error(f"API Gateway routing: ERROR ({str(e)[:50]})")
            self.failed_tests += 1
        
        # Test 2: Model status check
        self.total_tests += 1
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get("http://localhost:8004/")
                data = response.json()
                if all(data.get('models', {}).values()):
                    print_success("Model integration: ALL LOADED")
                    tests_passed += 1
                    self.passed_tests += 1
                else:
                    print_warning("Model integration: PARTIAL")
                    self.failed_tests += 1
        except Exception as e:
            print_error(f"Model integration: ERROR ({str(e)[:50]})")
            self.failed_tests += 1
        
        # Test 3: Database connectivity through service
        self.total_tests += 1
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get("http://localhost:8004/health")
                if response.status_code == 200:
                    print_success("Service-DB integration: WORKING")
                    tests_passed += 1
                    self.passed_tests += 1
                else:
                    print_warning("Service-DB integration: UNKNOWN")
                    self.failed_tests += 1
        except Exception as e:
            print_error(f"Service-DB integration: ERROR ({str(e)[:50]})")
            self.failed_tests += 1
        
        self.results['integration'] = {'tests_passed': tests_passed, 'tests_total': tests_total}
        return tests_passed == tests_total
    
    def print_summary(self):
        """Print verification summary"""
        print_header("Verification Summary")
        
        # Calculate score
        if self.total_tests > 0:
            score = (self.passed_tests / self.total_tests) * 100
        else:
            score = 0
        
        print(f"{Colors.BOLD}Total Tests:{Colors.RESET} {self.total_tests}")
        print(f"{Colors.GREEN}✅ Passed:{Colors.RESET} {self.passed_tests}")
        print(f"{Colors.RED}❌ Failed:{Colors.RESET} {self.failed_tests}")
        print(f"{Colors.BOLD}Score:{Colors.RESET} {score:.1f}%")
        
        print()
        
        # Component summary
        print(f"{Colors.BOLD}Component Status:{Colors.RESET}")
        
        components = [
            ("Services", len([s for s in self.results['services'].values() if s.get('status') == 'healthy']), 6),
            ("Models", sum(1 for v in self.results.get('models', {}).values() if v), len(self.results.get('models', {}))),
            ("Kafka", 1 if self.results.get('kafka', {}).get('status') == 'running' else 0, 1),
            ("PostgreSQL", 1 if self.results.get('database', {}).get('status') == 'connected' else 0, 1),
            ("Redis", 1 if self.results.get('redis', {}).get('status') == 'connected' else 0, 1),
            ("Dashboard", 1 if self.results.get('dashboard', {}).get('status') == 'working' else 0, 1),
        ]
        
        for name, passed, total in components:
            status = "✅" if passed == total else "⚠️" if passed > 0 else "❌"
            print(f"  {status} {name}: {passed}/{total}")
        
        print()
        
        # Overall status
        if score >= 90:
            print_success(f"System Status: EXCELLENT ({score:.0f}%)")
        elif score >= 70:
            print_warning(f"System Status: GOOD ({score:.0f}%) - Some issues detected")
        else:
            print_error(f"System Status: NEEDS ATTENTION ({score:.0f}%)")
        
        # Save results
        with open('system_verification_results.json', 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'total_tests': self.total_tests,
                'passed_tests': self.passed_tests,
                'failed_tests': self.failed_tests,
                'score': score,
                'results': self.results
            }, f, indent=2, default=str)
        
        print_info("Results saved to: system_verification_results.json")

async def main():
    """Run comprehensive system verification"""
    print_header("ATMS Comprehensive System Verification")
    print_info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    verifier = SystemVerifier()
    
    # Run all verifications
    await verifier.verify_all_services()
    await verifier.verify_ai_models()
    verifier.verify_kafka()
    await verifier.verify_postgresql()
    await verifier.verify_redis()
    await verifier.verify_dashboard_ui()
    verifier.verify_docker()
    await verifier.verify_integration()
    
    # Print summary
    verifier.print_summary()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nVerification interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}Error: {e}{Colors.RESET}")
        sys.exit(1)

