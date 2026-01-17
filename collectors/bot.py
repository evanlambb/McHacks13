"""
Data Collector Bot
==================
Extended TradingBot with data logging and pluggable experiment strategies.
"""

import json
import time
from typing import Dict, Optional
from student_algorithm import TradingBot
from collectors.logger import DataLogger
from collectors.strategies import ExperimentStrategy


class DataCollectorBot(TradingBot):
    """
    TradingBot extended with data logging and experiment strategy support.
    """
    
    def __init__(self, student_id: str, host: str, scenario: str, password: str = None, 
                 secure: bool = False, strategy: Optional[ExperimentStrategy] = None):
        """
        Initialize the data collector bot.
        
        Args:
            student_id: Team name
            host: Server host:port
            scenario: Scenario name
            password: Team password
            secure: Use HTTPS/WSS
            strategy: Experiment strategy to use (None = passive observer)
        """
        super().__init__(student_id, host, scenario, password, secure)
        
        # Experiment strategy
        self.strategy = strategy if strategy else None
        self.experiment_name = strategy.get_name() if strategy else "passive"
        
        # Data logger (will be initialized after registration)
        self.logger: Optional[DataLogger] = None
        
        # Store full order book data
        self.last_bids: list = []
        self.last_asks: list = []
        self.last_trade: float = 0.0
        
        # Track pending fill for logging
        self.pending_fill: Optional[Dict] = None
    
    def register(self) -> bool:
        """Register and initialize data logger."""
        success = super().register()
        if success and self.run_id:
            # Initialize logger after registration
            mode = "active" if self.strategy else "passive"
            self.logger = DataLogger(
                scenario=self.scenario,
                run_id=self.run_id,
                experiment_name=self.experiment_name,
                mode=mode
            )
        return success
    
    def _on_market_data(self, ws, message: str):
        """Handle incoming market data snapshot with logging."""
        try:
            recv_time = time.time()
            data = json.loads(message)
            
            # Skip connection confirmation messages
            if data.get("type") == "CONNECTED":
                return
            
            # Measure step latency
            if self.last_done_time is not None:
                step_latency = (recv_time - self.last_done_time) * 1000  # ms
                self.step_latencies.append(step_latency)
            
            # Extract market data
            self.current_step = data.get("step", 0)
            self.last_bid = data.get("bid", 0.0)
            self.last_ask = data.get("ask", 0.0)
            
            # Capture full order book if available
            # Handle both "MARKET_DATA" and "SNAPSHOT" message types
            if data.get("type") in ["MARKET_DATA", "SNAPSHOT"] or "bids" in data:
                self.last_bids = data.get("bids", [])
                self.last_asks = data.get("asks", [])
            else:
                # If full book not available, create minimal book from best bid/ask
                self.last_bids = [{"price": self.last_bid, "qty": 0}] if self.last_bid > 0 else []
                self.last_asks = [{"price": self.last_ask, "qty": 0}] if self.last_ask > 0 else []
            
            self.last_trade = data.get("last_trade", 0.0)
            
            # Log progress every 500 steps
            if self.current_step % 500 == 0 and self.step_latencies:
                avg_lat = sum(self.step_latencies[-100:]) / min(len(self.step_latencies), 100)
                print(f"[{self.student_id}] Step {self.current_step} | Orders: {self.orders_sent} | Inv: {self.inventory} | Avg Latency: {avg_lat:.1f}ms")
            
            # Calculate mid price
            if self.last_bid > 0 and self.last_ask > 0:
                self.last_mid = (self.last_bid + self.last_ask) / 2
            elif self.last_bid > 0:
                self.last_mid = self.last_bid
            elif self.last_ask > 0:
                self.last_mid = self.last_ask
            else:
                self.last_mid = 0
            
            # Use strategy to decide order
            order = None
            if self.strategy:
                order = self.strategy.decide_order(
                    bid=self.last_bid,
                    ask=self.last_ask,
                    mid=self.last_mid,
                    inventory=self.inventory,
                    step=self.current_step
                )
            else:
                # Fallback to base decide_order if no strategy
                order = self.decide_order(self.last_bid, self.last_ask, self.last_mid)
            
            # Log this step before sending order
            if self.logger:
                self.logger.log_step(
                    step=self.current_step,
                    bid=self.last_bid,
                    ask=self.last_ask,
                    mid=self.last_mid,
                    bids=self.last_bids,
                    asks=self.last_asks,
                    last_trade=self.last_trade,
                    inventory=self.inventory,
                    cash_flow=self.cash_flow,
                    pnl=self.pnl,
                    orders_sent=self.orders_sent,
                    action=order,
                    fill=self.pending_fill
                )
                self.pending_fill = None  # Clear after logging
            
            # Send order if we have one
            if order and self.order_ws and self.order_ws.sock:
                self._send_order(order)
            
            # Signal DONE to advance to next step
            self._send_done()
            
        except Exception as e:
            print(f"[{self.student_id}] Market data error: {e}")
    
    def _on_order_response(self, ws, message: str):
        """Handle order responses and fills with logging."""
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
                
                # Measure fill latency
                fill_latency = None
                if order_id in self.order_send_times:
                    fill_latency = (recv_time - self.order_send_times[order_id]) * 1000  # ms
                    self.fill_latencies.append(fill_latency)
                    del self.order_send_times[order_id]
                
                # Update inventory and cash flow
                if side == "BUY":
                    self.inventory += qty
                    self.cash_flow -= qty * price
                else:
                    self.inventory -= qty
                    self.cash_flow += qty * price
                
                # Calculate mark-to-market PnL
                self.pnl = self.cash_flow + self.inventory * self.last_mid
                
                # Store fill for next log entry
                self.pending_fill = {
                    "side": side,
                    "price": price,
                    "qty": qty,
                    "order_id": order_id,
                    "latency_ms": fill_latency
                }
                
                print(f"[{self.student_id}] FILL: {side} {qty} @ {price:.2f} | Inventory: {self.inventory} | PnL: {self.pnl:.2f}")
            
            elif msg_type == "ERROR":
                print(f"[{self.student_id}] ERROR: {data.get('message')}")
                
        except Exception as e:
            print(f"[{self.student_id}] Order response error: {e}")
    
    def run(self):
        """Main entry point - register, connect, and run."""
        # Step 1: Register
        if not self.register():
            raise ConnectionError(f"Failed to register with server at {self.host}. Check that the server is running and --host/--secure flags are correct.")
        
        # Step 2: Connect
        if not self.connect():
            raise ConnectionError(f"Failed to connect to WebSocket at {self.host}")
        
        # Step 3: Run until complete
        print(f"[{self.student_id}] Running experiment '{self.experiment_name}'... Press Ctrl+C to stop")
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
            
            # Close logger
            if self.logger:
                self.logger.close()
            
            print(f"\n[{self.student_id}] Final Results:")
            print(f"  Experiment: {self.experiment_name}")
            print(f"  Orders Sent: {self.orders_sent}")
            print(f"  Inventory: {self.inventory}")
            print(f"  PnL: {self.pnl:.2f}")
            print(f"  Data logged to: {self.logger.get_filepath() if self.logger else 'N/A'}")
            
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

