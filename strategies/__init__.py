"""
Trading Strategies Package
===========================
Modular trading strategies with regime classification.
"""

from strategies.metrics import IncrementalMetrics
from strategies.classifier import RegimeClassifier
from strategies.base import BaseStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.passive_mm import PassiveMarketMaker
from strategies.aggressive_mm import AggressiveMarketMaker
from strategies.crash_survival import CrashSurvivalStrategy
from strategies.router import StrategyRouter

__all__ = [
    "IncrementalMetrics",
    "RegimeClassifier",
    "BaseStrategy",
    "MeanReversionStrategy",
    "MomentumStrategy",
    "PassiveMarketMaker",
    "AggressiveMarketMaker",
    "CrashSurvivalStrategy",
    "StrategyRouter",
]
