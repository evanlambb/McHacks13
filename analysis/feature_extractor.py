"""
Feature Extraction Module for HFT-Style Regime Detection
========================================================
Extracts multi-timeframe features and detects regime changes using statistical methods.
"""

import statistics
from typing import Dict, Optional, Tuple, List
from collections import deque


class FeatureExtractor:
    """
    Extracts microstructure features from market data at multiple timeframes.
    Implements CUSUM change-point detection and spike detection.
    """
    
    # Timeframe windows (in steps)
    WINDOWS = {
        "short": 10,    # Immediate threats, spike detection
        "medium": 100,  # Trend/regime transitions
        "long": 500     # Baseline establishment
    }
    
    def __init__(self):
        # History buffers for each timeframe
        self.spread_history = deque(maxlen=self.WINDOWS["long"])
        self.depth_history = deque(maxlen=self.WINDOWS["long"])
        self.mid_history = deque(maxlen=self.WINDOWS["long"])
        self.imbalance_history = deque(maxlen=self.WINDOWS["long"])
        
        # CUSUM state for change-point detection
        self.cusum_pos = 0.0
        self.cusum_neg = 0.0
        self.cusum_threshold = 3.0
        self.cusum_slack = 0.5
        
        # Spike detection state (for mini_flash_crash)
        self.spike_active = False
        self.spike_steps_remaining = 0
        self.spike_baseline_spread = None
        
        # Baseline values (established during calibration)
        self.baseline_spread = None
        self.baseline_depth = None
        
    def update(self, spread: float, depth: int, mid: float, imbalance: float = 0.0):
        """
        Update internal state with new market data.
        
        Args:
            spread: Current bid-ask spread
            depth: Total order book depth (bid + ask)
            mid: Mid price
            imbalance: Order book imbalance (-1 to +1)
        """
        if spread > 0:
            self.spread_history.append(spread)
        if depth > 0:
            self.depth_history.append(depth)
        if mid > 0:
            self.mid_history.append(mid)
        self.imbalance_history.append(imbalance)
        
        # Update spike detection
        if self.spike_active:
            self.spike_steps_remaining -= 1
            if self.spike_steps_remaining <= 0:
                self.spike_active = False
                self.spike_baseline_spread = None
    
    def set_baseline(self, spread: float, depth: int):
        """Set baseline values for regime detection."""
        self.baseline_spread = spread
        self.baseline_depth = depth
    
    def extract(self, bid: float, ask: float, bids: List[Dict], asks: List[Dict], 
                mid: float) -> Dict[str, float]:
        """
        Extract multi-timeframe features from current market state.
        
        Returns:
            Dictionary of feature names -> values
        """
        features = {}
        
        # Current values
        spread = ask - bid if ask > 0 and bid > 0 else 0.0
        total_depth = sum(b.get("qty", 0) for b in bids[:10]) + sum(a.get("qty", 0) for a in asks[:10])
        imbalance = self.get_order_imbalance(bids, asks, levels=3)
        
        # Update internal state
        self.update(spread, total_depth, mid, imbalance)
        
        # Multi-timeframe spread features
        for window_name, window_size in self.WINDOWS.items():
            if len(self.spread_history) >= window_size:
                window_spreads = list(self.spread_history)[-window_size:]
                features[f"{window_name}_spread_mean"] = statistics.mean(window_spreads)
                features[f"{window_name}_spread_std"] = statistics.stdev(window_spreads) if len(window_spreads) > 1 else 0.0
                features[f"{window_name}_spread_max"] = max(window_spreads)
                features[f"{window_name}_spread_min"] = min(window_spreads)
            else:
                # Not enough data yet
                features[f"{window_name}_spread_mean"] = spread if spread > 0 else 0.0
                features[f"{window_name}_spread_std"] = 0.0
                features[f"{window_name}_spread_max"] = spread if spread > 0 else 0.0
                features[f"{window_name}_spread_min"] = spread if spread > 0 else 0.0
        
        # Multi-timeframe depth features
        for window_name, window_size in self.WINDOWS.items():
            if len(self.depth_history) >= window_size:
                window_depths = list(self.depth_history)[-window_size:]
                features[f"{window_name}_depth_mean"] = statistics.mean(window_depths)
                features[f"{window_name}_depth_std"] = statistics.stdev(window_depths) if len(window_depths) > 1 else 0.0
                features[f"{window_name}_depth_min"] = min(window_depths)
            else:
                features[f"{window_name}_depth_mean"] = total_depth if total_depth > 0 else 0.0
                features[f"{window_name}_depth_std"] = 0.0
                features[f"{window_name}_depth_min"] = total_depth if total_depth > 0 else 0.0
        
        # Multi-timeframe price features
        for window_name, window_size in self.WINDOWS.items():
            if len(self.mid_history) >= window_size:
                window_mids = list(self.mid_history)[-window_size:]
                features[f"{window_name}_price_change"] = window_mids[-1] - window_mids[0]
                features[f"{window_name}_volatility"] = statistics.stdev(window_mids) if len(window_mids) > 1 else 0.0
                features[f"{window_name}_price_velocity"] = abs(window_mids[-1] - window_mids[0]) / window_size if window_size > 0 else 0.0
            else:
                features[f"{window_name}_price_change"] = 0.0
                features[f"{window_name}_volatility"] = 0.0
                features[f"{window_name}_price_velocity"] = 0.0
        
        # Spread velocity (rate of change)
        if len(self.spread_history) >= 10:
            recent_avg = statistics.mean(list(self.spread_history)[-5:])
            earlier_avg = statistics.mean(list(self.spread_history)[-10:-5]) if len(self.spread_history) >= 10 else recent_avg
            if earlier_avg > 0:
                features["spread_velocity"] = (recent_avg - earlier_avg) / earlier_avg
            else:
                features["spread_velocity"] = 0.0
        else:
            features["spread_velocity"] = 0.0
        
        # Depth collapse ratio
        if self.baseline_depth and self.baseline_depth > 0:
            features["depth_collapse_ratio"] = features["medium_depth_mean"] / self.baseline_depth
        else:
            features["depth_collapse_ratio"] = 1.0
        
        # Current values
        features["current_spread"] = spread
        features["current_depth"] = total_depth
        features["current_imbalance"] = imbalance
        
        # Spread acceleration (short vs long)
        if features.get("long_spread_mean", 0) > 0:
            features["spread_acceleration"] = features["short_spread_mean"] / features["long_spread_mean"]
        else:
            features["spread_acceleration"] = 1.0
        
        return features
    
    def get_order_imbalance(self, bids: List[Dict], asks: List[Dict], levels: int = 3) -> float:
        """
        Calculate order book imbalance.
        
        Returns:
            Imbalance ratio from -1 (all asks) to +1 (all bids)
        """
        bid_qty = sum(b.get("qty", 0) for b in bids[:levels])
        ask_qty = sum(a.get("qty", 0) for a in asks[:levels])
        total = bid_qty + ask_qty
        
        if total == 0:
            return 0.0
        
        return (bid_qty - ask_qty) / total
    
    def cusum_detect(self, value: float, baseline: Optional[float] = None) -> Optional[str]:
        """
        CUSUM change-point detection for regime transitions.
        
        Args:
            value: Current value to test (e.g., spread)
            baseline: Baseline value (uses self.baseline_spread if None)
        
        Returns:
            "STRESS_UP" if upward change detected, "STRESS_DOWN" if downward,
            None if no change
        """
        if baseline is None:
            baseline = self.baseline_spread
        
        if baseline is None or baseline <= 0:
            return None
        
        # Normalize deviation
        deviation = (value - baseline) / max(0.1, baseline)
        
        # Update CUSUM statistics
        self.cusum_pos = max(0, self.cusum_pos + deviation - self.cusum_slack)
        self.cusum_neg = max(0, self.cusum_neg - deviation - self.cusum_slack)
        
        # Check for regime change
        if self.cusum_pos > self.cusum_threshold:
            self.cusum_pos = 0  # Reset after detection
            return "STRESS_UP"
        elif self.cusum_neg > self.cusum_threshold:
            self.cusum_neg = 0
            return "STRESS_DOWN"
        
        return None
    
    def detect_spike(self) -> Tuple[bool, int]:
        """
        Detect volatility spike (for mini_flash_crash scenario).
        Spikes last exactly 4 steps with sudden spread widening.
        
        Returns:
            (is_spike, steps_remaining)
        """
        if len(self.spread_history) < 5:
            return False, 0
        
        # Check if we're already in a spike
        if self.spike_active:
            return True, self.spike_steps_remaining
        
        # Detect new spike: sudden spread widening (>50% increase)
        recent_spreads = list(self.spread_history)[-5:]
        if len(self.spread_history) >= 20:
            baseline_spread = statistics.mean(list(self.spread_history)[-20:-5])
        else:
            baseline_spread = recent_spreads[0]
        
        if baseline_spread <= 0:
            return False, 0
        
        current_spread = recent_spreads[-1]
        spread_jump = current_spread / baseline_spread
        
        # Spike detected: spread widened by >50%
        if spread_jump > 1.5:
            self.spike_active = True
            self.spike_steps_remaining = 4  # Spikes last exactly 4 steps
            self.spike_baseline_spread = baseline_spread
            return True, 4
        
        return False, 0
    
    def reset_cusum(self):
        """Reset CUSUM statistics (useful after regime change)."""
        self.cusum_pos = 0.0
        self.cusum_neg = 0.0

