"""
Traffic Predictor
=================
Predictive analytics for traffic patterns using time series forecasting.
Lightweight models for real-time prediction.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from collections import deque
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Try to import Prophet (optional, for advanced forecasting)
try:
    from prophet import Prophet
    PROPHET_AVAILABLE = True
except ImportError:
    PROPHET_AVAILABLE = False
    logger.info("Prophet not available - using simple moving average prediction")


class TrafficPredictor:
    """
    Traffic pattern predictor using time series forecasting.
    Uses simple moving average for real-time prediction (fast).
    Can use Prophet for more advanced forecasting (slower, requires training).
    """
    
    def __init__(
        self,
        history_size: int = 100,
        prediction_horizon: int = 15,  # minutes
        use_prophet: bool = False
    ):
        """
        Initialize traffic predictor.
        
        Args:
            history_size: Number of historical points to keep
            prediction_horizon: Prediction horizon in minutes
            use_prophet: Whether to use Prophet (requires training data)
        """
        self.history_size = history_size
        self.prediction_horizon = prediction_horizon
        self.use_prophet = use_prophet and PROPHET_AVAILABLE
        
        # Historical data storage
        self.vehicle_count_history: Dict[str, deque] = {
            'north_south': deque(maxlen=history_size),
            'east_west': deque(maxlen=history_size)
        }
        self.timestamps: deque = deque(maxlen=history_size)
        
        # Prophet models (if available)
        self.prophet_models: Dict[str, Optional[Prophet]] = {}
        if self.use_prophet:
            for direction in ['north_south', 'east_west']:
                self.prophet_models[direction] = None
        
        logger.info(f"Traffic predictor initialized (Prophet: {self.use_prophet})")
    
    def update_history(self, metrics: Dict, timestamp: Optional[datetime] = None):
        """
        Update historical data.
        
        Args:
            metrics: Current traffic metrics
            timestamp: Timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        self.timestamps.append(timestamp)
        
        ns = metrics.get('north_south', {})
        ew = metrics.get('east_west', {})
        
        self.vehicle_count_history['north_south'].append(ns.get('vehicle_count', 0))
        self.vehicle_count_history['east_west'].append(ew.get('vehicle_count', 0))
    
    def predict_vehicle_count(
        self,
        direction: str,
        minutes_ahead: Optional[int] = None
    ) -> Tuple[float, float]:
        """
        Predict vehicle count for a direction.
        
        Args:
            direction: 'north_south' or 'east_west'
            minutes_ahead: Minutes to predict ahead (uses default if None)
            
        Returns:
            Tuple of (predicted_count, confidence_interval)
        """
        minutes_ahead = minutes_ahead or self.prediction_horizon
        
        if direction not in self.vehicle_count_history:
            return 0.0, 0.0
        
        history = list(self.vehicle_count_history[direction])
        
        if len(history) < 5:
            # Not enough data, return last value
            return float(history[-1]) if history else 0.0, 0.0
        
        if self.use_prophet and self.prophet_models[direction]:
            # Use Prophet for prediction
            return self._prophet_predict(direction, minutes_ahead)
        else:
            # Use simple moving average with trend
            return self._simple_predict(history, minutes_ahead)
    
    def _simple_predict(self, history: List[float], minutes_ahead: int) -> Tuple[float, float]:
        """Simple prediction using moving average and trend"""
        if not history:
            return 0.0, 0.0
        
        # Moving average
        window = min(10, len(history))
        recent = history[-window:]
        avg = np.mean(recent)
        
        # Trend (simple linear)
        if len(history) >= 2:
            trend = (history[-1] - history[0]) / len(history)
            prediction = avg + (trend * minutes_ahead)
        else:
            prediction = avg
        
        # Confidence interval (simple: based on variance)
        variance = np.var(recent) if len(recent) > 1 else 0.0
        confidence = np.sqrt(variance) * 1.96  # 95% confidence
        
        return float(max(0, prediction)), float(confidence)
    
    def _prophet_predict(self, direction: str, minutes_ahead: int) -> Tuple[float, float]:
        """Prophet-based prediction (requires trained model)"""
        if not self.prophet_models[direction]:
            # Fallback to simple prediction
            history = list(self.vehicle_count_history[direction])
            return self._simple_predict(history, minutes_ahead)
        
        try:
            # Create future dataframe
            future = self.prophet_models[direction].make_future_dataframe(
                periods=minutes_ahead,
                freq='min'
            )
            
            # Predict
            forecast = self.prophet_models[direction].predict(future)
            
            # Get prediction
            prediction = forecast['yhat'].iloc[-1]
            lower = forecast['yhat_lower'].iloc[-1]
            upper = forecast['yhat_upper'].iloc[-1]
            confidence = (upper - lower) / 2.0
            
            return float(max(0, prediction)), float(confidence)
            
        except Exception as e:
            logger.error(f"Prophet prediction failed: {e}")
            history = list(self.vehicle_count_history[direction])
            return self._simple_predict(history, minutes_ahead)
    
    def predict_congestion(self, minutes_ahead: int = 15) -> Dict[str, float]:
        """
        Predict congestion probability.
        
        Args:
            minutes_ahead: Minutes to predict ahead
            
        Returns:
            Dictionary with congestion probabilities per direction
        """
        ns_pred, _ = self.predict_vehicle_count('north_south', minutes_ahead)
        ew_pred, _ = self.predict_vehicle_count('east_west', minutes_ahead)
        
        # Simple congestion threshold: >50 vehicles
        congestion_threshold = 50.0
        
        return {
            'north_south': min(1.0, ns_pred / congestion_threshold),
            'east_west': min(1.0, ew_pred / congestion_threshold)
        }
    
    def detect_peak_hours(self) -> Dict[str, List[int]]:
        """
        Detect peak hours from historical data.
        
        Returns:
            Dictionary with peak hours per direction
        """
        if len(self.timestamps) < 24:
            return {'north_south': [], 'east_west': []}
        
        # Group by hour
        hourly_counts = {
            'north_south': [0] * 24,
            'east_west': [0] * 24
        }
        
        for i, ts in enumerate(self.timestamps):
            hour = ts.hour
            hourly_counts['north_south'][hour] += self.vehicle_count_history['north_south'][i]
            hourly_counts['east_west'][hour] += self.vehicle_count_history['east_west'][i]
        
        # Find peak hours (top 3)
        ns_peaks = sorted(range(24), key=lambda h: hourly_counts['north_south'][h], reverse=True)[:3]
        ew_peaks = sorted(range(24), key=lambda h: hourly_counts['east_west'][h], reverse=True)[:3]
        
        return {
            'north_south': ns_peaks,
            'east_west': ew_peaks
        }


def create_predictor(
    history_size: int = 100,
    prediction_horizon: int = 15
) -> TrafficPredictor:
    """Create traffic predictor instance"""
    return TrafficPredictor(
        history_size=history_size,
        prediction_horizon=prediction_horizon
    )

