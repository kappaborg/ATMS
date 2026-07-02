#!/usr/bin/env python3
"""
Optimized Trajectory Data Converter
====================================

Reduces redundant numpy type conversions and streamlines trajectory processing.
"""

import numpy as np
from typing import List, Dict, Any
from datetime import datetime

def convert_numpy_types_optimized(obj: Any) -> Any:
    """
    Optimized numpy type conversion with caching
    
    This version minimizes redundant conversions and uses faster type checks.
    """
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        # Convert to list directly if small, otherwise keep as array reference
        if obj.size < 1000:  # For small arrays, convert immediately
            return obj.tolist()
        else:
            # For large arrays, lazy conversion
            return [convert_numpy_types_optimized(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: convert_numpy_types_optimized(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        # Check if list contains numpy types before converting
        has_numpy = any(isinstance(item, (np.ndarray, np.integer, np.floating)) for item in obj)
        if has_numpy:
            return type(obj)(convert_numpy_types_optimized(item) for item in obj)
        else:
            return obj
    else:
        return obj

def optimize_trajectory_dict(t: Any) -> Dict:
    """
    Optimized trajectory dictionary conversion
    Reduces redundant calculations and conversions
    """
    # Pre-calculate common values
    positions = t.positions if t.positions else []
    velocities = t.velocities if t.velocities else []
    
    # Calculate velocity vector once
    velocity_vec = [0.0, 0.0]
    velocity_magnitude = 0.0
    if len(positions) >= 2:
        dx = float(positions[-1][0] - positions[-2][0])
        dy = float(positions[-1][1] - positions[-2][1])
        velocity_vec = [dx, dy]
        velocity_magnitude = float((dx**2 + dy**2)**0.5)
    elif velocities:
        velocity_magnitude = float(velocities[-1])
    
    # Build dictionary with minimal conversions
    traj_dict = {
        'track_id': int(t.track_id),
        'class_name': str(t.class_name),
        'last_position': [float(x) for x in positions[-1]] if positions else None,
        'velocity': velocity_vec,
        'velocity_magnitude': velocity_magnitude,
        'confidence': float(t.confidences[-1]) if t.confidences else 0.0,
        'views_seen': [str(v) for v in t.views_seen],
        'frames_tracked': int(len(positions)),
        'is_active': bool(t.is_active),
        'first_seen': t.first_seen.isoformat(),
        'last_seen': t.last_seen.isoformat(),
        'total_detections': int(len(positions)),
        # Only convert positions/velocities if needed (lazy)
        'positions': positions if not positions or not isinstance(positions[0], (np.ndarray, np.floating)) else [[float(x) for x in pos] for pos in positions],
        'velocities': velocities if not velocities or not isinstance(velocities[0], np.floating) else [float(vel) for vel in velocities]
    }
    
    return traj_dict


