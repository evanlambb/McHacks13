"""
Incremental Metrics Calculator
==============================
Efficiently calculate market metrics using O(1) incremental updates.
"""

from collections import deque
from typing import Optional


class IncrementalMetrics:
    """
    Efficiently track market metrics using incremental updates.
    All operations are O(1) after initialization.
    """
    
    def __init__(self, window_size: int = 100, calibration_steps: int = 200):
        self.window_size = window_size
        self.calibration_steps = calibration_steps
        
        # Rolling windows (fixed-size deques)
        self.mid_history = deque(maxlen=window_size)
        self.spread_history = deque(maxlen=window_size)
        self.depth_history = deque(maxlen=window_size)
        
        # Running sums for O(1) mean calculation
        self.mid_sum = 0.0
        self.spread_sum = 0.0
        self.depth_sum = 0.0
        
        # Running sum of squares for O(1) std calculation
        self.mid_sq_sum = 0.0
        self.spread_sq_sum = 0.0
        
        # Baseline values (set during calibration)
        self.baseline_spread: Optional[float] = None
        self.baseline_depth: Optional[float] = None
        self.baseline_mid: Optional[float] = None
        self.calibrated = False
        
        # Current computed metrics (updated each step)
        self.spread_ratio = 1.0
        self.depth_ratio = 1.0
        self.price_velocity = 0.0
        self.volatility = 0.0
        self.imbalance = 0.0
        self.z_score = 0.0
        
    def update(self, mid: float, spread: float, bid_depth: int, ask_depth: int):
        """
        Update all metrics with new data. O(1) complexity.
        
        Args:
            mid: Current mid price
            spread: Current spread (ask - bid)
            bid_depth: Total bid depth
            ask_depth: Total ask depth
        """
        total_depth = bid_depth + ask_depth
        
        # --- Incremental sum updates ---
        
        # If window is full, subtract the oldest value before adding new
        if len(self.mid_history) == self.window_size:
            old_mid = self.mid_history[0]
            old_spread = self.spread_history[0]
            old_depth = self.depth_history[0]
            
            self.mid_sum -= old_mid
            self.mid_sq_sum -= old_mid * old_mid
            self.spread_sum -= old_spread
            self.spread_sq_sum -= old_spread * old_spread
            self.depth_sum -= old_depth
        
        # Add new values
        self.mid_sum += mid
        self.mid_sq_sum += mid * mid
        self.spread_sum += spread
        self.spread_sq_sum += spread * spread
        self.depth_sum += total_depth
        
        # Append to history (deque handles maxlen automatically)
        self.mid_history.append(mid)
        self.spread_history.append(spread)
        self.depth_history.append(total_depth)
        
        # --- Calculate derived metrics ---
        n = len(self.mid_history)
        if n == 0:
            return
        
        # Current averages
        avg_mid = self.mid_sum / n
        avg_spread = self.spread_sum / n
        avg_depth = self.depth_sum / n
        
        # Variance using: Var(X) = E[X²] - E[X]²
        mid_variance = (self.mid_sq_sum / n) - (avg_mid * avg_mid)
        spread_variance = (self.spread_sq_sum / n) - (avg_spread * avg_spread)
        
        # Standard deviation (with safety check for negative variance due to float errors)
        self.volatility = (max(0, mid_variance)) ** 0.5
        
        # Z-score for mean reversion
        if self.volatility > 0.001:
            self.z_score = (mid - avg_mid) / self.volatility
        else:
            self.z_score = 0.0
        
        # Price velocity (10-step momentum)
        if n >= 10:
            self.price_velocity = (mid - self.mid_history[-10]) / 10
        else:
            self.price_velocity = 0.0
        
        # Order book imbalance
        if total_depth > 0:
            self.imbalance = (bid_depth - ask_depth) / total_depth
        else:
            self.imbalance = 0.0
        
        # --- Set baseline after calibration period ---
        if not self.calibrated and n >= self.calibration_steps:
            self.baseline_spread = avg_spread
            self.baseline_depth = avg_depth
            self.baseline_mid = avg_mid
            self.calibrated = True
        
        # --- Calculate ratios (only after calibration) ---
        if self.calibrated:
            self.spread_ratio = spread / self.baseline_spread if self.baseline_spread > 0 else 1.0
            self.depth_ratio = total_depth / self.baseline_depth if self.baseline_depth > 0 else 1.0
        else:
            self.spread_ratio = 1.0
            self.depth_ratio = 1.0
