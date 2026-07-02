"""
Emission Calculation Module
Calculates CO2 emissions and fuel consumption based on vehicle type and speed
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class EmissionCalculator:
    """
    Calculate vehicle emissions based on type and speed
    
    Based on real-world emission factors:
    - CO2 emissions (g/km)
    - Fuel consumption (L/100km)
    - NOx emissions (g/km)
    - PM2.5 emissions (g/km)
    """
    
    # Emission factors by vehicle type (g CO2 per km)
    EMISSION_FACTORS = {
        # Passenger vehicles
        'car': {
            'co2_base': 120,  # g/km at optimal speed (50-80 km/h)
            'fuel_base': 5.5,  # L/100km
            'nox': 0.06,  # g/km
            'pm25': 0.005,  # g/km
            'optimal_speed': 65  # km/h
        },
        'sedan': {
            'co2_base': 115,
            'fuel_base': 5.2,
            'nox': 0.05,
            'pm25': 0.004,
            'optimal_speed': 65
        },
        'suv': {
            'co2_base': 180,
            'fuel_base': 8.5,
            'nox': 0.08,
            'pm25': 0.007,
            'optimal_speed': 70
        },
        'minivan': {
            'co2_base': 150,
            'fuel_base': 7.0,
            'nox': 0.07,
            'pm25': 0.006,
            'optimal_speed': 70
        },
        
        # Commercial vehicles
        'truck': {
            'co2_base': 300,
            'fuel_base': 15.0,
            'nox': 0.50,
            'pm25': 0.050,
            'optimal_speed': 60
        },
        'bus': {
            'co2_base': 1200,
            'fuel_base': 35.0,
            'nox': 5.0,
            'pm25': 0.200,
            'optimal_speed': 50
        },
        'van': {
            'co2_base': 200,
            'fuel_base': 9.0,
            'nox': 0.12,
            'pm25': 0.010,
            'optimal_speed': 65
        },
        
        # Two-wheelers
        'motorcycle': {
            'co2_base': 80,
            'fuel_base': 3.5,
            'nox': 0.15,
            'pm25': 0.020,
            'optimal_speed': 60
        },
        'bicycle': {
            'co2_base': 0,
            'fuel_base': 0,
            'nox': 0,
            'pm25': 0,
            'optimal_speed': 20
        },
        
        # Public transport
        'tramway': {
            'co2_base': 0,  # Electric
            'fuel_base': 0,
            'nox': 0,
            'pm25': 0,
            'optimal_speed': 40
        },
        
        # Default
        'vehicle': {
            'co2_base': 140,
            'fuel_base': 6.5,
            'nox': 0.07,
            'pm25': 0.006,
            'optimal_speed': 65
        }
    }
    
    def __init__(self):
        """Initialize Emission Calculator"""
        self.total_calculations = 0
        self.total_co2_calculated = 0.0
        
    def calculate_speed_factor(self, speed: float, optimal_speed: float) -> float:
        """
        Calculate emission multiplier based on speed
        
        Emissions increase at:
        - Very low speeds (stop-and-go traffic): +40%
        - Very high speeds (>120 km/h): +30%
        - Optimal speed (50-80 km/h): baseline
        
        Args:
            speed: Current speed in km/h
            optimal_speed: Optimal speed for this vehicle type
        
        Returns:
            Emission multiplier factor
        """
        if speed <= 0:
            return 1.0  # Idling
        
        speed_diff = abs(speed - optimal_speed)
        
        if speed < 20:
            # Stop-and-go traffic: +40% emissions
            return 1.4
        elif speed < 40:
            # Slow traffic: +20% emissions
            return 1.2
        elif speed <= 80:
            # Optimal range: baseline
            return 1.0 + (speed_diff / 200)
        elif speed <= 100:
            # Fast: +10-15%
            return 1.1 + (speed_diff / 300)
        elif speed <= 120:
            # Very fast: +20%
            return 1.2
        else:
            # Excessive speed: +30%
            return 1.3
    
    def calculate_emissions(
        self,
        vehicle_type: str,
        speed: float = 0,
        distance_km: float = 1.0
    ) -> Dict:
        """
        Calculate emissions for a vehicle
        
        Args:
            vehicle_type: Type of vehicle (car, truck, bus, etc.)
            speed: Speed in km/h (0 if stationary)
            distance_km: Distance traveled in km
        
        Returns:
            Dict with emission values
        """
        try:
            # Normalize vehicle type
            vehicle_type = vehicle_type.lower().strip()
            
            # Get emission factors (use 'vehicle' as default)
            factors = self.EMISSION_FACTORS.get(
                vehicle_type,
                self.EMISSION_FACTORS['vehicle']
            )
            
            # Calculate speed factor
            speed_factor = self.calculate_speed_factor(speed, factors['optimal_speed'])
            
            # Calculate emissions
            co2_per_km = factors['co2_base'] * speed_factor
            fuel_per_100km = factors['fuel_base'] * speed_factor
            nox_per_km = factors['nox'] * speed_factor
            pm25_per_km = factors['pm25'] * speed_factor
            
            # Total emissions for distance
            co2_total = co2_per_km * distance_km
            fuel_total = (fuel_per_100km / 100) * distance_km
            nox_total = nox_per_km * distance_km
            pm25_total = pm25_per_km * distance_km
            
            # Update statistics
            self.total_calculations += 1
            self.total_co2_calculated += co2_total
            
            result = {
                # CO2 emissions
                'co2_g_km': round(co2_per_km, 2),
                'co2_total_g': round(co2_total, 2),
                'co2_kg': round(co2_total / 1000, 3),
                
                # Fuel consumption
                'fuel_l_100km': round(fuel_per_100km, 2),
                'fuel_total_l': round(fuel_total, 3),
                
                # Other pollutants
                'nox_g_km': round(nox_per_km, 3),
                'pm25_g_km': round(pm25_per_km, 4),
                
                # Metadata
                'vehicle_type': vehicle_type,
                'speed_kmh': round(speed, 1),
                'speed_factor': round(speed_factor, 2),
                'optimal_speed': factors['optimal_speed'],
                'distance_km': distance_km,
                
                # Environmental impact level
                'impact_level': self._get_impact_level(co2_per_km)
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Emission calculation error: {e}")
            return self._get_default_result()
    
    def _get_impact_level(self, co2_per_km: float) -> str:
        """Get environmental impact level based on CO2 emissions"""
        if co2_per_km == 0:
            return 'zero_emission'
        elif co2_per_km < 100:
            return 'low'
        elif co2_per_km < 150:
            return 'medium'
        elif co2_per_km < 200:
            return 'high'
        else:
            return 'very_high'
    
    def _get_default_result(self) -> Dict:
        """Return default result for error cases"""
        return {
            'co2_g_km': 0,
            'co2_total_g': 0,
            'co2_kg': 0,
            'fuel_l_100km': 0,
            'fuel_total_l': 0,
            'nox_g_km': 0,
            'pm25_g_km': 0,
            'vehicle_type': 'unknown',
            'speed_kmh': 0,
            'speed_factor': 1.0,
            'optimal_speed': 65,
            'distance_km': 0,
            'impact_level': 'unknown'
        }
    
    def calculate_fleet_emissions(
        self,
        detections: list,
        time_interval_seconds: float = 1.0
    ) -> Dict:
        """
        Calculate total emissions for all detected vehicles
        
        Args:
            detections: List of detection dicts with vehicle_type and speed
            time_interval_seconds: Time interval for this frame
        
        Returns:
            Aggregated emission statistics
        """
        total_co2 = 0
        total_fuel = 0
        total_nox = 0
        total_pm25 = 0
        
        vehicle_emissions = []
        
        for det in detections:
            vehicle_type = det.get('class', 'vehicle')
            speed = det.get('speed', 0)
            
            # Estimate distance traveled in time interval
            # distance = speed * time (convert km/h to km/s)
            distance_km = (speed / 3600) * time_interval_seconds
            
            emissions = self.calculate_emissions(vehicle_type, speed, distance_km)
            
            total_co2 += emissions['co2_total_g']
            total_fuel += emissions['fuel_total_l']
            total_nox += emissions['nox_g_km'] * distance_km
            total_pm25 += emissions['pm25_g_km'] * distance_km
            
            vehicle_emissions.append(emissions)
        
        return {
            'total_vehicles': len(detections),
            'total_co2_g': round(total_co2, 2),
            'total_co2_kg': round(total_co2 / 1000, 3),
            'total_fuel_l': round(total_fuel, 3),
            'total_nox_g': round(total_nox, 3),
            'total_pm25_g': round(total_pm25, 4),
            'time_interval_seconds': time_interval_seconds,
            'vehicle_emissions': vehicle_emissions
        }
    
    def get_statistics(self) -> Dict:
        """Get emission calculator statistics"""
        avg_co2 = (
            self.total_co2_calculated / self.total_calculations
            if self.total_calculations > 0 else 0
        )
        
        return {
            'total_calculations': self.total_calculations,
            'total_co2_calculated_g': round(self.total_co2_calculated, 2),
            'total_co2_calculated_kg': round(self.total_co2_calculated / 1000, 3),
            'average_co2_per_calculation': round(avg_co2, 2),
            'supported_vehicle_types': list(self.EMISSION_FACTORS.keys())
        }
    
    def reset_statistics(self):
        """Reset statistics"""
        self.total_calculations = 0
        self.total_co2_calculated = 0.0

