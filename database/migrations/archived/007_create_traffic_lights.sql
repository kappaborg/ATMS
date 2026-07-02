-- Migration 007: Create TRAFFIC_LIGHTS table
-- Purpose: Traffic light control and status management
-- Dependencies: 001_create_intersections.sql
-- Author: ATMS Team
-- Date: 2025-10-13

-- Create TRAFFIC_LIGHTS table
CREATE TABLE IF NOT EXISTS traffic_lights (
    id SERIAL PRIMARY KEY,
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE CASCADE,
    direction VARCHAR(50) NOT NULL,  -- north, south, east, west, etc.
    lane_number INTEGER,
    light_type VARCHAR(50) NOT NULL,  -- vehicle, pedestrian, bicycle, arrow
    controller_id VARCHAR(100),
    current_state VARCHAR(20) DEFAULT 'red',  -- red, yellow, green
    next_state VARCHAR(20),
    state_duration INTEGER,  -- seconds
    status VARCHAR(50) DEFAULT 'active',  -- active, inactive, maintenance, error
    protocol VARCHAR(50) DEFAULT 'NTCIP',  -- NTCIP, SNMP, HTTP, MODBUS
    ip_address INET,
    port INTEGER,
    configuration JSONB DEFAULT '{}',
    last_state_change TIMESTAMP,
    total_cycles INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_traffic_lights_intersection ON traffic_lights(intersection_id);
CREATE INDEX IF NOT EXISTS idx_traffic_lights_direction ON traffic_lights(direction);
CREATE INDEX IF NOT EXISTS idx_traffic_lights_state ON traffic_lights(current_state);
CREATE INDEX IF NOT EXISTS idx_traffic_lights_status ON traffic_lights(status);
CREATE INDEX IF NOT EXISTS idx_traffic_lights_controller ON traffic_lights(controller_id);

-- Create trigger for updated_at
CREATE TRIGGER update_traffic_lights_updated_at
    BEFORE UPDATE ON traffic_lights
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Create function to change light state
CREATE OR REPLACE FUNCTION change_light_state(
    p_light_id INTEGER,
    p_new_state VARCHAR
) RETURNS BOOLEAN AS $$
DECLARE
    v_current_state VARCHAR;
    v_valid_transition BOOLEAN := FALSE;
BEGIN
    -- Get current state
    SELECT current_state INTO v_current_state
    FROM traffic_lights
    WHERE id = p_light_id;
    
    -- Validate state transition
    CASE v_current_state
        WHEN 'red' THEN
            v_valid_transition := p_new_state IN ('green', 'yellow');  -- Emergency can go red->green
        WHEN 'green' THEN
            v_valid_transition := p_new_state = 'yellow';
        WHEN 'yellow' THEN
            v_valid_transition := p_new_state = 'red';
        ELSE
            v_valid_transition := TRUE;  -- Allow any transition from unknown state
    END CASE;
    
    IF v_valid_transition THEN
        UPDATE traffic_lights
        SET 
            current_state = p_new_state,
            last_state_change = CURRENT_TIMESTAMP,
            total_cycles = CASE WHEN p_new_state = 'red' THEN total_cycles + 1 ELSE total_cycles END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = p_light_id;
        
        RETURN TRUE;
    ELSE
        RAISE NOTICE 'Invalid state transition: % -> %', v_current_state, p_new_state;
        RETURN FALSE;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create LIGHT_PHASES table
CREATE TABLE IF NOT EXISTS light_phases (
    id BIGSERIAL PRIMARY KEY,
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE CASCADE,
    phase_number INTEGER NOT NULL,
    phase_sequence JSONB NOT NULL,  -- Array of {light_id, state, duration}
    duration_seconds INTEGER NOT NULL,
    trigger_reason VARCHAR(100),  -- scheduled, traffic_volume, emergency, pedestrian_request
    traffic_volume INTEGER,
    wait_time_saved INTEGER DEFAULT 0,  -- Estimated wait time saved (seconds)
    total_wait_time_saved INTEGER DEFAULT 0,
    emergency_override BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for light_phases
CREATE INDEX IF NOT EXISTS idx_light_phases_intersection ON light_phases(intersection_id);
CREATE INDEX IF NOT EXISTS idx_light_phases_timestamp ON light_phases(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_light_phases_trigger ON light_phases(trigger_reason);
CREATE INDEX IF NOT EXISTS idx_light_phases_emergency ON light_phases(emergency_override) WHERE emergency_override = TRUE;

-- Insert default traffic lights for intersection 1
INSERT INTO traffic_lights (intersection_id, direction, light_type, current_state, configuration)
VALUES 
    (1, 'north', 'vehicle', 'red', '{"min_green": 10, "max_green": 60}'),
    (1, 'south', 'vehicle', 'red', '{"min_green": 10, "max_green": 60}'),
    (1, 'east', 'vehicle', 'green', '{"min_green": 10, "max_green": 60}'),
    (1, 'west', 'vehicle', 'green', '{"min_green": 10, "max_green": 60}'),
    (1, 'north', 'pedestrian', 'red', '{"walk_time": 15, "clearance_time": 10}'),
    (1, 'south', 'pedestrian', 'red', '{"walk_time": 15, "clearance_time": 10}'),
    (1, 'east', 'pedestrian', 'red', '{"walk_time": 15, "clearance_time": 10}'),
    (1, 'west', 'pedestrian', 'red', '{"walk_time": 15, "clearance_time": 10}')
ON CONFLICT DO NOTHING;

-- Create view for current light status
CREATE OR REPLACE VIEW current_light_status AS
SELECT 
    tl.id,
    tl.intersection_id,
    i.name as intersection_name,
    tl.direction,
    tl.light_type,
    tl.current_state,
    tl.status,
    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - tl.last_state_change)) as seconds_in_current_state,
    tl.total_cycles,
    tl.last_state_change
FROM traffic_lights tl
LEFT JOIN intersections i ON tl.intersection_id = i.id
ORDER BY tl.intersection_id, tl.direction, tl.light_type;

-- Comments
COMMENT ON TABLE traffic_lights IS 'Traffic light control and status management';
COMMENT ON COLUMN traffic_lights.current_state IS 'Current light state: red, yellow, green';
COMMENT ON COLUMN traffic_lights.light_type IS 'Type of light: vehicle, pedestrian, bicycle, arrow';
COMMENT ON COLUMN traffic_lights.protocol IS 'Communication protocol: NTCIP, SNMP, HTTP, MODBUS';
COMMENT ON TABLE light_phases IS 'Traffic light phase management and optimization history';
COMMENT ON COLUMN light_phases.trigger_reason IS 'What triggered this phase: scheduled, traffic_volume, emergency, pedestrian_request';

