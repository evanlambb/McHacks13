"""
Data Collector - Experiment Runner
===================================
Orchestrates systematic experiments across scenarios and strategies.
"""

import argparse
import time
from collectors.bot import DataCollectorBot
from collectors.strategies import (
    PassiveObserver,
    AggressiveBuyer,
    AggressiveSeller,
    SpreadCrosser,
    QuantityTester,
    PriceExplorer,
    InventoryManager
)


# Available scenarios
SCENARIOS = [
    "normal_market",
    "stressed_market",
    "flash_crash",
    "hft_dominated",
    "mini_flash_crash"
]

# Predefined experiment configurations
EXPERIMENT_CONFIGS = {
    # Passive baseline - no trading
    "passive": {
        "strategy": PassiveObserver(),
        "description": "Passive observation - baseline market evolution"
    },
    
    # Aggressive trading tests
    "aggressive_buy_100": {
        "strategy": AggressiveBuyer(qty=100, frequency=10),
        "description": "Buy aggressively every 10 steps, qty=100"
    },
    "aggressive_sell_100": {
        "strategy": AggressiveSeller(qty=100, frequency=10),
        "description": "Sell aggressively every 10 steps, qty=100"
    },
    "spread_cross_100": {
        "strategy": SpreadCrosser(qty=100, frequency=10),
        "description": "Cross spread alternating buy/sell, qty=100"
    },
    
    # Quantity tests
    "qty_100": {
        "strategy": QuantityTester(qty=100, price_offset=0.0, frequency=10),
        "description": "Test qty=100 at mid price"
    },
    "qty_200": {
        "strategy": QuantityTester(qty=200, price_offset=0.0, frequency=10),
        "description": "Test qty=200 at mid price"
    },
    "qty_300": {
        "strategy": QuantityTester(qty=300, price_offset=0.0, frequency=10),
        "description": "Test qty=300 at mid price"
    },
    "qty_400": {
        "strategy": QuantityTester(qty=400, price_offset=0.0, frequency=10),
        "description": "Test qty=400 at mid price"
    },
    "qty_500": {
        "strategy": QuantityTester(qty=500, price_offset=0.0, frequency=10),
        "description": "Test qty=500 at mid price"
    },
    
    # Price level tests
    "price_bid": {
        "strategy": PriceExplorer(price_level="bid", qty=100, frequency=10),
        "description": "Test price at bid"
    },
    "price_ask": {
        "strategy": PriceExplorer(price_level="ask", qty=100, frequency=10),
        "description": "Test price at ask"
    },
    "price_mid": {
        "strategy": PriceExplorer(price_level="mid", qty=100, frequency=10),
        "description": "Test price at mid"
    },
    "price_bid_minus_1": {
        "strategy": PriceExplorer(price_level="bid-1", qty=100, frequency=10),
        "description": "Test price at bid-0.01"
    },
    "price_ask_plus_1": {
        "strategy": PriceExplorer(price_level="ask+1", qty=100, frequency=10),
        "description": "Test price at ask+0.01"
    },
    
    # Inventory management
    "inventory_mgmt": {
        "strategy": InventoryManager(qty=100, threshold=200, frequency=5),
        "description": "Inventory management - keep near zero"
    }
}


def run_single_experiment(scenario: str, experiment_name: str, student_id: str, 
                          password: str, host: str, secure: bool):
    """Run a single experiment."""
    config = EXPERIMENT_CONFIGS.get(experiment_name)
    if not config:
        print(f"ERROR: Unknown experiment '{experiment_name}'")
        return False
    
    strategy = config["strategy"]
    description = config["description"]
    
    print(f"\n{'='*70}")
    print(f"Running Experiment: {experiment_name}")
    print(f"Scenario: {scenario}")
    print(f"Description: {description}")
    print(f"{'='*70}\n")
    
    # Check if using default localhost and warn
    if host == "localhost:8080":
        print("WARNING: Using default host 'localhost:8080'.")
        print("If you're connecting to a remote server, specify --host <ip:port>")
        print("If using HTTPS/WSS, add --secure flag\n")
    
    bot = DataCollectorBot(
        student_id=student_id,
        host=host,
        scenario=scenario,
        password=password,
        secure=secure,
        strategy=strategy
    )
    
    try:
        bot.run()
        return True
    except ConnectionError as e:
        print(f"\n❌ CONNECTION ERROR: {e}")
        print(f"\nTroubleshooting:")
        print(f"  1. Is the server running?")
        print(f"  2. Check --host flag: currently '{host}'")
        print(f"  3. If using HTTPS/WSS, add --secure flag")
        print(f"  4. Example: --host 3.98.52.120:8433 --secure")
        return False
    except Exception as e:
        print(f"\n❌ ERROR running experiment: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_experiments(student_id: str, password: str, host: str, secure: bool,
                        scenarios: list = None, experiments: list = None):
    """
    Run multiple experiments across scenarios.
    
    Args:
        student_id: Team name
        password: Team password
        host: Server host:port
        secure: Use HTTPS/WSS
        scenarios: List of scenarios to run (None = all)
        experiments: List of experiment names to run (None = all)
    """
    if scenarios is None:
        scenarios = SCENARIOS
    
    if experiments is None:
        experiments = list(EXPERIMENT_CONFIGS.keys())
    
    print(f"\n{'='*70}")
    print(f"DATA COLLECTION EXPERIMENT RUNNER")
    print(f"{'='*70}")
    print(f"Scenarios: {', '.join(scenarios)}")
    print(f"Experiments: {', '.join(experiments)}")
    print(f"Total runs: {len(scenarios) * len(experiments)}")
    print(f"{'='*70}\n")
    
    results = []
    total_runs = len(scenarios) * len(experiments)
    current_run = 0
    
    for scenario in scenarios:
        for experiment_name in experiments:
            current_run += 1
            print(f"\n[{current_run}/{total_runs}] {scenario} - {experiment_name}")
            
            success = run_single_experiment(
                scenario=scenario,
                experiment_name=experiment_name,
                student_id=student_id,
                password=password,
                host=host,
                secure=secure
            )
            
            results.append({
                "scenario": scenario,
                "experiment": experiment_name,
                "success": success
            })
            
            # Small delay between runs
            if current_run < total_runs:
                print("\nWaiting 2 seconds before next run...")
                time.sleep(2)
    
    # Print summary
    print(f"\n{'='*70}")
    print(f"EXPERIMENT SUMMARY")
    print(f"{'='*70}")
    successful = sum(1 for r in results if r["success"])
    print(f"Successful: {successful}/{total_runs}")
    print(f"Failed: {total_runs - successful}/{total_runs}")
    print(f"\nResults:")
    for r in results:
        status = "✓" if r["success"] else "✗"
        print(f"  {status} {r['scenario']} - {r['experiment']}")
    print(f"{'='*70}\n")


def list_experiments():
    """List all available experiments."""
    print("\nAvailable Experiments:")
    print("=" * 70)
    for name, config in EXPERIMENT_CONFIGS.items():
        print(f"  {name:30} - {config['description']}")
    print("=" * 70)


def list_scenarios():
    """List all available scenarios."""
    print("\nAvailable Scenarios:")
    print("=" * 70)
    for scenario in SCENARIOS:
        print(f"  - {scenario}")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Data Collection Experiment Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run single experiment
  python -m collectors.runner --scenario normal_market --experiment passive --name team --password pwd
  
  # Run all experiments for one scenario
  python -m collectors.runner --scenario flash_crash --all-experiments --name team --password pwd
  
  # Run all scenarios with one experiment
  python -m collectors.runner --experiment passive --all-scenarios --name team --password pwd
  
  # Run everything (all scenarios, all experiments)
  python -m collectors.runner --all-scenarios --all-experiments --name team --password pwd
  
  # List available options
  python -m collectors.runner --list-experiments
  python -m collectors.runner --list-scenarios
        """
    )
    
    parser.add_argument("--name", required=True, help="Your team name")
    parser.add_argument("--password", required=True, help="Your team password")
    parser.add_argument("--host", default="localhost:8080", help="Server host:port")
    parser.add_argument("--secure", action="store_true", help="Use HTTPS/WSS")
    
    parser.add_argument("--scenario", help="Single scenario to run")
    parser.add_argument("--all-scenarios", action="store_true", help="Run all scenarios")
    
    parser.add_argument("--experiment", help="Single experiment to run")
    parser.add_argument("--all-experiments", action="store_true", help="Run all experiments")
    
    parser.add_argument("--list-experiments", action="store_true", help="List available experiments")
    parser.add_argument("--list-scenarios", action="store_true", help="List available scenarios")
    
    args = parser.parse_args()
    
    # Handle list commands
    if args.list_experiments:
        list_experiments()
        exit(0)
    
    if args.list_scenarios:
        list_scenarios()
        exit(0)
    
    # Determine scenarios
    if args.all_scenarios:
        scenarios = SCENARIOS
    elif args.scenario:
        if args.scenario not in SCENARIOS:
            print(f"ERROR: Unknown scenario '{args.scenario}'")
            print("Available scenarios:", ", ".join(SCENARIOS))
            exit(1)
        scenarios = [args.scenario]
    else:
        print("ERROR: Must specify --scenario or --all-scenarios")
        exit(1)
    
    # Determine experiments
    if args.all_experiments:
        experiments = list(EXPERIMENT_CONFIGS.keys())
    elif args.experiment:
        if args.experiment not in EXPERIMENT_CONFIGS:
            print(f"ERROR: Unknown experiment '{args.experiment}'")
            print("Run with --list-experiments to see available experiments")
            exit(1)
        experiments = [args.experiment]
    else:
        print("ERROR: Must specify --experiment or --all-experiments")
        exit(1)
    
    # Run experiments
    run_all_experiments(
        student_id=args.name,
        password=args.password,
        host=args.host,
        secure=args.secure,
        scenarios=scenarios,
        experiments=experiments
    )

