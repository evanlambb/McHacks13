"""
Base Strategy Class
===================
Abstract base class that all strategies inherit from.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from strategies.metrics import IncrementalMetrics


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    """
    
    def __init__(self, name: str):
        """
        Initialize strategy.
        
        Args:
            name: Strategy name for identification
        """
        self.name = name
    
    @abstractmethod
    def get_order(self, bid: float, ask: float, mid: float, inventory: int, 
                  step: int, metrics: IncrementalMetrics) -> Optional[Dict]:
        """
        Decide what order to submit (if any).
        
        Args:
            bid: Best bid price
            ask: Best ask price
            mid: Mid price
            inventory: Current position (positive = long, negative = short)
            step: Current simulation step
            metrics: IncrementalMetrics instance with current market metrics
            
        Returns:
            Order dict {"side": "BUY"|"SELL", "price": float, "qty": int} or None
        """
        pass
