## 🗄️ Database Migration Guide

**Version:** 1.0  
**Date:** October 13, 2025  
**Status:** Ready for Execution

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Migration Files](#migration-files)
4. [Execution Steps](#execution-steps)
5. [Validation](#validation)
6. [Rollback Procedure](#rollback-procedure)
7. [Troubleshooting](#troubleshooting)

---

## 🎯 Overview

This migration system aligns the database schema with the ER diagram and implements a comprehensive traffic management database with **15 tables**.

### What's Being Created:

**Infrastructure (5 tables):**
- ✅ `intersections` - Central hub for intersection data
- ✅ `users` - User authentication and authorization
- ✅ `sensor_devices` - Device registry (cameras, sensors)
- ✅ `system_logs` - Structured logging
- ✅ `system_config` - Configuration management

**AI/ML Analytics (5 tables):**
- ✅ `traffic_detections` - Vehicle detections
- ✅ `trajectories` - Kalman Filter tracking
- ✅ `emissions` - Environmental calculations
- ✅ `traffic_metrics` - Traffic metrics
- ✅ `analytics` - ML analytics data

**Traffic Control (5 tables):**
- ✅ `traffic_lights` - Signal control
- ✅ `light_phases` - Phase management
- ✅ `alerts` - Alert management
- ✅ `congestion_events` - Event tracking
- ✅ `ml_predictions` - ML predictions

**Additional Tables:**
- ✅ `user_roles` - Role-based access control
- ✅ `performance_metrics` - Performance tracking
- ✅ `schema_migrations` - Migration tracking

---

## ✅ Prerequisites

### 1. Database Requirements
```bash
# PostgreSQL 14+
psql --version  # Should be >= 14

# Required extensions
- uuid-ossp (UUID generation)
- postgis (Geographic data)
- pg_trgm (Text search)
- btree_gin (GIN indexes)
```

### 2. Database Connection
```bash
# Test connection
psql -h localhost -p 5432 -U atms_user -d atms_db -c "SELECT 1"
```

### 3. Backup Current Database
```bash
# Create backup before migration
pg_dump atms_db > backup_$(date +%Y%m%d_%H%M%S).sql
```

### 4. Environment Variables
```bash
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=atms_db
export DB_USER=atms_user
export DB_PASSWORD=atms_password
```

---

## 📁 Migration Files

### Migration Order:

| # | File | Purpose | Dependencies |
|---|------|---------|--------------|
| 0 | `000_master_migration.sql` | Setup migration system | None |
| 1 | `001_create_intersections.sql` | Create intersections table | None |
| 2 | `002_create_users.sql` | Create users & roles | None |
| 3 | `003_create_sensor_devices.sql` | Create sensor registry | #1 |
| 4 | `004_create_traffic_detections.sql` | Create detections table | #1, #3 |
| 5 | `005_create_trajectories.sql` | Create trajectories table | #1 |
| 6 | `006_create_emissions.sql` | Create emissions table | #1, #5 |
| 7 | `007_create_traffic_lights.sql` | Create traffic control | #1 |
| 8 | `008_create_system_monitoring.sql` | Create monitoring tables | #1, #2 |
| 9 | `009_create_analytics_config.sql` | Create analytics tables | #1 |
| 999 | `999_rollback.sql` | Rollback all migrations | All |

---

## 🚀 Execution Steps

### Method 1: Automated Script (Recommended)

```bash
# Navigate to database directory
cd /Users/kappasutra/Traffic/database

# Run migration script
./run_migrations.sh

# Or with custom settings
DB_HOST=localhost DB_PORT=5432 DB_NAME=atms_db ./run_migrations.sh
```

### Method 2: Manual Execution

```bash
# 1. Set environment
export PGPASSWORD=atms_password

# 2. Execute master migration
psql -h localhost -p 5432 -U atms_user -d atms_db -f migrations/000_master_migration.sql

# 3. Execute migrations in order
for i in {001..009}; do
    psql -h localhost -p 5432 -U atms_user -d atms_db -f migrations/${i}_*.sql
    echo "Migration $i completed"
done

# 4. Verify
psql -h localhost -p 5432 -U atms_user -d atms_db -c "SELECT * FROM migration_status;"
```

### Method 3: Docker Compose

```bash
# If using Docker
docker exec -i atms-postgres psql -U atms_user -d atms_db < migrations/000_master_migration.sql

# Run all migrations
for file in migrations/00{1..9}_*.sql; do
    docker exec -i atms-postgres psql -U atms_user -d atms_db < "$file"
done
```

---

## ✅ Validation

### 1. Check Migration Status

```sql
-- View migration history
SELECT * FROM migration_status ORDER BY execution_order;

-- Check for failures
SELECT * FROM schema_migrations WHERE success = FALSE;
```

### 2. Verify Tables

```sql
-- List all tables
\dt

-- Expected tables (17 total):
-- intersections, users, user_roles, sensor_devices,
-- traffic_detections, trajectories, emissions,
-- traffic_lights, light_phases, system_logs, alerts,
-- congestion_events, traffic_metrics, analytics,
-- system_config, ml_predictions, performance_metrics,
-- schema_migrations

-- Count tables
SELECT COUNT(*) FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_type = 'BASE TABLE';
-- Should return: 18 (including schema_migrations)
```

### 3. Check Relationships

```sql
-- Verify foreign keys
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
```

### 4. Verify Data Migration

```sql
-- Check if old data migrated
SELECT COUNT(*) FROM traffic_detections;  -- Should have old detection data
SELECT COUNT(*) FROM sensor_devices;      -- Should have camera_sources data
SELECT COUNT(*) FROM intersections;       -- Should have at least ID=1

-- Check default data
SELECT * FROM intersections WHERE id = 1;
SELECT * FROM users WHERE username = 'admin';
SELECT * FROM user_roles;
SELECT * FROM traffic_lights;
```

### 5. Test Views

```sql
-- Test created views
SELECT * FROM system_health_dashboard;
SELECT * FROM active_alerts LIMIT 5;
SELECT * FROM recent_detections LIMIT 10;
SELECT * FROM current_light_status;
SELECT * FROM active_trajectories LIMIT 10;
SELECT * FROM emission_summary LIMIT 10;
```

### 6. Test Functions

```sql
-- Test emission calculation function
SELECT * FROM calculate_emissions('sedan', 1000, 15.5, 0);

-- Test performance score calculation
SELECT calculate_performance_score('throughput', 850, 1000);

-- Test light state change
SELECT change_light_state(1, 'green');
SELECT current_state FROM traffic_lights WHERE id = 1;
```

---

## 🔄 Rollback Procedure

### ⚠️ WARNING: Rollback will DELETE ALL DATA!

```bash
# 1. Create backup first
pg_dump atms_db > emergency_backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Execute rollback
./run_migrations.sh --rollback

# Or manually
psql -h localhost -p 5432 -U atms_user -d atms_db -f migrations/999_rollback.sql

# 3. Restore from backup if needed
psql -h localhost -p 5432 -U atms_user -d atms_db < backup_file.sql
```

---

## 🔧 Troubleshooting

### Issue 1: Extension Not Found

**Error:** `ERROR: extension "postgis" does not exist`

**Solution:**
```bash
# Install PostGIS
sudo apt-get install postgresql-14-postgis-3  # Ubuntu/Debian
brew install postgis  # macOS

# Create extension
psql -d atms_db -c "CREATE EXTENSION postgis;"
```

### Issue 2: Permission Denied

**Error:** `ERROR: permission denied for schema public`

**Solution:**
```sql
-- Grant permissions
GRANT ALL ON SCHEMA public TO atms_user;
GRANT ALL ON ALL TABLES IN SCHEMA public TO atms_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO atms_user;
```

### Issue 3: Migration Already Applied

**Error:** Migration appears to run but tables don't exist

**Solution:**
```sql
-- Check migration status
SELECT * FROM schema_migrations WHERE success = FALSE;

-- Reset specific migration
DELETE FROM schema_migrations WHERE migration_name = '001_create_intersections';

-- Re-run migration
\i migrations/001_create_intersections.sql
```

### Issue 4: Foreign Key Constraint Error

**Error:** `ERROR: insert or update on table violates foreign key constraint`

**Solution:**
```sql
-- Check if referenced table exists
SELECT tablename FROM pg_tables WHERE schemaname = 'public';

-- Ensure migrations run in correct order
-- Re-run with correct order (001, 002, 003, etc.)
```

### Issue 5: Data Type Mismatch

**Error:** `ERROR: column "id" cannot be cast automatically to type uuid`

**Solution:**
```sql
-- For existing tables with different types
-- Drop and recreate (after backup!)
DROP TABLE IF EXISTS old_table CASCADE;

-- Or migrate data with type conversion
INSERT INTO new_table (id, ...)
SELECT uuid_generate_v4(), ...
FROM old_table;
```

---

## 📊 Post-Migration Checklist

### Database Level:
- [ ] All 18 tables created
- [ ] All foreign keys established
- [ ] All indexes created
- [ ] All views created
- [ ] All functions created
- [ ] All triggers created
- [ ] Default data inserted

### Application Level:
- [ ] Update database models
- [ ] Update API endpoints
- [ ] Update queries
- [ ] Update configuration
- [ ] Run integration tests
- [ ] Update documentation

### Monitoring:
- [ ] Verify database size
- [ ] Check index usage
- [ ] Monitor query performance
- [ ] Set up alerts
- [ ] Configure backups

---

## 📈 Performance Optimization

### After Migration:

```sql
-- 1. Analyze tables for query optimization
ANALYZE;

-- 2. Vacuum to reclaim space
VACUUM ANALYZE;

-- 3. Update table statistics
VACUUM ANALYZE intersections;
VACUUM ANALYZE traffic_detections;
VACUUM ANALYZE trajectories;

-- 4. Check index usage
SELECT schemaname, tablename, indexname, idx_scan
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;

-- 5. Check table sizes
SELECT
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

---

## 🔐 Security Recommendations

### 1. Change Default Passwords
```sql
-- Change default admin password
UPDATE users 
SET password_hash = crypt('new_secure_password', gen_salt('bf'))
WHERE username = 'admin';
```

### 2. Create Application User
```sql
-- Create read-only user for reporting
CREATE USER atms_readonly WITH PASSWORD 'readonly_password';
GRANT CONNECT ON DATABASE atms_db TO atms_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO atms_readonly;
```

### 3. Enable Row-Level Security (Optional)
```sql
-- Example: Restrict users to their intersection data
ALTER TABLE traffic_detections ENABLE ROW LEVEL SECURITY;

CREATE POLICY intersection_isolation ON traffic_detections
    FOR ALL
    TO atms_user
    USING (intersection_id IN (
        SELECT intersection_id FROM user_intersections 
        WHERE user_id = current_user_id()
    ));
```

---

## 📝 Maintenance Schedule

### Daily:
- Monitor migration_status for failures
- Check system_logs for errors
- Review active_alerts

### Weekly:
- Vacuum and analyze tables
- Review database size growth
- Check slow queries

### Monthly:
- Full database backup
- Index maintenance
- Archive old data

---

## 🆘 Support

### Get Help:
1. Check migration logs: `SELECT * FROM migration_status;`
2. Check error logs: `SELECT * FROM recent_errors;`
3. Review migration files for comments
4. Check DATABASE_SCHEMA_ANALYSIS.md for details

### Useful Commands:
```bash
# View migration script help
./run_migrations.sh --help

# Check database connection
psql -h localhost -U atms_user -d atms_db -c "\conninfo"

# List all tables
psql -h localhost -U atms_user -d atms_db -c "\dt"

# Describe specific table
psql -h localhost -U atms_user -d atms_db -c "\d traffic_detections"
```

---

**Document Version:** 1.0  
**Last Updated:** October 13, 2025  
**Migration Files:** `/database/migrations/`  
**Execution Script:** `/database/run_migrations.sh`

