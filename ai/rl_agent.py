"""
Reinforcement Learning Agent
=============================
RL agent for traffic decision optimization using PPO algorithm.
Inference-only mode for production (fast, no training overhead).
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
import logging
from pathlib import Path
import pickle

logger = logging.getLogger(__name__)

# Try to import stable-baselines3 (optional)
try:
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env
    SB3_AVAILABLE = True
except ImportError:
    SB3_AVAILABLE = False
    logger.warning("stable-baselines3 not available - RL agent will use rule-based fallback")
    PPO = None


class RLAgent:
    """
    Reinforcement Learning agent for traffic decision optimization.
    Uses PPO (Proximal Policy Optimization) algorithm.
    
    In production, runs in inference-only mode for fast decisions.
    Training is done offline in a separate process.
    """
    
    def __init__(
        self,
        model_path: Optional[Path] = None,
        use_rl: bool = True,
        fallback_to_rules: bool = True
    ):
        """
        Initialize RL agent.
        
        Args:
            model_path: Path to trained model (optional)
            use_rl: Whether to use RL (False = rule-based only)
            fallback_to_rules: Fall back to rules if RL fails
        """
        self.model_path = model_path
        self.use_rl = use_rl and SB3_AVAILABLE
        self.fallback_to_rules = fallback_to_rules
        self.model = None
        
        # State and action spaces
        self.state_dim = 8  # [vehicle_count_ns, vehicle_count_ew, emission_ns, emission_ew, 
                            #  waiting_time_ns, waiting_time_ew, current_phase, time_of_day]
        self.action_dim = 2  # [phase_change, duration]
        
        # Load model if available
        if self.use_rl and model_path and model_path.exists():
            try:
                self.model = PPO.load(str(model_path))
                logger.info(f"✅ RL model loaded from {model_path}")
            except Exception as e:
                logger.warning(f"Failed to load RL model: {e}")
                self.model = None
                if not fallback_to_rules:
                    raise
        
        if not self.use_rl or self.model is None:
            logger.info("Using rule-based decision making (RL not available)")
    
    def state_to_features(self, state: Dict) -> np.ndarray:
        """
        Convert state dictionary to feature vector.
        
        Args:
            state: State dictionary with traffic metrics
            
        Returns:
            Feature vector (numpy array)
        """
        ns = state.get('north_south', {})
        ew = state.get('east_west', {})
        current_phase = state.get('current_phase', 0)  # 0=RED, 1=YELLOW, 2=GREEN
        time_of_day = state.get('time_of_day', 0.5)  # 0.0-1.0 (normalized hour)
        
        features = np.array([
            ns.get('vehicle_count', 0) / 100.0,  # Normalize
            ew.get('vehicle_count', 0) / 100.0,
            ns.get('total_emission', 0) / 1000.0,  # Normalize
            ew.get('total_emission', 0) / 1000.0,
            ns.get('average_waiting_time', 0) / 60.0,  # Normalize to minutes
            ew.get('average_waiting_time', 0) / 60.0,
            current_phase / 2.0,  # Normalize to 0-1
            time_of_day
        ], dtype=np.float32)
        
        return features
    
    def predict_action(self, state: Dict) -> Tuple[int, float]:
        """
        Predict action (phase change and duration) from state.
        
        Args:
            state: Current traffic state
            
        Returns:
            Tuple of (phase_action, duration_seconds)
        """
        if not self.use_rl or self.model is None:
            # Fallback to rule-based
            return self._rule_based_action(state)
        
        try:
            # Convert state to features
            features = self.state_to_features(state)
            features = features.reshape(1, -1)  # Add batch dimension
            
            # Predict action
            action, _ = self.model.predict(features, deterministic=True)
            
            # Parse action
            phase_action = int(action[0])  # 0=keep, 1=change to NS, 2=change to EW
            duration = float(action[1] * 30.0 + 10.0)  # Scale to 10-40 seconds
            
            return phase_action, duration
            
        except Exception as e:
            logger.error(f"RL prediction failed: {e}")
            if self.fallback_to_rules:
                return self._rule_based_action(state)
            raise
    
    def _rule_based_action(self, state: Dict) -> Tuple[int, float]:
        """
        Rule-based action (fallback when RL is not available).
        
        Args:
            state: Current traffic state
            
        Returns:
            Tuple of (phase_action, duration_seconds)
        """
        ns = state.get('north_south', {})
        ew = state.get('east_west', {})
        
        ns_score = ns.get('vehicle_count', 0) + (ns.get('total_emission', 0) / 10.0)
        ew_score = ew.get('vehicle_count', 0) + (ew.get('total_emission', 0) / 10.0)
        
        # Simple rule: favor direction with higher score
        if ns_score > ew_score * 1.2:  # 20% threshold
            return 1, 30.0  # Change to NS
        elif ew_score > ns_score * 1.2:
            return 2, 30.0  # Change to EW
        else:
            return 0, 30.0  # Keep current
    
    def calculate_reward(
        self,
        state: Dict,
        action: Tuple[int, float],
        next_state: Dict
    ) -> float:
        """
        Calculate reward for RL training.
        
        Args:
            state: Previous state
            action: Action taken
            next_state: New state after action
            
        Returns:
            Reward value
        """
        # Reward components
        ns_prev = state.get('north_south', {})
        ew_prev = state.get('east_west', {})
        ns_next = next_state.get('north_south', {})
        ew_next = next_state.get('east_west', {})
        
        # 1. Traffic flow improvement (negative waiting time)
        waiting_improvement = (
            (ns_prev.get('average_waiting_time', 0) - ns_next.get('average_waiting_time', 0)) +
            (ew_prev.get('average_waiting_time', 0) - ew_next.get('average_waiting_time', 0))
        ) * 0.1
        
        # 2. Emission reduction
        emission_reduction = (
            (ns_prev.get('total_emission', 0) - ns_next.get('total_emission', 0)) +
            (ew_prev.get('total_emission', 0) - ew_next.get('total_emission', 0))
        ) * 0.01
        
        # 3. Vehicles served
        vehicles_served = (ns_next.get('vehicle_count', 0) + ew_next.get('vehicle_count', 0)) * 0.05
        
        # Total reward
        reward = waiting_improvement + emission_reduction + vehicles_served
        
        return float(reward)


def create_rl_agent(
    model_path: Optional[Path] = None,
    use_rl: bool = True
) -> RLAgent:
    """Create RL agent instance"""
    return RLAgent(model_path=model_path, use_rl=use_rl)

