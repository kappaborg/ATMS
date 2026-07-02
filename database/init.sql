-- ATMS Database Schema
-- =====================
-- Database initialization script for Adaptive Traffic Management System

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- CREATE EXTENSION IF NOT EXISTS "postgis";  -- Optional: Uncomment if PostGIS is installed

-- ============================================
-- Intersections Table
-- ============================================
CREATE TABLE IF NOT EXISTS intersections (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    location_lat DECIMAL(10, 8),
    location_lng DECIMAL(11, 8),
    description TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- Cameras Table
-- ============================================
CREATE TABLE IF NOT EXISTS cameras (
    id SERIAL PRIMARY KEY,
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    camera_url VARCHAR(512),
    camera_type VARCHAR(50),  -- 'RTSP', 'MJPEG', 'HTTP'
    view_type VARCHAR(50),  -- 'top_view', 'side_profile', 'front_bumper'
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- Detections Table
-- ============================================
CREATE TABLE IF NOT EXISTS detections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    intersection_id INTEGER REFERENCES intersections(id),
    camera_id INTEGER REFERENCES cameras(id),
    frame_id VARCHAR(100),
    object_class VARCHAR(50),  -- 'minivan', 'sedan', 'suv', 'pedestrian', etc.
    confidence DECIMAL(5, 4),
    bbox_x1 DECIMAL(10, 2),
    bbox_y1 DECIMAL(10, 2),
    bbox_x2 DECIMAL(10, 2),
    bbox_y2 DECIMAL(10, 2),
    detection_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster queries
CREATE INDEX idx_detections_timestamp ON detections(detection_timestamp);
CREATE INDEX idx_detections_intersection ON detections(intersection_id);
CREATE INDEX idx_detections_class ON detections(object_class);

-- ============================================
-- Trajectories Table
-- ============================================
CREATE TABLE IF NOT EXISTS trajectories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    track_id INTEGER NOT NULL,
    intersection_id INTEGER REFERENCES intersections(id),
    vehicle_class VARCHAR(50),
    start_timestamp TIMESTAMP,
    end_timestamp TIMESTAMP,
    total_frames INTEGER DEFAULT 0,
    average_velocity DECIMAL(10, 2),
    trajectory_path JSONB,  -- Store full trajectory as JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster queries
CREATE INDEX idx_trajectories_track_id ON trajectories(track_id);
CREATE INDEX idx_trajectories_intersection ON trajectories(intersection_id);
CREATE INDEX idx_trajectories_start_time ON trajectories(start_timestamp);

-- ============================================
-- Emissions Table
-- ============================================
CREATE TABLE IF NOT EXISTS emissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trajectory_id UUID REFERENCES trajectories(id),
    intersection_id INTEGER REFERENCES intersections(id),
    vehicle_class VARCHAR(50),
    co2_grams DECIMAL(10, 2),
    nox_grams DECIMAL(10, 4),
    pm_grams DECIMAL(10, 6),
    co_grams DECIMAL(10, 4),
    hc_grams DECIMAL(10, 4),
    co2_equivalent_grams DECIMAL(10, 2),  -- Total CO2 equivalent
    fuel_consumed_liters DECIMAL(10, 3),  -- Fuel consumption
    fuel_cost_dollars DECIMAL(10, 2),     -- Fuel cost
    cost_per_km DECIMAL(10, 3),           -- Cost efficiency
    efficiency_score DECIMAL(5, 2),       -- Efficiency rating (0-100)
    distance_meters DECIMAL(10, 2),
    average_speed_kmh DECIMAL(8, 2),
    max_speed_kmh DECIMAL(8, 2),          -- Maximum speed
    idle_time_seconds INTEGER,
    acceleration_events INTEGER,          -- Number of acceleration events
    environmental_impact_score DECIMAL(5, 2),
    emission_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster queries
CREATE INDEX idx_emissions_timestamp ON emissions(emission_timestamp);
CREATE INDEX idx_emissions_intersection ON emissions(intersection_id);
CREATE INDEX idx_emissions_vehicle_class ON emissions(vehicle_class);

-- ============================================
-- Traffic Metrics Table
-- ============================================
CREATE TABLE IF NOT EXISTS traffic_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    intersection_id INTEGER REFERENCES intersections(id),
    metric_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_vehicles INTEGER DEFAULT 0,
    vehicles_by_class JSONB,  -- {'minivan': 5, 'sedan': 10, 'suv': 3}
    average_speed_kmh DECIMAL(8, 2),
    average_waiting_time_seconds INTEGER,
    total_emissions_co2 DECIMAL(10, 2),
    traffic_density VARCHAR(20),  -- 'low', 'medium', 'high', 'congested'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster queries
CREATE INDEX idx_traffic_metrics_timestamp ON traffic_metrics(metric_timestamp);
CREATE INDEX idx_traffic_metrics_intersection ON traffic_metrics(intersection_id);

-- ============================================
-- Decisions Table
-- ============================================
CREATE TABLE IF NOT EXISTS decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    intersection_id INTEGER REFERENCES intersections(id),
    decision_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    current_phase VARCHAR(50),
    recommended_phase VARCHAR(50),
    priority VARCHAR(20),  -- 'emergency', 'high', 'medium', 'low'
    reason TEXT,
    confidence DECIMAL(5, 4),
    expected_impact JSONB,  -- {'emission_reduction': 30, 'flow_improvement': 25}
    was_executed BOOLEAN DEFAULT false,
    execution_timestamp TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster queries
CREATE INDEX idx_decisions_timestamp ON decisions(decision_timestamp);
CREATE INDEX idx_decisions_intersection ON decisions(intersection_id);
CREATE INDEX idx_decisions_priority ON decisions(priority);

-- ============================================
-- Signal Events Table
-- ============================================
CREATE TABLE IF NOT EXISTS signal_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    intersection_id INTEGER REFERENCES intersections(id),
    direction VARCHAR(50),  -- 'north_south', 'east_west'
    previous_state VARCHAR(20),
    new_state VARCHAR(20),  -- 'red', 'yellow', 'green'
    event_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    duration_seconds INTEGER,
    is_manual BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster queries
CREATE INDEX idx_signal_events_timestamp ON signal_events(event_timestamp);
CREATE INDEX idx_signal_events_intersection ON signal_events(intersection_id);

-- ============================================
-- Alerts Table
-- ============================================
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    intersection_id INTEGER REFERENCES intersections(id),
    alert_type VARCHAR(50),  -- 'phase_change', 'manual_control', 'emergency', 'system'
    severity VARCHAR(20),  -- 'info', 'warning', 'error', 'critical'
    title VARCHAR(255),
    message TEXT,
    metadata JSONB,
    is_acknowledged BOOLEAN DEFAULT false,
    acknowledged_at TIMESTAMP,
    alert_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster queries
CREATE INDEX idx_alerts_timestamp ON alerts(alert_timestamp);
CREATE INDEX idx_alerts_intersection ON alerts(intersection_id);
CREATE INDEX idx_alerts_severity ON alerts(severity);
CREATE INDEX idx_alerts_acknowledged ON alerts(is_acknowledged);

-- ============================================
-- System Metrics Table (for monitoring)
-- ============================================
CREATE TABLE IF NOT EXISTS system_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service_name VARCHAR(100),
    metric_name VARCHAR(100),
    metric_value DECIMAL(12, 4),
    metric_unit VARCHAR(50),
    metric_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster queries
CREATE INDEX idx_system_metrics_timestamp ON system_metrics(metric_timestamp);
CREATE INDEX idx_system_metrics_service ON system_metrics(service_name);

-- ============================================
-- Insert Default Data
-- ============================================

-- Insert default intersection
INSERT INTO intersections (id, name, location_lat, location_lng, description, is_active)
VALUES 
    (1, 'Main Intersection 1', 37.7749, -122.4194, 'Primary test intersection', true)
ON CONFLICT (id) DO NOTHING;

-- Insert default camera
INSERT INTO cameras (id, intersection_id, name, camera_url, camera_type, view_type, is_active)
VALUES 
    (1, 1, 'iPhone Camera', 'http://192.168.0.10:8081/video', 'MJPEG', 'side_profile', true)
ON CONFLICT (id) DO NOTHING;

-- ============================================
-- Create Functions
-- ============================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updating updated_at
CREATE TRIGGER update_intersections_updated_at BEFORE UPDATE ON intersections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_cameras_updated_at BEFORE UPDATE ON cameras
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- Create Views for Analytics
-- ============================================

-- View: Hourly Traffic Summary
CREATE OR REPLACE VIEW hourly_traffic_summary AS
SELECT 
    intersection_id,
    DATE_TRUNC('hour', metric_timestamp) as hour,
    AVG(total_vehicles) as avg_vehicles,
    AVG(average_speed_kmh) as avg_speed,
    SUM(total_emissions_co2) as total_co2,
    COUNT(*) as data_points
FROM traffic_metrics
GROUP BY intersection_id, DATE_TRUNC('hour', metric_timestamp)
ORDER BY hour DESC;

-- View: Recent Detections Summary
CREATE OR REPLACE VIEW recent_detections_summary AS
SELECT 
    intersection_id,
    object_class,
    COUNT(*) as detection_count,
    AVG(confidence) as avg_confidence,
    MAX(detection_timestamp) as last_detection
FROM detections
WHERE detection_timestamp > NOW() - INTERVAL '1 hour'
GROUP BY intersection_id, object_class;

-- View: Active Alerts
CREATE OR REPLACE VIEW active_alerts AS
SELECT 
    id,
    intersection_id,
    alert_type,
    severity,
    title,
    message,
    alert_timestamp
FROM alerts
WHERE is_acknowledged = false
ORDER BY 
    CASE severity
        WHEN 'critical' THEN 1
        WHEN 'error' THEN 2
        WHEN 'warning' THEN 3
        WHEN 'info' THEN 4
    END,
    alert_timestamp DESC;

-- ============================================
-- Grant Permissions
-- ============================================

-- Grant all privileges to atms_user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO atms_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO atms_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO atms_user;

-- ============================================
-- Completion Message
-- ============================================

DO $$
BEGIN
    RAISE NOTICE '============================================';
    RAISE NOTICE 'ATMS Database Schema Initialized Successfully!';
    RAISE NOTICE '============================================';
    RAISE NOTICE 'Database: atms';
    RAISE NOTICE 'User: atms_user';
    RAISE NOTICE 'Tables Created: 10';
    RAISE NOTICE 'Views Created: 3';
    RAISE NOTICE 'Indexes Created: 16';
    RAISE NOTICE 'Features: Emissions, Fuel, Cost tracking';
    RAISE NOTICE '============================================';
END $$;
