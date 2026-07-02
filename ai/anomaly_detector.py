"""
Anomaly Detector
================
Lightweight anomaly detection for traffic events.
Uses Isolation Forest for fast real-time detection.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from collections import deque
import logging

logger = logging.getLogger(__name__)

# Try to import scikit-learn (optional)
try:
    from sklearn.ensemble import IsolationForest
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not available - using simple threshold-based anomaly detection")
    IsolationForest = None


class AnomalyDetector:
    """
    Anomaly detector for traffic events.
    Uses Isolation Forest for fast, lightweight detection.
    Falls back to statistical methods if scikit-learn is not available.
    """
    
    def __init__(
        self,
        contamination: float = 0.1,  # Expected anomaly rate
        use_ml: bool = True,
        history_size: int = 1000
    ):
        """
        Initialize anomaly detector.
        
        Args:
            contamination: Expected proportion of anomalies
            use_ml: Whether to use ML model (Isolation Forest)
            history_size: Size of historical data to keep
        """
        self.contamination = contamination
        self.use_ml = use_ml and SKLEARN_AVAILABLE
        self.history_size = history_size
        
        # Historical data
        self.feature_history: deque = deque(maxlen=history_size)
        self.anomaly_scores: deque = deque(maxlen=history_size)
        
        # ML model
        self.model = None
        if self.use_ml:
            try:
                self.model = IsolationForest(
                    contamination=contamination,
                    random_state=42,
                    n_estimators=100
                )
                logger.info("✅ Isolation Forest anomaly detector initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Isolation Forest: {e}")
                self.model = None
                self.use_ml = False
        
        if not self.use_ml:
            logger.info("Using statistical anomaly detection (threshold-based)")
    
    def extract_features(self, metrics: Dict) -> np.ndarray:
        """
        Extract features from traffic metrics.
        
        Args:
            metrics: Traffic metrics dictionary
            
        Returns:
            Feature vector
        """
        ns = metrics.get('north_south', {})
        ew = metrics.get('east_west', {})
        
        features = np.array([
            ns.get('vehicle_count', 0),
            ew.get('vehicle_count', 0),
            ns.get('total_emission', 0),
            ew.get('total_emission', 0),
            ns.get('average_waiting_time', 0),
            ew.get('average_waiting_time', 0),
            ns.get('average_velocity', 0),
            ew.get('average_velocity', 0),
        ], dtype=np.float32)
        
        return features
    
    def detect_anomaly(self, metrics: Dict) -> Tuple[bool, float]:
        """
        Detect if current metrics represent an anomaly.
        
        Args:
            metrics: Current traffic metrics
            
        Returns:
            Tuple of (is_anomaly, anomaly_score)
        """
        features = self.extract_features(metrics)
        
        if self.use_ml and self.model:
            return self._ml_detect(features)
        else:
            return self._statistical_detect(features)
    
    def _ml_detect(self, features: np.ndarray) -> Tuple[bool, float]:
        """ML-based anomaly detection using Isolation Forest"""
        try:
            # Add to history
            self.feature_history.append(features)
            
            # Need at least 10 samples to train
            if len(self.feature_history) < 10:
                return False, 0.0
            
            # Retrain periodically (every 100 samples)
            if len(self.feature_history) % 100 == 0:
                X = np.array(list(self.feature_history))
                self.model.fit(X)
            
            # Predict anomaly
            prediction = self.model.predict(features.reshape(1, -1))
            score = self.model.score_samples(features.reshape(1, -1))[0]
            
            # prediction: -1 = anomaly, 1 = normal
            is_anomaly = prediction[0] == -1
            anomaly_score = float(-score)  # Negative score = more anomalous
            
            self.anomaly_scores.append(anomaly_score)
            
            return is_anomaly, anomaly_score
            
        except Exception as e:
            logger.error(f"ML anomaly detection failed: {e}")
            return self._statistical_detect(features)
    
    def _statistical_detect(self, features: np.ndarray) -> Tuple[bool, float]:
        """Statistical anomaly detection (threshold-based)"""
        if len(self.feature_history) < 5:
            # Not enough history, add and return normal
            self.feature_history.append(features)
            return False, 0.0
        
        # Calculate statistics
        X = np.array(list(self.feature_history))
        mean = np.mean(X, axis=0)
        std = np.std(X, axis=0)
        
        # Avoid division by zero
        std = np.where(std == 0, 1.0, std)
        
        # Z-score
        z_scores = np.abs((features - mean) / std)
        max_z_score = np.max(z_scores)
        
        # Threshold: >3 standard deviations = anomaly
        is_anomaly = max_z_score > 3.0
        anomaly_score = float(max_z_score / 3.0)  # Normalize to 0-1+
        
        # Add to history
        self.feature_history.append(features)
        self.anomaly_scores.append(anomaly_score)
        
        return is_anomaly, anomaly_score
    
    def classify_anomaly(self, metrics: Dict) -> Optional[str]:
        """
        Classify type of anomaly.
        
        Args:
            metrics: Traffic metrics
            
        Returns:
            Anomaly type or None if normal
        """
        is_anomaly, score = self.detect_anomaly(metrics)
        
        if not is_anomaly:
            return None
        
        ns = metrics.get('north_south', {})
        ew = metrics.get('east_west', {})
        
        # Classify based on metrics
        if ns.get('vehicle_count', 0) > 100 or ew.get('vehicle_count', 0) > 100:
            return "HIGH_TRAFFIC"
        elif ns.get('average_waiting_time', 0) > 120 or ew.get('average_waiting_time', 0) > 120:
            return "CONGESTION"
        elif ns.get('total_emission', 0) > 1000 or ew.get('total_emission', 0) > 1000:
            return "HIGH_EMISSION"
        elif ns.get('average_velocity', 0) < 5 or ew.get('average_velocity', 0) < 5:
            return "LOW_SPEED"
        else:
            return "UNKNOWN_ANOMALY"


def create_anomaly_detector(
    contamination: float = 0.1,
    use_ml: bool = True
) -> AnomalyDetector:
    """Create anomaly detector instance"""
    return AnomalyDetector(contamination=contamination, use_ml=use_ml)

