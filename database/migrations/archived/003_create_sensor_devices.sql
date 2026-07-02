-- Migration 003: Create SENSOR_DEVICES table
-- Purpose: Registry for all sensor devices (cameras, detectors, etc.)
-- Dependencies: 001_create_intersections.sql
-- Author: ATMS Team
-- Date: 2025-10-13

-- Create SENSOR_DEVICES table
CREATE TABLE IF NOT EXISTS sensor_devices (
    id SERIAL PRIMARY KEY,
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE CASCADE,
    device_type VARCHAR(50) NOT NULL,  -- camera, radar, lidar, loop_detector
    model VARCHAR(100),
    manufacturer VARCHAR(100),
    serial_number VARCHAR(100) UNIQUE,
    ip_address INET,
    port INTEGER,
    rtsp_url TEXT,
    http_url TEXT,
    configuration JSONB DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'active',  -- active, inactive, maintenance, error
    last_maintenance DATE,
    next_maintenance DATE,
    firmware_version VARCHAR(50),
    installation_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_sensor_devices_intersection ON sensor_devices(intersection_id);
CREATE INDEX IF NOT EXISTS idx_sensor_devices_type ON sensor_devices(device_type);
CREATE INDEX IF NOT EXISTS idx_sensor_devices_status ON sensor_devices(status);
CREATE INDEX IF NOT EXISTS idx_sensor_devices_ip ON sensor_devices(ip_address);

-- Create trigger for updated_at
CREATE TRIGGER update_sensor_devices_updated_at
    BEFORE UPDATE ON sensor_devices
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Migrate existing camera_sources if they exist
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'camera_sources') THEN
        INSERT INTO sensor_devices (
            intersection_id, 
            device_type, 
            model, 
            ip_address, 
            rtsp_url, 
            http_url, 
            configuration, 
            status
        )
        SELECT 
            1 as intersection_id,  -- Default intersection
            'camera' as device_type,
            model,
            ip_address::INET,
            rtsp_url,
            http_url,
            configuration,
            status
        FROM camera_sources
        WHERE NOT EXISTS (
            SELECT 1 FROM sensor_devices WHERE serial_number = camera_sources.id::TEXT
        );
    END IF;
END $$;

-- Insert default camera device
INSERT INTO sensor_devices (
    id, 
    intersection_id, 
    device_type, 
    model, 
    ip_address, 
    port,
    http_url,
    configuration,
    status
)
VALUES (
    1,
    1,
    'camera',
    'IP Webcam',
    '192.168.0.11',
    8081,
    'http://192.168.0.11:8081/video',
    '{"resolution": "640x640", "fps": 30, "format": "MJPEG"}',
    'active'
)
ON CONFLICT (id) DO UPDATE SET
    http_url = EXCLUDED.http_url,
    configuration = EXCLUDED.configuration,
    updated_at = CURRENT_TIMESTAMP;

-- Comments
COMMENT ON TABLE sensor_devices IS 'Registry for all sensor devices including cameras, radars, and detectors';
COMMENT ON COLUMN sensor_devices.device_type IS 'Type of sensor: camera, radar, lidar, loop_detector';
COMMENT ON COLUMN sensor_devices.status IS 'Device status: active, inactive, maintenance, error';
COMMENT ON COLUMN sensor_devices.configuration IS 'Device-specific configuration in JSON format';

