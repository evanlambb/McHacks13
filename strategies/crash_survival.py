"""
Crash Survival Strategy
=======================
Emergency strategy that only flattens positions during crashes.
"""

from typing import Dict, Optional
from strategies.base import BaseStrategy
from strategies.metrics import IncrementalMetrics


class CrashSurvivalStrategy(BaseStrategy):
    """
    Crash survival strategy.
    
    Only action: flatten positions aggressively. Never adds new positions.
    """
    
    def __init__(self, flatten_threshold: int = 200, qty: int = 500):
        """
        Initialize crash survival strategy.
        
        Args:
            flatten_threshold: Minimum inventory to trigger unwind
            qty: Order quantity for unwinding
        """
        super().__init__("crash_survival")
        self.flatten_threshold = flatten_threshold
        self.qty = qty
    
    def get_order(self, bid: float, ask: float, mid: float, inventory: int,
                  step: int, metrics: IncrementalMetrics) -> Optional[Dict]:
        """
        Generate order - only flatten positions, never add.
        """
        # Only action: flatten position aggressively
        if abs(inventory) > self.flatten_threshold:
            qty = min(self.qty, abs(inventory))
            if inventory > 0:
                # Sell below bid to guarantee fill
                return {"side": "SELL", "price": round(bid - 0.10, 2), "qty": qty}
            else:
                # Buy above ask to guarantee fill
                return {"side": "BUY", "price": round(ask + 0.10, 2), "qty": qty}
        
        # Stay flat - no new positions
        return None
