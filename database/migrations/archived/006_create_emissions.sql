-- Migration 006: Create EMISSIONS table
-- Purpose: Store emission calculations (CO2, NOx, PM, fuel consumption)
-- Dependencies: 001_create_intersections.sql, 005_create_trajectories.sql
-- Author: ATMS Team
-- Date: 2025-10-13

-- Create EMISSIONS table
CREATE TABLE IF NOT EXISTS emissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trajectory_id UUID REFERENCES trajectories(id) ON DELETE CASCADE,
    intersection_id INTEGER REFERENCES intersections(id) ON DELETE CASCADE,
    vehicle_id VARCHAR(50),
    vehicle_class VARCHAR(50) NOT NULL,
    distance_meters DECIMAL(10, 2) NOT NULL,
    velocity_ms DECIMAL(8, 2),  -- meters per second
    idle_time_seconds INTEGER DEFAULT 0,
    -- Emissions in grams
    co2_g DECIMAL(10, 2),  -- Carbon Dioxide
    nox_g DECIMAL(10, 4),  -- Nitrogen Oxides
    pm_g DECIMAL(10, 4),   -- Particulate Matter
    co_g DECIMAL(10, 4),   -- Carbon Monoxide
    hc_g DECIMAL(10, 4),   -- Hydrocarbons
    -- Fuel consumption
    fuel_consumption_l DECIMAL(10, 4),  -- Liters
    fuel_type VARCHAR(20) DEFAULT 'petrol',  -- petrol, diesel, electric, hybrid
    fuel_cost_usd DECIMAL(10, 2),
    -- Speed factor adjustment
    speed_factor DECIMAL(4, 2) DEFAULT 1.0,
    congestion_factor DECIMAL(4, 2) DEFAULT 1.0,
    -- Metadata
    calculation_method VARCHAR(50) DEFAULT 'COPERT',  -- COPERT, MOVES, MOBILE
    metadata JSONB DEFAULT '{}',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_emissions_trajectory ON emissions(trajectory_id);
CREATE INDEX IF NOT EXISTS idx_emissions_intersection ON emissions(intersection_id);
CREATE INDEX IF NOT EXISTS idx_emissions_vehicle_class ON emissions(vehicle_class);
CREATE INDEX IF NOT EXISTS idx_emissions_timestamp ON emissions(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_emissions_fuel_type ON emissions(fuel_type);

-- Create function for emission calculation
CREATE OR REPLACE FUNCTION calculate_emissions(
    p_vehicle_class VARCHAR,
    p_distance_meters DECIMAL,
    p_velocity_ms DECIMAL,
    p_idle_time_seconds INTEGER DEFAULT 0
) RETURNS TABLE (
    co2_g DECIMAL,
    nox_g DECIMAL,
    pm_g DECIMAL,
    co_g DECIMAL,
    hc_g DECIMAL,
    fuel_l DECIMAL,
    fuel_cost DECIMAL
) AS $$
DECLARE
    v_distance_km DECIMAL;
    v_speed_kmh DECIMAL;
    v_speed_factor DECIMAL := 1.0;
    v_fuel_price_per_liter DECIMAL := 1.50;  -- USD per liter
    -- Base emission factors (g/km)
    v_co2_factor DECIMAL;
    v_nox_factor DECIMAL;
    v_pm_factor DECIMAL;
    v_co_factor DECIMAL;
    v_hc_factor DECIMAL;
    v_fuel_factor DECIMAL;  -- L/100km
BEGIN
    -- Convert to km and km/h
    v_distance_km := p_distance_meters / 1000.0;
    v_speed_kmh := p_velocity_ms * 3.6;
    
    -- Speed adjustment factor
    IF v_speed_kmh < 30 THEN
        v_speed_factor := 1.3;  -- Congested traffic
    ELSIF v_speed_kmh > 90 THEN
        v_speed_factor := 1.2;  -- Highway speeds
    ELSE
        v_speed_factor := 1.0;  -- Normal traffic
    END IF;
    
    -- Set emission factors based on vehicle class
    CASE p_vehicle_class
        WHEN 'sedan' THEN
            v_co2_factor := 120;
            v_nox_factor := 0.12;
            v_pm_factor := 0.06;
            v_co_factor := 0.30;
            v_hc_factor := 0.02;
            v_fuel_factor := 5.5;
        WHEN 'suv' THEN
            v_co2_factor := 180;
            v_nox_factor := 0.18;
            v_pm_factor := 0.09;
            v_co_factor := 0.45;
            v_hc_factor := 0.03;
            v_fuel_factor := 8.5;
        WHEN 'minivan' THEN
            v_co2_factor := 150;
            v_nox_factor := 0.15;
            v_pm_factor := 0.075;
            v_co_factor := 0.375;
            v_hc_factor := 0.025;
            v_fuel_factor := 7.0;
        WHEN 'truck' THEN
            v_co2_factor := 250;
            v_nox_factor := 0.50;
            v_pm_factor := 0.20;
            v_co_factor := 0.80;
            v_hc_factor := 0.05;
            v_fuel_factor := 15.0;
        WHEN 'bus' THEN
            v_co2_factor := 300;
            v_nox_factor := 0.80;
            v_pm_factor := 0.30;
            v_co_factor := 1.00;
            v_hc_factor := 0.08;
            v_fuel_factor := 20.0;
        ELSE  -- Default to sedan
            v_co2_factor := 120;
            v_nox_factor := 0.12;
            v_pm_factor := 0.06;
            v_co_factor := 0.30;
            v_hc_factor := 0.02;
            v_fuel_factor := 5.5;
    END CASE;
    
    -- Calculate emissions (factor * distance * speed_adjustment)
    co2_g := v_co2_factor * v_distance_km * v_speed_factor;
    nox_g := v_nox_factor * v_distance_km * v_speed_factor;
    pm_g := v_pm_factor * v_distance_km * v_speed_factor;
    co_g := v_co_factor * v_distance_km * v_speed_factor;
    hc_g := v_hc_factor * v_distance_km * v_speed_factor;
    
    -- Calculate fuel consumption (L/100km * km / 100)
    fuel_l := (v_fuel_factor * v_distance_km) / 100.0;
    
    -- Add idle emissions (if applicable)
    IF p_idle_time_seconds > 0 THEN
        -- Idle emissions are typically 0.5-1.0 g CO2/second
        co2_g := co2_g + (p_idle_time_seconds * 0.7);
        fuel_l := fuel_l + (p_idle_time_seconds * 0.0003);  -- ~1L/hour idle
    END IF;
    
    -- Calculate fuel cost
    fuel_cost := fuel_l * v_fuel_price_per_liter;
    
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

-- Create view for emission summary
CREATE OR REPLACE VIEW emission_summary AS
SELECT 
    e.intersection_id,
    i.name as intersection_name,
    e.vehicle_class,
    e.fuel_type,
    COUNT(*) as total_records,
    SUM(e.co2_g) as total_co2_g,
    SUM(e.nox_g) as total_nox_g,
    SUM(e.pm_g) as total_pm_g,
    SUM(e.fuel_consumption_l) as total_fuel_l,
    SUM(e.fuel_cost_usd) as total_fuel_cost,
    AVG(e.velocity_ms * 3.6) as avg_speed_kmh,
    DATE(e.timestamp) as date
FROM emissions e
LEFT JOIN intersections i ON e.intersection_id = i.id
GROUP BY e.intersection_id, i.name, e.vehicle_class, e.fuel_type, DATE(e.timestamp)
ORDER BY date DESC, total_co2_g DESC;

-- Comments
COMMENT ON TABLE emissions IS 'Vehicle emission calculations (CO2, NOx, PM, fuel consumption)';
COMMENT ON COLUMN emissions.co2_g IS 'Carbon Dioxide emissions in grams';
COMMENT ON COLUMN emissions.nox_g IS 'Nitrogen Oxides emissions in grams';
COMMENT ON COLUMN emissions.pm_g IS 'Particulate Matter emissions in grams';
COMMENT ON COLUMN emissions.fuel_consumption_l IS 'Fuel consumption in liters';
COMMENT ON COLUMN emissions.speed_factor IS 'Speed-based emission adjustment factor';
COMMENT ON COLUMN emissions.calculation_method IS 'Emission calculation methodology used';

