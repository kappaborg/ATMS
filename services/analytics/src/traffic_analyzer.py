#!/usr/bin/env python3
"""
Traffic Pattern Analyzer
Phase 4 - Week 15-16: Analytics Implementation

Features:
- Traffic pattern analysis
- Predictive maintenance
- Trend analysis
- Statistical reporting
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import statistics
import numpy as np
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class TrafficPattern:
    """Traffic pattern data"""
    time_of_day: int  # Hour (0-23)
    day_of_week: int  # 0=Monday, 6=Sunday
    vehicle_count: int
    average_speed: float
    congestion_level: float  # 0-1
    peak_hour: bool


@dataclass
class MaintenancePrediction:
    """Predictive maintenance prediction"""
    component: str
    predicted_failure_date: datetime
    confidence: float
    maintenance_type: str
    priority: str


class TrafficPatternAnalyzer:
    """Analyzes traffic patterns and trends"""
    
    def __init__(self):
        self.patterns: List[TrafficPattern] = []
        self.historical_data: Dict[str, List[float]] = defaultdict(list)
    
    def add_pattern(self, pattern: TrafficPattern):
        """Add traffic pattern data"""
        self.patterns.append(pattern)
        
        # Store historical data by time slot
        time_key = f"{pattern.day_of_week}_{pattern.time_of_day}"
        self.historical_data[time_key].append(pattern.vehicle_count)
    
    def analyze_daily_patterns(self) -> Dict[str, any]:
        """Analyze daily traffic patterns"""
        if not self.patterns:
            return {}
        
        # Group by hour
        hourly_counts = defaultdict(list)
        for pattern in self.patterns:
            hourly_counts[pattern.time_of_day].append(pattern.vehicle_count)
        
        # Calculate statistics per hour
        hourly_stats = {}
        for hour in range(24):
            counts = hourly_counts[hour]
            if counts:
                hourly_stats[hour] = {
                    "average": statistics.mean(counts),
                    "median": statistics.median(counts),
                    "std_dev": statistics.stdev(counts) if len(counts) > 1 else 0,
                    "min": min(counts),
                    "max": max(counts)
                }
        
        # Identify peak hours
        peak_hours = sorted(
            hourly_stats.items(),
            key=lambda x: x[1]["average"],
            reverse=True
        )[:3]  # Top 3 peak hours
        
        return {
            "hourly_statistics": hourly_stats,
            "peak_hours": [{"hour": h, "stats": s} for h, s in peak_hours],
            "total_patterns": len(self.patterns)
        }
    
    def analyze_weekly_patterns(self) -> Dict[str, any]:
        """Analyze weekly traffic patterns"""
        if not self.patterns:
            return {}
        
        # Group by day of week
        daily_counts = defaultdict(list)
        for pattern in self.patterns:
            daily_counts[pattern.day_of_week].append(pattern.vehicle_count)
        
        # Calculate statistics per day
        daily_stats = {}
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for day in range(7):
            counts = daily_counts[day]
            if counts:
                daily_stats[day_names[day]] = {
                    "average": statistics.mean(counts),
                    "median": statistics.median(counts),
                    "std_dev": statistics.stdev(counts) if len(counts) > 1 else 0
                }
        
        return {
            "daily_statistics": daily_stats,
            "busiest_day": max(daily_stats.items(), key=lambda x: x[1]["average"])[0] if daily_stats else None
        }
    
    def predict_traffic(self, day_of_week: int, hour: int) -> Dict[str, any]:
        """Predict traffic for a specific time"""
        time_key = f"{day_of_week}_{hour}"
        historical = self.historical_data.get(time_key, [])
        
        if not historical:
            return {"predicted_count": 0, "confidence": 0.0}
        
        # Simple prediction using historical average
        predicted = statistics.mean(historical)
        confidence = min(1.0, len(historical) / 100.0)  # More data = higher confidence
        
        return {
            "predicted_count": int(predicted),
            "confidence": confidence,
            "historical_samples": len(historical)
        }


class PredictiveMaintenance:
    """Predictive maintenance analyzer"""
    
    def __init__(self):
        self.component_data: Dict[str, List[Dict]] = defaultdict(list)
        self.failure_thresholds = {
            "camera": {"max_errors": 100, "max_downtime": 3600},  # 1 hour
            "detector": {"max_errors": 50, "max_downtime": 1800},  # 30 min
            "signal_controller": {"max_errors": 20, "max_downtime": 600}  # 10 min
        }
    
    def add_component_metric(self, component: str, metric: Dict):
        """Add component metric data"""
        self.component_data[component].append({
            **metric,
            "timestamp": datetime.utcnow()
        })
    
    def predict_maintenance(self, component: str) -> Optional[MaintenancePrediction]:
        """Predict maintenance needs for a component"""
        if component not in self.component_data:
            return None
        
        metrics = self.component_data[component]
        if len(metrics) < 10:
            return None  # Not enough data
        
        # Analyze error rates
        recent_metrics = metrics[-100:]  # Last 100 data points
        error_count = sum(1 for m in recent_metrics if m.get("error", False))
        error_rate = error_count / len(recent_metrics)
        
        # Check against thresholds
        threshold = self.failure_thresholds.get(component, {}).get("max_errors", 50)
        if error_rate * 100 > threshold:
            # Predict failure within 7 days
            predicted_date = datetime.utcnow() + timedelta(days=7)
            confidence = min(0.9, error_rate * 2)
            
            return MaintenancePrediction(
                component=component,
                predicted_failure_date=predicted_date,
                confidence=confidence,
                maintenance_type="preventive",
                priority="HIGH" if confidence > 0.7 else "MEDIUM"
            )
        
        return None
    
    def get_all_predictions(self) -> List[MaintenancePrediction]:
        """Get maintenance predictions for all components"""
        predictions = []
        for component in self.component_data.keys():
            prediction = self.predict_maintenance(component)
            if prediction:
                predictions.append(prediction)
        return predictions


class TrendAnalyzer:
    """Analyzes trends in traffic data"""
    
    def __init__(self):
        self.trend_data: List[Dict] = []
    
    def add_data_point(self, timestamp: datetime, value: float, metric: str):
        """Add data point for trend analysis"""
        self.trend_data.append({
            "timestamp": timestamp,
            "value": value,
            "metric": metric
        })
    
    def calculate_trend(self, metric: str, days: int = 7) -> Dict[str, any]:
        """Calculate trend for a metric over specified days"""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        recent_data = [
            d for d in self.trend_data
            if d["metric"] == metric and d["timestamp"] >= cutoff_date
        ]
        
        if len(recent_data) < 2:
            return {"trend": "insufficient_data"}
        
        # Sort by timestamp
        recent_data.sort(key=lambda x: x["timestamp"])
        values = [d["value"] for d in recent_data]
        
        # Calculate linear trend
        x = np.arange(len(values))
        slope = np.polyfit(x, values, 1)[0]
        
        # Determine trend direction
        if slope > 0.1:
            trend = "increasing"
        elif slope < -0.1:
            trend = "decreasing"
        else:
            trend = "stable"
        
        return {
            "trend": trend,
            "slope": float(slope),
            "average": float(statistics.mean(values)),
            "data_points": len(values),
            "period_days": days
        }

