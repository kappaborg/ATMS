-- Migration 005: Create TRAJECTORIES table
-- Purpose: Store vehicle trajectory data from Kalman Filter tracking
-- Dependencies: 001_create_intersections.sql
-- Author: ATMS Team
-- Date: 2025-10-13

-- Create TRAJECTORIES table
CREATE TABLE IF NOT EXISTS trajectories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    track_id VARCHAR(50) UNIQUE NOT NULL,
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE CASCADE,
    vehicle_class VARCHAR(50),
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    total_detections INTEGER DEFAULT 0,
    average_velocity DECIMAL(8, 2),  -- meters per second
    max_velocity DECIMAL(8, 2),
    min_velocity DECIMAL(8, 2),
    velocity_magnitude DECIMAL(8, 2),
    distance_traveled DECIMAL(10, 2),  -- meters
    trajectory_path JSONB,  -- Array of [x, y] positions
    velocities JSONB,  -- Array of velocity values
    positions JSONB,  -- Detailed position history
    direction VARCHAR(50),  -- north, south, east, west, northeast, etc.
    status VARCHAR(50) DEFAULT 'active',  -- active, completed, lost
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_trajectories_track_id ON trajectories(track_id);
CREATE INDEX IF NOT EXISTS idx_trajectories_intersection ON trajectories(intersection_id);
CREATE INDEX IF NOT EXISTS idx_trajectories_vehicle_class ON trajectories(vehicle_class);
CREATE INDEX IF NOT EXISTS idx_trajectories_first_seen ON trajectories(first_seen DESC);
CREATE INDEX IF NOT EXISTS idx_trajectories_last_seen ON trajectories(last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_trajectories_status ON trajectories(status);

-- Create GIN indexes for JSONB
CREATE INDEX IF NOT EXISTS idx_trajectories_path ON trajectories USING GIN(trajectory_path);
CREATE INDEX IF NOT EXISTS idx_trajectories_positions ON trajectories USING GIN(positions);

-- Create trigger for updated_at
CREATE TRIGGER update_trajectories_updated_at
    BEFORE UPDATE ON trajectories
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Create function to calculate trajectory statistics
CREATE OR REPLACE FUNCTION calculate_trajectory_stats()
RETURNS TRIGGER AS $$
BEGIN
    -- Calculate distance traveled from positions
    IF NEW.positions IS NOT NULL THEN
        NEW.distance_traveled := (
            SELECT SUM(
                SQRT(
                    POWER((pos->>'x')::DECIMAL - LAG((pos->>'x')::DECIMAL) OVER (ORDER BY ordinality), 2) +
                    POWER((pos->>'y')::DECIMAL - LAG((pos->>'y')::DECIMAL) OVER (ORDER BY ordinality), 2)
                )
            )
            FROM jsonb_array_elements(NEW.positions) WITH ORDINALITY AS pos
        );
    END IF;
    
    -- Calculate velocity stats from velocities array
    IF NEW.velocities IS NOT NULL THEN
        NEW.average_velocity := (
            SELECT AVG((value->>'magnitude')::DECIMAL)
            FROM jsonb_array_elements(NEW.velocities) AS value
        );
        NEW.max_velocity := (
            SELECT MAX((value->>'magnitude')::DECIMAL)
            FROM jsonb_array_elements(NEW.velocities) AS value
        );
        NEW.min_velocity := (
            SELECT MIN((value->>'magnitude')::DECIMAL)
            FROM jsonb_array_elements(NEW.velocities) AS value
        );
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for automatic stats calculation
CREATE TRIGGER calculate_trajectory_stats_trigger
    BEFORE INSERT OR UPDATE ON trajectories
    FOR EACH ROW
    WHEN (NEW.positions IS NOT NULL OR NEW.velocities IS NOT NULL)
    EXECUTE FUNCTION calculate_trajectory_stats();

-- Create view for active trajectories
CREATE OR REPLACE VIEW active_trajectories AS
SELECT 
    t.id,
    t.track_id,
    t.intersection_id,
    i.name as intersection_name,
    t.vehicle_class,
    t.average_velocity,
    t.distance_traveled,
    t.total_detections,
    EXTRACT(EPOCH FROM (t.last_seen - t.first_seen)) as duration_seconds,
    t.status,
    t.last_seen
FROM trajectories t
LEFT JOIN intersections i ON t.intersection_id = i.id
WHERE t.status = 'active'
ORDER BY t.last_seen DESC;

-- Comments
COMMENT ON TABLE trajectories IS 'Vehicle trajectory data from Kalman Filter tracking';
COMMENT ON COLUMN trajectories.track_id IS 'Unique track identifier from tracking algorithm';
COMMENT ON COLUMN trajectories.trajectory_path IS 'Array of [x,y] positions representing vehicle path';
COMMENT ON COLUMN trajectories.velocities IS 'Array of velocity measurements over time';
COMMENT ON COLUMN trajectories.status IS 'Track status: active, completed, lost';
COMMENT ON COLUMN trajectories.distance_traveled IS 'Total distance traveled in meters';

