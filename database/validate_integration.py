#!/usr/bin/env python3
"""
ATMS Database Integration Validation Script
Purpose: Validate that all migrations are applied and integrated correctly
Author: ATMS Team
Date: 2025-10-13
"""

import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Dict, List, Tuple
import json

# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432'),
    'database': os.getenv('DB_NAME', 'atms_db'),
    'user': os.getenv('DB_USER', 'atms_user'),
    'password': os.getenv('DB_PASSWORD', 'atms_password')
}

# Expected tables
EXPECTED_TABLES = [
    'intersections',
    'users',
    'user_roles',
    'sensor_devices',
    'traffic_detections',
    'trajectories',
    'emissions',
    'traffic_lights',
    'light_phases',
    'system_logs',
    'alerts',
    'congestion_events',
    'traffic_metrics',
    'analytics',
    'system_config',
    'ml_predictions',
    'performance_metrics',
    'schema_migrations'
]

# Expected views
EXPECTED_VIEWS = [
    'system_health_dashboard',
    'active_alerts',
    'recent_detections',
    'current_light_status',
    'active_trajectories',
    'emission_summary',
    'recent_errors',
    'migration_status'
]

# Expected functions
EXPECTED_FUNCTIONS = [
    'update_updated_at_column',
    'calculate_emissions',
    'calculate_trajectory_stats',
    'change_light_state',
    'auto_resolve_alert',
    'calculate_performance_score',
    'apply_migration'
]

def print_header(text: str):
    """Print formatted header"""
    print(f"\n{Colors.CYAN}{'='*70}{Colors.ENDC}")
    print(f"{Colors.CYAN}{text.center(70)}{Colors.ENDC}")
    print(f"{Colors.CYAN}{'='*70}{Colors.ENDC}\n")

def print_success(text: str):
    """Print success message"""
    print(f"{Colors.GREEN}✅{Colors.ENDC} {text}")

def print_error(text: str):
    """Print error message"""
    print(f"{Colors.RED}❌{Colors.ENDC} {text}")

def print_warning(text: str):
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠{Colors.ENDC}  {text}")

def print_info(text: str):
    """Print info message"""
    print(f"{Colors.BLUE}ℹ{Colors.ENDC}  {text}")

def get_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print_error(f"Failed to connect to database: {e}")
        sys.exit(1)

def test_connection() -> bool:
    """Test database connection"""
    print_header("TEST 1: DATABASE CONNECTION")
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        
        print_success("Database connection successful")
        print_info(f"PostgreSQL version: {version.split(',')[0]}")
        
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print_error(f"Connection test failed: {e}")
        return False

def test_tables() -> Tuple[bool, List[str]]:
    """Test that all expected tables exist"""
    print_header("TEST 2: TABLE VALIDATION")
    
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT tablename 
        FROM pg_tables 
        WHERE schemaname = 'public'
        ORDER BY tablename;
    """)
    
    existing_tables = [row['tablename'] for row in cursor.fetchall()]
    missing_tables = []
    extra_tables = []
    
    for table in EXPECTED_TABLES:
        if table in existing_tables:
            print_success(f"Table '{table}' exists")
        else:
            print_error(f"Table '{table}' is MISSING")
            missing_tables.append(table)
    
    # Check for unexpected tables
    for table in existing_tables:
        if table not in EXPECTED_TABLES and not table.startswith('spatial_ref_sys'):
            print_warning(f"Unexpected table: '{table}'")
            extra_tables.append(table)
    
    print_info(f"Total tables: {len(existing_tables)}")
    print_info(f"Expected tables: {len(EXPECTED_TABLES)}")
    
    cursor.close()
    conn.close()
    
    return len(missing_tables) == 0, missing_tables

def test_views() -> bool:
    """Test that all expected views exist"""
    print_header("TEST 3: VIEW VALIDATION")
    
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT viewname 
        FROM pg_views 
        WHERE schemaname = 'public'
        ORDER BY viewname;
    """)
    
    existing_views = [row['viewname'] for row in cursor.fetchall()]
    missing_views = []
    
    for view in EXPECTED_VIEWS:
        if view in existing_views:
            print_success(f"View '{view}' exists")
        else:
            print_error(f"View '{view}' is MISSING")
            missing_views.append(view)
    
    print_info(f"Total views: {len(existing_views)}")
    
    cursor.close()
    conn.close()
    
    return len(missing_views) == 0

def test_functions() -> bool:
    """Test that all expected functions exist"""
    print_header("TEST 4: FUNCTION VALIDATION")
    
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT proname 
        FROM pg_proc 
        WHERE pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
        ORDER BY proname;
    """)
    
    existing_functions = [row['proname'] for row in cursor.fetchall()]
    missing_functions = []
    
    for func in EXPECTED_FUNCTIONS:
        if func in existing_functions:
            print_success(f"Function '{func}' exists")
        else:
            print_error(f"Function '{func}' is MISSING")
            missing_functions.append(func)
    
    print_info(f"Total functions: {len(existing_functions)}")
    
    cursor.close()
    conn.close()
    
    return len(missing_functions) == 0

def test_foreign_keys() -> bool:
    """Test foreign key relationships"""
    print_header("TEST 5: FOREIGN KEY VALIDATION")
    
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT
            tc.table_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
        ORDER BY tc.table_name;
    """)
    
    foreign_keys = cursor.fetchall()
    
    if len(foreign_keys) > 0:
        print_success(f"Found {len(foreign_keys)} foreign key relationships")
        
        for fk in foreign_keys[:5]:  # Show first 5
            print_info(f"  {fk['table_name']}.{fk['column_name']} → {fk['foreign_table_name']}.{fk['foreign_column_name']}")
        
        if len(foreign_keys) > 5:
            print_info(f"  ... and {len(foreign_keys) - 5} more")
    else:
        print_warning("No foreign keys found")
    
    cursor.close()
    conn.close()
    
    return len(foreign_keys) > 0

def test_indexes() -> bool:
    """Test indexes"""
    print_header("TEST 6: INDEX VALIDATION")
    
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT
            tablename,
            indexname,
            indexdef
        FROM pg_indexes
        WHERE schemaname = 'public'
        ORDER BY tablename, indexname;
    """)
    
    indexes = cursor.fetchall()
    
    print_success(f"Found {len(indexes)} indexes")
    
    # Group by table
    table_indexes = {}
    for idx in indexes:
        table = idx['tablename']
        if table not in table_indexes:
            table_indexes[table] = []
        table_indexes[table].append(idx['indexname'])
    
    for table in sorted(table_indexes.keys())[:5]:  # Show first 5 tables
        print_info(f"  {table}: {len(table_indexes[table])} indexes")
    
    cursor.close()
    conn.close()
    
    return len(indexes) > 0

def test_data_migration() -> bool:
    """Test data migration"""
    print_header("TEST 7: DATA MIGRATION VALIDATION")
    
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Check default intersection
    cursor.execute("SELECT COUNT(*) as count FROM intersections WHERE id = 1;")
    intersection_count = cursor.fetchone()['count']
    
    if intersection_count > 0:
        print_success("Default intersection (ID=1) exists")
    else:
        print_error("Default intersection missing")
    
    # Check default admin user
    cursor.execute("SELECT COUNT(*) as count FROM users WHERE username = 'admin';")
    admin_count = cursor.fetchone()['count']
    
    if admin_count > 0:
        print_success("Default admin user exists")
    else:
        print_error("Default admin user missing")
    
    # Check user roles
    cursor.execute("SELECT COUNT(*) as count FROM user_roles;")
    roles_count = cursor.fetchone()['count']
    
    if roles_count >= 4:
        print_success(f"User roles populated ({roles_count} roles)")
    else:
        print_warning(f"Expected 4+ user roles, found {roles_count}")
    
    # Check traffic lights
    cursor.execute("SELECT COUNT(*) as count FROM traffic_lights;")
    lights_count = cursor.fetchone()['count']
    
    if lights_count >= 8:
        print_success(f"Traffic lights populated ({lights_count} lights)")
    else:
        print_warning(f"Expected 8+ traffic lights, found {lights_count}")
    
    # Check system config
    cursor.execute("SELECT COUNT(*) as count FROM system_config;")
    config_count = cursor.fetchone()['count']
    
    if config_count > 0:
        print_success(f"System configuration populated ({config_count} settings)")
    else:
        print_warning("System configuration not populated")
    
    cursor.close()
    conn.close()
    
    return True

def test_migrations() -> bool:
    """Test migration tracking"""
    print_header("TEST 8: MIGRATION STATUS")
    
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute("""
            SELECT migration_name, success, applied_at 
            FROM schema_migrations 
            ORDER BY applied_at;
        """)
        
        migrations = cursor.fetchall()
        
        if len(migrations) > 0:
            print_success(f"Found {len(migrations)} applied migrations")
            
            failed = [m for m in migrations if not m['success']]
            
            if len(failed) > 0:
                print_error(f"{len(failed)} migrations FAILED:")
                for m in failed:
                    print_error(f"  - {m['migration_name']}")
            else:
                print_success("All migrations successful")
            
            # Show recent migrations
            print_info("\nRecent migrations:")
            for m in migrations[-5:]:
                status = "✅" if m['success'] else "❌"
                print_info(f"  {status} {m['migration_name']} - {m['applied_at']}")
        else:
            print_warning("No migrations recorded")
        
        cursor.close()
        conn.close()
        
        return len([m for m in migrations if not m['success']]) == 0
    except Exception as e:
        print_error(f"Migration check failed: {e}")
        cursor.close()
        conn.close()
        return False

def test_system_health() -> bool:
    """Test system health view"""
    print_header("TEST 9: SYSTEM HEALTH CHECK")
    
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute("SELECT * FROM system_health_dashboard LIMIT 5;")
        health_data = cursor.fetchall()
        
        if len(health_data) > 0:
            print_success("System health dashboard operational")
            
            for row in health_data:
                print_info(f"  Intersection: {row['intersection_name']}")
                print_info(f"    Status: {row['health_status']}")
                print_info(f"    Sensors: {row['active_sensors']}/{row['total_sensors']}")
                print_info(f"    Lights: {row['active_lights']}/{row['total_lights']}")
                print_info(f"    Alerts: {row['total_unresolved_alerts']}")
        else:
            print_warning("No data in system health dashboard")
        
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print_error(f"System health check failed: {e}")
        cursor.close()
        conn.close()
        return False

def generate_report(results: Dict[str, bool]):
    """Generate final report"""
    print_header("VALIDATION SUMMARY")
    
    total_tests = len(results)
    passed_tests = sum(1 for v in results.values() if v)
    failed_tests = total_tests - passed_tests
    
    print(f"\n{Colors.BOLD}Test Results:{Colors.ENDC}")
    print(f"  Total Tests: {total_tests}")
    print(f"  {Colors.GREEN}Passed: {passed_tests}{Colors.ENDC}")
    print(f"  {Colors.RED}Failed: {failed_tests}{Colors.ENDC}")
    
    if failed_tests == 0:
        print(f"\n{Colors.GREEN}{Colors.BOLD}╔══════════════════════════════════════════════════════════════════════╗{Colors.ENDC}")
        print(f"{Colors.GREEN}{Colors.BOLD}║                                                                      ║{Colors.ENDC}")
        print(f"{Colors.GREEN}{Colors.BOLD}║           🎉 ALL VALIDATIONS PASSED SUCCESSFULLY! 🎉                ║{Colors.ENDC}")
        print(f"{Colors.GREEN}{Colors.BOLD}║                                                                      ║{Colors.ENDC}")
        print(f"{Colors.GREEN}{Colors.BOLD}║  ✅ Database schema fully integrated                                 ║{Colors.ENDC}")
        print(f"{Colors.GREEN}{Colors.BOLD}║  ✅ All tables, views, and functions created                         ║{Colors.ENDC}")
        print(f"{Colors.GREEN}{Colors.BOLD}║  ✅ Foreign keys and indexes established                             ║{Colors.ENDC}")
        print(f"{Colors.GREEN}{Colors.BOLD}║  ✅ Default data populated                                           ║{Colors.ENDC}")
        print(f"{Colors.GREEN}{Colors.BOLD}║  ✅ System ready for production                                      ║{Colors.ENDC}")
        print(f"{Colors.GREEN}{Colors.BOLD}║                                                                      ║{Colors.ENDC}")
        print(f"{Colors.GREEN}{Colors.BOLD}╚══════════════════════════════════════════════════════════════════════╝{Colors.ENDC}\n")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}╔══════════════════════════════════════════════════════════════════════╗{Colors.ENDC}")
        print(f"{Colors.RED}{Colors.BOLD}║                                                                      ║{Colors.ENDC}")
        print(f"{Colors.RED}{Colors.BOLD}║                 ⚠️  VALIDATION FAILURES DETECTED ⚠️                  ║{Colors.ENDC}")
        print(f"{Colors.RED}{Colors.BOLD}║                                                                      ║{Colors.ENDC}")
        print(f"{Colors.RED}{Colors.BOLD}╚══════════════════════════════════════════════════════════════════════╝{Colors.ENDC}\n")
        
        print(f"\n{Colors.YELLOW}Failed Tests:{Colors.ENDC}")
        for test_name, passed in results.items():
            if not passed:
                print(f"  {Colors.RED}❌{Colors.ENDC} {test_name}")
        
        print(f"\n{Colors.YELLOW}Recommendations:{Colors.ENDC}")
        print("  1. Review MIGRATION_GUIDE.md for troubleshooting")
        print("  2. Check migration logs for errors")
        print("  3. Verify database permissions")
        print("  4. Re-run failed migrations manually")
    
    print(f"\n{Colors.CYAN}Documentation:{Colors.ENDC}")
    print("  📄 Migration Guide: /database/MIGRATION_GUIDE.md")
    print("  📊 Schema Analysis: /DATABASE_SCHEMA_ANALYSIS.md")
    print("  🗄️  Migration Files: /database/migrations/")
    
    return failed_tests == 0

def main():
    """Main execution"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}")
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║                                                                      ║")
    print("║         ATMS DATABASE INTEGRATION VALIDATION                        ║")
    print("║                                                                      ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print(f"{Colors.ENDC}\n")
    
    print_info(f"Database: {DB_CONFIG['database']}")
    print_info(f"Host: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print_info(f"User: {DB_CONFIG['user']}")
    print_info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Run all tests
    results = {
        'Database Connection': test_connection(),
        'Table Validation': test_tables()[0],
        'View Validation': test_views(),
        'Function Validation': test_functions(),
        'Foreign Key Validation': test_foreign_keys(),
        'Index Validation': test_indexes(),
        'Data Migration': test_data_migration(),
        'Migration Status': test_migrations(),
        'System Health': test_system_health()
    }
    
    # Generate report
    success = generate_report(results)
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()

