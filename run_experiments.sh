#!/bin/bash
# Data Collection Batch Runner
# Runs multiple experiments consecutively

NAME="${1:-Three-Bayesians}"
PASSWORD="${2:-Limit_Up_Limit_D0wn!}"
HOST="${3:-localhost:8080}"
SECURE="${4:-}"
SCENARIO="${5:-normal_market}"

echo "========================================"
echo "Batch Experiment Runner"
echo "========================================"
echo "Scenario: $SCENARIO"
echo "Team: $NAME"
echo "Host: $HOST"
echo "========================================"
echo ""

# Define experiments to run
experiments=(
    # Quantity tests
    "qty_100"
    "qty_200"
    "qty_300"
    "qty_400"
    "qty_500"
    
    # Aggressive trading
    "aggressive_buy_100"
    "aggressive_sell_100"
    "spread_cross_100"
    
    # Inventory management
    "inventory_mgmt"
)

total=${#experiments[@]}
current=0
successful=0
failed=0

for exp in "${experiments[@]}"; do
    current=$((current + 1))
    echo ""
    echo "[$current/$total] Running: $exp"
    echo "----------------------------------------"
    
    cmd="python -m collectors.runner --scenario $SCENARIO --experiment $exp --name $NAME --password $PASSWORD --host $HOST"
    
    if [ -n "$SECURE" ]; then
        cmd="$cmd --secure"
    fi
    
    if $cmd; then
        successful=$((successful + 1))
        echo "✓ Success: $exp"
    else
        failed=$((failed + 1))
        echo "✗ Failed: $exp"
    fi
    
    # Small delay between runs
    if [ $current -lt $total ]; then
        echo ""
        echo "Waiting 3 seconds before next experiment..."
        echo ""
        sleep 3
    fi
done

echo ""
echo "========================================"
echo "Batch Run Complete"
echo "========================================"
echo "Successful: $successful/$total"
echo "Failed: $failed/$total"
echo "========================================"
echo ""

# Generate summary report
echo "Generating summary report..."
python -m analysis.summary --summary
echo ""
echo "Done! Check data/processed/summary_report.csv"

