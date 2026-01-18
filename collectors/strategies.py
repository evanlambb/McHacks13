"""
Experiment Strategies for Market Data Collection
================================================
Pluggable strategies to test different trading behaviors and market mechanics.
"""

from typing import Dict, Optional
from abc import ABC, abstractmethod
import sys
import os

# Add parent directory to path to import strategies
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategies.router import StrategyRouter


class ExperimentStrategy(ABC):
    """Base class for experiment strategies."""
    
    def __init__(self, name: str):
        self.name = name
        self.step_count = 0
    
    @abstractmethod
    def decide_order(self, bid: float, ask: float, mid: float, inventory: int, step: int) -> Optional[Dict]:
        """
        Decide what order to submit (if any).
        
        Args:
            bid: Best bid price
            ask: Best ask price
            mid: Mid price
            inventory: Current position
            step: Current simulation step
            
        Returns:
            Order dict {"side": "BUY"|"SELL", "price": float, "qty": int} or None
        """
        pass
    
    def get_name(self) -> str:
        """Get the strategy name."""
        return self.name


class PassiveObserver(ExperimentStrategy):
    """
    No trading - just observe market evolution.
    Useful for establishing baseline market behavior.
    """
    
    def __init__(self):
        super().__init__("passive")
    
    def decide_order(self, bid: float, ask: float, mid: float, inventory: int, step: int) -> Optional[Dict]:
        return None


class AggressiveBuyer(ExperimentStrategy):
    """
    Always buy at ask price (crossing the spread).
    Tests buy fill mechanics and market impact.
    """
    
    def __init__(self, qty: int = 100, frequency: int = 1):
        """
        Args:
            qty: Quantity to buy each time
            frequency: Trade every N steps (1 = every step)
        """
        super().__init__(f"aggressive_buy_qty{qty}_freq{frequency}")
        self.qty = qty
        self.frequency = frequency
    
    def decide_order(self, bid: float, ask: float, mid: float, inventory: int, step: int) -> Optional[Dict]:
        if ask <= 0:
            return None
        
        if step % self.frequency == 0:
            return {"side": "BUY", "price": round(ask, 2), "qty": self.qty}
        return None


class AggressiveSeller(ExperimentStrategy):
    """
    Always sell at bid price (crossing the spread).
    Tests sell fill mechanics and market impact.
    """
    
    def __init__(self, qty: int = 100, frequency: int = 1):
        """
        Args:
            qty: Quantity to sell each time
            frequency: Trade every N steps (1 = every step)
        """
        super().__init__(f"aggressive_sell_qty{qty}_freq{frequency}")
        self.qty = qty
        self.frequency = frequency
    
    def decide_order(self, bid: float, ask: float, mid: float, inventory: int, step: int) -> Optional[Dict]:
        if bid <= 0:
            return None
        
        if step % self.frequency == 0:
            return {"side": "SELL", "price": round(bid, 2), "qty": self.qty}
        return None


class SpreadCrosser(ExperimentStrategy):
    """
    Alternate between buying and selling, crossing the spread.
    Tests both sides of fill mechanics.
    """
    
    def __init__(self, qty: int = 100, frequency: int = 1):
        """
        Args:
            qty: Quantity per trade
            frequency: Trade every N steps
        """
        super().__init__(f"spread_cross_qty{qty}_freq{frequency}")
        self.qty = qty
        self.frequency = frequency
    
    def decide_order(self, bid: float, ask: float, mid: float, inventory: int, step: int) -> Optional[Dict]:
        if bid <= 0 or ask <= 0:
            return None
        
        if step % self.frequency == 0:
            # Alternate buy/sell
            if (step // self.frequency) % 2 == 0:
                return {"side": "BUY", "price": round(ask, 2), "qty": self.qty}
            else:
                return {"side": "SELL", "price": round(bid, 2), "qty": self.qty}
        return None


class QuantityTester(ExperimentStrategy):
    """
    Test different quantities at fixed price.
    Useful for understanding how quantity affects fills.
    """
    
    def __init__(self, qty: int = 200, price_offset: float = 0.0, frequency: int = 10):
        """
        Args:
            qty: Quantity to trade
            price_offset: Price offset from mid (0 = mid, positive = above mid, negative = below mid)
            frequency: Trade every N steps
        """
        super().__init__(f"qty_test_{qty}_offset{price_offset}_freq{frequency}")
        self.qty = qty
        self.price_offset = price_offset
        self.frequency = frequency
    
    def decide_order(self, bid: float, ask: float, mid: float, inventory: int, step: int) -> Optional[Dict]:
        if mid <= 0:
            return None
        
        if step % self.frequency == 0:
            # Alternate buy/sell to avoid extreme inventory
            target_price = mid + self.price_offset
            
            if (step // self.frequency) % 2 == 0:
                # Buy at target price (or ask if target > ask)
                price = min(round(target_price, 2), round(ask, 2)) if ask > 0 else round(target_price, 2)
                return {"side": "BUY", "price": price, "qty": self.qty}
            else:
                # Sell at target price (or bid if target < bid)
                price = max(round(target_price, 2), round(bid, 2)) if bid > 0 else round(target_price, 2)
                return {"side": "SELL", "price": price, "qty": self.qty}
        return None


class PriceExplorer(ExperimentStrategy):
    """
    Test different price levels (at bid, at ask, at mid, above/below).
    Useful for understanding fill mechanics at different price points.
    """
    
    def __init__(self, price_level: str = "mid", qty: int = 100, frequency: int = 10):
        """
        Args:
            price_level: "bid", "ask", "mid", "bid-1", "ask+1", etc.
            qty: Quantity to trade
            frequency: Trade every N steps
        """
        super().__init__(f"price_explore_{price_level}_qty{qty}_freq{frequency}")
        self.price_level = price_level
        self.qty = qty
        self.frequency = frequency
    
    def decide_order(self, bid: float, ask: float, mid: float, inventory: int, step: int) -> Optional[Dict]:
        if bid <= 0 or ask <= 0 or mid <= 0:
            return None
        
        if step % self.frequency == 0:
            # Determine target price based on price_level
            if self.price_level == "bid":
                target_price = bid
            elif self.price_level == "ask":
                target_price = ask
            elif self.price_level == "mid":
                target_price = mid
            elif self.price_level == "bid-1":
                target_price = bid - 0.01
            elif self.price_level == "ask+1":
                target_price = ask + 0.01
            elif self.price_level == "mid-0.5":
                target_price = mid - 0.5
            elif self.price_level == "mid+0.5":
                target_price = mid + 0.5
            else:
                target_price = mid
            
            # Alternate buy/sell
            if (step // self.frequency) % 2 == 0:
                return {"side": "BUY", "price": round(target_price, 2), "qty": self.qty}
            else:
                return {"side": "SELL", "price": round(target_price, 2), "qty": self.qty}
        return None


class InventoryManager(ExperimentStrategy):
    """
    Trade to maintain inventory near zero.
    Tests inventory management strategies.
    """
    
    def __init__(self, qty: int = 100, threshold: int = 200, frequency: int = 5):
        """
        Args:
            qty: Quantity per trade
            threshold: Inventory threshold before trading
            frequency: Check every N steps
        """
        super().__init__(f"inventory_mgmt_qty{qty}_thresh{threshold}_freq{frequency}")
        self.qty = qty
        self.threshold = threshold
        self.frequency = frequency
    
    def decide_order(self, bid: float, ask: float, mid: float, inventory: int, step: int) -> Optional[Dict]:
        if bid <= 0 or ask <= 0:
            return None
        
        if step % self.frequency == 0:
            # If too long, sell
            if inventory > self.threshold:
                return {"side": "SELL", "price": round(bid, 2), "qty": self.qty}
            # If too short, buy
            elif inventory < -self.threshold:
                return {"side": "BUY", "price": round(ask, 2), "qty": self.qty}
        return None


class RouterStrategy(ExperimentStrategy):
    """
    Wrapper strategy that uses the StrategyRouter with regime classification.
    Uses default depth values since ExperimentStrategy interface doesn't provide book data.
    """
    
    def __init__(self):
        super().__init__("router_strategy")
        self.router = StrategyRouter()
        # Default depth values (will be approximate)
        self.default_bid_depth = 1000
        self.default_ask_depth = 1000
    
    def decide_order(self, bid: float, ask: float, mid: float, inventory: int, step: int) -> Optional[Dict]:
        """
        Delegate to StrategyRouter.
        
        Note: Uses default depth values since ExperimentStrategy interface
        doesn't provide full book data. For accurate depth, use DataCollectorBot
        directly with student_algorithm.py which has full book access.
        """
        return self.router.decide_order(
            bid=bid,
            ask=ask,
            mid=mid,
            inventory=inventory,
            step=step,
            bid_depth=self.default_bid_depth,
            ask_depth=self.default_ask_depth
        )

