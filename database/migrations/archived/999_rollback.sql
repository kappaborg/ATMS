-- ROLLBACK SCRIPT
-- Purpose: Rollback all migrations (USE WITH CAUTION!)
-- Author: ATMS Team
-- Date: 2025-10-13
-- WARNING: This will drop all tables and data!

-- Create backup reminder function
CREATE OR REPLACE FUNCTION confirm_rollback()
RETURNS VOID AS $$
BEGIN
    RAISE NOTICE '========================================';
    RAISE NOTICE 'DATABASE ROLLBACK SCRIPT';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'WARNING: This will delete ALL tables and data!';
    RAISE NOTICE '';
    RAISE NOTICE 'Before proceeding, ensure you have:';
    RAISE NOTICE '1. Created a database backup';
    RAISE NOTICE '2. Confirmed this is the correct database';
    RAISE NOTICE '3. Received authorization to proceed';
    RAISE NOTICE '';
    RAISE NOTICE 'To create a backup, run:';
    RAISE NOTICE 'pg_dump atms_db > backup_$(date +%%Y%%m%%d_%%H%%M%%S).sql';
    RAISE NOTICE '========================================';
END;
$$ LANGUAGE plpgsql;

-- Display warning
SELECT confirm_rollback();

-- Rollback migrations in reverse order

-- Drop views first
DROP VIEW IF EXISTS system_health_dashboard CASCADE;
DROP VIEW IF EXISTS recent_errors CASCADE;
DROP VIEW IF EXISTS active_alerts CASCADE;
DROP VIEW IF EXISTS current_light_status CASCADE;
DROP VIEW IF EXISTS emission_summary CASCADE;
DROP VIEW IF EXISTS active_trajectories CASCADE;
DROP VIEW IF EXISTS recent_detections CASCADE;
DROP VIEW IF EXISTS migration_status CASCADE;

-- Drop functions
DROP FUNCTION IF EXISTS calculate_performance_score CASCADE;
DROP FUNCTION IF EXISTS calculate_trajectory_stats CASCADE;
DROP FUNCTION IF EXISTS calculate_emissions CASCADE;
DROP FUNCTION IF EXISTS change_light_state CASCADE;
DROP FUNCTION IF EXISTS auto_resolve_alert CASCADE;
DROP FUNCTION IF EXISTS apply_migration CASCADE;
DROP FUNCTION IF EXISTS update_updated_at_column CASCADE;
DROP FUNCTION IF EXISTS confirm_rollback CASCADE;

-- Drop triggers
DROP TRIGGER IF EXISTS update_intersections_updated_at ON intersections;
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
DROP TRIGGER IF EXISTS update_sensor_devices_updated_at ON sensor_devices;
DROP TRIGGER IF EXISTS update_trajectories_updated_at ON trajectories;
DROP TRIGGER IF EXISTS calculate_trajectory_stats_trigger ON trajectories;
DROP TRIGGER IF EXISTS update_traffic_lights_updated_at ON traffic_lights;
DROP TRIGGER IF EXISTS update_alerts_updated_at ON alerts;
DROP TRIGGER IF EXISTS auto_resolve_alert_trigger ON alerts;
DROP TRIGGER IF EXISTS update_congestion_events_updated_at ON congestion_events;
DROP TRIGGER IF EXISTS update_system_config_updated_at ON system_config;

-- Migration 009: Drop analytics and config tables
DROP TABLE IF EXISTS performance_metrics CASCADE;
DROP TABLE IF EXISTS ml_predictions CASCADE;
DROP TABLE IF EXISTS system_config CASCADE;
DROP TABLE IF EXISTS analytics CASCADE;

-- Migration 008: Drop monitoring tables
DROP TABLE IF EXISTS traffic_metrics CASCADE;
DROP TABLE IF EXISTS congestion_events CASCADE;
DROP TABLE IF EXISTS alerts CASCADE;
DROP TABLE IF EXISTS system_logs CASCADE;

-- Migration 007: Drop traffic control tables
DROP TABLE IF EXISTS light_phases CASCADE;
DROP TABLE IF EXISTS traffic_lights CASCADE;

-- Migration 006: Drop emissions table
DROP TABLE IF EXISTS emissions CASCADE;

-- Migration 005: Drop trajectories table
DROP TABLE IF EXISTS trajectories CASCADE;

-- Migration 004: Drop detections table
DROP TABLE IF EXISTS traffic_detections CASCADE;

-- Migration 003: Drop sensor devices table
DROP TABLE IF EXISTS sensor_devices CASCADE;

-- Migration 002: Drop users and roles tables
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS user_roles CASCADE;

-- Migration 001: Drop intersections table
DROP TABLE IF EXISTS intersections CASCADE;

-- Drop migration tracking table
DROP TABLE IF EXISTS schema_migrations CASCADE;

-- Drop extensions (optional - comment out if used by other databases)
-- DROP EXTENSION IF EXISTS "uuid-ossp" CASCADE;
-- DROP EXTENSION IF EXISTS "postgis" CASCADE;
-- DROP EXTENSION IF EXISTS "pg_trgm" CASCADE;
-- DROP EXTENSION IF EXISTS "btree_gin" CASCADE;

-- Final message
DO $$
BEGIN
    RAISE NOTICE '========================================';
    RAISE NOTICE 'ROLLBACK COMPLETE';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'All tables have been dropped.';
    RAISE NOTICE 'To restore from backup, run:';
    RAISE NOTICE 'psql atms_db < backup_file.sql';
    RAISE NOTICE '========================================';
END $$;

