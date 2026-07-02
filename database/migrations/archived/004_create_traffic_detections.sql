-- Migration 004: Create/Update TRAFFIC_DETECTIONS table
-- Purpose: Store all vehicle detections from AI models
-- Dependencies: 001_create_intersections.sql, 003_create_sensor_devices.sql
-- Author: ATMS Team
-- Date: 2025-10-13

-- Create TRAFFIC_DETECTIONS table (or update existing detections table)
CREATE TABLE IF NOT EXISTS traffic_detections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE CASCADE,
    sensor_id INTEGER REFERENCES sensor_devices(id) ON DELETE SET NULL,
    frame_id VARCHAR(50),
    object_type VARCHAR(50) NOT NULL,  -- vehicle, pedestrian, cyclist, etc.
    vehicle_class VARCHAR(50),  -- sedan, suv, minivan, truck, bus
    confidence DECIMAL(5, 4) NOT NULL,
    bbox JSONB,  -- {x1, y1, x2, y2} or {x, y, width, height}
    position_x INTEGER,
    position_y INTEGER,
    speed_kmh DECIMAL(6, 2),
    direction_degrees INTEGER,
    view_type VARCHAR(50),  -- top_view, side_profile, front_bumper
    contributing_views JSONB,
    fusion_confidence DECIMAL(5, 4),
    metadata JSONB DEFAULT '{}',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_traffic_detections_intersection ON traffic_detections(intersection_id);
CREATE INDEX IF NOT EXISTS idx_traffic_detections_sensor ON traffic_detections(sensor_id);
CREATE INDEX IF NOT EXISTS idx_traffic_detections_timestamp ON traffic_detections(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_traffic_detections_object_type ON traffic_detections(object_type);
CREATE INDEX IF NOT EXISTS idx_traffic_detections_vehicle_class ON traffic_detections(vehicle_class);
CREATE INDEX IF NOT EXISTS idx_traffic_detections_frame ON traffic_detections(frame_id);

-- Create GIN index for JSONB columns
CREATE INDEX IF NOT EXISTS idx_traffic_detections_bbox ON traffic_detections USING GIN(bbox);
CREATE INDEX IF NOT EXISTS idx_traffic_detections_metadata ON traffic_detections USING GIN(metadata);

-- Migrate data from old 'detections' table if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_name = 'detections' 
        AND table_name != 'traffic_detections'
    ) THEN
        -- Copy data from old table
        INSERT INTO traffic_detections (
            id,
            intersection_id,
            sensor_id,
            frame_id,
            object_type,
            vehicle_class,
            confidence,
            bbox,
            view_type,
            contributing_views,
            fusion_confidence,
            timestamp,
            created_at
        )
        SELECT 
            id,
            COALESCE(intersection_id, 1),  -- Default to intersection 1
            camera_id,  -- Map camera_id to sensor_id
            frame_id,
            'vehicle' as object_type,
            vehicle_class,
            confidence,
            bbox,
            view_type,
            contributing_views,
            fusion_confidence,
            timestamp,
            created_at
        FROM detections
        WHERE NOT EXISTS (
            SELECT 1 FROM traffic_detections WHERE traffic_detections.id = detections.id
        );
        
        RAISE NOTICE 'Migrated data from detections to traffic_detections';
    END IF;
END $$;

-- Create view for easy querying
CREATE OR REPLACE VIEW recent_detections AS
SELECT 
    td.id,
    td.intersection_id,
    i.name as intersection_name,
    td.sensor_id,
    sd.device_type,
    td.object_type,
    td.vehicle_class,
    td.confidence,
    td.speed_kmh,
    td.direction_degrees,
    td.timestamp
FROM traffic_detections td
LEFT JOIN intersections i ON td.intersection_id = i.id
LEFT JOIN sensor_devices sd ON td.sensor_id = sd.id
WHERE td.timestamp > NOW() - INTERVAL '1 hour'
ORDER BY td.timestamp DESC;

-- Comments
COMMENT ON TABLE traffic_detections IS 'All vehicle and object detections from AI models';
COMMENT ON COLUMN traffic_detections.object_type IS 'Type of detected object: vehicle, pedestrian, cyclist';
COMMENT ON COLUMN traffic_detections.vehicle_class IS 'Vehicle classification: sedan, suv, minivan, truck, bus';
COMMENT ON COLUMN traffic_detections.bbox IS 'Bounding box coordinates in JSON format';
COMMENT ON COLUMN traffic_detections.contributing_views IS 'Multi-view fusion - which views contributed to detection';
COMMENT ON COLUMN traffic_detections.fusion_confidence IS 'Confidence score after multi-view fusion';

