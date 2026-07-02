-- Migration 008: Create system monitoring tables
-- Purpose: System logs, alerts, and monitoring
-- Dependencies: 001_create_intersections.sql, 002_create_users.sql
-- Author: ATMS Team
-- Date: 2025-10-13

-- Create SYSTEM_LOGS table
CREATE TABLE IF NOT EXISTS system_logs (
    id BIGSERIAL PRIMARY KEY,
    component VARCHAR(100) NOT NULL,  -- ai_perception, sensor_fusion, decision_engine, etc.
    log_level VARCHAR(20) NOT NULL,  -- DEBUG, INFO, WARNING, ERROR, CRITICAL
    message TEXT NOT NULL,
    error_code VARCHAR(50),
    stack_trace TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for system_logs
CREATE INDEX IF NOT EXISTS idx_system_logs_component ON system_logs(component);
CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(log_level);
CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON system_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_system_logs_user ON system_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_system_logs_intersection ON system_logs(intersection_id);
CREATE INDEX IF NOT EXISTS idx_system_logs_error_code ON system_logs(error_code) WHERE error_code IS NOT NULL;

-- Create GIN index for metadata
CREATE INDEX IF NOT EXISTS idx_system_logs_metadata ON system_logs USING GIN(metadata);

-- Create ALERTS table
CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE CASCADE,
    alert_type VARCHAR(50) NOT NULL,  -- traffic_congestion, system_error, emergency_vehicle, sensor_failure
    severity VARCHAR(20) NOT NULL,  -- low, medium, high, critical
    title VARCHAR(255) NOT NULL,
    description TEXT,
    source_component VARCHAR(100),
    affected_devices JSONB,
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    acknowledged_at TIMESTAMP,
    resolved BOOLEAN DEFAULT FALSE,
    resolved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMP,
    resolution_notes TEXT,
    auto_resolve BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for alerts
CREATE INDEX IF NOT EXISTS idx_alerts_intersection ON alerts(intersection_id);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged ON alerts(acknowledged);
CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON alerts(resolved);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC);

-- Create trigger for alerts updated_at
CREATE TRIGGER update_alerts_updated_at
    BEFORE UPDATE ON alerts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Create CONGESTION_EVENTS table
CREATE TABLE IF NOT EXISTS congestion_events (
    id SERIAL PRIMARY KEY,
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE CASCADE,
    direction VARCHAR(50),
    severity VARCHAR(20) NOT NULL,  -- light, moderate, heavy, severe
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_minutes INTEGER,
    max_queue_length INTEGER,
    avg_wait_time_seconds INTEGER,
    vehicles_affected INTEGER,
    cause VARCHAR(100),  -- high_volume, accident, signal_malfunction, weather, special_event
    resolved_by VARCHAR(100),  -- auto, manual, signal_optimization, traffic_cleared
    impact_score DECIMAL(5, 2),  -- 0-100 scale
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for congestion_events
CREATE INDEX IF NOT EXISTS idx_congestion_intersection ON congestion_events(intersection_id);
CREATE INDEX IF NOT EXISTS idx_congestion_severity ON congestion_events(severity);
CREATE INDEX IF NOT EXISTS idx_congestion_start ON congestion_events(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_congestion_direction ON congestion_events(direction);
CREATE INDEX IF NOT EXISTS idx_congestion_active ON congestion_events(end_time) WHERE end_time IS NULL;

-- Create trigger for congestion_events updated_at
CREATE TRIGGER update_congestion_events_updated_at
    BEFORE UPDATE ON congestion_events
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Create TRAFFIC_METRICS table (if not exists)
CREATE TABLE IF NOT EXISTS traffic_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE CASCADE,
    metric_type VARCHAR(50) NOT NULL,  -- volume, speed, density, occupancy, queue_length
    direction VARCHAR(50),
    value DECIMAL(10, 2) NOT NULL,
    unit VARCHAR(20),  -- vehicles/hour, km/h, vehicles/km, percentage, vehicles
    aggregation_period VARCHAR(20),  -- 1min, 5min, 15min, 1hour, 1day
    metadata JSONB DEFAULT '{}',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for traffic_metrics
CREATE INDEX IF NOT EXISTS idx_traffic_metrics_intersection ON traffic_metrics(intersection_id);
CREATE INDEX IF NOT EXISTS idx_traffic_metrics_type ON traffic_metrics(metric_type);
CREATE INDEX IF NOT EXISTS idx_traffic_metrics_timestamp ON traffic_metrics(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_traffic_metrics_direction ON traffic_metrics(direction);

-- Create function to auto-resolve alerts
CREATE OR REPLACE FUNCTION auto_resolve_alert()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.auto_resolve = TRUE AND NEW.acknowledged = TRUE AND NEW.resolved = FALSE THEN
        NEW.resolved := TRUE;
        NEW.resolved_at := CURRENT_TIMESTAMP;
        NEW.resolved_by := NEW.acknowledged_by;
        NEW.resolution_notes := 'Auto-resolved after acknowledgment';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for auto-resolve
CREATE TRIGGER auto_resolve_alert_trigger
    BEFORE UPDATE ON alerts
    FOR EACH ROW
    WHEN (NEW.acknowledged = TRUE AND OLD.acknowledged = FALSE)
    EXECUTE FUNCTION auto_resolve_alert();

-- Create views for monitoring
CREATE OR REPLACE VIEW active_alerts AS
SELECT 
    a.id,
    a.intersection_id,
    i.name as intersection_name,
    a.alert_type,
    a.severity,
    a.title,
    a.description,
    a.acknowledged,
    u1.username as acknowledged_by_user,
    a.acknowledged_at,
    a.created_at,
    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - a.created_at))/60 as minutes_active
FROM alerts a
LEFT JOIN intersections i ON a.intersection_id = i.id
LEFT JOIN users u1 ON a.acknowledged_by = u1.id
WHERE a.resolved = FALSE
ORDER BY 
    CASE a.severity
        WHEN 'critical' THEN 1
        WHEN 'high' THEN 2
        WHEN 'medium' THEN 3
        WHEN 'low' THEN 4
    END,
    a.created_at DESC;

CREATE OR REPLACE VIEW recent_errors AS
SELECT 
    sl.id,
    sl.component,
    sl.log_level,
    sl.message,
    sl.error_code,
    sl.intersection_id,
    i.name as intersection_name,
    sl.timestamp
FROM system_logs sl
LEFT JOIN intersections i ON sl.intersection_id = i.id
WHERE sl.log_level IN ('ERROR', 'CRITICAL')
    AND sl.timestamp > NOW() - INTERVAL '24 hours'
ORDER BY sl.timestamp DESC;

-- Comments
COMMENT ON TABLE system_logs IS 'System-wide logging for all components';
COMMENT ON TABLE alerts IS 'Alert and notification management';
COMMENT ON TABLE congestion_events IS 'Traffic congestion event tracking and analysis';
COMMENT ON TABLE traffic_metrics IS 'Aggregated traffic metrics and KPIs';
COMMENT ON COLUMN alerts.severity IS 'Alert severity: low, medium, high, critical';
COMMENT ON COLUMN congestion_events.impact_score IS 'Congestion impact score (0-100)';

