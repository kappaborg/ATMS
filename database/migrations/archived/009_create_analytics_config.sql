-- Migration 009: Create analytics and configuration tables
-- Purpose: Analytics data and system configuration
-- Dependencies: 001_create_intersections.sql
-- Author: ATMS Team
-- Date: 2025-10-13

-- Create ANALYTICS table
CREATE TABLE IF NOT EXISTS analytics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE CASCADE,
    analytics_type VARCHAR(50) NOT NULL,  -- hourly_summary, daily_report, performance_metrics, ml_predictions
    time_period VARCHAR(50),  -- hour, day, week, month
    data JSONB NOT NULL,
    metrics JSONB,
    insights JSONB,
    recommendations JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for analytics
CREATE INDEX IF NOT EXISTS idx_analytics_intersection ON analytics(intersection_id);
CREATE INDEX IF NOT EXISTS idx_analytics_type ON analytics(analytics_type);
CREATE INDEX IF NOT EXISTS idx_analytics_period ON analytics(time_period);
CREATE INDEX IF NOT EXISTS idx_analytics_created ON analytics(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_data ON analytics USING GIN(data);

-- Create SYSTEM_CONFIG table
CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    category VARCHAR(50),  -- ai_models, traffic_control, sensors, alerts, system
    description TEXT,
    is_encrypted BOOLEAN DEFAULT FALSE,
    last_modified_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for system_config
CREATE INDEX IF NOT EXISTS idx_system_config_category ON system_config(category);
CREATE INDEX IF NOT EXISTS idx_system_config_updated ON system_config(updated_at DESC);

-- Create trigger for system_config updated_at
CREATE TRIGGER update_system_config_updated_at
    BEFORE UPDATE ON system_config
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Create ML_PREDICTIONS table
CREATE TABLE IF NOT EXISTS ml_predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE CASCADE,
    prediction_type VARCHAR(50) NOT NULL,  -- traffic_volume, congestion, arrival_time, signal_timing
    model_name VARCHAR(100),
    model_version VARCHAR(20),
    prediction_horizon_minutes INTEGER,
    predicted_value DECIMAL(10, 2),
    confidence DECIMAL(5, 4),
    actual_value DECIMAL(10, 2),
    accuracy DECIMAL(5, 4),
    features JSONB,
    metadata JSONB DEFAULT '{}',
    prediction_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    target_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for ml_predictions
CREATE INDEX IF NOT EXISTS idx_ml_predictions_intersection ON ml_predictions(intersection_id);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_type ON ml_predictions(prediction_type);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_model ON ml_predictions(model_name);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_time ON ml_predictions(prediction_time DESC);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_target ON ml_predictions(target_time);

-- Insert default system configurations
INSERT INTO system_config (key, value, category, description) VALUES
    ('ai_models.detection_threshold', '0.5', 'ai_models', 'Minimum confidence threshold for vehicle detection'),
    ('ai_models.tracking_max_age', '30', 'ai_models', 'Maximum age (frames) for trajectory tracking'),
    ('ai_models.fusion_weights', '{"top_view": 0.3, "side_profile": 0.4, "front_bumper": 0.3}', 'ai_models', 'Multi-view fusion weights'),
    ('traffic_control.min_green_time', '10', 'traffic_control', 'Minimum green light duration (seconds)'),
    ('traffic_control.max_green_time', '60', 'traffic_control', 'Maximum green light duration (seconds)'),
    ('traffic_control.yellow_time', '3', 'traffic_control', 'Yellow light duration (seconds)'),
    ('traffic_control.all_red_time', '2', 'traffic_control', 'All-red clearance time (seconds)'),
    ('sensors.health_check_interval', '60', 'sensors', 'Sensor health check interval (seconds)'),
    ('sensors.retry_attempts', '3', 'sensors', 'Number of retry attempts for failed sensors'),
    ('alerts.critical_threshold', '80', 'alerts', 'Threshold for critical alerts (percentage)'),
    ('alerts.email_notifications', 'true', 'alerts', 'Enable email notifications for alerts'),
    ('system.data_retention_days', '90', 'system', 'Data retention period (days)'),
    ('system.log_level', 'INFO', 'system', 'System-wide logging level')
ON CONFLICT (key) DO NOTHING;

-- Create PERFORMANCE_METRICS table
CREATE TABLE IF NOT EXISTS performance_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE CASCADE,
    metric_name VARCHAR(100) NOT NULL,
    metric_value DECIMAL(12, 4) NOT NULL,
    metric_unit VARCHAR(20),
    benchmark_value DECIMAL(12, 4),
    performance_score DECIMAL(5, 2),  -- 0-100 scale
    time_period VARCHAR(20),  -- real_time, 1hour, 1day, 1week
    metadata JSONB DEFAULT '{}',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance_metrics
CREATE INDEX IF NOT EXISTS idx_performance_metrics_intersection ON performance_metrics(intersection_id);
CREATE INDEX IF NOT EXISTS idx_performance_metrics_name ON performance_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_performance_metrics_timestamp ON performance_metrics(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_performance_metrics_period ON performance_metrics(time_period);

-- Create function to calculate performance score
CREATE OR REPLACE FUNCTION calculate_performance_score(
    p_metric_name VARCHAR,
    p_metric_value DECIMAL,
    p_benchmark_value DECIMAL
) RETURNS DECIMAL AS $$
DECLARE
    v_score DECIMAL;
    v_better_when_higher BOOLEAN;
BEGIN
    -- Determine if metric is better when higher or lower
    v_better_when_higher := p_metric_name IN (
        'throughput', 'average_speed', 'efficiency', 'green_time_utilization'
    );
    
    IF p_benchmark_value IS NULL OR p_benchmark_value = 0 THEN
        RETURN NULL;
    END IF;
    
    -- Calculate score (0-100)
    IF v_better_when_higher THEN
        v_score := (p_metric_value / p_benchmark_value) * 100;
    ELSE
        v_score := (p_benchmark_value / p_metric_value) * 100;
    END IF;
    
    -- Cap at 100
    IF v_score > 100 THEN
        v_score := 100;
    END IF;
    
    -- Floor at 0
    IF v_score < 0 THEN
        v_score := 0;
    END IF;
    
    RETURN ROUND(v_score, 2);
END;
$$ LANGUAGE plpgsql;

-- Create view for system health dashboard
CREATE OR REPLACE VIEW system_health_dashboard AS
SELECT 
    i.id as intersection_id,
    i.name as intersection_name,
    i.status as intersection_status,
    COUNT(DISTINCT sd.id) as total_sensors,
    COUNT(DISTINCT sd.id) FILTER (WHERE sd.status = 'active') as active_sensors,
    COUNT(DISTINCT tl.id) as total_lights,
    COUNT(DISTINCT tl.id) FILTER (WHERE tl.status = 'active') as active_lights,
    COUNT(DISTINCT a.id) FILTER (WHERE a.resolved = FALSE AND a.severity = 'critical') as critical_alerts,
    COUNT(DISTINCT a.id) FILTER (WHERE a.resolved = FALSE) as total_unresolved_alerts,
    MAX(td.timestamp) as last_detection_time,
    COUNT(td.id) FILTER (WHERE td.timestamp > NOW() - INTERVAL '5 minutes') as detections_last_5min,
    CASE 
        WHEN COUNT(DISTINCT a.id) FILTER (WHERE a.resolved = FALSE AND a.severity = 'critical') > 0 THEN 'critical'
        WHEN COUNT(DISTINCT a.id) FILTER (WHERE a.resolved = FALSE AND a.severity = 'high') > 0 THEN 'warning'
        WHEN COUNT(DISTINCT sd.id) FILTER (WHERE sd.status != 'active') > 0 THEN 'degraded'
        ELSE 'healthy'
    END as health_status
FROM intersections i
LEFT JOIN sensor_devices sd ON i.id = sd.intersection_id
LEFT JOIN traffic_lights tl ON i.id = tl.intersection_id
LEFT JOIN alerts a ON i.id = a.intersection_id
LEFT JOIN traffic_detections td ON i.id = td.intersection_id
GROUP BY i.id, i.name, i.status;

-- Comments
COMMENT ON TABLE analytics IS 'Analytics data including summaries, reports, and insights';
COMMENT ON TABLE system_config IS 'System-wide configuration key-value store';
COMMENT ON TABLE ml_predictions IS 'Machine learning model predictions and accuracy tracking';
COMMENT ON TABLE performance_metrics IS 'System and intersection performance metrics';
COMMENT ON COLUMN ml_predictions.confidence IS 'Model prediction confidence (0-1)';
COMMENT ON COLUMN ml_predictions.accuracy IS 'Actual prediction accuracy when compared to real value';
COMMENT ON COLUMN performance_metrics.performance_score IS 'Performance score (0-100) compared to benchmark';

