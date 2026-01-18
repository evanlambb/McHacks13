"""
Configuration Loader for Trading Bot
====================================
Loads and validates scenario-specific configuration files.
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional, Any

# Get the directory where this file is located
_CONFIG_DIR = Path(__file__).parent


def load_config(scenario_id: str) -> Dict[str, Any]:
    """
    Load configuration for a specific scenario.
    
    Args:
        scenario_id: Scenario identifier (e.g., "normal_market", "hft_dominated")
    
    Returns:
        Configuration dictionary
    
    Raises:
        FileNotFoundError: If config file doesn't exist
        json.JSONDecodeError: If config file is invalid JSON
    """
    config_path = _CONFIG_DIR / f"{scenario_id}.json"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # Validate config structure
    validate_config(config)
    
    return config


def load_all_configs() -> Dict[str, Dict[str, Any]]:
    """
    Load all available configuration files.
    
    Returns:
        Dictionary mapping scenario_id -> config dict
    """
    configs = {}
    
    for config_file in _CONFIG_DIR.glob("*.json"):
        if config_file.name == "__init__.py":
            continue
        
        scenario_id = config_file.stem
        try:
            configs[scenario_id] = load_config(scenario_id)
        except Exception as e:
            print(f"Warning: Failed to load {config_file.name}: {e}")
            continue
    
    return configs


def get_default_config() -> Dict[str, Any]:
    """
    Get the default/fallback configuration.
    
    Returns:
        Default configuration dictionary
    """
    try:
        return load_config("default")
    except FileNotFoundError:
        # If default.json doesn't exist, return a conservative fallback
        return {
            "scenario_id": "default",
            "detection_signature": {
                "spread_range": [0.25, 1.0],
                "depth_range": [3000, 15000],
                "volatility_range": [0.0005, 0.003]
            },
            "base_params": {
                "tick_size": 0.25,
                "calibration_steps": 300,
                "inventory_warning": 2000,
                "inventory_danger": 3500,
                "inventory_critical": 4500
            },
            "regime_thresholds": {
                "crash_spread_multiplier": 3.0,
                "stressed_spread_multiplier": 1.8,
                "hft_depth_ratio": 0.5,
                "crash_price_velocity": 2.0
            },
            "regime_strategies": {
                "NORMAL": {
                    "trade_frequency": 50,
                    "order_size": 200,
                    "max_inventory": 2500,
                    "spread_capture": True,
                    "compete": True
                },
                "HFT": {
                    "trade_frequency": 150,
                    "order_size": 100,
                    "max_inventory": 1000,
                    "spread_capture": True,
                    "compete": False
                },
                "STRESSED": {
                    "trade_frequency": 100,
                    "order_size": 200,
                    "max_inventory": 2000,
                    "spread_capture": True,
                    "compete": True
                },
                "CRASH": {
                    "trade_frequency": 1,
                    "order_size": 500,
                    "max_inventory": 200,
                    "spread_capture": False,
                    "unwind_only": True,
                    "compete": False
                }
            }
        }


def validate_config(config: Dict[str, Any]) -> None:
    """
    Validate that a configuration dictionary has the required structure.
    
    Args:
        config: Configuration dictionary to validate
    
    Raises:
        ValueError: If config structure is invalid
    """
    required_keys = [
        "scenario_id",
        "detection_signature",
        "base_params",
        "regime_thresholds",
        "regime_strategies"
    ]
    
    for key in required_keys:
        if key not in config:
            raise ValueError(f"Missing required config key: {key}")
    
    # Validate detection_signature
    sig = config["detection_signature"]
    if not all(k in sig for k in ["spread_range", "depth_range", "volatility_range"]):
        raise ValueError("detection_signature missing required fields")
    
    # Validate base_params
    base = config["base_params"]
    required_base = ["tick_size", "calibration_steps", "inventory_warning", 
                     "inventory_danger", "inventory_critical"]
    for key in required_base:
        if key not in base:
            raise ValueError(f"base_params missing required field: {key}")
    
    # Validate regime_thresholds
    thresholds = config["regime_thresholds"]
    required_thresholds = ["crash_spread_multiplier", "stressed_spread_multiplier",
                          "hft_depth_ratio", "crash_price_velocity"]
    for key in required_thresholds:
        if key not in thresholds:
            raise ValueError(f"regime_thresholds missing required field: {key}")
    
    # Validate regime_strategies
    strategies = config["regime_strategies"]
    required_regimes = ["NORMAL", "HFT", "STRESSED", "CRASH"]
    for regime in required_regimes:
        if regime not in strategies:
            raise ValueError(f"regime_strategies missing required regime: {regime}")
        
        regime_config = strategies[regime]
        required_regime_keys = ["trade_frequency", "order_size", "max_inventory",
                               "spread_capture", "compete"]
        for key in required_regime_keys:
            if key not in regime_config:
                raise ValueError(f"regime_strategies.{regime} missing required field: {key}")


def match_scenario_signature(calibration_data: Dict[str, Any], 
                            all_configs: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    """
    Match calibration data to a scenario based on detection signatures.
    
    Args:
        calibration_data: Dictionary with keys:
            - avg_spread: Average spread during calibration
            - avg_depth: Average order book depth
            - spread_std: Standard deviation of spreads
            - volatility: Price volatility measure
            - price_drift: Optional price drift over calibration period
            - depth_variability: Optional coefficient of variation for depth
        all_configs: Optional pre-loaded configs dict
    
    Returns:
        Best matching scenario_id
    """
    if all_configs is None:
        all_configs = load_all_configs()
    
    avg_spread = calibration_data.get("avg_spread", 0.5)
    avg_depth = calibration_data.get("avg_depth", 10000)
    spread_std = calibration_data.get("spread_std", 0.1)
    volatility = calibration_data.get("volatility", 0.001)
    price_drift = calibration_data.get("price_drift", 0.0)  # Price change over calibration
    depth_variability = calibration_data.get("depth_variability", 0.0)  # Depth CV
    
    # If depth data is missing (default fallback), don't use depth for matching
    depth_available = avg_depth != 10000 or calibration_data.get("depth_available", False)
    
    # Calculate spread coefficient of variation
    spread_cv = spread_std / avg_spread if avg_spread > 0 else 0
    
    best_match = None
    best_score = -1
    
    # Debug info for scenario detection
    debug_scores = {}
    
    for scenario_id, config in all_configs.items():
        if scenario_id == "default":
            continue
        
        sig = config["detection_signature"]
        spread_range = sig["spread_range"]
        depth_range = sig["depth_range"]
        vol_range = sig["volatility_range"]
        
        # Calculate match score
        score = 0
        
        # Spread match (most important)
        if spread_range[0] <= avg_spread <= spread_range[1]:
            score += 5
        elif spread_range[0] * 0.7 <= avg_spread <= spread_range[1] * 1.3:
            score += 2
        
        # Depth match (only if depth data is available)
        if depth_available:
            if depth_range[0] <= avg_depth <= depth_range[1]:
                score += 3
            elif depth_range[0] * 0.5 <= avg_depth <= depth_range[1] * 1.5:
                score += 1
        
        # Volatility match
        if vol_range[0] <= volatility <= vol_range[1]:
            score += 2
        elif vol_range[0] * 0.5 <= volatility <= vol_range[1] * 2.0:
            score += 1
        
        # =============================================
        # SCENARIO-SPECIFIC DETECTION LOGIC
        # =============================================
        
        # STRESSED_MARKET: Key indicators
        # - Negative price drift (fundamentalDrift = -0.0001)
        # - Only 3 MMs (lower depth, more variable)
        # - Higher volatility (0.002 vs 0.001)
        # - Spread often elevated but can be moderate early on
        if scenario_id == "stressed_market":
            # MUTUAL EXCLUSION: Stressed should NOT have tight spreads
            if avg_spread < 0.25:
                score -= 4  # Not stressed if spread is very tight
            
            # MUTUAL EXCLUSION: Stressed should NOT have high depth (only 3 MMs)
            if depth_available and avg_depth > 8000:
                score -= 3  # Not stressed with 20 MMs worth of depth
            
            # Reduced drift bonus (was +8, now +3 to avoid overwhelming)
            if price_drift < -0.0005:
                score += 3  # Reduced from +8 - drift can be noisy
            elif price_drift < 0:
                score += 2  # Some negative drift
            
            # Low depth due to only 3 MMs (vs 5 in normal)
            if depth_available and avg_depth < 4000:
                score += 3
            
            # Higher volatility expected
            if volatility > 0.0012:
                score += 2
            
            # Moderate-to-elevated spread (can start moderate and widen)
            if 0.3 <= avg_spread <= 2.0:
                score += 2
            
            # Depth variability - fewer MMs means more variable depth
            if depth_variability > 0.4:
                score += 2
        
        # HFT_DOMINATED: Very tight spreads, thin depth, high activity
        # Unique signature: tight spread AND thin depth together
        if scenario_id == "hft_dominated":
            # Strong unique signal: both conditions together
            if avg_spread < 0.3 and avg_depth < 3000:
                score += 6  # Strong unique signal - tight spread AND thin depth
            elif avg_spread < 0.2:
                score += 3  # Tight spread alone
            elif avg_spread < 0.15:
                score += 2  # Very tight spread
            
            # Penalize if spread is wide (not HFT)
            if avg_spread > 0.5:
                score -= 5  # Definitely not HFT if spread is wide
            elif avg_spread > 0.3:
                score -= 2  # Moderate penalty for wider spreads
        
        # NORMAL_MARKET: Moderate spread, good depth, stable
        if scenario_id == "normal_market":
            # Strong signal: moderate spread AND good depth
            if 0.25 <= avg_spread <= 0.75 and depth_available and avg_depth > 5000:
                score += 5  # Both conditions together
            elif 0.25 <= avg_spread <= 0.75:
                score += 4  # Moderate spread
            elif depth_available and avg_depth > 5000:
                score += 2  # Good depth
            
            # No significant price drift
            if abs(price_drift) < 0.0003:
                score += 2
            
            # Low spread variability
            if spread_cv < 0.5:
                score += 1
            
            # Penalize if showing stressed characteristics
            if price_drift < -0.0005:
                score -= 5  # Not normal if negative drift
        
        # FLASH_CRASH: Institutional selling at step 18000
        # During calibration (early steps), looks like normal market
        if scenario_id == "flash_crash":
            # High spread variability is a signal
            if spread_cv > 0.6:
                score += 2
            # But don't match if we see negative drift - that's stressed
            if price_drift < -0.0005:
                score -= 4  # flash_crash doesn't have fundamental drift
            # flash_crash has 20 MMs, so depth should be decent initially
            if depth_available and avg_depth > 8000:
                score += 2
        
        # MINI_FLASH_CRASH: Spiking traders cause random volatility
        if scenario_id == "mini_flash_crash":
            if spread_cv > 0.5 and volatility > 0.001:
                score += 2
            # Also doesn't have fundamental drift
            if price_drift < -0.0005:
                score -= 3
        
        debug_scores[scenario_id] = score
        
        if score > best_score:
            best_score = score
            best_match = scenario_id
    
    # Print debug info for scenario detection
    print(f"[SCENARIO DETECTION DEBUG] Scores: {debug_scores}")
    print(f"[SCENARIO DETECTION DEBUG] Data: spread={avg_spread:.4f}, depth={avg_depth:.0f}, "
          f"vol={volatility:.6f}, drift={price_drift:.6f}, spread_cv={spread_cv:.4f}, depth_cv={depth_variability:.4f}")
    
    # If no good match, return default
    if best_score < 3:
        return "default"
    
    return best_match or "default"

