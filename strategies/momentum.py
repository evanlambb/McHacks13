"""
Momentum Strategy
=================
Trades on the assumption that trends continue.
"""

from typing import Dict, Optional
from strategies.base import BaseStrategy
from strategies.metrics import IncrementalMetrics


class MomentumStrategy(BaseStrategy):
    """
    Momentum strategy - follows trends.
    
    Enters positions when price is moving strongly in one direction,
    expecting the trend to continue.
    """
    
    def __init__(self, velocity_threshold: float = 0.05, max_inventory: int = 2000,
                 qty: int = 200, trade_freq: int = 20):
        """
        Initialize momentum strategy.
        
        Args:
            velocity_threshold: Minimum price velocity to trigger trade
            max_inventory: Maximum inventory before stopping new positions
            qty: Order quantity
            trade_freq: Trade every N steps
        """
        super().__init__("momentum")
        self.velocity_threshold = velocity_threshold
        self.max_inventory = max_inventory
        self.qty = qty
        self.trade_freq = trade_freq
    
    def get_order(self, bid: float, ask: float, mid: float, inventory: int,
                  step: int, metrics: IncrementalMetrics) -> Optional[Dict]:
        """
        Generate order based on momentum signals.
        """
        # Trade only at specified frequency
        if step % self.trade_freq != 0:
            return None
        
        # Don't exceed inventory limits
        if abs(inventory) >= self.max_inventory:
            return None
        
        price_velocity = metrics.price_velocity
        
        # Strong upward momentum
        if price_velocity > self.velocity_threshold and inventory < self.max_inventory:
            return {"side": "BUY", "price": round(ask, 2), "qty": self.qty}
        
        # Strong downward momentum
        if price_velocity < -self.velocity_threshold and inventory > -self.max_inventory:
            return {"side": "SELL", "price": round(bid, 2), "qty": self.qty}
        
        return None
