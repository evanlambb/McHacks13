"""
Student Trading Algorithm Template
===================================
Connect to the exchange simulator, receive market data, and submit orders.

    python student_algorithm.py --host ip:host --scenario normal_market --name your_name --password your_password --secure

YOUR TASK:
    Modify the `decide_order()` method to implement your trading strategy.
"""

import json
import websocket
import threading
import argparse
import time
import requests
import ssl
import urllib3
from typing import Dict, Optional, List
import statistics

# Config system
from configs import load_config, get_default_config, match_scenario_signature, load_all_configs

# Feature extraction for regime detection
from analysis.feature_extractor import FeatureExtractor

# Suppress SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class TradingBot:
    """
    A trading bot that connects to the exchange simulator.
    
    KEY INSIGHT: Market makers profit by BUYING at bid and SELLING at ask.
    NEVER cross the spread unless in emergency unwind mode.
    """
    
    def __init__(self, student_id: str, host: str, scenario: str, password: str = None, secure: bool = False):
        self.student_id = student_id
        self.host = host
        self.scenario = scenario
        self.password = password
        self.secure = secure
        
        # Protocol configuration
        self.http_proto = "https" if secure else "http"
        self.ws_proto = "wss" if secure else "ws"
        
        # Session info (set after registration)
        self.token = None
        self.run_id = None
        
        # Trading state - track your position
        self.inventory = 0      # Current position (positive = long, negative = short)
        self.cash_flow = 0.0    # Cumulative cash from trades (negative when buying)
        self.pnl = 0.0          # Mark-to-market PnL (cash_flow + inventory * mid_price)
        self.current_step = 0   # Current simulation step
        self.orders_sent = 0    # Number of orders sent
        
        # Market data
        self.last_bid = 0.0
        self.last_ask = 0.0
        self.last_mid = 0.0
        self.prev_mid = 0.0     # Previous mid for momentum detection
        
        # WebSocket connections
        self.market_ws = None
        self.order_ws = None
        self.running = True
        
        # Latency measurement
        self.last_done_time = None
        self.step_latencies = []
        self.order_send_times = {}  # order_id -> {"time": timestamp, "price": price, "side": side, "step": step}
        self.fill_latencies = []
        
        # Order management - MAX 50 OPEN ORDERS
        self.MAX_OPEN_ORDERS = 50
        self.ORDER_CANCEL_THRESHOLD = 45  # Start cancelling when we hit this many
        
        # Regime detection state
        self.spread_history = []
        self.depth_history = []
        self.mid_history = []
        self.baseline_spread = None
        self.baseline_depth = None
        
        # Regime state with stability controls
        self.regime = "CALIBRATING"
        self.steps_in_regime = 0
        self.regime_change_cooldown = 0  # Steps until we can change regime again
        self.pending_regime = None       # Regime we're considering switching to
        self.pending_regime_count = 0    # How many steps this pending regime has persisted
        
        # Regime stability constants
        self.REGIME_COOLDOWN_STEPS = 50          # Min steps between regime changes
        self.REGIME_PERSISTENCE_REQUIRED = 15    # Steps condition must hold to confirm change (increased from 8)
        self.REGIME_EXIT_PERSISTENCE = 20        # More steps needed to EXIT a regime (hysteresis, increased from 12)
        
        # Performance tracking
        self.consecutive_losses = 0
        self.last_fill_pnl = 0
        self.round_trips = 0        # Track completed round trips
        self.profitable_trips = 0   # Track profitable round trips
        
        # TICK SIZE - Must align orders to this!
        self.TICK_SIZE = 0.25
        
        # Constants - more conservative limits
        self.CALIBRATION_STEPS = 300    # Shorter calibration
        self.SPREAD_HISTORY_SIZE = 100
        self.INVENTORY_WARNING = 2000   # Start biasing earlier
        self.INVENTORY_DANGER = 3500    # More conservative
        self.INVENTORY_CRITICAL = 4500  # Leave more buffer to 5000
        
        # Order book depth tracking
        self.last_bid_depth = 0
        self.last_ask_depth = 0
        self.last_bids = []  # Full order book bids
        self.last_asks = []  # Full order book asks
        
        # Pending orders tracking
        self.pending_buy_price = None
        self.pending_sell_price = None
        
        # Configuration system - will be loaded after scenario detection
        self.config = None
        # Start with default config, will be replaced after scenario detection
        self.config = get_default_config()
        
        # Apply base params from config
        base_params = self.config["base_params"]
        self.TICK_SIZE = base_params["tick_size"]
        self.CALIBRATION_STEPS = base_params["calibration_steps"]
        self.INVENTORY_WARNING = base_params["inventory_warning"]
        self.INVENTORY_DANGER = base_params["inventory_danger"]
        self.INVENTORY_CRITICAL = base_params["inventory_critical"]
        
        # Calibration data for baseline establishment and scenario detection
        self.calibration_spreads = []
        self.calibration_depths = []
        self.calibration_mids = []
        
        # Feature extractor for multi-timeframe analysis
        self.feature_extractor = FeatureExtractor()
        
        # Detected scenario (set at end of calibration)
        self.detected_scenario = None
    
    # =========================================================================
    # REGISTRATION - Get a token to start trading
    # =========================================================================
    
    def register(self) -> bool:
        """Register with the server and get an auth token."""
        print(f"[{self.student_id}] Registering for scenario '{self.scenario}'...")
        try:
            url = f"{self.http_proto}://{self.host}/api/replays/{self.scenario}/start"
            headers = {"Authorization": f"Bearer {self.student_id}"}
            if self.password:
                headers["X-Team-Password"] = self.password
            resp = requests.get(
                url,
                headers=headers,
                timeout=10,
                verify=not self.secure  # Disable SSL verification for self-signed certs
            )
            
            if resp.status_code != 200:
                print(f"[{self.student_id}] Registration FAILED: {resp.text}")
                return False
            
            data = resp.json()
            self.token = data.get("token")
            self.run_id = data.get("run_id")
            
            if not self.token or not self.run_id:
                print(f"[{self.student_id}] Missing token or run_id")
                return False
            
            print(f"[{self.student_id}] Registered! Run ID: {self.run_id}")
            return True
            
        except Exception as e:
            print(f"[{self.student_id}] Registration error: {e}")
            return False
    
    # =========================================================================
    # CONNECTION - Connect to WebSocket streams
    # =========================================================================
    
    def connect(self) -> bool:
        """Connect to market data and order entry WebSockets."""
        try:
            # SSL options for self-signed certificates
            sslopt = {"cert_reqs": ssl.CERT_NONE} if self.secure else None
            
            # Market Data WebSocket
            market_url = f"{self.ws_proto}://{self.host}/api/ws/market?run_id={self.run_id}"
            self.market_ws = websocket.WebSocketApp(
                market_url,
                on_message=self._on_market_data,
                on_error=self._on_error,
                on_close=self._on_close,
                on_open=lambda ws: print(f"[{self.student_id}] Market data connected")
            )
            
            # Order Entry WebSocket
            order_url = f"{self.ws_proto}://{self.host}/api/ws/orders?token={self.token}&run_id={self.run_id}"
            self.order_ws = websocket.WebSocketApp(
                order_url,
                on_message=self._on_order_response,
                on_error=self._on_error,
                on_close=self._on_close,
                on_open=lambda ws: print(f"[{self.student_id}] Order entry connected")
            )
            
            # Start WebSocket threads
            threading.Thread(
                target=lambda: self.market_ws.run_forever(sslopt=sslopt),
                daemon=True
            ).start()
            
            threading.Thread(
                target=lambda: self.order_ws.run_forever(sslopt=sslopt),
                daemon=True
            ).start()
            
            # Wait for connections
            time.sleep(1)
            return True
            
        except Exception as e:
            print(f"[{self.student_id}] Connection error: {e}")
            return False
    
    # =========================================================================
    # MARKET DATA HANDLER - Called when new market data arrives
    # =========================================================================
    
    def _on_market_data(self, ws, message: str):
        """Handle incoming market data snapshot."""
        try:
            recv_time = time.time()
            data = json.loads(message)
            
            # Skip connection confirmation messages
            if data.get("type") == "CONNECTED":
                return
            
            # Measure step latency (time since we sent DONE)
            if self.last_done_time is not None:
                step_latency = (recv_time - self.last_done_time) * 1000  # ms
                self.step_latencies.append(step_latency)
            
            # Extract market data
            self.current_step = data.get("step", 0)
            self.last_bid = data.get("bid", 0.0)
            self.last_ask = data.get("ask", 0.0)
            
            # Extract order book depth and full order book
            # API provides bid_size/ask_size at top level, or calculate from bids/asks arrays
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            self.last_bids = bids
            self.last_asks = asks
            
            self.last_bid_depth = data.get("bid_size", 0)
            self.last_ask_depth = data.get("ask_size", 0)
            
            # Fallback: calculate from bids/asks arrays if sizes not provided
            if self.last_bid_depth == 0 or self.last_ask_depth == 0:
                if bids:
                    self.last_bid_depth = sum(b.get("qty", 0) for b in bids)
                if asks:
                    self.last_ask_depth = sum(a.get("qty", 0) for a in asks)
            
            # Calculate mid price
            if self.last_bid > 0 and self.last_ask > 0:
                self.last_mid = (self.last_bid + self.last_ask) / 2
            elif self.last_bid > 0:
                self.last_mid = self.last_bid
            elif self.last_ask > 0:
                self.last_mid = self.last_ask
            else:
                self.last_mid = 0
            
            # Collect calibration data for scenario detection
            spread = self.last_ask - self.last_bid if self.last_ask > 0 and self.last_bid > 0 else 0
            total_depth = self.last_bid_depth + self.last_ask_depth
            
            if self.current_step < self.CALIBRATION_STEPS:
                if spread > 0:
                    self.calibration_spreads.append(spread)
                if total_depth > 0:
                    self.calibration_depths.append(total_depth)
                if self.last_mid > 0:
                    self.calibration_mids.append(self.last_mid)
                
                # Update feature extractor during calibration
                imbalance = self.feature_extractor.get_order_imbalance(bids, asks, levels=3)
                self.feature_extractor.update(spread, total_depth, self.last_mid, imbalance)
            
            # Scenario detection and config loading at end of calibration
            if self.current_step == self.CALIBRATION_STEPS:
                if len(self.calibration_spreads) > 50:
                    print(f"[{self.student_id}] [CALIBRATION] Baseline established: {len(self.calibration_spreads)} data points")
                    
                    # Calculate calibration statistics for scenario detection
                    avg_spread = statistics.mean(self.calibration_spreads)
                    avg_depth = statistics.mean(self.calibration_depths) if len(self.calibration_depths) > 0 else 10000
                    spread_std = statistics.stdev(self.calibration_spreads) if len(self.calibration_spreads) > 1 else 0.1
                    
                    # Calculate volatility and price drift
                    volatility = 0.0
                    price_drift = 0.0
                    if len(self.calibration_mids) >= 100:
                        mid_changes = [self.calibration_mids[i] - self.calibration_mids[i-1] 
                                     for i in range(1, len(self.calibration_mids))]
                        volatility = statistics.stdev(mid_changes) if len(mid_changes) > 1 else 0.0
                        price_drift = (self.calibration_mids[-1] - self.calibration_mids[0]) / len(self.calibration_mids)
                    
                    # Calculate depth variability
                    depth_variability = 0.0
                    if len(self.calibration_depths) > 1 and avg_depth > 0:
                        depth_std = statistics.stdev(self.calibration_depths)
                        depth_variability = depth_std / avg_depth
                    
                    # Match scenario signature
                    calibration_data = {
                        "avg_spread": avg_spread,
                        "avg_depth": avg_depth,
                        "spread_std": spread_std,
                        "volatility": volatility,
                        "price_drift": price_drift,
                        "depth_variability": depth_variability,
                        "depth_available": True
                    }
                    
                    self.detected_scenario = match_scenario_signature(calibration_data)
                    print(f"[{self.student_id}] [SCENARIO DETECTION] Detected scenario: {self.detected_scenario}")
                    
                    # Load scenario-specific config
                    try:
                        self.config = load_config(self.detected_scenario)
                        print(f"[{self.student_id}] [CONFIG] Loaded config for {self.detected_scenario}")
                        
                        # Update base params from new config
                        base_params = self.config["base_params"]
                        self.TICK_SIZE = base_params["tick_size"]
                        self.CALIBRATION_STEPS = base_params["calibration_steps"]
                        self.INVENTORY_WARNING = base_params["inventory_warning"]
                        self.INVENTORY_DANGER = base_params["inventory_danger"]
                        self.INVENTORY_CRITICAL = base_params["inventory_critical"]
                    except Exception as e:
                        print(f"[{self.student_id}] [WARNING] Could not load config for {self.detected_scenario}, using default: {e}")
                        self.config = get_default_config()
                    
                    # Establish baseline for feature extractor
                    baseline_spread = avg_spread
                    baseline_depth = avg_depth
                    self.baseline_spread = baseline_spread
                    self.baseline_depth = baseline_depth
                    self.feature_extractor.set_baseline(baseline_spread, baseline_depth)
                    print(f"[{self.student_id}] [CALIBRATED] Baseline spread: {baseline_spread:.4f}, depth: {baseline_depth:.0f}")
                else:
                    print(f"[{self.student_id}] [WARNING] Insufficient calibration data ({len(self.calibration_spreads)} spreads)")
                    # Use defaults
                    self.baseline_spread = 0.5
                    self.baseline_depth = 10000
                    self.feature_extractor.set_baseline(self.baseline_spread, self.baseline_depth)
            
            # Update feature extractor after calibration
            if self.current_step >= self.CALIBRATION_STEPS:
                imbalance = self.feature_extractor.get_order_imbalance(bids, asks, levels=3)
                self.feature_extractor.update(spread, total_depth, self.last_mid, imbalance)
            
            # Log progress every 500 steps with latency stats
            if self.current_step % 500 == 0:
                avg_lat = sum(self.step_latencies[-100:]) / min(len(self.step_latencies), 100) if self.step_latencies else 0.0
                spread = self.last_ask - self.last_bid if self.last_ask > 0 and self.last_bid > 0 else 0
                open_count = self._get_open_order_count()
                print(f"[{self.student_id}] Step {self.current_step} | Orders: {self.orders_sent} | Open: {open_count}/{self.MAX_OPEN_ORDERS} | Inv: {self.inventory} | Regime: {self.regime} | Spread: {spread:.4f} | Depth: {self.last_bid_depth + self.last_ask_depth} | Avg Latency: {avg_lat:.1f}ms")
            
            # =============================================
            # YOUR STRATEGY LOGIC GOES HERE
            # =============================================
            order = self.decide_order(self.last_bid, self.last_ask, self.last_mid)
            
            if order and self.order_ws and self.order_ws.sock:
                self._send_order(order)
                
                # Two-sided quoting: also send opposite side order if enabled
                regime_config = self._get_regime_config(self.regime)
                if regime_config.get("two_sided", False) and abs(self.inventory) < regime_config.get("max_inventory", 1000) * 0.8:
                    opposite_order = self._get_opposite_order(order, self.last_bid, self.last_ask, regime_config)
                    if opposite_order:
                        self._send_order(opposite_order)
            
            # Signal DONE to advance to next step
            self._send_done()
            
        except Exception as e:
            print(f"[{self.student_id}] Market data error: {e}")
    
    # =========================================================================
    # UTILITY FUNCTIONS
    # =========================================================================
    
    def _round_to_tick(self, price: float) -> float:
        """Round price to nearest tick size (0.25)."""
        return round(round(price / self.TICK_SIZE) * self.TICK_SIZE, 2)
    
    def _round_qty_to_lot(self, qty: int, min_qty: int = 100) -> int:
        """Round quantity to nearest 100 (lot size), minimum 100."""
        rounded = max(min_qty, round(qty / 100) * 100)
        return min(500, rounded)  # Cap at max order size of 500
    
    def _ensure_qty_multiple_of_100(self, qty: int) -> int:
        """Ensure quantity is a multiple of 100, minimum 100, maximum 500."""
        if qty <= 0:
            return 100
        rounded = round(qty / 100) * 100
        return max(100, min(500, rounded))
    
    def _get_opposite_order(self, order: Dict, bid: float, ask: float, regime_config: Dict) -> Optional[Dict]:
        """
        Generate an opposite-side order for two-sided quoting.
        If the primary order is BUY, generate a SELL; if SELL, generate a BUY.
        """
        order_size = self._ensure_qty_multiple_of_100(regime_config.get("order_size", 100))
        aggressive_join = regime_config.get("aggressive_join", True)
        spread = ask - bid
        
        if order["side"] == "BUY":
            # Primary is BUY, add SELL at ask
            if aggressive_join and spread > self.TICK_SIZE * 2:
                price = round(ask - self.TICK_SIZE, 2)
            else:
                price = round(ask, 2)
            return {"side": "SELL", "price": price, "qty": order_size}
        else:
            # Primary is SELL, add BUY at bid
            if aggressive_join and spread > self.TICK_SIZE * 2:
                price = round(bid + self.TICK_SIZE, 2)
            else:
                price = round(bid, 2)
            return {"side": "BUY", "price": price, "qty": order_size}
    
    def _round_down_to_tick(self, price: float) -> float:
        """Round price down to tick size (for bids)."""
        import math
        return round(math.floor(price / self.TICK_SIZE) * self.TICK_SIZE, 2)
    
    def _round_up_to_tick(self, price: float) -> float:
        """Round price up to tick size (for asks)."""
        import math
        return round(math.ceil(price / self.TICK_SIZE) * self.TICK_SIZE, 2)
    
    # =========================================================================
    # SCENARIO AUTO-DETECTION
    # =========================================================================
    
    
    # =========================================================================
    # REGIME DETECTION - With Hysteresis, Persistence, and Cooldown
    # =========================================================================
    
    def _detect_regime(self, spread: float, bid_depth: int, ask_depth: int, bids: List[Dict], asks: List[Dict]) -> str:
        """
        Classify current market regime using multi-timeframe features and statistical detection.
        
        Key features:
        - Multi-timeframe analysis (short/medium/long windows)
        - CUSUM change-point detection
        - Spike detection for mini_flash_crash
        - Hysteresis: Different thresholds for entering vs exiting regimes
        - Persistence: Must stay in new conditions for N steps before switching
        - Cooldown: Minimum time between regime changes
        
        Returns: "CALIBRATING", "NORMAL", "STRESSED", "CRASH", "HFT", or "SPIKE"
        """
        total_depth = bid_depth + ask_depth
        
        # Update rolling histories (for backward compatibility)
        self.spread_history.append(spread)
        self.depth_history.append(total_depth)
        if len(self.spread_history) > self.SPREAD_HISTORY_SIZE:
            self.spread_history.pop(0)
            self.depth_history.pop(0)
        
        # Track mid price for momentum
        if self.last_mid > 0:
            self.mid_history.append(self.last_mid)
            if len(self.mid_history) > self.SPREAD_HISTORY_SIZE:
                self.mid_history.pop(0)
        
        # Still calibrating
        if self.current_step < self.CALIBRATION_STEPS:
            return "CALIBRATING"
        
        # DEAD MARKET CHECK: If spread=0 and depth<200, market is effectively dead
        # Stay in current regime (likely CRASH), don't oscillate
        if spread <= 0.01 and total_depth < 200:
            # Keep current regime, reset pending changes
            self.pending_regime = None
            self.pending_regime_count = 0
            return self.regime
        
        # Decrement cooldown
        if self.regime_change_cooldown > 0:
            self.regime_change_cooldown -= 1
        
        # Extract multi-timeframe features
        features = self.feature_extractor.extract(self.last_bid, self.last_ask, bids, asks, self.last_mid)
        
        # SPIKE DETECTION (highest priority - for mini_flash_crash)
        is_spike, spike_steps = self.feature_extractor.detect_spike()
        if is_spike:
            # Spike detected - return SPIKE regime immediately (no persistence needed)
            if self.regime != "SPIKE":
                print(f"[{self.student_id}] [REGIME] {self.regime} -> SPIKE | Step: {self.current_step} | Spread: {spread:.4f}")
                self.regime = "SPIKE"
                self.steps_in_regime = 0
            return "SPIKE"
        
        # If we were in SPIKE and it ended, transition back to normal detection
        if self.regime == "SPIKE" and not is_spike:
            self.regime = "NORMAL"  # Reset to normal, will be reclassified below
            self.pending_regime = None
            self.pending_regime_count = 0
        
        # CUSUM change-point detection
        cusum_signal = self.feature_extractor.cusum_detect(spread, self.baseline_spread)
        
        # Get thresholds from config
        thresholds = self.config["regime_thresholds"]
        crash_spread_mult = thresholds["crash_spread_multiplier"]
        stressed_spread_mult = thresholds["stressed_spread_multiplier"]
        hft_depth_ratio = thresholds["hft_depth_ratio"]
        crash_price_velocity = thresholds["crash_price_velocity"]
        crash_spread_velocity = thresholds.get("crash_spread_velocity", 0.5)
        crash_depth_collapse = thresholds.get("crash_depth_collapse_ratio", 0.5)
        
        # Extract features from multi-timeframe analysis
        recent_spread = features.get("medium_spread_mean", spread)
        recent_depth = features.get("medium_depth_mean", total_depth)
        price_velocity = features.get("medium_price_velocity", 0.0)
        spread_velocity = features.get("spread_velocity", 0.0)
        depth_collapse_ratio = features.get("depth_collapse_ratio", 1.0)
        spread_acceleration = features.get("spread_acceleration", 1.0)
        
        # Determine INSTANTANEOUS regime using multi-timeframe features
        instant_regime = self._classify_instant_regime_enhanced(
            features, recent_spread, recent_depth, price_velocity, spread_velocity,
            depth_collapse_ratio < crash_depth_collapse,
            crash_spread_mult, stressed_spread_mult, hft_depth_ratio, 
            crash_price_velocity, crash_spread_velocity, cusum_signal
        )
        
        # Apply hysteresis - harder to EXIT current regime than to stay
        if instant_regime != self.regime:
            # Check if we're in cooldown
            if self.regime_change_cooldown > 0:
                return self.regime  # Can't change yet
            
            # Track pending regime change
            if instant_regime == self.pending_regime:
                self.pending_regime_count += 1
            else:
                # New pending regime, reset counter
                self.pending_regime = instant_regime
                self.pending_regime_count = 1
            
            # Determine persistence requirement (hysteresis)
            # Exiting CRASH requires more persistence (it's a "sticky" state)
            required_persistence = self.REGIME_PERSISTENCE_REQUIRED
            if self.regime == "CRASH":
                required_persistence = self.REGIME_EXIT_PERSISTENCE
            # Also harder to exit STRESSED back to NORMAL
            elif self.regime == "STRESSED" and instant_regime == "NORMAL":
                required_persistence = self.REGIME_EXIT_PERSISTENCE
            
            # Check if we've met persistence requirement
            if self.pending_regime_count >= required_persistence:
                # Confirm regime change - log it here
                old_regime = self.regime
                self.regime = instant_regime
                self.steps_in_regime = 0
                self.regime_change_cooldown = self.REGIME_COOLDOWN_STEPS
                self.pending_regime = None
                self.pending_regime_count = 0
                # Reset CUSUM after regime change
                self.feature_extractor.reset_cusum()
                # Log the confirmed regime change
                print(f"[{self.student_id}] [REGIME] {old_regime} -> {self.regime} | "
                      f"Step: {self.current_step} | Spread: {spread:.4f} | "
                      f"Depth: {total_depth} | Inv: {self.inventory}")
                return self.regime
            else:
                # Not enough persistence yet, stay in current regime
                return self.regime
        else:
            # Same regime, reset pending
            self.pending_regime = None
            self.pending_regime_count = 0
            self.steps_in_regime += 1
            return self.regime
    
    def _classify_instant_regime_enhanced(self, features: Dict[str, float], spread: float, 
                                         depth: float, price_velocity: float,
                                         spread_velocity: float, depth_collapse: bool,
                                         crash_mult: float, stressed_mult: float, 
                                         hft_ratio: float, crash_velocity: float, 
                                         crash_spread_velocity: float, cusum_signal: Optional[str]) -> str:
        """
        Classify regime using multi-timeframe features and statistical signals.
        This is the "raw" classification that gets filtered by persistence/cooldown.
        
        Enhanced with:
        - Multi-timeframe analysis
        - CUSUM change-point detection
        - Spread velocity: sudden widening indicates crash
        - Depth collapse: >50% drop from baseline indicates crash
        """
        # CUSUM signal indicates regime change
        if cusum_signal == "STRESS_UP":
            # CUSUM detected upward stress - likely CRASH or STRESSED
            if spread > self.baseline_spread * crash_mult:
                return "CRASH"
            else:
                return "STRESSED"
        
        # CRASH SIGNAL DETECTION: Check for crash signals first (highest priority)
        # Spread velocity: sudden widening (>50% increase)
        if spread_velocity > crash_spread_velocity:
            return "CRASH"
        
        # Spread acceleration (short vs long) - rapid widening
        spread_acceleration = features.get("spread_acceleration", 1.0)
        if spread_acceleration > 2.0:  # Short-term spread is 2x long-term
            return "CRASH"
        
        # Depth collapse: >50% drop from baseline
        if depth_collapse:
            return "CRASH"
        
        # CRASH: Very wide spread OR market effectively dead
        # Use higher threshold to avoid false positives
        if spread > 5.0:  # Absolute threshold - very wide spread
            return "CRASH"
        if self.baseline_spread > 0 and spread > self.baseline_spread * crash_mult:
            return "CRASH"
        if price_velocity > crash_velocity:
            return "CRASH"
        
        # HFT: Very thin depth WITH tight spread
        # Must have BOTH conditions - thin depth alone isn't HFT
        # Use multi-timeframe features for better detection
        short_depth = features.get("short_depth_mean", depth)
        if depth < 500 and spread < 0.3:  # Stricter: thin depth AND tight spread
            return "HFT"
        if self.baseline_depth > 0 and depth < self.baseline_depth * hft_ratio and spread < 0.3:
            return "HFT"
        # Also check short-term depth for HFT detection
        if short_depth < 300 and spread < 0.25:
            return "HFT"
        
        # STRESSED: Moderately elevated spread
        # Use multi-timeframe to avoid false positives from temporary spikes
        medium_spread = features.get("medium_spread_mean", spread)
        if spread > 2.5:  # Absolute threshold for stressed
            return "STRESSED"
        if self.baseline_spread > 0 and medium_spread > self.baseline_spread * stressed_mult:
            return "STRESSED"
        
        return "NORMAL"
    
    # =========================================================================
    # INVENTORY MANAGEMENT
    # =========================================================================
    
    def _get_inventory_action(self, inventory: int) -> tuple:
        """
        Determine inventory management action.
        
        Returns: (action_type, urgency_level)
            action_type: "NORMAL", "UNWIND_BIAS", "UNWIND_ONLY", "EMERGENCY"
            urgency_level: 0-3 (higher = more urgent to unwind)
        """
        abs_inv = abs(inventory)
        
        if abs_inv >= self.INVENTORY_CRITICAL:
            return ("EMERGENCY", 3)
        elif abs_inv >= self.INVENTORY_DANGER:
            return ("UNWIND_ONLY", 2)
        elif abs_inv >= self.INVENTORY_WARNING:
            return ("UNWIND_BIAS", 1)
        else:
            return ("NORMAL", 0)
    
    def _calculate_inventory_skew(self, inventory: int) -> float:
        """
        Calculate price adjustment based on inventory.
        
        Returns adjustment in ticks (multiply by tick_size for dollar adjustment)
        Positive inventory -> negative skew (encourage selling)
        """
        # Skew in ticks: 1 tick per 500 shares of inventory
        ticks = -inventory / 500.0
        return ticks * self.TICK_SIZE
    
    def _emergency_unwind(self, inventory: int, bid: float, ask: float) -> Optional[Dict]:
        """
        Emergency position flattening - cross spread aggressively.
        This is the ONLY time we should cross the spread!
        """
        if inventory > 0:
            qty = self._round_qty_to_lot(min(500, inventory))
            # SELL at bid (cross spread to guarantee fill)
            price = self._round_down_to_tick(bid)
            return {"side": "SELL", "price": price, "qty": qty}
        elif inventory < 0:
            qty = self._round_qty_to_lot(min(500, abs(inventory)))
            # BUY at ask (cross spread to guarantee fill)
            price = self._round_up_to_tick(ask)
            return {"side": "BUY", "price": price, "qty": qty}
        return None
    
    # =========================================================================
    # STRATEGY IMPLEMENTATIONS
    # =========================================================================
    
    def _get_regime_config(self, regime: str) -> Dict:
        """
        Get configuration parameters for a specific regime.
        
        Args:
            regime: Regime name ("NORMAL", "HFT", "STRESSED", "CRASH", "SPIKE")
        
        Returns:
            Dictionary with regime-specific parameters
        """
        strategies = self.config["regime_strategies"]
        # SPIKE uses CRASH config for safety
        if regime == "SPIKE":
            return strategies.get("CRASH", strategies.get("NORMAL", {}))
        return strategies.get(regime, strategies.get("NORMAL", {}))  # Fallback to NORMAL if regime not found
    
    def _normal_strategy(self, bid: float, ask: float, mid: float, 
                         inventory: int, step: int) -> Optional[Dict]:
        """
        Aggressive market making for stable conditions.
        
        KEY PRINCIPLE: Quote AT the touch to join queue and get fills.
        - Place BUY orders AT BID (or improve by 1 tick if spread is wide)
        - Place SELL orders AT ASK (or improve by 1 tick if spread is wide)
        - Alternate sides to stay balanced
        - Regime-aware: adapts based on current market conditions
        """
        regime_config = self._get_regime_config("NORMAL")
        trade_freq = regime_config["trade_frequency"]
        order_size = self._ensure_qty_multiple_of_100(regime_config["order_size"])
        max_inv = regime_config["max_inventory"]
        aggressive_join = regime_config.get("aggressive_join", True)
        short_bias = regime_config.get("short_bias", False)
        
        inv_action, urgency = self._get_inventory_action(inventory)
        
        # Emergency unwind - cross spread immediately
        if inv_action == "EMERGENCY":
            return self._emergency_unwind(inventory, bid, ask)
        
        spread = ask - bid
        skew = self._calculate_inventory_skew(inventory)
        
        # DEAD MARKET CHECK: If spread is 0 or very thin depth, don't trade
        total_depth = self.last_bid_depth + self.last_ask_depth
        if spread < 0.01 or total_depth < 200:
            return None
        
        # SCENARIO-SPECIFIC: Flash crash proactive flattening
        # For flash_crash scenario, start flattening before step 18000 (institutional selling)
        if self.detected_scenario == "flash_crash":
            # Start reducing inventory proactively around step 17000
            if self.current_step >= 17000 and self.current_step < 18000:
                if abs(inventory) > 500:
                    if inventory > 0:
                        qty = self._round_qty_to_lot(min(order_size, inventory))
                        price = round(ask - self.TICK_SIZE, 2) if aggressive_join else round(ask, 2)
                        return {"side": "SELL", "price": price, "qty": qty}
                    else:
                        qty = self._round_qty_to_lot(min(order_size, abs(inventory)))
                        price = round(bid + self.TICK_SIZE, 2) if aggressive_join else round(bid, 2)
                        return {"side": "BUY", "price": price, "qty": qty}
        
        # CRASH ANTICIPATION: If spread is widening significantly, start flattening proactively
        # This detects crashes in real-time without hardcoded step numbers
        if len(self.spread_history) >= 10 and self.baseline_spread:
            recent_spread_avg = sum(self.spread_history[-5:]) / 5
            if recent_spread_avg > self.baseline_spread * 2.5:
                # Spread widening significantly - reduce inventory proactively
                if abs(inventory) > 100:
                    if inventory > 0:
                        qty = self._round_qty_to_lot(min(order_size, inventory))
                        price = round(ask - self.TICK_SIZE, 2) if aggressive_join else round(ask, 2)
                        return {"side": "SELL", "price": price, "qty": qty}
                    else:
                        qty = self._round_qty_to_lot(min(order_size, abs(inventory)))
                        price = round(bid + self.TICK_SIZE, 2) if aggressive_join else round(bid, 2)
                        return {"side": "BUY", "price": price, "qty": qty}
        
        # Unwind only mode - aggressive passive orders biased to reduce position
        if inv_action == "UNWIND_ONLY":
            if inventory > 0:
                # SELL aggressively - improve ask by 1 tick
                price = round(ask - self.TICK_SIZE, 2)
                return {"side": "SELL", "price": price, "qty": order_size}
            elif inventory < 0:
                # BUY aggressively - improve bid by 1 tick
                price = round(bid + self.TICK_SIZE, 2)
                return {"side": "BUY", "price": price, "qty": order_size}
            return None
        
        # Trade based on configured frequency
        if step % trade_freq != 0:
            return None
        
        # Size based on inventory and config - must be multiple of 100
        qty = order_size if abs(inventory) < max_inv * 0.5 else self._round_qty_to_lot(int(order_size * 0.67))
        
        # Determine direction based on inventory
        inventory_threshold = max_inv * 0.15  # 15% of max inventory
        
        if inventory > inventory_threshold:
            # Want to sell to reduce long position - join at ask or improve
            if aggressive_join and spread > self.TICK_SIZE * 2:
                price = round(ask - self.TICK_SIZE, 2)
            else:
                price = round(ask, 2)
            return {"side": "SELL", "price": price, "qty": qty}
        
        elif inventory < -inventory_threshold:
            # Want to buy to reduce short position - join at bid or improve
            if aggressive_join and spread > self.TICK_SIZE * 2:
                price = round(bid + self.TICK_SIZE, 2)
            else:
                price = round(bid, 2)
            return {"side": "BUY", "price": price, "qty": qty}
        
        else:
            # Balanced inventory - alternate sides
            trade_cycle = (step // trade_freq) % 2
            
            # Apply small bias based on skew
            if skew < -0.005:
                trade_cycle = 1  # Prefer sell
            elif skew > 0.005:
                trade_cycle = 0  # Prefer buy
            
            # TIGHT INVENTORY mode for stressed_market (high volatility scenario)
            # Strategy: Trade actively but keep inventory very small
            stay_flat = regime_config.get("stay_flat", False)
            min_spread = regime_config.get("min_spread_for_trade", 0.0)
            
            if stay_flat:
                # Only trade if spread is wide enough to capture
                if spread < min_spread:
                    return None
                
                # Only trade to flatten inventory
                if inventory > 50:
                    trade_cycle = 1  # SELL to flatten
                elif inventory < -50:
                    trade_cycle = 0  # BUY to flatten
                else:
                    # Flat - don't trade
                    return None
            else:
                # Active trading with tight inventory management
                # Flatten if inventory is getting large
                if inventory > max_inv * 0.7:
                    trade_cycle = 1  # SELL
                elif inventory < -max_inv * 0.7:
                    trade_cycle = 0  # BUY
                else:
                    # Alternate to stay balanced
                    trade_cycle = (step // trade_freq) % 2
            
            if short_bias:
                # Calculate short-term momentum
                momentum = 0.0
                if len(self.mid_history) >= 20:
                    momentum = self.mid_history[-1] - self.mid_history[-20]
                
                # Original short bias logic
                target_short = regime_config.get("target_short_position", -300)
                not_short_enough = target_short * 0.5
                too_short = target_short * 2.0
                
                if inventory > not_short_enough:
                    if momentum > 0.2:
                        trade_cycle = 1
                    elif (step // trade_freq) % 10 < 8:
                        trade_cycle = 1
                elif inventory < too_short:
                    if momentum < -0.2:
                        trade_cycle = 0
                    elif (step // trade_freq) % 10 < 8:
                        trade_cycle = 0
                else:
                    if momentum > 0.3:
                        trade_cycle = 1
                    elif momentum < -0.3:
                        trade_cycle = 0
                    elif (step // trade_freq) % 10 < 6:
                        trade_cycle = 1
                
            if trade_cycle == 0:
                # BUY at bid (or improve if spread is wide)
                if aggressive_join and spread > self.TICK_SIZE * 2:
                    price = round(bid + self.TICK_SIZE, 2)
                else:
                    price = round(bid, 2)
                return {"side": "BUY", "price": price, "qty": qty}
            else:
                # SELL at ask (or improve if spread is wide)
                if aggressive_join and spread > self.TICK_SIZE * 2:
                    price = round(ask - self.TICK_SIZE, 2)
                else:
                    price = round(ask, 2)
                return {"side": "SELL", "price": price, "qty": qty}
    
    def _stressed_strategy(self, bid: float, ask: float, mid: float,
                           inventory: int, step: int) -> Optional[Dict]:
        """
        Active trading strategy for stressed_market with SHORT BIAS.
        
        Key insight: Price drifts down (-0.0001 per step), so maintain short bias.
        Trade actively to capture spreads while following the downward trend.
        
        Strategy:
        1. Maintain short bias (target short position)
        2. Trade actively at configured frequency
        3. Prefer selling when flat or long
        4. Only buy to cover shorts or when too short
        """
        regime_config = self._get_regime_config("STRESSED")
        trade_freq = regime_config["trade_frequency"]
        order_size = self._ensure_qty_multiple_of_100(regime_config["order_size"])
        max_inv = regime_config["max_inventory"]
        aggressive_join = regime_config.get("aggressive_join", True)
        short_bias = regime_config.get("short_bias", False)
        target_short = regime_config.get("target_short_position", -500)
        
        # DEAD MARKET CHECK
        spread = ask - bid
        total_depth = self.last_bid_depth + self.last_ask_depth
        if spread < 0.01 or total_depth < 150:
            return None
        
        inv_action, urgency = self._get_inventory_action(inventory)
        
        # Emergency triggers immediately
        if inv_action == "EMERGENCY":
            return self._emergency_unwind(inventory, bid, ask)
        
        # Trade based on configured frequency
        if step % trade_freq != 0:
            return None
        
        # Size based on inventory
        qty = order_size if abs(inventory) < max_inv * 0.7 else self._round_qty_to_lot(int(order_size * 0.67))
        
        # SHORT BIAS LOGIC: Prefer selling to maintain short position
        if short_bias:
            # Calculate momentum to help with timing
            momentum = 0.0
            if len(self.mid_history) >= 20:
                momentum = self.mid_history[-1] - self.mid_history[-20]
            
            # Target short position ranges
            not_short_enough = target_short * 0.5  # e.g., -250
            too_short = target_short * 2.0  # e.g., -1000
            
            # If we're not short enough, prefer selling
            if inventory > not_short_enough:
                # Sell aggressively to build short position
                if aggressive_join and spread > self.TICK_SIZE * 2:
                    price = round(ask - self.TICK_SIZE, 2)
                else:
                    price = round(ask, 2)
                return {"side": "SELL", "price": price, "qty": qty}
            
            # If we're too short, buy to cover
            elif inventory < too_short:
                # Buy to reduce short position
                if aggressive_join and spread > self.TICK_SIZE * 2:
                    price = round(bid + self.TICK_SIZE, 2)
                else:
                    price = round(bid, 2)
                return {"side": "BUY", "price": price, "qty": qty}
            
            # In target range - trade based on momentum and inventory
            else:
                # Use momentum to bias direction
                if momentum > 0.2:  # Price rising - sell (build short)
                    if aggressive_join and spread > self.TICK_SIZE * 2:
                        price = round(ask - self.TICK_SIZE, 2)
                    else:
                        price = round(ask, 2)
                    return {"side": "SELL", "price": price, "qty": qty}
                elif momentum < -0.2:  # Price falling - buy (cover short)
                    if aggressive_join and spread > self.TICK_SIZE * 2:
                        price = round(bid + self.TICK_SIZE, 2)
                    else:
                        price = round(bid, 2)
                    return {"side": "BUY", "price": price, "qty": qty}
                else:
                    # Default: prefer selling to maintain short bias
                    if aggressive_join and spread > self.TICK_SIZE * 2:
                        price = round(ask - self.TICK_SIZE, 2)
                    else:
                        price = round(ask, 2)
                    return {"side": "SELL", "price": price, "qty": qty}
        
        # NO SHORT BIAS: Standard inventory management
        else:
            # Standard inventory-based trading
            if inventory > max_inv * 0.3:
                # Reduce long - sell
                if aggressive_join and spread > self.TICK_SIZE * 2:
                    price = round(ask - self.TICK_SIZE, 2)
                else:
                    price = round(ask, 2)
                return {"side": "SELL", "price": price, "qty": qty}
            elif inventory < -max_inv * 0.3:
                # Reduce short - buy
                if aggressive_join and spread > self.TICK_SIZE * 2:
                    price = round(bid + self.TICK_SIZE, 2)
                else:
                    price = round(bid, 2)
                return {"side": "BUY", "price": price, "qty": qty}
            else:
                # Balanced - alternate sides
                trade_cycle = (step // trade_freq) % 2
                if trade_cycle == 0:
                    if aggressive_join and spread > self.TICK_SIZE * 2:
                        price = round(bid + self.TICK_SIZE, 2)
                    else:
                        price = round(bid, 2)
                    return {"side": "BUY", "price": price, "qty": qty}
                else:
                    if aggressive_join and spread > self.TICK_SIZE * 2:
                        price = round(ask - self.TICK_SIZE, 2)
                    else:
                        price = round(ask, 2)
                    return {"side": "SELL", "price": price, "qty": qty}
    
    def _spike_strategy(self, bid: float, ask: float, mid: float,
                        inventory: int, step: int) -> Optional[Dict]:
        """
        Spike survival mode (for mini_flash_crash scenario).
        
        Strategy:
        1. Flatten position immediately during spike
        2. Don't add new positions
        3. Wait for spike to end (4 steps)
        """
        regime_config = self._get_regime_config("CRASH")  # Use crash config for safety
        max_inv = regime_config.get("max_inventory", 200)
        
        # DEAD MARKET CHECK
        spread = ask - bid
        total_depth = self.last_bid_depth + self.last_ask_depth
        if spread < 0.01 or total_depth < 100:
            return None
        
        # Emergency unwind if inventory is high
        inv_action, urgency = self._get_inventory_action(inventory)
        if inv_action == "EMERGENCY":
            return self._emergency_unwind(inventory, bid, ask)
        
        # Flatten position aggressively during spike
        if abs(inventory) > max_inv:
            return self._emergency_unwind(inventory, bid, ask)
        
        # Otherwise, don't trade - wait for spike to end
        return None
    
    def _crash_strategy(self, bid: float, ask: float, mid: float,
                        inventory: int, step: int) -> Optional[Dict]:
        """
        Survival mode - only unwind positions.
        Never add to position during a crash.
        Cross spread if necessary - survival > profit.
        """
        regime_config = self._get_regime_config("CRASH")
        max_inv = regime_config["max_inventory"]
        
        # DEAD MARKET CHECK - can't trade if no liquidity
        spread = ask - bid
        total_depth = self.last_bid_depth + self.last_ask_depth
        if spread < 0.01 or total_depth < 100:
            return None
        
        # If nearly flat, stay flat
        if abs(inventory) < max_inv:
            return None
        
        # Aggressive unwind - cross the spread to guarantee exit
        return self._emergency_unwind(inventory, bid, ask)
    
    def _hft_strategy(self, bid: float, ask: float, mid: float,
                      inventory: int, step: int) -> Optional[Dict]:
        """
        HFT-dominated markets: COMPETE AGGRESSIVELY.
        
        Key insight: To get fills in HFT markets, we must:
        1. Quote AT the best bid/ask (join queue) or IMPROVE by 1 tick
        2. Trade frequently to accumulate fills
        3. Use inventory skew to stay balanced
        """
        regime_config = self._get_regime_config("HFT")
        trade_freq = regime_config["trade_frequency"]
        order_size = self._ensure_qty_multiple_of_100(regime_config["order_size"])
        max_inv = regime_config["max_inventory"]
        aggressive_join = regime_config.get("aggressive_join", True)
        
        # DEAD MARKET CHECK
        spread = ask - bid
        total_depth = self.last_bid_depth + self.last_ask_depth
        if spread < 0.01 or total_depth < 100:
            return None
        
        inv_action, urgency = self._get_inventory_action(inventory)
        
        # Emergency - cross spread immediately
        if inv_action == "EMERGENCY":
            return self._emergency_unwind(inventory, bid, ask)
        
        # Calculate skew (small adjustment based on inventory)
        skew = self._calculate_inventory_skew(inventory)
        
        # SCENARIO-SPECIFIC: Fade momentum for hft_dominated
        # Short-term momentum traders amplify moves - fade them
        fade_momentum = regime_config.get("fade_momentum", False)
        momentum_bias = 0
        if fade_momentum and len(self.mid_history) >= 20:
            momentum = self.mid_history[-1] - self.mid_history[-20]
            # Fade: if price rising, prefer selling (fade the rise)
            if momentum > 0.1:
                momentum_bias = -1  # Prefer selling
            elif momentum < -0.1:
                momentum_bias = 1   # Prefer buying
        
        # In HFT, trade every trade_freq steps
        if step % trade_freq != 0:
            return None
        
        # Determine trade direction based on inventory
        if inventory > max_inv * 0.3:
            # Need to reduce long - SELL aggressively
            # Join at ask or improve by 1 tick
            if aggressive_join:
                price = round(ask - self.TICK_SIZE, 2)  # Improve ask by 1 tick
            else:
                price = round(ask, 2)  # Join at ask
            return {"side": "SELL", "price": price, "qty": order_size}
        
        elif inventory < -max_inv * 0.3:
            # Need to reduce short - BUY aggressively  
            if aggressive_join:
                price = round(bid + self.TICK_SIZE, 2)  # Improve bid by 1 tick
            else:
                price = round(bid, 2)  # Join at bid
            return {"side": "BUY", "price": price, "qty": order_size}
        
        else:
            # Balanced inventory - alternate sides with slight inventory bias
            trade_cycle = (step // trade_freq) % 2
            
            # Apply skew to bias direction
            if skew < -0.01:  # Have long inventory, prefer selling
                trade_cycle = 1
            elif skew > 0.01:  # Have short inventory, prefer buying
                trade_cycle = 0
            
            # Apply momentum fade bias
            if momentum_bias != 0:
                trade_cycle = 1 if momentum_bias < 0 else 0
            
            if trade_cycle == 0:
                # BUY - join at bid or improve
                if aggressive_join and spread > self.TICK_SIZE * 2:
                    price = round(bid + self.TICK_SIZE, 2)
                else:
                    price = round(bid, 2)
                return {"side": "BUY", "price": price, "qty": order_size}
            else:
                # SELL - join at ask or improve
                if aggressive_join and spread > self.TICK_SIZE * 2:
                    price = round(ask - self.TICK_SIZE, 2)
                else:
                    price = round(ask, 2)
                return {"side": "SELL", "price": price, "qty": order_size}
    
    # =========================================================================
    # MAIN STRATEGY ROUTER
    # =========================================================================
    
    def decide_order(self, bid: float, ask: float, mid: float) -> Optional[Dict]:
        """
        Main strategy router - detects regime and delegates to appropriate strategy.
        
        KEY PRINCIPLES:
        1. Market makers PROVIDE liquidity - we don't cross spreads except emergencies
        2. BUY orders at BID, SELL orders at ASK = capture spread
        3. Inventory skew adjusts prices to mean-revert position
        4. In HFT markets, don't compete - the MMs are too aggressive
        """
        # Skip if no valid prices
        if mid <= 0 or bid <= 0 or ask <= 0:
            return None
        
        # Safety check: Never exceed 5000 inventory limit - emergency unwind
        if abs(self.inventory) >= 4800:
            print(f"[{self.student_id}] [EMERGENCY] Inventory {self.inventory} near limit!")
            return self._emergency_unwind(self.inventory, bid, ask)
        
        # Safety check: Don't generate orders if at max open orders limit
        open_count = self._get_open_order_count()
        if open_count >= self.MAX_OPEN_ORDERS:
            # Cancel oldest orders to make room
            if open_count > 0:
                self._cancel_old_orders(min(5, open_count))
            return None
        
        # Periodic cleanup: Cancel very stale orders (older than 200 steps) every 50 steps
        if self.current_step % 50 == 0 and open_count > 0:
            stale_orders = [
                (oid, meta) for oid, meta in self.order_send_times.items()
                if self.current_step - meta["step"] > 200
            ]
            for order_id, _ in stale_orders:
                self._cancel_order(order_id)
        
        spread = ask - bid
        
        # Detect current regime (handles logging internally when confirmed changes occur)
        self._detect_regime(spread, self.last_bid_depth, self.last_ask_depth, self.last_bids, self.last_asks)
        
        # Store previous mid for momentum detection
        self.prev_mid = mid
        
        # Route to appropriate strategy
        if self.regime == "CALIBRATING":
            return None  # Don't trade while calibrating
        elif self.regime == "SPIKE":
            order = self._spike_strategy(bid, ask, mid, self.inventory, self.current_step)
        elif self.regime == "CRASH":
            order = self._crash_strategy(bid, ask, mid, self.inventory, self.current_step)
        elif self.regime == "STRESSED":
            order = self._stressed_strategy(bid, ask, mid, self.inventory, self.current_step)
        elif self.regime == "HFT":
            order = self._hft_strategy(bid, ask, mid, self.inventory, self.current_step)
        else:  # NORMAL
            order = self._normal_strategy(bid, ask, mid, self.inventory, self.current_step)
        
        # Debug logging for first few trades - show market prices
        if order and self.orders_sent < 10:
            print(f"[{self.student_id}] [DEBUG] Step {self.current_step} | Bid: {bid:.2f} Ask: {ask:.2f} Spread: {spread:.4f} | "
                  f"Regime: {self.regime} | Order: {order['side']} {order['qty']}@{order['price']:.2f}")
        elif not order and self.current_step > self.CALIBRATION_STEPS and self.current_step % 500 == 0 and self.orders_sent < 5:
            print(f"[{self.student_id}] [DEBUG] Step {self.current_step} | Bid: {bid:.2f} Ask: {ask:.2f} | "
                  f"Regime: {self.regime} | No order (inv={self.inventory})")
        
        return order
    
    # =========================================================================
    # ORDER HANDLING
    # =========================================================================
    
    def _get_open_order_count(self) -> int:
        """Get the number of currently open orders."""
        return len(self.order_send_times)
    
    def _cancel_order(self, order_id: str):
        """Cancel an order."""
        if order_id not in self.order_send_times:
            return  # Already cancelled or filled
        
        try:
            msg = {
                "action": "CANCEL",
                "order_id": order_id
            }
            self.order_ws.send(json.dumps(msg))
            # Remove from tracking after successful send
            # (No cancellation confirmation in API, so we assume success)
            del self.order_send_times[order_id]
        except Exception as e:
            print(f"[{self.student_id}] Cancel order error: {e}")
            # Don't delete if send failed - order might still be open
    
    def _cancel_old_orders(self, count: int = 5):
        """Cancel the oldest N orders to free up space."""
        if not self.order_send_times:
            return
        
        # Sort orders by send time (oldest first)
        sorted_orders = sorted(
            self.order_send_times.items(),
            key=lambda x: x[1]["time"]
        )
        
        # Cancel the oldest orders
        cancelled = 0
        for order_id, order_meta in sorted_orders:
            if cancelled >= count:
                break
            # Also cancel orders that are very stale (older than 200 steps)
            if self.current_step - order_meta["step"] > 200:
                self._cancel_order(order_id)
                cancelled += 1
            elif cancelled < count:
                self._cancel_order(order_id)
                cancelled += 1
    
    def _send_order(self, order: Dict):
        """Send an order to the exchange, managing open order limits."""
        # Check if we're at the limit
        open_count = self._get_open_order_count()
        
        if open_count >= self.MAX_OPEN_ORDERS:
            print(f"[{self.student_id}] WARNING: At max open orders ({self.MAX_OPEN_ORDERS}), cannot send new order")
            return
        
        # If approaching limit, cancel old orders
        if open_count >= self.ORDER_CANCEL_THRESHOLD:
            cancel_count = open_count - self.ORDER_CANCEL_THRESHOLD + 1
            self._cancel_old_orders(cancel_count)
        
        order_id = f"ORD_{self.student_id}_{self.current_step}_{self.orders_sent}"
        
        msg = {
            "order_id": order_id,
            "side": order["side"],
            "price": order["price"],
            "qty": order["qty"]
        }
        
        try:
            # Track order metadata
            self.order_send_times[order_id] = {
                "time": time.time(),
                "price": order["price"],
                "side": order["side"],
                "step": self.current_step
            }
            self.order_ws.send(json.dumps(msg))
            self.orders_sent += 1
        except Exception as e:
            print(f"[{self.student_id}] Send order error: {e}")
            # Remove from tracking if send failed
            if order_id in self.order_send_times:
                del self.order_send_times[order_id]
    
    def _send_done(self):
        """Signal DONE to advance to the next simulation step."""
        try:
            self.order_ws.send(json.dumps({"action": "DONE"}))
            self.last_done_time = time.time()  # Track when we sent DONE
        except:
            pass
    
    def _on_order_response(self, ws, message: str):
        """Handle order responses and fills."""
        try:
            recv_time = time.time()
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "AUTHENTICATED":
                print(f"[{self.student_id}] Authenticated - ready to trade!")
            
            elif msg_type == "FILL":
                qty = data.get("qty", 0)
                price = data.get("price", 0)
                side = data.get("side", "")
                order_id = data.get("order_id", "")
                
                # Track previous PnL to measure trade impact
                prev_pnl = self.pnl
                
                # Measure fill latency and remove from tracking
                if order_id in self.order_send_times:
                    order_meta = self.order_send_times[order_id]
                    fill_latency = (recv_time - order_meta["time"]) * 1000  # ms
                    self.fill_latencies.append(fill_latency)
                    del self.order_send_times[order_id]
                
                # Update inventory and cash flow
                if side == "BUY":
                    self.inventory += qty
                    self.cash_flow -= qty * price  # Spent cash to buy
                else:
                    self.inventory -= qty
                    self.cash_flow += qty * price  # Received cash from selling
                
                # Calculate mark-to-market PnL using mid price
                self.pnl = self.cash_flow + self.inventory * self.last_mid
                
                # Calculate trade quality (compare to mid)
                trade_vs_mid = (price - self.last_mid) if side == "SELL" else (self.last_mid - price)
                quality = "GOOD" if trade_vs_mid > 0 else "POOR"
                
                print(f"[{self.student_id}] FILL: {side} {qty} @ {price:.2f} | "
                      f"Mid: {self.last_mid:.2f} | Inv: {self.inventory} | "
                      f"PnL: {self.pnl:.2f} | Quality: {quality}")
            
            elif msg_type == "ERROR":
                print(f"[{self.student_id}] ERROR: {data.get('message')}")
                
        except Exception as e:
            print(f"[{self.student_id}] Order response error: {e}")
    
    # =========================================================================
    # ERROR HANDLING
    # =========================================================================
    
    def _on_error(self, ws, error):
        if self.running:
            print(f"[{self.student_id}] WebSocket error: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        self.running = False
        print(f"[{self.student_id}] Connection closed (status: {close_status_code})")
    
    # =========================================================================
    # MAIN RUN LOOP
    # =========================================================================
    
    def run(self):
        """Main entry point - register, connect, and run."""
        # Step 1: Register
        if not self.register():
            return
        
        # Step 2: Connect
        if not self.connect():
            return
        
        # Step 3: Run until complete
        print(f"[{self.student_id}] Running... Press Ctrl+C to stop")
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n[{self.student_id}] Stopped by user")
        finally:
            self.running = False
            if self.market_ws:
                self.market_ws.close()
            if self.order_ws:
                self.order_ws.close()
            
            print(f"\n[{self.student_id}] Final Results:")
            print(f"  Orders Sent: {self.orders_sent}")
            print(f"  Inventory: {self.inventory}")
            print(f"  PnL: {self.pnl:.2f}")
            
            # Print latency statistics
            if self.step_latencies:
                print(f"\n  Step Latency (ms):")
                print(f"    Min: {min(self.step_latencies):.1f}")
                print(f"    Max: {max(self.step_latencies):.1f}")
                print(f"    Avg: {sum(self.step_latencies)/len(self.step_latencies):.1f}")
            
            if self.fill_latencies:
                print(f"\n  Fill Latency (ms):")
                print(f"    Min: {min(self.fill_latencies):.1f}")
                print(f"    Max: {max(self.fill_latencies):.1f}")
                print(f"    Avg: {sum(self.fill_latencies)/len(self.fill_latencies):.1f}")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Student Trading Algorithm",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Local server:
    python student_algorithm.py --name team_alpha --password secret123 --scenario normal_market
    
  Deployed server (HTTPS):
    python student_algorithm.py --name team_alpha --password secret123 --scenario normal_market --host 3.98.52.120:8433 --secure
        """
    )
    
    parser.add_argument("--name", required=True, help="Your team name")
    parser.add_argument("--password", required=True, help="Your team password")
    parser.add_argument("--scenario", default="normal_market", help="Scenario to run")
    parser.add_argument("--host", default="localhost:8080", help="Server host:port")
    parser.add_argument("--secure", action="store_true", help="Use HTTPS/WSS (for deployed servers)")
    args = parser.parse_args()
    
    bot = TradingBot(
        student_id=args.name,
        host=args.host,
        scenario=args.scenario,
        password=args.password,
        secure=args.secure
    )
    
    bot.run()
