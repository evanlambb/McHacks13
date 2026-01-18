# Market Simulator - Complete Reverse Engineering Analysis

**Date**: January 2026  
**Method**: CFR Java decompiler on `exchange-simulator-0.0.1-SNAPSHOT.jar`  
**Status**: ✅ Verified - All trader logic decompiled and analyzed

---

## Quick Start

### Running the Simulator

```bash
# Start simulator (from app/ directory)
cd app
java -jar exchange-simulator-0.0.1-SNAPSHOT.jar

# Run your algorithm
python student_algorithm.py --name team_alpha --password secret123 --scenario normal_market
```

### Available Scenarios

| Scenario | Duration | Description |
|----------|----------|-------------|
| `normal_market` | 36,000 steps (1 hour) | Baseline stable market |
| `stressed_market` | 36,000 steps (1 hour) | Declining fundamentals, reduced liquidity |
| `flash_crash` | 54,000 steps (1.5 hours) | Institutional selling triggers crash |
| `hft_dominated` | 36,000 steps (1 hour) | High frequency traders, thin book |
| `mini_flash_crash` | 36,000 steps (1 hour) | Random volatility spikes |

---

## Critical Parameter Transformations

⚠️ **Important**: JSON parameters are transformed before use:

| JSON Parameter | Actual Value | Example |
|----------------|--------------|---------|
| `orderInterval` | `value × 10` | `12 → 120 steps` |
| `percentageOfVolume` | `value ÷ 100` | `9 → 0.09 (9%)` |
| `startTime` | `((hour-8)×3600 + min×60 + sec) × 10` | `"08:30:00" → 18,000 steps` |

**Why this matters**: The InstitutionalTrader in flash_crash starts at step **18,000**, not step 0.

---

## Trader Logic Summary

### 1. SpikingTrader (Mini Flash Crash Trigger)

**Purpose**: Create sudden volatility bursts

```python
def decide(snapshot):
    if status > 0:  # Currently in spike
        submit_market_order(direction, 100)
        status -= 1
    elif random() < activationProbability:  # 0.5% chance
        direction = random_choice(["BUY", "SELL"])
        status = spikeLength  # 4 steps
        submit_market_order(direction, 100)
        status -= 1
```

**Key Parameters**:
- `activationProbability`: 0.005 (0.5% per step)
- `spikeLength`: 4 steps
- `orderVolume`: 100 shares per step

**Expected Behavior**: With 2 spiking traders in mini_flash_crash:
- ~1% chance of spike per step
- ~360 spike events over 36,000 steps
- Each spike: 400 shares traded over 4 steps

---

### 2. InstitutionalTrader (Flash Crash Trigger)

**Purpose**: Simulate large institutional selling algorithm

```python
def decide(snapshot):
    step = snapshot.step
    
    # Wait for start time
    if step < startStep:  # 18,000 for flash_crash
        return []
    
    # Check if done selling
    if inventory <= 0:
        return []
    
    # Rate limit: wait orderIntervalSteps between orders
    if step - lastOrderStep < 120:  # orderInterval=12 → 120 steps
        return []
    
    # Sell 9% of rolling 600-step volume
    targetQty = int(0.09 * max(rollingVolume, 100))
    orderQty = max(100, min(targetQty, inventory))
    
    submit_market_order("SELL", orderQty)
    inventory -= orderQty
    lastOrderStep = step
```

**Key Parameters** (flash_crash scenario):
- `initialInventory`: 220,000 shares
- `percentageOfVolume`: 0.09 (9%)
- `orderIntervalSteps`: 120 (12 seconds simulated)
- `startStep`: 18,000 (30 minutes into simulation)

**Expected Behavior**:
- Starts selling at step 18,000
- Sells every 120 steps
- Sells 9% of rolling volume (last 600 steps)
- Will take ~450 orders to dump 220k shares (if volume is constant)

---

### 3. MarketMaker (Liquidity Provider)

**Purpose**: Provide two-sided quotes, manage inventory risk

```python
def decide(snapshot):
    mid = calculate_mid(snapshot)
    
    # STRESS MODE ENTRY
    if abs(position) >= inventoryLimit:  # e.g., 5000
        stressedMode = True
        restartStep = currentStep + restPeriod  # e.g., +12,000
    
    # STRESS MODE EXIT
    if stressedMode and abs(position) <= safeInventory:  # e.g., 101
        stressedMode = False
    
    # IN STRESS: Panic unwind
    if stressedMode:
        cancel_all_orders()
        if position > 0:
            submit_market_order("SELL", min(position, 500))
        elif position < 0:
            submit_market_order("BUY", min(abs(position), 500))
        return
    
    # NORMAL: Quote two-sided
    if currentStep >= restartStep:
        if random() < deltaMM:  # e.g., 0.3
            cancel_all_orders()
        
        if random() < gamma:  # e.g., 0.8
            edge = random() * spreadEdge  # e.g., 0-4.0
            edge = max(0.1, edge)
            submit_limit_order("BUY", mid - edge, 500)
            submit_limit_order("SELL", mid + edge, 500)
```

**Key Parameters** vary by scenario:

| Scenario | Count | inventoryLimit | safeInventory | restPeriod | Implication |
|----------|-------|----------------|---------------|------------|-------------|
| normal_market | 5 | 5000 | 2000 | 600 | Quick recovery (1 min) |
| flash_crash | 20 | 5000 | **101** | **12,000** | Panic easily, gone 20 min |
| stressed_market | 3 | 5000 | 500 | **18,000** | Only 3 MMs, gone 30 min |
| hft_dominated | 8 | **50,000** | 300 | 3000 | Almost never stress |
| mini_flash_crash | 5 | 4000 | 101 | 12,000 | Moderate risk |

**Critical Insight**: When MMs hit their inventory limit, they:
1. Stop quoting immediately
2. Market-order to unwind position
3. Stay out of market for `restPeriod` steps
4. This creates **liquidity vacuum** → crash amplification

---

### 4. MomentumTrader (Trend Follower)

**Purpose**: Follow price trends with exponential decay

```python
def decide(snapshot):
    mid = calculate_mid(snapshot)
    
    # Update momentum (exponential moving average)
    if lastPrice > 0:
        priceChange = mid - lastPrice
        momentum = (1 - rho) * momentum + rho * priceChange
    
    # Normalize momentum
    tanhMomentum = tanh(momentum)
    
    # Probabilities scaled by parameters
    limitProb = min(1.0, abs(chi * tanhMomentum / numTraders))
    marketProb = min(1.0, abs(psi * tanhMomentum / numTraders))
    
    # Maybe submit limit order in direction of momentum
    if random() < limitProb and momentum != 0:
        side = "BUY" if momentum > 0 else "SELL"
        offset = logNormal(-5, 1) / 10000  # tiny offset
        price = mid + (-offset if side == "BUY" else offset)
        submit_limit_order(side, round(price, 1), 100)
    
    # Maybe submit market order in direction of momentum
    if random() < marketProb and momentum != 0:
        side = "BUY" if momentum > 0 else "SELL"
        submit_market_order(side, 100)
    
    lastPrice = mid
```

**Key Parameters**:

| Type | rho (decay) | chi | psi | Behavior |
|------|-------------|-----|-----|----------|
| Long-term | 0.001-0.01 | 0.3-50 | 0.09-15 | Slow trend following |
| Short-term | 0.9-0.95 | 0.12-80 | 0.03-25 | Fast momentum chasing |

**Strategic Insight**: 
- High `rho` (0.9) = fast decay, reacts to recent moves
- Low `rho` (0.01) = slow decay, follows longer trends
- Can predict their order flow by tracking momentum

---

### 5. FundamentalTrader (Mean Reversion)

**Purpose**: Trade toward fundamental value

```python
def decide(snapshot):
    mid = calculate_mid(snapshot)
    mispricing = fundamentalValue - mid
    absMispricing = abs(mispricing)
    
    # Demand increases with mispricing (cubic term for extremes)
    demand = kappa1 * absMispricing + kappa2 * absMispricing^3
    mu = demand / numTraders / 100
    mu = min(mu, 1.0)
    
    # Trade with probability mu every updateInterval steps
    if step % updateInterval == 0 and random() < mu:
        if mispricing > 0:  # Price below fundamental
            submit_market_order("BUY", 100)
        elif mispricing < 0:  # Price above fundamental
            submit_market_order("SELL", 100)
```

**Key Parameters**:
- `kappa1`: Linear response (0.139-0.5)
- `kappa2`: Cubic response for large deviations (0.05-0.4562)
- `updateInterval`: Steps between trades (100-500)

**Strategic Insight**: Strong fundamental traders (high kappa) create mean reversion. Price won't drift far from $1000 in most scenarios.

---

### 6. NoiseTrader (Random Activity)

**Purpose**: Provide random order flow

```python
def decide(snapshot):
    mid = calculate_mid(snapshot)
    
    # Random limit order
    if random() < alpha:  # alpha = min(eta/numTraders, 1.0)
        side = random_choice(["BUY", "SELL"])
        offset = logNormal(-5, 1) / 10000
        price = mid + (-offset if side == "BUY" else offset)
        submit_limit_order(side, round(price, 1), 100)
    
    # Random market order
    if random() < beta:  # beta = kappa * alpha
        side = random_choice(["BUY", "SELL"])
        submit_market_order(side, 100)
```

**Key Parameters**:
- `eta`: Activity level (0.25-5.0)
- `kappa`: Market order ratio (0.005-0.25)

**Strategic Insight**: Free liquidity. Noise traders are predictably unpredictable.

---

## Scenario-Specific Analysis

### Scenario 1: normal_market

**Characteristics**:
- 30 fundamental traders (strong mean reversion)
- 5 market makers with quick recovery (600 step rest)
- Balanced momentum (15 LT, 15 ST)
- High noise activity (eta=5.0)

**Strategy**: Aggressive market making
- Tight spreads (MMs recover quickly)
- High frequency trading
- Inventory skew toward mean reversion
- Trade every 10-20 steps

**Expected PnL**: Moderate, consistent spread capture

---

### Scenario 2: flash_crash

**Characteristics**:
- Institutional selling starts at step **18,000** (30 min in)
- 20 market makers but **panic easily** (safeInventory=101)
- MMs gone for 20 min when stressed (restPeriod=12,000)
- Weak momentum (low chi/psi values)

**Critical Timeline**:
1. **Steps 0-18,000**: Normal market
2. **Step 18,000**: Institutional starts selling
3. **Steps 18,000-18,120**: First institutional sell
4. **Steps 18,120+**: Selling every 120 steps

**Strategy**: 
- **Phase 1 (0-18,000)**: Aggressive market making
- **Phase 2 (18,000+)**: 
  - Detect institutional selling (volume spike)
  - Flatten position **immediately**
  - Short ahead of crash if skilled
  - Wait for MMs to blow up and withdraw
  - Provide liquidity at wide spreads during crash
  - Buy back when price bottoms

**Key Exploit**: You know the crash starts at step 18,000. Start reducing inventory at step 17,000.

---

### Scenario 3: stressed_market

**Characteristics**:
- **Negative drift** (-0.0001 per step)
- Only **3 market makers** (thin liquidity)
- MMs gone for **30 min** when stressed (restPeriod=18,000)
- Higher volatility (0.002 vs 0.001)

**Strategy**:
- Short bias (price trends down)
- Wide spreads (liquidity scarce)
- Conservative position sizes
- If MMs blow up, they're gone for half the simulation

**Key Exploit**: Fundamental value drifts down. Don't fight the trend.

---

### Scenario 4: hft_dominated

**Characteristics**:
- 50 short-term momentum traders (rho=0.95, fast decay)
- 8 market makers with **50k inventory limit** (almost never stress)
- Minimal fundamental traders (count=10, interval=500)
- High order cancellation (35%)

**Counter-intuitive**: Despite the name, this is actually **stable**
- MMs never blow up (50k limit)
- Momentum traders have weak influence (low chi/psi)
- Book is actually **deep and liquid**

**Strategy**:
- Small position sizes (100 shares)
- Fast execution
- Fade short-term momentum spikes
- Trade frequently

---

### Scenario 5: mini_flash_crash

**Characteristics**:
- 2 spiking traders (0.5% activation each)
- ~360 spike events expected
- MMs panic easily (safeInventory=101)
- MMs gone for 20 min when stressed

**Strategy**:
- **Crash detection**: 
  - Spread widening (>2x baseline)
  - Depth decline (>50%)
  - Volume spike
- **Response**:
  - Flatten position during spikes
  - Resume after 4 steps (spike length)
- **Exploit**: Provide liquidity at wide spreads during spikes

---

## Key Exploitable Insights

### 1. Market Maker Withdrawal Creates Opportunity

When MMs hit inventory limit:
- They **panic sell/buy** to unwind (market orders)
- They **disappear** for 600-18,000 steps
- This creates **liquidity vacuum**

**Exploit**: 
- Detect MM withdrawal (spread widening, depth drop)
- Quote at wider spreads
- Capture inflated spreads during liquidity vacuum

---

### 2. Institutional Trader is Predictable

Flash crash scenario:
- Starts at **step 18,000** (known)
- Sells every **120 steps** (known)
- Sells **9% of volume** (predictable quantity)

**Exploit**:
- Flatten position before step 18,000
- Short ahead of institutional selling
- Cover when volume dries up or MMs return

---

### 3. Momentum Traders Amplify Moves

Momentum = `(1-rho) * momentum + rho * priceChange`

Short-term (rho=0.9): React strongly to recent 1-2 tick moves
Long-term (rho=0.01): Follow longer trends

**Exploit**:
- Predict their order flow by tracking momentum
- Fade extreme momentum (they'll reverse)
- Front-run their orders on breakouts

---

### 4. Spiking Traders Are Random but Bounded

- 0.5% activation probability
- Exactly 4 steps of orders
- 100 shares per step

**Exploit**:
- Detect spike start (sudden volume)
- Know it lasts exactly 4 steps
- Flatten and wait, resume after step 4

---

## Recommended Strategy Architecture

### Core Components

```python
class OptimalTrader:
    def __init__(self):
        self.crash_detector = CrashDetector()
        self.regime = "NORMAL"
        self.inventory_manager = InventoryManager()
        
    def decide_order(self, snapshot):
        # 1. Update state
        self.crash_detector.update(snapshot)
        crash_score = self.crash_detector.get_score()
        
        # 2. Classify regime
        if crash_score > 0.6:
            self.regime = "CRASH"
        elif spread > baseline * 1.5:
            self.regime = "STRESSED"
        else:
            self.regime = "NORMAL"
        
        # 3. Execute regime-specific strategy
        if self.regime == "CRASH":
            return self.crash_strategy()
        elif self.regime == "STRESSED":
            return self.stressed_strategy()
        else:
            return self.normal_strategy()
```

### Crash Detection

```python
class CrashDetector:
    def __init__(self):
        self.spread_history = []
        self.depth_history = []
        self.baseline_spread = None
        
    def update(self, snapshot):
        self.spread_history.append(snapshot.spread)
        self.depth_history.append(snapshot.bid_depth + snapshot.ask_depth)
        
        # Establish baseline
        if len(self.spread_history) == 500:
            self.baseline_spread = mean(self.spread_history)
    
    def get_score(self):
        if not self.baseline_spread:
            return 0.0
        
        current_spread = mean(self.spread_history[-5:])
        spread_ratio = current_spread / self.baseline_spread
        
        current_depth = mean(self.depth_history[-5:])
        avg_depth = mean(self.depth_history[:-5])
        depth_ratio = current_depth / avg_depth if avg_depth > 0 else 1.0
        
        # Crash score: high spread, low depth
        return 0.5 * max(0, spread_ratio - 1) + 0.5 * max(0, 1 - depth_ratio)
```

### Inventory Management

```python
class InventoryManager:
    HARD_LIMIT = 5000  # Never exceed
    SOFT_LIMIT = 4000  # Start unwinding
    WARNING_LIMIT = 3000  # Reduce size
    
    def get_position_adjustment(self, inventory):
        if abs(inventory) >= SOFT_LIMIT:
            return "UNWIND_AGGRESSIVE"  # Market orders
        elif abs(inventory) >= WARNING_LIMIT:
            return "UNWIND_PASSIVE"  # Skewed quotes
        else:
            return "NORMAL"  # Symmetric quotes
    
    def calculate_skew(self, inventory):
        # Avellaneda-Stoikov style
        return -0.01 * inventory  # Adjust quotes based on inventory
```

---

## Next Steps for Implementation

1. **Build Crash Detector**: Test against collected data to tune thresholds
2. **Implement Regime Classifier**: NORMAL/STRESSED/CRASH modes
3. **Design Inventory Skew**: Avellaneda-Stoikov style quote adjustment
4. **Add Scenario-Specific Logic**: 
   - Flash crash: Flatten before step 18,000
   - Mini flash crash: Detect and survive 4-step spikes
5. **Backtest**: Run against all scenarios, optimize parameters
6. **Add Circuit Breakers**: Safety limits for unknown conditions

---

## Decompiled Source Files

Full verified Java source code available in `/simulator_analysis/decompiled/`:
- `BaseTrader.java` - Abstract base, position tracking
- `SpikingTrader.java` - Volatility spike logic
- `InstitutionalTrader.java` - Large seller algorithm
- `MarketMaker.java` - Two-sided quoting, stress mode
- `MomentumTrader.java` - Trend following logic
- `FundamentalTrader.java` - Mean reversion logic
- `NoiseTrader.java` - Random order generation
- `SimulationContext.java` - Parameter transformations
- `DeterministicRandom.java` - Seeded RNG

---

## Determinism Notes

The simulation is **deterministic** given the same seed. This means:
- Same seed → same AI trader decisions
- But **your actions affect the outcome**
- You can't replay and "cheat" because your orders change the market

**Use this to**:
- Test strategies repeatedly on the same scenario
- Understand exact market evolution
- Optimize parameters empirically

---

**End of Analysis**
