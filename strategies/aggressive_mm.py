"""
Aggressive Market Maker Strategy
=================================
Crosses the spread to guarantee fills for high activity.
"""

from typing import Dict, Optional
from strategies.base import BaseStrategy
from strategies.metrics import IncrementalMetrics


class AggressiveMarketMaker(BaseStrategy):
    """
    Aggressive market making strategy.
    
    Crosses the spread to guarantee fills, trades frequently for high notional.
    """
    
    def __init__(self, max_inventory: int = 3500, qty: int = 250, trade_freq: int = 10):
        """
        Initialize aggressive market maker.
        
        Args:
            max_inventory: Maximum inventory before stopping new positions
            qty: Order quantity
            trade_freq: Trade every N steps
        """
        super().__init__("aggressive_mm")
        self.max_inventory = max_inventory
        self.qty = qty
        self.trade_freq = trade_freq
    
    def get_order(self, bid: float, ask: float, mid: float, inventory: int,
                  step: int, metrics: IncrementalMetrics) -> Optional[Dict]:
        """
        Generate order based on aggressive market making logic.
        """
        # Force unwind if over limit
        if inventory >= self.max_inventory:
            return {"side": "SELL", "price": round(bid, 2), "qty": 300}
        if inventory <= -self.max_inventory:
            return {"side": "BUY", "price": round(ask, 2), "qty": 300}
        
        # Trade at specified frequency
        if step % self.trade_freq != 0:
            return None
        
        # Inventory skew
        skew = -0.008 * inventory
        
        # Bias toward reducing position
        if inventory > 1000:
            return {"side": "SELL", "price": round(bid + 0.01, 2), "qty": self.qty}
        elif inventory < -1000:
            return {"side": "BUY", "price": round(ask - 0.01, 2), "qty": self.qty}
        else:
            # Alternate sides
            if (step // self.trade_freq) % 2 == 0:
                spread = ask - bid
                return {"side": "BUY", "price": round(mid - spread/4 + skew, 2), "qty": self.qty}
            else:
                spread = ask - bid
                return {"side": "SELL", "price": round(mid + spread/4 + skew, 2), "qty": self.qty}
