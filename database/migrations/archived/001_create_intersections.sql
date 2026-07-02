-- Migration 001: Create INTERSECTIONS table (Central Hub)
-- Purpose: Central hub for all intersection-related data
-- Dependencies: None
-- Author: ATMS Team
-- Date: 2025-10-13

-- Create INTERSECTIONS table
CREATE TABLE IF NOT EXISTS intersections (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    location GEOGRAPHY(POINT, 4326),  -- PostGIS for geospatial data
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    configuration JSONB DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'active',
    timezone VARCHAR(50) DEFAULT 'UTC',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_intersections_name ON intersections(name);
CREATE INDEX IF NOT EXISTS idx_intersections_status ON intersections(status);
CREATE INDEX IF NOT EXISTS idx_intersections_location ON intersections USING GIST(location);

-- Create trigger for updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_intersections_updated_at
    BEFORE UPDATE ON intersections
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Insert default intersection
INSERT INTO intersections (id, name, latitude, longitude, configuration)
VALUES (1, 'Main Intersection', 37.7749, -122.4194, '{"lanes": 4, "type": "urban"}')
ON CONFLICT (id) DO NOTHING;

-- Comments
COMMENT ON TABLE intersections IS 'Central hub for intersection metadata and configuration';
COMMENT ON COLUMN intersections.id IS 'Primary key - intersection identifier';
COMMENT ON COLUMN intersections.name IS 'Human-readable intersection name';
COMMENT ON COLUMN intersections.location IS 'Geographic location (PostGIS POINT)';
COMMENT ON COLUMN intersections.configuration IS 'JSON configuration data';
COMMENT ON COLUMN intersections.status IS 'Intersection status: active, inactive, maintenance';

