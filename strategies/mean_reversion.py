"""
Mean Reversion Strategy
=======================
Trades on the assumption that prices revert to their mean.
"""

from typing import Dict, Optional
from strategies.base import BaseStrategy
from strategies.metrics import IncrementalMetrics


class MeanReversionStrategy(BaseStrategy):
    """
    Mean reversion strategy for stable markets.
    
    Enters positions when price deviates significantly from mean,
    exits when price returns to mean.
    """
    
    def __init__(self, entry_z: float = 1.5, exit_z: float = 0.5, 
                 max_inventory: int = 2500, qty: int = 200):
        """
        Initialize mean reversion strategy.
        
        Args:
            entry_z: Z-score threshold to enter position
            exit_z: Z-score threshold to exit position
            max_inventory: Maximum inventory before stopping new positions
            qty: Order quantity
        """
        super().__init__("mean_reversion")
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.max_inventory = max_inventory
        self.qty = qty
    
    def get_order(self, bid: float, ask: float, mid: float, inventory: int,
                  step: int, metrics: IncrementalMetrics) -> Optional[Dict]:
        """
        Generate order based on mean reversion signals.
        """
        # Don't exceed inventory limits
        if abs(inventory) >= self.max_inventory:
            return None
        
        z_score = metrics.z_score
        
        # Entry: price far from mean
        if z_score < -self.entry_z and inventory < self.max_inventory:
            return {"side": "BUY", "price": round(ask, 2), "qty": self.qty}
        
        if z_score > self.entry_z and inventory > -self.max_inventory:
            return {"side": "SELL", "price": round(bid, 2), "qty": self.qty}
        
        # Exit: price returned to mean
        if abs(z_score) < self.exit_z:
            if inventory > 300:
                return {"side": "SELL", "price": round(bid, 2), "qty": min(self.qty, inventory)}
            if inventory < -300:
                return {"side": "BUY", "price": round(ask, 2), "qty": min(self.qty, abs(inventory))}
        
        return None
