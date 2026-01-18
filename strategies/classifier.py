"""
Regime Classifier
=================
Classify market into regimes based on metrics.
"""

from strategies.metrics import IncrementalMetrics


class RegimeClassifier:
    """
    Classifies market regime based on observable signals.
    """
    
    # Regime constants
    CALIBRATING = "CALIBRATING"
    NORMAL = "NORMAL"
    STRESSED = "STRESSED"
    CRASH = "CRASH"
    HFT = "HFT"
    RECOVERY = "RECOVERY"
    
    def __init__(self):
        self.current_regime = self.CALIBRATING
        self.previous_regime = self.CALIBRATING
        self.regime_duration = 0
        self.crash_cooldown = 0  # Steps since last crash
    
    def classify(self, metrics: IncrementalMetrics) -> str:
        """
        Determine current market regime based on metrics.
        
        Args:
            metrics: IncrementalMetrics instance with current market state
            
        Returns:
            Regime string (CALIBRATING, NORMAL, STRESSED, CRASH, HFT, RECOVERY)
        """
        self.previous_regime = self.current_regime
        
        # Still calibrating
        if not metrics.calibrated:
            self.current_regime = self.CALIBRATING
            return self.current_regime
        
        # Extract signals
        spread_ratio = metrics.spread_ratio
        depth_ratio = metrics.depth_ratio
        abs_velocity = abs(metrics.price_velocity)
        abs_imbalance = abs(metrics.imbalance)
        
        # --- CRASH detection (highest priority) ---
        if spread_ratio > 2.5 or abs_velocity > 0.15 or abs_imbalance > 0.6:
            self.current_regime = self.CRASH
            self.crash_cooldown = 0
        
        # --- RECOVERY detection (recently exited crash) ---
        elif self.previous_regime == self.CRASH and spread_ratio < 2.0:
            self.current_regime = self.RECOVERY
            self.crash_cooldown = 100  # Stay cautious for 100 steps
        
        elif self.current_regime == self.RECOVERY:
            self.crash_cooldown -= 1
            if self.crash_cooldown <= 0 and spread_ratio < 1.5:
                # Transition out of recovery
                self.current_regime = self.NORMAL
        
        # --- STRESSED detection ---
        elif spread_ratio > 1.5 or abs_imbalance > 0.4 or depth_ratio < 0.5:
            self.current_regime = self.STRESSED
        
        # --- HFT detection (thin but stable) ---
        elif depth_ratio < 0.6 and spread_ratio < 1.3:
            self.current_regime = self.HFT
        
        # --- Default: NORMAL ---
        else:
            self.current_regime = self.NORMAL
        
        # Track duration
        if self.current_regime == self.previous_regime:
            self.regime_duration += 1
        else:
            self.regime_duration = 0
        
        return self.current_regime
