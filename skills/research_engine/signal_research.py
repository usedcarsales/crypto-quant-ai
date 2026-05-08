#!/usr/bin/env python3
"""
signal_research.py — Signal Alpha Research Engine
Phase 6 Innovation — QuantAlpha Signal Quality Scoring

Purpose:
  Analyze which signal sources (TA, OnChain, SmartMoney, DeFi, Social)
  actually produce alpha (excess returns). Generates weekly scorecards
  that feed back into correlation engine weights and can be sold as
  a data product ("QuantAlpha Signal Scores").

Revenue Model:
  - Internal: auto-tune correlation weights weekly
  - External: API endpoint returning source scores (future)
  - Content: Weekly "Alpha Report" posted to Discord/Moltbook

Usage:
  python skills/research_engine/signal_research.py [--weeks N] [--output md|json]
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

# ─── State Files ────────────────────────────────────────────────────────────────

TRADE_JOURNAL  = "/tmp/crypto-quant-trade-journal.json"
SIGNAL_HISTORY = "/tmp/crypto-quant-signal-history.json"
WEIGHTS_FILE   = "/tmp/crypto-quant-ai/config/correlation_weights.json"
REPORT_DIR     = "/tmp/crypto-quant-ai/reports"

# ─── Data Loading ───────────────────────────────────────────────────────────────

def load_trade_journal() -> dict:
    """Load closed + open trades from paper trading journal."""
    if not os.path.exists(TRADE_JOURNAL):
        return {"trades": [], "closed_trades": []}
    with open(TRADE_JOURNAL) as f:
        return json.load(f)


def load_signal_history() -> dict:
    """Load signal history with source annotations."""
    if not os.path.exists(SIGNAL_HISTORY):
        return {"signals": []}
    with open(SIGNAL_HISTORY) as f:
        return json.load(f)


# ─── Trade-Signal Matching ──────────────────────────────────────────────────────

def match_signals_to_trades(signals: List[dict], trades: List[dict]) -> List[dict]:
    """
    Match each trade to the signal that generated it.
    Returns enriched trades with signal_source info.
    """
    # Index signals by (coin, direction, entry_time_approx)
    sig_index = defaultdict(list)
    for s in signals:
        key = (s.get("coin"), s.get("direction"))
        sig_index[key].append(s)

    enriched = []
    for t in trades:
        coin = t.get("coin")
        direction = t.get("direction")
        entry_time = t.get("entered_at", "")

        # Find matching signal within 1 hour of entry
        candidates = sig_index.get((coin, direction), [])
        matched = None
        for c in candidates:
            sig_time = c.get("timestamp", "")
            if entry_time and sig_time:
                try:
                    dt_entry = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                    dt_sig = datetime.fromisoformat(sig_time.replace("Z", "+00:00"))
                    if abs((dt_entry - dt_sig).total_seconds()) < 3600:
                        matched = c
                        break
                except Exception:
                    continue

        enriched.append({
            **t,
            "signal_source": matched.get("source", "composite") if matched else "unknown",
            "signal_score": matched.get("composite_score", 0) if matched else 0,
            "signal_confidence": matched.get("confidence_score", 0) if matched else 0,
        })

    return enriched


# ─── Alpha Calculations ─────────────────────────────────────────────────────────

def calc_source_alpha(enriched_trades: List[dict]) -> Dict[str, dict]:
    """
    Calculate alpha per signal source.
    Alpha = avg P&L of trades from that source minus avg P&L of all trades.
    """
    if not enriched_trades:
        return {}

    all_pnls = [t.get("pnl_realized", 0) for t in enriched_trades if t.get("status") == "CLOSED"]
    baseline = sum(all_pnls) / len(all_pnls) if all_pnls else 0

    source_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "pnl_sum": 0, "pnl_list": []})

    for t in enriched_trades:
        if t.get("status") != "CLOSED":
            continue
        src = t.get("signal_source", "unknown")
        pnl = t.get("pnl_realized", 0)
        source_stats[src]["trades"] += 1
        source_stats[src]["pnl_sum"] += pnl
        source_stats[src]["pnl_list"].append(pnl)
        if pnl > 0:
            source_stats[src]["wins"] += 1
        else:
            source_stats[src]["losses"] += 1

    results = {}
    for src, stats in source_stats.items():
        n = stats["trades"]
        if n < 3:
            continue  # insufficient data
        avg_pnl = stats["pnl_sum"] / n
        alpha = avg_pnl - baseline
        wr = stats["wins"] / n * 100
        # Sharpe-ish: avg / std (annualized approximation)
        std = _std(stats["pnl_list"])
        sharpe = (avg_pnl / std * (n ** 0.5)) if std > 0 else 0

        # Quality score 0-100
        score = min(100, max(0, (
            wr * 0.4 +                    # win rate weight
            (avg_pnl + 20) * 2 * 0.3 +   # avg pnl normalized (-10 to +10)
            sharpe * 10 * 0.2 +           # sharpe scaled
            min(n, 20) * 2.5 * 0.1        # sample size
        )))

        results[src] = {
            "trades": n,
            "wins": stats["wins"],
            "losses": stats["losses"],
            "win_rate_pct": round(wr, 1),
            "avg_pnl_usd": round(avg_pnl, 2),
            "alpha_usd": round(alpha, 2),
            "sharpe": round(sharpe, 2),
            "quality_score": round(score, 1),
            "grade": _grade(score),
        }

    return results


def _std(values: List[float]) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return variance ** 0.5


def _grade(score: float) -> str:
    if score >= 80: return "A"
    if score >= 65: return "B"
    if score >= 50: return "C"
    if score >= 35: return "D"
    return "F"


# ─── Weight Auto-Tuning ────────────────────────────────────────────────────────

def auto_tune_weights(source_scores: Dict[str, dict], current_weights: Optional[dict] = None) -> dict:
    """
    Adjust correlation engine weights based on source quality scores.
    Higher quality = higher weight. Normalize to sum 100.
    """
    default_weights = {
        "ta": 35, "onchain": 20, "smart_money": 20,
        "defi": 15, "social": 10,
    }
    weights = current_weights or default_weights

    # Map source names to weight keys
    mapping = {
        "composite": "ta",  # composite is mostly TA-weighted
        "ta": "ta",
        "onchain": "onchain",
        "smart_money": "smart_money",
        "whale": "smart_money",
        "defi": "defi",
        "social": "social",
        "sentiment": "social",
    }

    # Quality multipliers
    multipliers = {}
    for src, data in source_scores.items():
        key = mapping.get(src, "ta")
        # Score 50 = neutral (1.0x), 100 = 1.5x, 0 = 0.5x
        mult = 0.5 + (data["quality_score"] / 100)
        multipliers[key] = max(multipliers.get(key, 0), mult)

    # Apply multipliers
    new_weights = {}
    for key, base in weights.items():
        new_weights[key] = base * multipliers.get(key, 1.0)

    # Normalize to 100
    total = sum(new_weights.values())
    if total > 0:
        new_weights = {k: round(v / total * 100, 1) for k, v in new_weights.items()}

    return new_weights


# ─── Report Generation ──────────────────────────────────────────────────────────

def generate_report(source_scores: Dict[str, dict], new_weights: dict, lookback_weeks: int = 2) -> str:
    """Generate markdown report for Discord/Moltbook."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# 📊 QuantAlpha Signal Research Report",
        f"**Generated:** {now} | **Lookback:** {lookback_weeks} weeks\n",
        "## Source Quality Scores\n",
        "| Source | Trades | Win Rate | Avg P&L | Alpha | Sharpe | Score | Grade |",
        "|--------|--------|----------|---------|-------|--------|-------|-------|",
    ]

    for src, data in sorted(source_scores.items(), key=lambda x: x[1]["quality_score"], reverse=True):
        alpha_sign = "+" if data["alpha_usd"] >= 0 else ""
        lines.append(
            f"| {src:12} | {data['trades']:4} | {data['win_rate_pct']:5.1f}% | "
            f"${data['avg_pnl_usd']:+.2f} | {alpha_sign}${data['alpha_usd']:.2f} | "
            f"{data['sharpe']:5.2f} | {data['quality_score']:5.1f} | {data['grade']} |"
        )

    lines.append("\n## Recommended Correlation Weights\n")
    for key, val in new_weights.items():
        lines.append(f"- **{key}:** {val}%")

    # Actionable insight
    best = max(source_scores.items(), key=lambda x: x[1]["quality_score"]) if source_scores else (None, None)
    worst = min(source_scores.items(), key=lambda x: x[1]["quality_score"]) if source_scores else (None, None)

    if best and worst and best[0] != worst[0]:
        lines.append(f"\n## 💡 Insight")
        lines.append(f"**Boost {best[0]}** (score {best[1]['quality_score']:.1f}) — strongest alpha generator.")
        lines.append(f"**Review {worst[0]}** (score {worst[1]['quality_score']:.1f}) — may need recalibration.")

    lines.append("\n---")
    lines.append("*QuantAlpha Signal Research — auto-generated from paper trading history*")

    return "\n".join(lines)


# ─── Persistence ────────────────────────────────────────────────────────────────

def save_weights(weights: dict):
    """Save tuned weights to config file."""
    os.makedirs(os.path.dirname(WEIGHTS_FILE), exist_ok=True)
    with open(WEIGHTS_FILE, "w") as f:
        json.dump(weights, f, indent=2)


def save_report(report: str, suffix: str = "alpha"):
    """Save report to reports directory."""
    os.makedirs(REPORT_DIR, exist_ok=True)
    date_str = datetime.now(timezone.utc).date().isoformat()
    path = f"{REPORT_DIR}/signal_research_{suffix}_{date_str}.md"
    with open(path, "w") as f:
        f.write(report)
    return path


# ─── Main ───────────────────────────────────────────────────────────────────────

def main(lookback_weeks: int = 2, output: str = "md") -> str:
    print(f"=== QuantAlpha Signal Research ===")
    print(f"Lookback: {lookback_weeks} weeks | Output: {output}\n")

    # Load data
    journal = load_trade_journal()
    all_trades = journal.get("trades", []) + journal.get("closed_trades", [])
    history = load_signal_history()
    signals = history.get("signals", [])

    print(f"Loaded {len(signals)} signals, {len(all_trades)} trades")

    if len(all_trades) < 5:
        msg = "⚠️ Insufficient trade history for meaningful analysis (need 5+ closed trades)"
        print(msg)
        return msg

    # Enrich trades with signal source
    enriched = match_signals_to_trades(signals, all_trades)

    # Calculate alpha per source
    scores = calc_source_alpha(enriched)
    if not scores:
        msg = "⚠️ No source has 3+ trades — need more data"
        print(msg)
        return msg

    # Auto-tune weights
    current_weights = None
    if os.path.exists(WEIGHTS_FILE):
        with open(WEIGHTS_FILE) as f:
            current_weights = json.load(f)

    new_weights = auto_tune_weights(scores, current_weights)
    save_weights(new_weights)
    print(f"Weights tuned: {json.dumps(new_weights)}")

    # Generate report
    report = generate_report(scores, new_weights, lookback_weeks)
    report_path = save_report(report)
    print(f"Report saved: {report_path}")

    if output == "md":
        print("\n" + report)
        return report
    else:
        return json.dumps({"scores": scores, "weights": new_weights}, indent=2)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="QuantAlpha Signal Research")
    parser.add_argument("--weeks", type=int, default=2, help="Lookback weeks")
    parser.add_argument("--output", choices=["md", "json"], default="md", help="Output format")
    args = parser.parse_args()
    main(args.weeks, args.output)
