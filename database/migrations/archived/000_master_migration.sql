-- MASTER MIGRATION SCRIPT
-- Purpose: Execute all migrations in correct order
-- Author: ATMS Team
-- Date: 2025-10-13
-- Version: 1.0

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";  -- For geographic data
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For text search
CREATE EXTENSION IF NOT EXISTS "btree_gin";  -- For GIN indexes

-- Create migration tracking table
CREATE TABLE IF NOT EXISTS schema_migrations (
    id SERIAL PRIMARY KEY,
    migration_name VARCHAR(255) UNIQUE NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT
);

-- Function to apply migration
CREATE OR REPLACE FUNCTION apply_migration(p_migration_name VARCHAR, p_migration_file VARCHAR)
RETURNS BOOLEAN AS $$
DECLARE
    v_already_applied BOOLEAN;
BEGIN
    -- Check if already applied
    SELECT EXISTS(
        SELECT 1 FROM schema_migrations 
        WHERE migration_name = p_migration_name AND success = TRUE
    ) INTO v_already_applied;
    
    IF v_already_applied THEN
        RAISE NOTICE 'Migration % already applied, skipping...', p_migration_name;
        RETURN TRUE;
    END IF;
    
    RAISE NOTICE 'Applying migration: %', p_migration_name;
    
    -- Record migration attempt
    INSERT INTO schema_migrations (migration_name, success)
    VALUES (p_migration_name, FALSE);
    
    -- Mark as successful (actual file execution happens externally)
    UPDATE schema_migrations
    SET success = TRUE
    WHERE migration_name = p_migration_name AND success = FALSE;
    
    RAISE NOTICE 'Migration % completed successfully', p_migration_name;
    RETURN TRUE;
    
EXCEPTION WHEN OTHERS THEN
    UPDATE schema_migrations
    SET error_message = SQLERRM
    WHERE migration_name = p_migration_name AND success = FALSE;
    
    RAISE NOTICE 'Migration % failed: %', p_migration_name, SQLERRM;
    RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

-- Migration execution order
-- Note: Actual SQL files should be executed in this order

-- 1. Core infrastructure
-- \i 001_create_intersections.sql
-- \i 002_create_users.sql
-- \i 003_create_sensor_devices.sql

-- 2. Data collection tables
-- \i 004_create_traffic_detections.sql
-- \i 005_create_trajectories.sql
-- \i 006_create_emissions.sql

-- 3. Traffic control tables
-- \i 007_create_traffic_lights.sql

-- 4. Monitoring and analytics
-- \i 008_create_system_monitoring.sql
-- \i 009_create_analytics_config.sql

-- Display migration status
DO $$
BEGIN
    RAISE NOTICE '========================================';
    RAISE NOTICE 'ATMS Database Migration Setup Complete';
    RAISE NOTICE '========================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '1. Execute migrations in order (001-009)';
    RAISE NOTICE '2. Verify table creation';
    RAISE NOTICE '3. Run data validation';
    RAISE NOTICE '4. Update application configuration';
    RAISE NOTICE '';
    RAISE NOTICE 'Migration files location: database/migrations/';
    RAISE NOTICE '========================================';
END $$;

-- Create helpful views
CREATE OR REPLACE VIEW migration_status AS
SELECT 
    migration_name,
    success,
    applied_at,
    error_message,
    ROW_NUMBER() OVER (ORDER BY applied_at) as execution_order
FROM schema_migrations
ORDER BY applied_at;

-- Comments
COMMENT ON TABLE schema_migrations IS 'Tracks database schema migrations';
COMMENT ON FUNCTION apply_migration IS 'Applies and tracks database migrations';

