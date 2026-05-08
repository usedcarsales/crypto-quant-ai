#!/usr/bin/env python3
"""
strategy_backtester.py — QuantAlpha Strategy Optimizer
Phase 6 Innovation — Turn paper trading history into strategy insights

Purpose:
  Take the closed trade journal and backtest what would have happened
  if different parameters were used (SL/TP ratios, position sizing,
  confidence thresholds). Generates strategy recommendations.

Revenue Model:
  - Internal: auto-optimize strategy parameters weekly
  - External: "What-if" analysis for subscribers
  - Content: "Strategy Deep Dive" reports posted to Discord

Usage:
  python skills/research_engine/strategy_backtester.py [--trades-file PATH] [--output md|json]
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ─── Constants ─────────────────────────────────────────────────────────────────

TRADE_JOURNAL = "/tmp/crypto-quant-trade-journal.json"
REPORT_DIR = "/tmp/crypto-quant-ai/reports"


# ─── Data Loading ────────────────────────────────────────────────────────────────

def load_closed_trades(path: str = TRADE_JOURNAL) -> List[dict]:
    """Load only closed trades from journal."""
    if not os.path.exists(path):
        return []
    with open(path) as f:
        data = json.load(f)
    return [t for t in data.get("closed_trades", []) if t.get("status") == "CLOSED"]


# ─── Backtest Logic ────────────────────────────────────────────────────────────

def backtest_sl_tp_variations(trades: List[dict]) -> Dict[str, dict]:
    """
    For each trade, calculate what P&L would have been at different SL/TP levels.
    We use the actual high/low data from the trade if available, or estimate from
    entry price and SL/TP settings.
    """
    scenarios = {}
    
    # Test: tighter SL (3% vs 5%), wider TP (12% vs 8%), asymmetric (3/12)
    configs = [
        ("current", None, None),  # uses actual trade outcome
        ("tight_sl_3", 0.03, None),
        ("wide_tp_12", None, 0.12),
        ("asymmetric_3_12", 0.03, 0.12),
        ("asymmetric_4_10", 0.04, 0.10),
        ("conservative_4_8", 0.04, 0.08),
    ]
    
    for name, sl_pct, tp_pct in configs:
        wins = losses = total_pnl = max_dd = 0
        running_pnl = 0
        peak = 0
        
        for t in trades:
            entry = t.get("entry_price", 0)
            direction = t.get("direction", "BUY")
            
            if name == "current":
                pnl = t.get("pnl_realized", 0)
            else:
                # Simulate with different SL/TP
                # We don't have actual high/low, so use a heuristic:
                # If trade was a win at current settings, assume it would have
                # hit the new TP too (unless tighter SL would have stopped it earlier)
                # If trade was a loss, check if tighter SL would have lost less
                pnl = simulate_trade_pnl(t, sl_pct, tp_pct)
            
            running_pnl += pnl
            peak = max(peak, running_pnl)
            dd = peak - running_pnl
            max_dd = max(max_dd, dd)
            
            total_pnl += pnl
            if pnl > 0:
                wins += 1
            else:
                losses += 1
        
        n = wins + losses
        wr = (wins / n * 100) if n > 0 else 0
        avg = total_pnl / n if n > 0 else 0
        
        scenarios[name] = {
            "trades": n,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wr, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg, 2),
            "max_drawdown": round(max_dd, 2),
            "profit_factor": round(abs(total_pnl / max_dd), 2) if max_dd > 0 else float('inf'),
            "grade": _grade_pnl(total_pnl, max_dd, wr),
        }
    
    return scenarios


def simulate_trade_pnl(trade: dict, sl_pct: Optional[float], tp_pct: Optional[float]) -> float:
    """
    Simulate what P&L would have been with different SL/TP.
    Uses a heuristic based on actual outcome and position size.
    """
    actual_pnl = trade.get("pnl_realized", 0)
    actual_sl = trade.get("stop_loss_pct", 0.05)
    actual_tp = trade.get("take_profit_pct", 0.08)
    position_size = trade.get("position_size_usd", 1000)
    direction = trade.get("direction", "BUY")
    entry = trade.get("entry_price", 0)
    
    if entry == 0 or position_size == 0:
        return actual_pnl
    
    # If actual trade was a win, assume price reached at least actual TP
    # If new TP is wider, we might have made more (but not guaranteed)
    # If new SL is tighter, we might have been stopped out earlier
    
    if actual_pnl > 0:
        # Was a win — assume it hit actual TP
        # If new TP is wider, give 50% chance of reaching it
        # If new SL is tighter AND price dipped before hitting TP, might have lost
        new_tp = tp_pct or actual_tp
        if new_tp > actual_tp:
            # More ambitious target — might not have been reached
            # Assume 70% chance of hitting wider target
            if hash(trade.get("id", "")) % 10 < 7:
                return position_size * new_tp
            else:
                return actual_pnl  # Still hit original TP
        else:
            return position_size * new_tp  # Tighter TP = less profit
    else:
        # Was a loss — assume it hit actual SL
        new_sl = sl_pct or actual_sl
        if new_sl < actual_sl:
            # Tighter stop = smaller loss
            return -position_size * new_sl
        else:
            # Wider stop = potentially bigger loss
            return -position_size * new_sl
    
    return actual_pnl


def backtest_position_sizing(trades: List[dict]) -> Dict[str, dict]:
    """
    Test different position sizing strategies.
    """
    configs = [
        ("fixed_1k", lambda t: 1000),
        ("fixed_2k", lambda t: 2000),
        ("fixed_500", lambda t: 500),
        ("confidence_weighted", lambda t: 500 + t.get("confidence_score", 0.5) * 1500),
        ("kelly_half", lambda t: _kelly_size(t, 0.5)),
    ]
    
    results = {}
    for name, sizing_fn in configs:
        wins = losses = total_pnl = max_dd = 0
        running = peak = 0
        
        for t in trades:
            size = sizing_fn(t)
            # Scale actual P&L by position size ratio
            actual_size = t.get("position_size_usd", 1000)
            ratio = size / actual_size if actual_size > 0 else 1
            pnl = t.get("pnl_realized", 0) * ratio
            
            running += pnl
            peak = max(peak, running)
            max_dd = max(max_dd, peak - running)
            total_pnl += pnl
            if pnl > 0:
                wins += 1
            else:
                losses += 1
        
        n = wins + losses
        wr = (wins / n * 100) if n > 0 else 0
        results[name] = {
            "trades": n,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wr, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / n, 2) if n > 0 else 0,
            "max_drawdown": round(max_dd, 2),
            "grade": _grade_pnl(total_pnl, max_dd, wr),
        }
    
    return results


def _kelly_size(trade: dict, fraction: float = 0.5) -> float:
    """
    Kelly criterion position sizing.
    f* = (bp - q) / b where b=avg win, p=win rate, q=lose rate
    We use historical data from the trade's own signal source.
    """
    # Simplified: use confidence score as proxy for edge
    confidence = trade.get("confidence_score", 0.5)
    # Assume 1:1.5 reward/risk
    b = 1.5
    p = confidence
    q = 1 - p
    kelly = (b * p - q) / b if b > 0 else 0
    kelly = max(0, min(kelly, 0.25))  # Cap at 25%
    return 10000 * kelly * fraction  # Half-Kelly


def backtest_confidence_thresholds(trades: List[dict]) -> Dict[str, dict]:
    """
    Test what happens if we only take trades above certain confidence thresholds.
    """
    thresholds = [0.0, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9]
    results = {}
    
    for threshold in thresholds:
        filtered = [t for t in trades if t.get("confidence_score", 0) >= threshold]
        if len(filtered) < 3:
            continue
        
        wins = sum(1 for t in filtered if t.get("pnl_realized", 0) > 0)
        losses = len(filtered) - wins
        total_pnl = sum(t.get("pnl_realized", 0) for t in filtered)
        wr = (wins / len(filtered) * 100) if filtered else 0
        
        results[f"min_{threshold}"] = {
            "trades": len(filtered),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wr, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / len(filtered), 2) if filtered else 0,
            "grade": _grade_pnl(total_pnl, 0, wr),
        }
    
    return results


def _grade_pnl(pnl: float, max_dd: float, wr: float) -> str:
    """Grade a strategy scenario."""
    score = 0
    if pnl > 0: score += 30
    if pnl > 100: score += 20
    if wr > 50: score += 20
    if wr > 60: score += 10
    if max_dd < pnl * 2: score += 20
    
    if score >= 80: return "A"
    if score >= 60: return "B"
    if score >= 40: return "C"
    if score >= 20: return "D"
    return "F"


# ─── Report Generation ──────────────────────────────────────────────────────────

def generate_report(sl_scenarios: dict, sizing_scenarios: dict, confidence_scenarios: dict) -> str:
    """Generate markdown report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# 🧪 QuantAlpha Strategy Backtest Report",
        f"**Generated:** {now} | **Trades analyzed:** {list(sl_scenarios.values())[0]['trades'] if sl_scenarios else 0}\n",
        "## SL/TP Strategy Comparison\n",
        "| Strategy | Trades | Win Rate | Total P&L | Max DD | Grade |",
        "|----------|--------|----------|-----------|--------|-------|",
    ]
    
    for name, data in sorted(sl_scenarios.items(), key=lambda x: x[1]["total_pnl"], reverse=True):
        lines.append(
            f"| {name:20} | {data['trades']:4} | {data['win_rate']:5.1f}% | "
            f"${data['total_pnl']:+.2f} | ${data['max_drawdown']:.2f} | {data['grade']} |"
        )
    
    lines.append("\n## Position Sizing Comparison\n")
    lines.append("| Strategy | Trades | Win Rate | Total P&L | Max DD | Grade |")
    lines.append("|----------|--------|----------|-----------|--------|-------|")
    
    for name, data in sorted(sizing_scenarios.items(), key=lambda x: x[1]["total_pnl"], reverse=True):
        lines.append(
            f"| {name:20} | {data['trades']:4} | {data['win_rate']:5.1f}% | "
            f"${data['total_pnl']:+.2f} | ${data['max_drawdown']:.2f} | {data['grade']} |"
        )
    
    lines.append("\n## Confidence Threshold Analysis\n")
    lines.append("| Min Confidence | Trades Taken | Win Rate | Total P&L | Avg P&L | Grade |")
    lines.append("|----------------|-------------|----------|-----------|---------|-------|")
    
    for name, data in sorted(confidence_scenarios.items(), key=lambda x: float(x[0].split('_')[1])):
        lines.append(
            f"| {name:14} | {data['trades']:11} | {data['win_rate']:5.1f}% | "
            f"${data['total_pnl']:+.2f} | ${data['avg_pnl']:+.2f} | {data['grade']} |"
        )
    
    # Best recommendation
    if sl_scenarios:
        best_sl = max(sl_scenarios.items(), key=lambda x: x[1]["total_pnl"])
        best_conf = max(confidence_scenarios.items(), key=lambda x: x[1]["total_pnl"]) if confidence_scenarios else (None, None)
        
        lines.append("\n## 💡 Recommendations")
        lines.append(f"**Best SL/TP config:** `{best_sl[0]}` — ${best_sl[1]['total_pnl']:+.2f} total P&L")
        if best_conf and best_conf[0]:
            lines.append(f"**Best confidence filter:** `{best_conf[0]}` — {best_conf[1]['win_rate']:.1f}% win rate")
        lines.append("\n*Note: These are simulations based on historical trades. Past performance does not guarantee future results.*")
    
    lines.append("\n---\n*QuantAlpha Strategy Backtest — auto-generated from paper trading history*")
    return "\n".join(lines)


# ─── Persistence ────────────────────────────────────────────────────────────────

def save_report(report: str):
    os.makedirs(REPORT_DIR, exist_ok=True)
    date_str = datetime.now(timezone.utc).date().isoformat()
    path = f"{REPORT_DIR}/strategy_backtest_{date_str}.md"
    with open(path, "w") as f:
        f.write(report)
    return path


# ─── Main ───────────────────────────────────────────────────────────────────────

def main(output: str = "md") -> str:
    print("=== QuantAlpha Strategy Backtester ===\n")
    
    trades = load_closed_trades()
    print(f"Loaded {len(trades)} closed trades")
    
    if len(trades) < 5:
        msg = "⚠️ Insufficient trade history for meaningful backtesting (need 5+ closed trades)"
        print(msg)
        return msg
    
    # Run backtests
    print("\nRunning SL/TP variations...")
    sl_results = backtest_sl_tp_variations(trades)
    
    print("Running position sizing scenarios...")
    sizing_results = backtest_position_sizing(trades)
    
    print("Running confidence thresholds...")
    conf_results = backtest_confidence_thresholds(trades)
    
    # Generate report
    report = generate_report(sl_results, sizing_results, conf_results)
    report_path = save_report(report)
    print(f"\nReport saved: {report_path}")
    
    if output == "md":
        print("\n" + report)
        return report
    else:
        return json.dumps({
            "sl_tp": sl_results,
            "sizing": sizing_results,
            "confidence": conf_results,
        }, indent=2)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", choices=["md", "json"], default="md")
    args = parser.parse_args()
    main(args.output)
