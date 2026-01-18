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
from typing import Dict, Optional
import statistics

# Config system
from configs import load_config, get_default_config, match_scenario_signature, load_all_configs

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
        
        # Regime state
        self.regime = "CALIBRATING"
        self.steps_in_regime = 0
        
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
        
        # Pending orders tracking
        self.pending_buy_price = None
        self.pending_sell_price = None
        
        # Configuration system
        self.detected_scenario = None  # Will be set during calibration
        self.config = None  # Will be loaded after scenario detection
        self.all_configs = load_all_configs()  # Pre-load all configs for matching
        
        # Try to load config based on CLI scenario argument (may be overridden by auto-detection)
        try:
            self.config = load_config(scenario)
            print(f"[{self.student_id}] Loaded config for scenario: {scenario}")
        except Exception as e:
            print(f"[{self.student_id}] Warning: Could not load config for '{scenario}', using default: {e}")
            self.config = get_default_config()
        
        # Apply base params from config
        base_params = self.config["base_params"]
        self.TICK_SIZE = base_params["tick_size"]
        self.CALIBRATION_STEPS = base_params["calibration_steps"]
        self.INVENTORY_WARNING = base_params["inventory_warning"]
        self.INVENTORY_DANGER = base_params["inventory_danger"]
        self.INVENTORY_CRITICAL = base_params["inventory_critical"]
        
        # Calibration data for scenario detection
        self.calibration_spreads = []
        self.calibration_depths = []
        self.calibration_mids = []
    
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
            
            # Extract order book depth
            # API provides bid_size/ask_size at top level, or calculate from bids/asks arrays
            self.last_bid_depth = data.get("bid_size", 0)
            self.last_ask_depth = data.get("ask_size", 0)
            
            # Fallback: calculate from bids/asks arrays if sizes not provided
            if self.last_bid_depth == 0 or self.last_ask_depth == 0:
                bids = data.get("bids", [])
                asks = data.get("asks", [])
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
            if self.current_step < self.CALIBRATION_STEPS:
                spread = self.last_ask - self.last_bid if self.last_ask > 0 and self.last_bid > 0 else 0
                total_depth = self.last_bid_depth + self.last_ask_depth
                if spread > 0:
                    self.calibration_spreads.append(spread)
                if total_depth > 0:
                    self.calibration_depths.append(total_depth)
                if self.last_mid > 0:
                    self.calibration_mids.append(self.last_mid)
            
            # Auto-detect scenario at end of calibration
            if self.current_step == self.CALIBRATION_STEPS:
                try:
                    if len(self.calibration_spreads) > 50:
                        self._detect_and_load_scenario()
                    else:
                        print(f"[{self.student_id}] [WARNING] Insufficient calibration data ({len(self.calibration_spreads)} spreads), skipping auto-detection")
                except Exception as e:
                    print(f"[{self.student_id}] [ERROR] Scenario detection failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Log progress every 500 steps with latency stats
            if self.current_step % 500 == 0:
                avg_lat = sum(self.step_latencies[-100:]) / min(len(self.step_latencies), 100) if self.step_latencies else 0.0
                scenario_info = f"Scenario: {self.detected_scenario}" if self.detected_scenario else f"CLI: {self.scenario}"
                spread = self.last_ask - self.last_bid if self.last_ask > 0 and self.last_bid > 0 else 0
                open_count = self._get_open_order_count()
                print(f"[{self.student_id}] Step {self.current_step} | Orders: {self.orders_sent} | Open: {open_count}/{self.MAX_OPEN_ORDERS} | Inv: {self.inventory} | Regime: {self.regime} | {scenario_info} | Spread: {spread:.4f} | Depth: {self.last_bid_depth + self.last_ask_depth} | Avg Latency: {avg_lat:.1f}ms")
            
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
    
    def _get_opposite_order(self, order: Dict, bid: float, ask: float, regime_config: Dict) -> Optional[Dict]:
        """
        Generate an opposite-side order for two-sided quoting.
        If the primary order is BUY, generate a SELL; if SELL, generate a BUY.
        """
        order_size = regime_config.get("order_size", 100)
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
    
    def _detect_and_load_scenario(self):
        """
        Auto-detect scenario from calibration data and reload appropriate config.
        """
        if len(self.calibration_spreads) < 50:
            print(f"[{self.student_id}] Warning: Insufficient calibration data for scenario detection")
            return
        
        # Calculate calibration statistics - check for empty lists first
        if not self.calibration_spreads:
            print(f"[{self.student_id}] Warning: No spread data collected")
            return
        
        avg_spread = statistics.mean(self.calibration_spreads)
        spread_std = statistics.stdev(self.calibration_spreads) if len(self.calibration_spreads) > 1 else 0
        
        # Depth might be empty if book data wasn't available
        if self.calibration_depths:
            avg_depth = statistics.mean(self.calibration_depths)
        else:
            avg_depth = 10000  # Default fallback
            print(f"[{self.student_id}] Warning: No depth data collected, using default")
        
        # Calculate price volatility from mid prices
        volatility = 0.0
        if len(self.calibration_mids) > 10:
            mid_changes = [abs(self.calibration_mids[i] - self.calibration_mids[i-1]) 
                          for i in range(1, len(self.calibration_mids))]
            if mid_changes:
                volatility = statistics.mean(mid_changes)
        
        # Prepare calibration data for matching
        calibration_data = {
            "avg_spread": avg_spread,
            "avg_depth": avg_depth,
            "spread_std": spread_std,
            "volatility": volatility,
            "depth_available": len(self.calibration_depths) > 0
        }
        
        # Match to scenario
        detected_scenario = match_scenario_signature(calibration_data, self.all_configs)
        
        print(f"[{self.student_id}] [CALIBRATION] Avg Spread: {avg_spread:.4f}, Avg Depth: {avg_depth:.0f}, "
              f"Spread Std: {spread_std:.4f}, Volatility: {volatility:.6f}")
        print(f"[{self.student_id}] [SCENARIO DETECTION] CLI scenario: {self.scenario}, "
              f"Detected: {detected_scenario}")
        
        # If detected scenario differs from CLI, reload config
        if detected_scenario != self.scenario:
            try:
                self.config = load_config(detected_scenario)
                self.detected_scenario = detected_scenario
                
                # Update base params from new config
                base_params = self.config["base_params"]
                self.INVENTORY_WARNING = base_params["inventory_warning"]
                self.INVENTORY_DANGER = base_params["inventory_danger"]
                self.INVENTORY_CRITICAL = base_params["inventory_critical"]
                
                print(f"[{self.student_id}] [CONFIG RELOADED] Using config for detected scenario: {detected_scenario}")
            except Exception as e:
                print(f"[{self.student_id}] [WARNING] Failed to load config for {detected_scenario}: {e}")
                print(f"[{self.student_id}] [FALLBACK] Continuing with original config for {self.scenario}")
        else:
            self.detected_scenario = self.scenario
            print(f"[{self.student_id}] [SCENARIO CONFIRMED] Using config for {self.scenario}")
    
    # =========================================================================
    # REGIME DETECTION
    # =========================================================================
    
    def _detect_regime(self, spread: float, bid_depth: int, ask_depth: int) -> str:
        """
        Classify current market regime based on spread and depth.
        
        Returns: "CALIBRATING", "NORMAL", "STRESSED", "CRASH", or "HFT"
        """
        total_depth = bid_depth + ask_depth
        
        # Update rolling histories
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
        
        # Establish baseline on first exit from calibration
        if self.baseline_spread is None:
            if len(self.spread_history) == 0:
                print(f"[{self.student_id}] [WARNING] No spread history available, using defaults")
                self.baseline_spread = 0.5  # Default fallback
                self.baseline_depth = 10000  # Default fallback
            else:
                self.baseline_spread = sum(self.spread_history) / len(self.spread_history)
                self.baseline_depth = sum(self.depth_history) / len(self.depth_history) if len(self.depth_history) > 0 else 10000
            print(f"[{self.student_id}] [CALIBRATED] Baseline spread: {self.baseline_spread:.4f}, depth: {self.baseline_depth:.0f}")
        
        # Calculate recent metrics
        recent_spread = sum(self.spread_history[-10:]) / min(10, len(self.spread_history))
        recent_depth = sum(self.depth_history[-10:]) / min(10, len(self.depth_history))
        
        # Get thresholds from config
        thresholds = self.config["regime_thresholds"]
        crash_spread_mult = thresholds["crash_spread_multiplier"]
        stressed_spread_mult = thresholds["stressed_spread_multiplier"]
        hft_depth_ratio = thresholds["hft_depth_ratio"]
        crash_price_velocity = thresholds["crash_price_velocity"]
        
        # Calculate price velocity for crash detection
        price_velocity = 0.0
        if len(self.mid_history) >= 10:
            price_velocity = abs(self.mid_history[-1] - self.mid_history[-10])
        
        # CRASH detection - most urgent (spread explodes OR rapid price move)
        if recent_spread > self.baseline_spread * crash_spread_mult:
            return "CRASH"
        if price_velocity > crash_price_velocity:
            return "CRASH"
        
        # Check for rapid spread acceleration (crash incoming)
        if len(self.spread_history) >= 20:
            old_spread = sum(self.spread_history[-20:-10]) / 10
            if recent_spread > old_spread * 2.0 and recent_spread > self.baseline_spread * (crash_spread_mult * 0.5):
                return "CRASH"
        
        # HFT detection - very thin liquidity compared to baseline
        # Only detect HFT if baseline is established and depth is significantly lower
        if self.baseline_depth > 0 and recent_depth < self.baseline_depth * hft_depth_ratio:
            # Additional check: spread should also be tight (HFT markets have tight spreads)
            if recent_spread < self.baseline_spread * 1.2:
                return "HFT"
        # Also detect by absolute thin depth, but only if spread is also tight
        min_depth_threshold = 1000
        if recent_depth < min_depth_threshold and recent_spread < 0.15:
            return "HFT"
        
        # Stressed market - elevated spread
        if recent_spread > self.baseline_spread * stressed_spread_mult:
            return "STRESSED"
        
        # Default to normal
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
            qty = min(500, inventory)
            # SELL at bid (cross spread to guarantee fill)
            price = self._round_down_to_tick(bid)
            return {"side": "SELL", "price": price, "qty": qty}
        elif inventory < 0:
            qty = min(500, abs(inventory))
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
            regime: Regime name ("NORMAL", "HFT", "STRESSED", "CRASH")
        
        Returns:
            Dictionary with regime-specific parameters
        """
        strategies = self.config["regime_strategies"]
        return strategies.get(regime, strategies["NORMAL"])  # Fallback to NORMAL if regime not found
    
    def _normal_strategy(self, bid: float, ask: float, mid: float, 
                         inventory: int, step: int) -> Optional[Dict]:
        """
        Aggressive market making for stable conditions.
        
        KEY PRINCIPLE: Quote AT the touch to join queue and get fills.
        - Place BUY orders AT BID (or improve by 1 tick if spread is wide)
        - Place SELL orders AT ASK (or improve by 1 tick if spread is wide)
        - Alternate sides to stay balanced
        """
        regime_config = self._get_regime_config("NORMAL")
        trade_freq = regime_config["trade_frequency"]
        order_size = regime_config["order_size"]
        max_inv = regime_config["max_inventory"]
        aggressive_join = regime_config.get("aggressive_join", True)
        
        inv_action, urgency = self._get_inventory_action(inventory)
        
        # Emergency unwind - cross spread immediately
        if inv_action == "EMERGENCY":
            return self._emergency_unwind(inventory, bid, ask)
        
        spread = ask - bid
        skew = self._calculate_inventory_skew(inventory)
        
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
        Conservative approach for elevated volatility.
        - Trade much less frequently
        - Smaller size
        - Passive orders only, wider from mid
        """
        regime_config = self._get_regime_config("STRESSED")
        trade_freq = regime_config["trade_frequency"]
        order_size = regime_config["order_size"]
        max_inv = regime_config["max_inventory"]
        short_bias = regime_config.get("short_bias", False)
        
        inv_action, urgency = self._get_inventory_action(inventory)
        
        # Emergency triggers immediately
        if inv_action == "EMERGENCY":
            return self._emergency_unwind(inventory, bid, ask)
        
        # In stressed markets with high inventory, unwind passively but more frequently
        if inv_action == "UNWIND_ONLY" and step % (trade_freq // 3) == 0:
            skew = self._calculate_inventory_skew(inventory)
            if inventory > 0:
                price = self._round_to_tick(ask + skew)
                return {"side": "SELL", "price": price, "qty": order_size}
            elif inventory < 0:
                price = self._round_to_tick(bid + skew)
                return {"side": "BUY", "price": price, "qty": order_size}
        
        # Very infrequent trading otherwise
        if step % trade_freq != 0:
            return None
        
        # Only trade if inventory is building up significantly
        threshold = max_inv * 0.5
        if abs(inventory) > threshold:
            skew = self._calculate_inventory_skew(inventory)
            if inventory > 0:
                # Passive SELL at ask
                price = self._round_to_tick(ask + skew)
                return {"side": "SELL", "price": price, "qty": order_size}
            else:
                # Passive BUY at bid
                price = self._round_to_tick(bid + skew)
                return {"side": "BUY", "price": price, "qty": order_size}
        
        # Short bias: prefer selling in stressed markets
        if short_bias and abs(inventory) < threshold and step % (trade_freq * 2) == 0:
            skew = self._calculate_inventory_skew(inventory)
            price = self._round_to_tick(ask + skew)
            return {"side": "SELL", "price": price, "qty": order_size}
        
        return None  # Stay flat in stressed conditions if inventory is manageable
    
    def _crash_strategy(self, bid: float, ask: float, mid: float,
                        inventory: int, step: int) -> Optional[Dict]:
        """
        Survival mode - only unwind positions.
        Never add to position during a crash.
        Cross spread if necessary - survival > profit.
        """
        regime_config = self._get_regime_config("CRASH")
        max_inv = regime_config["max_inventory"]
        
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
        order_size = regime_config["order_size"]
        max_inv = regime_config["max_inventory"]
        aggressive_join = regime_config.get("aggressive_join", True)
        
        inv_action, urgency = self._get_inventory_action(inventory)
        
        # Emergency - cross spread immediately
        if inv_action == "EMERGENCY":
            return self._emergency_unwind(inventory, bid, ask)
        
        # Calculate skew (small adjustment based on inventory)
        skew = self._calculate_inventory_skew(inventory)
        
        # In HFT, trade every trade_freq steps
        if step % trade_freq != 0:
            return None
        
        spread = ask - bid
        
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
        
        # Detect current regime
        new_regime = self._detect_regime(spread, self.last_bid_depth, self.last_ask_depth)
        
        # Log regime changes with context
        if new_regime != self.regime:
            print(f"[{self.student_id}] [REGIME] {self.regime} -> {new_regime} | "
                  f"Step: {self.current_step} | Spread: {spread:.4f} | "
                  f"Depth: {self.last_bid_depth + self.last_ask_depth} | Inv: {self.inventory}")
            self.regime = new_regime
            self.steps_in_regime = 0
        else:
            self.steps_in_regime += 1
        
        # Store previous mid for momentum detection
        self.prev_mid = mid
        
        # Route to appropriate strategy
        if self.regime == "CALIBRATING":
            return None  # Don't trade while calibrating
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
