# Data Collection Framework

Systematic experimentation framework for understanding market mechanics and testing trading strategies.

## Overview

This framework allows you to:
- Collect baseline market data (passive observation)
- Test different price/quantity combinations
- Experiment with various trading strategies
- Analyze results across all scenarios

## Files

- `collectors/logger.py` - Structured JSONL logging
- `collectors/strategies.py` - Pluggable experiment strategies
- `collectors/bot.py` - Extended TradingBot with logging
- `collectors/runner.py` - Experiment runner script
- `analysis/summary.py` - Summary statistics and CSV export

## Quick Start

### Important: Server Connection

You **must** specify the server host and port. The default `localhost:8080` will only work if you're running a local server.

**For remote servers (most common):**
```bash
python -m collectors.runner --scenario normal_market --experiment passive \
  --name your_team --password your_password \
  --host <SERVER_IP>:<PORT> --secure
```

**Example:**
```bash
python -m collectors.runner --scenario normal_market --experiment passive \
  --name Three-Bayesians --password Limit_Up_Limit_D0wn! \
  --host 3.98.52.120:8433 --secure
```

### 1. Run Passive Baseline Collection

Collect baseline data for all scenarios without trading:

```bash
python -m collectors.runner --scenario normal_market --experiment passive \
  --name your_team --password your_password \
  --host <SERVER_IP>:<PORT> --secure
```

### 2. Test Quantity Effects

Test how different quantities affect fills:

```bash
python -m collectors.runner --scenario normal_market --experiment qty_100 --name your_team --password your_password --host ip:port --secure
python -m collectors.runner --scenario normal_market --experiment qty_300 --name your_team --password your_password --host ip:port --secure
python -m collectors.runner --scenario normal_market --experiment qty_500 --name your_team --password your_password --host ip:port --secure
```

### 3. Test Price Levels

Test fill mechanics at different price points:

```bash
python -m collectors.runner --scenario normal_market --experiment price_bid --name your_team --password your_password --host ip:port --secure
python -m collectors.runner --scenario normal_market --experiment price_mid --name your_team --password your_password --host ip:port --secure
python -m collectors.runner --scenario normal_market --experiment price_ask --name your_team --password your_password --host ip:port --secure
```

### 4. Run All Experiments for One Scenario

```bash
python -m collectors.runner --scenario flash_crash --all-experiments --name your_team --password your_password --host ip:port --secure
```

### 5. List Available Options

```bash
python -m collectors.runner --list-experiments
python -m collectors.runner --list-scenarios
```

## Available Experiments

| Experiment | Description |
|------------|-------------|
| `passive` | No trading - baseline market observation |
| `aggressive_buy_100` | Buy aggressively every 10 steps, qty=100 |
| `aggressive_sell_100` | Sell aggressively every 10 steps, qty=100 |
| `spread_cross_100` | Alternate buy/sell crossing spread, qty=100 |
| `qty_100`, `qty_200`, `qty_300`, `qty_400`, `qty_500` | Test different quantities at mid price |
| `price_bid`, `price_ask`, `price_mid` | Test prices at bid/ask/mid |
| `price_bid_minus_1`, `price_ask_plus_1` | Test prices slightly off market |
| `inventory_mgmt` | Inventory management strategy |

## Available Scenarios

- `normal_market` - Baseline conditions
- `stressed_market` - Elevated volatility
- `flash_crash` - Extreme volatility events
- `hft_dominated` - Fast book updates, thin liquidity
- `mini_flash_crash` - Smaller crash events

## Data Output

All data is saved to the `data/raw/` directory in JSONL format:

```
data/
  ├── raw/
  │   ├── normal_market_passive_passive_20240117_100000.jsonl
  │   ├── normal_market_qty_100_active_20240117_100500.jsonl
  │   └── ...
  └── processed/
      ├── summary_report.csv
      └── ...
```

Each JSONL file contains one record per simulation step with:
- Market state (bid/ask/mid/spread, full order book)
- Your state (inventory, cash_flow, pnl)
- Actions taken (orders submitted)
- Results (fills received, latencies)

## Analyzing Data

### Generate Summary Report

Create a CSV summary of all experiments:

```bash
python -m analysis.summary --summary
```

This creates `data/processed/summary_report.csv` with one row per experiment run.

### Convert JSONL to CSV

Convert individual files for easier analysis:

```bash
python -m analysis.summary --file data/raw/normal_market_passive_passive_20240117_100000.jsonl
```

Or convert all files:

```bash
python -m analysis.summary --convert-all
```

### View Statistics for Single File

```bash
python -m analysis.summary --file data/raw/normal_market_passive_passive_20240117_100000.jsonl
```

## Experiment Design

### Understanding Fill Mechanics

1. **Passive baseline**: Run `passive` experiment first to understand baseline market
2. **Price exploration**: Test `price_bid`, `price_mid`, `price_ask` to see fill rates
3. **Quantity testing**: Test `qty_100` through `qty_500` to understand quantity impact

### Understanding Market Impact

1. Run `passive` for a scenario
2. Run `aggressive_buy_100` for the same scenario
3. Compare market evolution - does aggressive trading change future prices?

### Testing Determinism

1. Run the same scenario + experiment twice
2. Compare JSONL files - are market states identical?
3. This verifies the simulation is deterministic

## Example Workflow

```bash
# Step 1: Collect passive baselines for all scenarios
for scenario in normal_market stressed_market flash_crash hft_dominated mini_flash_crash; do
    python -m collectors.runner --scenario $scenario --experiment passive --name team --password pwd --host ip:port --secure
done

# Step 2: Test quantity effects on one scenario
for qty in qty_100 qty_200 qty_300 qty_400 qty_500; do
    python -m collectors.runner --scenario normal_market --experiment $qty --name team --password pwd --host ip:port --secure
done

# Step 3: Generate summary report
python -m analysis.summary --summary

# Step 4: Analyze results
# Open data/processed/summary_report.csv in Excel/Python to compare experiments
```

## Troubleshooting

### Connection Errors

**Error:** `Failed to establish a new connection` or `Connection refused`

**Solution:**
1. Check that you've specified `--host` with the correct server address
2. If using HTTPS/WSS, add the `--secure` flag
3. Verify the server is running and accessible
4. Check your network connection

**Example with correct flags:**
```bash
python -m collectors.runner --scenario normal_market --experiment passive \
  --name Three-Bayesians --password Limit_Up_Limit_D0wn! \
  --host 3.98.52.120:8433 --secure
```

### Common Issues

- **"No connection could be made"**: Missing `--host` flag or wrong server address
- **"Registration failed"**: Check team name and password are correct
- **"SSL errors"**: Add `--secure` flag for HTTPS/WSS connections

## Tips

1. **Start with passive**: Always collect passive baselines first to understand market behavior
2. **One scenario at a time**: Focus on understanding one scenario deeply before moving to others
3. **Systematic testing**: Test one variable at a time (price OR quantity, not both)
4. **Compare results**: Use the summary report to compare fill rates, PnL, inventory across experiments
5. **Check determinism**: Verify that passive runs produce identical market evolution
6. **Always specify --host**: Don't rely on default localhost unless running a local server

## Next Steps

After collecting data:
1. Use `data_summary.py` to generate statistics
2. Analyze fill rates, market impact, and price/quantity relationships
3. Move to **TRADING_ANALYZE** phase to identify patterns and crash signatures
4. Design strategies based on discovered mechanics

