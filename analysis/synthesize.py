"""
Experiment Data Synthesis Script
=================================
Synthesizes all CSV experiment data to identify what worked, what didn't,
what went as expected, and what was surprising.
"""

import csv
from pathlib import Path
from typing import Dict, List, Tuple, Any
from datetime import datetime


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float."""
    try:
        return float(value) if value else default
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to int."""
    try:
        return int(value) if value else default
    except (ValueError, TypeError):
        return default


def load_and_parse_csv(csv_path: str = "data/processed/summary_report.csv") -> List[Dict]:
    """Load CSV and create list of dicts with derived metrics."""
    records = []
    
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric fields
            record = {}
            for key, value in row.items():
                if key in ['final_pnl', 'total_fills', 'max_inventory', 'min_pnl', 'max_pnl',
                          'total_fill_qty', 'avg_fill_price', 'fill_rate_pct', 'inventory_utilization',
                          'notional_traded', 'pnl_per_fill', 'inventory_risk_score', 'composite_score',
                          'avg_fill_latency_ms', 'min_fill_latency_ms', 'max_fill_latency_ms',
                          'total_actions', 'buy_actions', 'sell_actions', 'total_steps']:
                    record[key] = safe_float(value)
                elif key in ['total_fills', 'buy_fills', 'sell_fills', 'max_inventory', 'final_inventory',
                            'total_actions', 'buy_actions', 'sell_actions', 'total_steps']:
                    record[key] = safe_int(value)
                else:
                    record[key] = value
            
            # Calculate derived metrics
            total_fills = record.get('total_fills', 0)
            final_pnl = record.get('final_pnl', 0)
            max_inventory = safe_float(record.get('max_inventory', 0))
            min_inventory = safe_float(record.get('min_inventory', 0))
            
            # Calculate max absolute inventory (considering both long and short positions)
            max_abs_inventory = max(abs(max_inventory), abs(min_inventory))
            
            record['pnl_per_fill'] = final_pnl / total_fills if total_fills > 0 else 0
            record['inventory_utilization'] = max_abs_inventory / 5000.0 if max_abs_inventory > 0 else 0
            record['fill_efficiency'] = record.get('fill_rate_pct', 0) / 100.0
            
            # Risk-adjusted return (PnL / max drawdown)
            min_pnl = record.get('min_pnl', 0)
            max_pnl = record.get('max_pnl', 0)
            if min_pnl < 0:
                max_drawdown = abs(min_pnl)
            elif max_pnl > 0:
                max_drawdown = max_pnl
            else:
                max_drawdown = 1
            record['max_drawdown'] = max_drawdown
            record['risk_adjusted_return'] = final_pnl / max_drawdown if max_drawdown > 0 else 0
            
            # Notional traded
            total_fill_qty = record.get('total_fill_qty', 0)
            avg_fill_price = record.get('avg_fill_price', 0)
            record['notional_traded'] = total_fill_qty * avg_fill_price
            
            # Inventory risk score (lower is better, 0 = no risk, 1 = maxed out)
            record['inventory_risk_score'] = record['inventory_utilization']
            
            records.append(record)
    
    return records


def categorize_experiments(records: List[Dict]) -> Dict[str, List[str]]:
    """Categorize experiments by type."""
    categories = {
        'passive': [],
        'aggressive': [],
        'price_explore': [],
        'qty_test': [],
        'spread_cross': [],
        'inventory_mgmt': []
    }
    
    for record in records:
        exp = record['experiment']
        
        if 'passive' in exp:
            categories['passive'].append(exp)
        elif 'aggressive' in exp:
            categories['aggressive'].append(exp)
        elif 'price_explore' in exp:
            categories['price_explore'].append(exp)
        elif 'qty_test' in exp:
            categories['qty_test'].append(exp)
        elif 'spread_cross' in exp:
            categories['spread_cross'].append(exp)
        elif 'inventory_mgmt' in exp:
            categories['inventory_mgmt'].append(exp)
    
    return categories


def compute_effectiveness_rankings(records: List[Dict]) -> Dict[str, List[Dict]]:
    """Compute effectiveness rankings across 4 competition dimensions."""
    # Calculate composite scores first
    max_pnl = max(abs(r['final_pnl']) for r in records) if records else 1
    max_notional = max(r['notional_traded'] for r in records) if records else 1
    max_latency = max(r.get('avg_fill_latency_ms', 0) for r in records if r.get('avg_fill_latency_ms', 0) > 0) if records else 1
    
    for record in records:
        pnl_norm = record['final_pnl'] / max_pnl if max_pnl > 0 else 0
        notional_norm = record['notional_traded'] / max_notional if max_notional > 0 else 0
        latency_norm = 1 - (record.get('avg_fill_latency_ms', 0) / max_latency) if max_latency > 0 else 0
        
        record['composite_score'] = (
            0.4 * pnl_norm +
            0.3 * notional_norm +
            0.2 * (1 - record['inventory_risk_score']) +
            0.1 * latency_norm
        )
    
    rankings = {}
    
    # 1. Profitability ranking
    rankings['profitability'] = sorted(
        records,
        key=lambda r: r['final_pnl'],
        reverse=True
    )
    
    # 2. Notional traded ranking
    rankings['notional'] = sorted(
        records,
        key=lambda r: r['notional_traded'],
        reverse=True
    )
    
    # 3. Inventory management ranking (lower utilization is better)
    rankings['inventory_mgmt'] = sorted(
        records,
        key=lambda r: r['inventory_risk_score']
    )
    
    # 4. Speed ranking (based on fill latency - lower is better)
    speed_records = [r for r in records if r.get('avg_fill_latency_ms', 0) > 0]
    rankings['speed'] = sorted(
        speed_records,
        key=lambda r: r.get('avg_fill_latency_ms', float('inf'))
    )
    
    # Overall composite score
    rankings['overall'] = sorted(
        records,
        key=lambda r: r['composite_score'],
        reverse=True
    )
    
    return rankings


def analyze_what_worked(records: List[Dict]) -> List[Dict]:
    """Identify experiments that worked well."""
    worked = []
    worked_experiments = set()
    
    # Positive PnL experiments
    for record in records:
        if record['final_pnl'] > 0:
            worked.append({
                'experiment': record['experiment'],
                'reason': 'Profitable',
                'final_pnl': record['final_pnl'],
                'fill_rate': record.get('fill_rate_pct', 0),
                'inventory_risk': record['inventory_risk_score']
            })
            worked_experiments.add(record['experiment'])
    
    # High fill rate with controlled inventory
    for record in records:
        if (record.get('fill_rate_pct', 0) > 50 and 
            record['inventory_risk_score'] < 0.5 and
            record['experiment'] not in worked_experiments):
            worked.append({
                'experiment': record['experiment'],
                'reason': 'High fill rate, low inventory risk',
                'final_pnl': record['final_pnl'],
                'fill_rate': record.get('fill_rate_pct', 0),
                'inventory_risk': record['inventory_risk_score']
            })
            worked_experiments.add(record['experiment'])
    
    return worked


def analyze_what_didnt_work(records: List[Dict]) -> List[Dict]:
    """Identify experiments that failed."""
    failed = []
    failed_experiments = set()
    
    # Zero fills despite actions
    for record in records:
        if record.get('total_actions', 0) > 0 and record.get('total_fills', 0) == 0:
            failed.append({
                'experiment': record['experiment'],
                'reason': f"Zero fills despite {record['total_actions']} actions",
                'actions': record['total_actions'],
                'final_pnl': record['final_pnl']
            })
            failed_experiments.add(record['experiment'])
    
    # Inventory blow-ups
    for record in records:
        if record['inventory_utilization'] >= 1.0 and record['experiment'] not in failed_experiments:
            failed.append({
                'experiment': record['experiment'],
                'reason': f"Inventory limit hit (max: {record['max_inventory']})",
                'max_inventory': record['max_inventory'],
                'final_pnl': record['final_pnl']
            })
            failed_experiments.add(record['experiment'])
    
    # Large losses
    for record in records:
        if record['final_pnl'] < -1000 and record['experiment'] not in failed_experiments:
            failed.append({
                'experiment': record['experiment'],
                'reason': f"Large loss: ${record['final_pnl']:.2f}",
                'final_pnl': record['final_pnl'],
                'fill_rate': record.get('fill_rate_pct', 0)
            })
            failed_experiments.add(record['experiment'])
    
    return failed


def analyze_surprising_findings(records: List[Dict], categories: Dict[str, List[str]]) -> List[Dict]:
    """Identify surprising findings vs expectations."""
    surprises = []
    
    # Helper to find record by experiment name
    def find_record(exp_name: str) -> Dict:
        for r in records:
            if r['experiment'] == exp_name:
                return r
        return {}
    
    # Helper to filter records
    def filter_records(condition) -> List[Dict]:
        return [r for r in records if condition(r)]
    
    # 1. Mid-price orders never fill
    mid_price = find_record('price_explore_mid_qty100_freq10')
    if mid_price and mid_price.get('total_actions', 0) > 0 and mid_price.get('total_fills', 0) == 0:
        surprises.append({
            'finding': 'Mid-price limit orders never execute',
            'experiment': 'price_explore_mid_qty100_freq10',
            'details': f"Submitted {mid_price['total_actions']} orders at mid-price, got 0 fills",
            'implication': 'Limit orders at mid-price don\'t execute - need to cross spread or be more aggressive'
        })
    
    # 2. Quantity sweet spot
    qty_experiments = filter_records(lambda r: 'qty_test' in r['experiment'])
    qty_with_fills = filter_records(lambda r: 'qty_test' in r['experiment'] and r.get('total_fills', 0) > 0)
    qty_without_fills = filter_records(lambda r: 'qty_test' in r['experiment'] and r.get('total_fills', 0) == 0)
    
    if len(qty_with_fills) > 0 and len(qty_without_fills) > 0:
        worked_qtys = [exp.split('_')[2] for exp in [r['experiment'] for r in qty_with_fills]]
        failed_qtys = [exp.split('_')[2] for exp in [r['experiment'] for r in qty_without_fills]]
        surprises.append({
            'finding': 'Quantity sweet spot exists',
            'experiment': 'qty_test series',
            'details': f"Qty {', '.join(worked_qtys)} got fills and profit, but qty {', '.join(failed_qtys)} got zero fills",
            'implication': 'Optimal quantity is around 300-400 shares, not 100-200 or 500'
        })
    
    # 3. Spread crossing is costly
    spread_cross = find_record('spread_cross_qty100_freq10')
    if spread_cross and spread_cross.get('fill_rate_pct', 0) > 80 and spread_cross.get('final_pnl', 0) < -10000:
        surprises.append({
            'finding': 'Spread crossing strategy loses money despite high fill rate',
            'experiment': 'spread_cross_qty100_freq10',
            'details': f"{spread_cross.get('fill_rate_pct', 0):.1f}% fill rate but lost ${spread_cross.get('final_pnl', 0):.2f}",
            'implication': 'Crossing the spread costs money - you pay the spread, not capture it. Need better pricing.'
        })
    
    # 4. Aggressive strategies hit limits quickly
    aggressive = filter_records(lambda r: 'aggressive' in r['experiment'])
    if len(aggressive) > 0:
        hit_limits = filter_records(lambda r: 'aggressive' in r['experiment'] and r['inventory_utilization'] >= 1.0)
        if len(hit_limits) > 0:
            surprises.append({
                'finding': 'Aggressive strategies hit inventory limits very quickly',
                'experiment': 'aggressive_buy/sell',
                'details': f"Hit 5000 inventory limit in ~{hit_limits[0].get('total_steps', 0)} steps",
                'implication': 'Need inventory management to prevent hitting limits'
            })
    
    # 5. Market stability
    passive = find_record('passive')
    if passive and safe_float(passive.get('mid_range', 0)) < 0.2:
        surprises.append({
            'finding': 'Market is extremely stable',
            'experiment': 'passive',
            'details': f"Mid price range only {safe_float(passive.get('mid_range', 0)):.2f}, spread stayed 0.1-0.2",
            'implication': 'Normal market has very tight spreads, making market making challenging'
        })
    
    # 6. Price exploration asymmetry
    price_explore = filter_records(lambda r: 'price_explore' in r['experiment'])
    if len(price_explore) > 0:
        ask_explore_list = filter_records(lambda r: 'price_explore' in r['experiment'] and 'ask' in r['experiment'])
        bid_explore_list = filter_records(lambda r: 'price_explore' in r['experiment'] and 'bid' in r['experiment'])
        if ask_explore_list and bid_explore_list:
            ask_explore = ask_explore_list[0]
            bid_explore = bid_explore_list[0]
            if ask_explore.get('total_fills', 0) > 0 and bid_explore.get('total_fills', 0) > 0:
                ask_pnl = ask_explore.get('final_pnl', 0)
                bid_pnl = bid_explore.get('final_pnl', 0)
                if ask_pnl < bid_pnl:
                    surprises.append({
                        'finding': 'Asymmetric fill behavior between bid and ask',
                        'experiment': 'price_explore_bid/ask',
                        'details': f"Ask exploration: {ask_explore.get('total_fills', 0)} fills, ${ask_pnl:.2f} PnL. Bid exploration: {bid_explore.get('total_fills', 0)} fills, ${bid_pnl:.2f} PnL",
                        'implication': 'Market may have directional bias or different liquidity on each side'
                    })
    
    return surprises


def format_table(headers: List[str], rows: List[List[Any]], max_width: int = 80) -> str:
    """Format a simple table without external dependencies."""
    if not rows:
        return "  (no data)"
    
    # Calculate column widths
    col_widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))
    
    # Limit column widths to prevent overflow
    total_width = sum(col_widths) + len(headers) * 3 + 1
    if total_width > max_width:
        excess = total_width - max_width
        for i in range(len(col_widths)):
            if col_widths[i] > 20:
                reduction = min(excess, col_widths[i] - 20)
                col_widths[i] -= reduction
                excess -= reduction
                if excess <= 0:
                    break
    
    # Format header
    header_row = " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "-" * len(header_row)
    
    # Format rows
    formatted_rows = []
    for row in rows:
        formatted_row = " | ".join(
            str(cell)[:col_widths[i]].ljust(col_widths[i]) 
            for i, cell in enumerate(row[:len(headers)])
        )
        formatted_rows.append(formatted_row)
    
    return "\n".join([header_row, separator] + formatted_rows)


def generate_report(records: List[Dict], categories: Dict[str, List[str]], 
                    rankings: Dict[str, List[Dict]],
                    worked: List[Dict], failed: List[Dict], 
                    surprises: List[Dict]) -> str:
    """Generate comprehensive synthesis report."""
    report = []
    report.append("=" * 80)
    report.append("EXPERIMENT SYNTHESIS REPORT")
    report.append("=" * 80)
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"Total Experiments: {len(records)}")
    report.append("")
    
    # Section 1: Effectiveness Rankings
    report.append("[1] EFFECTIVENESS RANKINGS")
    report.append("-" * 80)
    
    report.append("\n1.1 Profitability Ranking:")
    profitability_rows = [
        [r['experiment'], f"${r['final_pnl']:.2f}", f"${r.get('pnl_per_fill', 0):.2f}", r.get('total_fills', 0)]
        for r in rankings['profitability'][:10]
    ]
    report.append(format_table(
        ['Experiment', 'Final PnL', 'PnL per Fill', 'Total Fills'],
        profitability_rows
    ))
    
    report.append("\n1.2 Notional Traded Ranking:")
    notional_rows = [
        [r['experiment'], f"${r['notional_traded']:.2f}", r.get('total_fills', 0), r.get('total_fill_qty', 0)]
        for r in rankings['notional'][:10]
    ]
    report.append(format_table(
        ['Experiment', 'Notional Traded', 'Total Fills', 'Total Fill Qty'],
        notional_rows
    ))
    
    report.append("\n1.3 Inventory Management Ranking (lower is better):")
    inventory_rows = [
        [r['experiment'], f"{r['inventory_risk_score']:.3f}", r.get('max_inventory', 0), r.get('final_inventory', 0)]
        for r in rankings['inventory_mgmt'][:10]
    ]
    report.append(format_table(
        ['Experiment', 'Risk Score', 'Max Inventory', 'Final Inventory'],
        inventory_rows
    ))
    
    if len(rankings['speed']) > 0:
        report.append("\n1.4 Speed Ranking (lower latency is better):")
        speed_rows = [
            [r['experiment'], f"{r.get('avg_fill_latency_ms', 0):.2f}", 
             f"{r.get('min_fill_latency_ms', 0):.2f}", f"{r.get('max_fill_latency_ms', 0):.2f}"]
            for r in rankings['speed'][:10]
        ]
        report.append(format_table(
            ['Experiment', 'Avg Latency (ms)', 'Min Latency (ms)', 'Max Latency (ms)'],
            speed_rows
        ))
    
    report.append("\n1.5 Overall Composite Score:")
    overall_rows = [
        [r['experiment'], f"{r['composite_score']:.3f}", f"${r['final_pnl']:.2f}", 
         f"${r['notional_traded']:.2f}", f"{r['inventory_risk_score']:.3f}"]
        for r in rankings['overall'][:10]
    ]
    report.append(format_table(
        ['Experiment', 'Composite Score', 'Final PnL', 'Notional Traded', 'Inventory Risk'],
        overall_rows
    ))
    
    # Section 2: What Worked
    report.append("\n" + "=" * 80)
    report.append("[2] WHAT WORKED")
    report.append("-" * 80)
    
    if worked:
        worked_rows = [[w['experiment'], w['reason'], f"${w['final_pnl']:.2f}", 
                        f"{w['fill_rate']:.1f}%", f"{w['inventory_risk']:.2f}"] 
                       for w in worked]
        report.append(format_table(
            ['Experiment', 'Reason', 'Final PnL', 'Fill Rate', 'Inventory Risk'],
            worked_rows
        ))
    else:
        report.append("No experiments showed clear success signals.")
    
    # Section 3: What Didn't Work
    report.append("\n" + "=" * 80)
    report.append("[3] WHAT DIDN'T WORK")
    report.append("-" * 80)
    
    if failed:
        failed_rows = [[f['experiment'], f['reason']] for f in failed]
        report.append(format_table(
            ['Experiment', 'Failure Reason'],
            failed_rows
        ))
    else:
        report.append("All experiments had some level of success.")
    
    # Section 4: Surprising Findings
    report.append("\n" + "=" * 80)
    report.append("[4] SURPRISING FINDINGS")
    report.append("-" * 80)
    
    if surprises:
        for i, surprise in enumerate(surprises, 1):
            report.append(f"\n{i}. {surprise['finding']}")
            report.append(f"   Experiment: {surprise['experiment']}")
            report.append(f"   Details: {surprise['details']}")
            report.append(f"   Implication: {surprise['implication']}")
    else:
        report.append("No surprising findings identified.")
    
    # Section 5: Strategic Recommendations
    report.append("\n" + "=" * 80)
    report.append("[5] STRATEGIC RECOMMENDATIONS")
    report.append("-" * 80)
    
    recommendations = []
    
    # Based on what worked
    if worked:
        profitable_exps = [w for w in worked if w['final_pnl'] > 0]
        if profitable_exps:
            best = max(profitable_exps, key=lambda x: x['final_pnl'])
            recommendations.append(f"[+] Best performing strategy: {best['experiment']} (PnL: ${best['final_pnl']:.2f})")
            recommendations.append(f"    -> Consider adapting this approach for production strategy")
    
    # Based on failures
    zero_fill_exps = [f for f in failed if 'Zero fills' in f['reason']]
    if zero_fill_exps:
        recommendations.append(f"[-] Avoid strategies that got zero fills:")
        for exp in zero_fill_exps:
            recommendations.append(f"    -> {exp['experiment']}: {exp['reason']}")
    
    # Based on surprises
    if surprises:
        qty_surprise = [s for s in surprises if 'Quantity sweet spot' in s['finding']]
        if qty_surprise:
            recommendations.append(f"[+] Quantity optimization:")
            recommendations.append(f"    -> Use quantities around 300-400 shares for optimal fill rates")
        
        spread_surprise = [s for s in surprises if 'Spread crossing' in s['finding']]
        if spread_surprise:
            recommendations.append(f"[-] Spread crossing strategy:")
            recommendations.append(f"    -> Don't cross the spread blindly - need better pricing logic")
    
    # Inventory management
    blowups = [f for f in failed if 'Inventory limit' in f['reason']]
    if blowups:
        recommendations.append(f"[!] Critical: Implement inventory management")
        recommendations.append(f"    -> Multiple strategies hit the 5000 inventory limit")
        recommendations.append(f"    -> Need dynamic position limits and rebalancing")
    
    if recommendations:
        report.append("\n".join(recommendations))
    else:
        report.append("Continue systematic experimentation to identify optimal strategies.")
    
    report.append("\n" + "=" * 80)
    
    return "\n".join(report)


def main():
    """Main execution function."""
    csv_path = "data/processed/summary_report.csv"
    
    if not Path(csv_path).exists():
        print(f"Error: {csv_path} not found")
        return
    
    print("Loading and parsing CSV...")
    records = load_and_parse_csv(csv_path)
    print(f"Loaded {len(records)} experiments")
    
    print("Categorizing experiments...")
    categories = categorize_experiments(records)
    
    print("Computing effectiveness rankings...")
    rankings = compute_effectiveness_rankings(records)
    
    print("Analyzing what worked...")
    worked = analyze_what_worked(records)
    
    print("Analyzing what didn't work...")
    failed = analyze_what_didnt_work(records)
    
    print("Identifying surprising findings...")
    surprises = analyze_surprising_findings(records, categories)
    
    print("Generating report...")
    report = generate_report(records, categories, rankings, worked, failed, surprises)
    
    # Print to console
    print("\n" + report)
    
    # Save to markdown file
    output_path = Path("data/processed/synthesis_report.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(report)
    
    print(f"\nReport saved to: {output_path}")


if __name__ == "__main__":
    main()

