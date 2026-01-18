"""
Passive Market Maker Strategy
=============================
Provides liquidity by quoting both sides of the market.
"""

from typing import Dict, Optional
from strategies.base import BaseStrategy
from strategies.metrics import IncrementalMetrics


class PassiveMarketMaker(BaseStrategy):
    """
    Passive market making strategy.
    
    Quotes at mid price with inventory skew to maintain balanced position.
    """
    
    def __init__(self, skew_factor: float = 0.008, max_inventory: int = 3000,
                 qty: int = 200, trade_freq: int = 15):
        """
        Initialize passive market maker.
        
        Args:
            skew_factor: How much to adjust quotes per unit of inventory
            max_inventory: Maximum inventory before stopping new positions
            qty: Order quantity
            trade_freq: Trade every N steps
        """
        super().__init__("passive_mm")
        self.skew_factor = skew_factor
        self.max_inventory = max_inventory
        self.qty = qty
        self.trade_freq = trade_freq
    
    def get_order(self, bid: float, ask: float, mid: float, inventory: int,
                  step: int, metrics: IncrementalMetrics) -> Optional[Dict]:
        """
        Generate order based on passive market making logic.
        """
        # Trade only at specified frequency
        if step % self.trade_freq != 0:
            return None
        
        # Don't exceed inventory limits
        if abs(inventory) >= self.max_inventory:
            return None
        
        # Inventory skew: shift quotes to reduce position
        skew = -self.skew_factor * inventory
        
        # Alternate BUY/SELL to maintain two-sided market
        if (step // self.trade_freq) % 2 == 0:
            # Buy at mid with skew
            return {"side": "BUY", "price": round(mid + skew, 2), "qty": self.qty}
        else:
            # Sell at mid with skew
            return {"side": "SELL", "price": round(mid + skew, 2), "qty": self.qty}
