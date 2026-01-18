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
    
    # If depth data is missing (default fallback), don't use depth for matching
    depth_available = avg_depth != 10000 or calibration_data.get("depth_available", False)
    
    best_match = None
    best_score = -1
    
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
            score += 5  # Increased weight
        elif spread_range[0] * 0.8 <= avg_spread <= spread_range[1] * 1.2:
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
        
        # Special case: HFT has very thin depth AND tight spread
        if scenario_id == "hft_dominated":
            if avg_depth < 2000 and avg_spread < 0.15:
                score += 5
            elif avg_spread > 0.20:  # Normal market has wider spread
                score -= 3  # Penalize HFT match if spread is too wide
        
        # Special case: Normal market has moderate spread (0.25-0.75)
        if scenario_id == "normal_market":
            if 0.25 <= avg_spread <= 0.75:
                score += 4
            elif avg_spread < 0.15:  # Too tight for normal
                score -= 2
        
        # Special case: Stressed has elevated spread
        if scenario_id == "stressed_market" and avg_spread > 0.75:
            score += 3
        
        # Special case: Flash crashes have high spread variance
        if scenario_id in ["flash_crash", "mini_flash_crash"]:
            spread_cv = spread_std / avg_spread if avg_spread > 0 else 0
            if spread_cv > 0.5:
                score += 3
        
        if score > best_score:
            best_score = score
            best_match = scenario_id
    
    # If no good match, return default
    if best_score < 3:
        return "default"
    
    return best_match or "default"

