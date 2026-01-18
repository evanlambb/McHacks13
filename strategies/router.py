"""
Strategy Router
===============
Routes to appropriate strategy based on market regime.
"""

from typing import Dict, Optional
from strategies.metrics import IncrementalMetrics
from strategies.classifier import RegimeClassifier
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.passive_mm import PassiveMarketMaker
from strategies.aggressive_mm import AggressiveMarketMaker
from strategies.crash_survival import CrashSurvivalStrategy


class StrategyRouter:
    """
    Routes to appropriate strategy based on market regime classification.
    """
    
    def __init__(self):
        """Initialize router with metrics, classifier, and all strategies."""
        self.metrics = IncrementalMetrics()
        self.classifier = RegimeClassifier()
        self.strategies = {
            "mean_reversion": MeanReversionStrategy(),
            "momentum": MomentumStrategy(),
            "passive_mm": PassiveMarketMaker(),
            "aggressive_mm": AggressiveMarketMaker(),
            "crash_survival": CrashSurvivalStrategy(),
        }
    
    def decide_order(self, bid: float, ask: float, mid: float, inventory: int,
                     step: int, bid_depth: int, ask_depth: int) -> Optional[Dict]:
        """
        Main decision method: update metrics, classify regime, route to strategy.
        
        Args:
            bid: Best bid price
            ask: Best ask price
            mid: Mid price
            inventory: Current position
            step: Current simulation step
            bid_depth: Total bid depth
            ask_depth: Total ask depth
            
        Returns:
            Order dict or None
        """
        # Skip if no valid prices
        if mid <= 0 or bid <= 0 or ask <= 0:
            return None
        
        spread = ask - bid
        
        # 1. Update metrics
        self.metrics.update(mid, spread, bid_depth, ask_depth)
        
        # 2. Classify regime
        regime = self.classifier.classify(self.metrics)
        
        # Log regime changes (optional, can be removed for production)
        if regime != self.classifier.previous_regime:
            print(f"[Step {step}] REGIME CHANGE: {self.classifier.previous_regime} → {regime}")
        
        # 3. Route to appropriate strategy
        order = None
        
        if regime == RegimeClassifier.CALIBRATING:
            # Don't trade during calibration
            order = None
        
        elif regime == RegimeClassifier.CRASH:
            # CRASH: Survival mode - only flatten
            order = self.strategies["crash_survival"].get_order(
                bid, ask, mid, inventory, step, self.metrics
            )
        
        elif regime == RegimeClassifier.RECOVERY:
            # RECOVERY: Conservative approach
            order = self.strategies["passive_mm"].get_order(
                bid, ask, mid, inventory, step, self.metrics
            )
        
        elif regime == RegimeClassifier.STRESSED:
            # STRESSED: Conservative with wider spreads
            order = self.strategies["passive_mm"].get_order(
                bid, ask, mid, inventory, step, self.metrics
            )
        
        elif regime == RegimeClassifier.HFT:
            # HFT: Careful, small sizes
            order = self.strategies["passive_mm"].get_order(
                bid, ask, mid, inventory, step, self.metrics
            )
        
        elif regime == RegimeClassifier.NORMAL:
            # NORMAL: Check if mean reversion opportunity exists
            z_score = self.metrics.z_score
            
            # Strong mean reversion signal takes priority
            if abs(z_score) > 1.5:
                order = self.strategies["mean_reversion"].get_order(
                    bid, ask, mid, inventory, step, self.metrics
                )
            else:
                # Default to aggressive market making
                order = self.strategies["aggressive_mm"].get_order(
                    bid, ask, mid, inventory, step, self.metrics
                )
        
        # 4. Apply risk management overlay
        order = self._apply_risk_management(order, bid, ask, inventory)
        
        return order
    
    def _apply_risk_management(self, order: Optional[Dict], bid: float, ask: float,
                              inventory: int) -> Optional[Dict]:
        """
        Final risk checks before returning order.
        
        Args:
            order: Order from strategy (may be None)
            bid: Best bid price
            ask: Best ask price
            inventory: Current inventory
            
        Returns:
            Order dict or None (may be modified or blocked)
        """
        # Hard inventory limit check
        HARD_LIMIT = 4500
        
        # If no order, check if we need emergency unwind
        if order is None:
            if inventory >= HARD_LIMIT:
                return {"side": "SELL", "price": round(bid - 0.05, 2), "qty": 500}
            if inventory <= -HARD_LIMIT:
                return {"side": "BUY", "price": round(ask + 0.05, 2), "qty": 500}
            return None
        
        # Validate order wouldn't breach limit
        if order["side"] == "BUY":
            resulting_inventory = inventory + order["qty"]
        else:
            resulting_inventory = inventory - order["qty"]
        
        if abs(resulting_inventory) >= HARD_LIMIT:
            # Block order that would breach limit
            # Instead, try to unwind if we're close to limit
            if inventory > 3500:
                return {"side": "SELL", "price": round(bid, 2), "qty": min(300, inventory - 3000)}
            if inventory < -3500:
                return {"side": "BUY", "price": round(ask, 2), "qty": min(300, abs(inventory) - 3000)}
            return None
        
        # Validate qty bounds (100-500)
        order["qty"] = max(100, min(500, order["qty"]))
        
        return order
