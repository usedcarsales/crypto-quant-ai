"""
Signal Refinement Loop — Phase 5, Task 5.5
Reads paper trade history, calculates rolling 7-day signal accuracy per source,
and auto-tunes weights in risk_policy.json.

Auto-tunes on daily paper trading cron cycle (9 AM ET).
Weight adjustments capped at ±5% per cycle.

Output: data/weight_adjustments.json
"""

import importlib.util as _spec
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional


# ─── Paths ───────────────────────────────────────────────────────────────────

RISK_POLICY_PATH      = "config/risk_policy.json"
PAPER_TRADES_PATH     = "data/paper_trades.json"
WEIGHT_ADJUSTMENTS    = "data/weight_adjustments.json"
SIGNAL_SOURCES        = ["ta", "onchain", "sentiment", "derivatives", "social"]


# ─── Config ───────────────────────────────────────────────────────────────────

WEIGHT_CHANGE_CAP    = 0.05   # ±5% max per cycle
ACCURACY_LOW         = 0.40   # <40% → reduce weight
ACCURACY_HIGH        = 0.60   # >60% → increase weight
LOOKBACK_DAYS        = 7
MIN_TRADES_FOR_ADJUST = 3    # need at least 3 trades to act on a source


# ─── Load Helpers ─────────────────────────────────────────────────────────────

def _load_json(path: str):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_json(path: str, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ─── Load Dependencies ─────────────────────────────────────────────────────────

def _load_mod(name, path):
    s = _spec.spec_from_file_location(name, path)
    m = _spec.module_from_spec(s)
    s.loader.exec_module(m)
    return m

RISK_MOD  = _load_mod("risk",  "skills/signal_engine/risk_manager.py")


# ─── Load Paper Trades ─────────────────────────────────────────────────────────

def load_paper_trades() -> list:
    """Load all paper trades from data/paper_trades.json."""
    data = _load_json(PAPER_TRADES_PATH)
    trades = data.get("trades", []) if isinstance(data, dict) else data
    if not isinstance(trades, list):
        trades = []
    return trades


def get_trades_in_window(trades: list, days: int = 7) -> list:
    """Filter trades within the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ts = cutoff.isoformat()
    return [t for t in trades if t.get("closed_at", "") >= cutoff_ts]


# ─── Signal Accuracy Calculation ───────────────────────────────────────────────

def get_signal_source(trade: dict) -> str:
    """Extract primary signal source from a trade."""
    return trade.get("signal_source", "unknown").lower()


def was_profitable(trade: dict) -> Optional[bool]:
    """Returns True if trade was profitable, False if not, None if inconclusive."""
    pnl = trade.get("pnl", None)
    if pnl is None:
        return None
    return pnl > 0


def calc_source_accuracy(trades: list, source: str) -> dict:
    """
    Calculate accuracy for a specific signal source over the trade window.

    Returns: {
        source, trades_count, wins, losses,
        accuracy_pct, avg_pnl, weighted_accuracy
    }
    """
    source_trades = [t for t in trades if get_signal_source(t) == source]

    if len(source_trades) < MIN_TRADES_FOR_ADJUST:
        return {
            "source":       source,
            "trades_count": len(source_trades),
            "wins":         0,
            "losses":       0,
            "accuracy_pct": None,
            "avg_pnl":      0,
            "weighted_accuracy": None,
            "reason":       f"Only {len(source_trades)} trades (min {MIN_TRADES_FOR_ADJUST})",
        }

    wins   = sum(1 for t in source_trades if was_profitable(t) is True)
    losses = sum(1 for t in source_trades if was_profitable(t) is False)
    total  = wins + losses

    if total == 0:
        return {"source": source, "trades_count": len(source_trades),
                "accuracy_pct": None, "reason": "No closed trades"}

    accuracy = wins / total

    # Weighted accuracy: more recent trades count more
    # Simple: weight by recency within window (1.0 for most recent, 0.5 for oldest)
    weighted = 0
    n = len(source_trades)
    total_weight = sum(0.5 + 0.5 * (i / max(n - 1, 1)) for i in range(n))
    weighted = 0
    for i, t in enumerate(sorted(source_trades, key=lambda x: x.get("closed_at", ""), reverse=True)):
        w = 0.5 + 0.5 * (i / max(n - 1, 1))
        if was_profitable(t):
            weighted += w

    weighted_accuracy = weighted / total_weight if total_weight else 0

    avg_pnl = sum(t.get("pnl", 0) for t in source_trades) / len(source_trades)

    return {
        "source":            source,
        "trades_count":      len(source_trades),
        "wins":              wins,
        "losses":            losses,
        "accuracy_pct":      round(accuracy * 100, 1),
        "avg_pnl":           round(avg_pnl, 2),
        "weighted_accuracy": round(weighted_accuracy * 100, 1),
        "reason":            None,
    }


def calc_all_source_accuracies(trades: list, days: int = 7) -> dict:
    """Calculate accuracy for all signal sources."""
    window_trades = get_trades_in_window(trades, days)
    results = {}
    for src in SIGNAL_SOURCES:
        results[src] = calc_source_accuracy(window_trades, src)
    return results


# ─── Weight Adjustment Logic ───────────────────────────────────────────────────

def calc_new_weight(current_weight: float, accuracy: float, direction: str) -> float:
    """
    Calculate new weight for a signal source.
    direction: "increase" or "decrease"
    Capped at ±WEIGHT_CHANGE_CAP per cycle.
    """
    change = WEIGHT_CHANGE_CAP

    if direction == "increase":
        # Proportional: better accuracy → bigger bump, capped at 5%
        bonus = change * ((accuracy - ACCURACY_HIGH) / (1.0 - ACCURACY_HIGH))
        new_weight = current_weight + max(min(bonus, change), 0.005)  # at least 0.5%
    else:
        penalty = change * ((ACCURACY_LOW - accuracy) / ACCURACY_LOW)
        new_weight = current_weight - max(min(penalty, change), 0.005)

    # Clamp to reasonable bounds
    return round(max(0.01, min(0.95, new_weight)), 4)


def determine_adjustment(src: str, current_weight: float, stats: dict) -> Optional[dict]:
    """Determine if a weight should be adjusted based on accuracy stats."""
    acc = stats.get("accuracy_pct")
    if acc is None:
        return None  # not enough data

    acc_frac = acc / 100.0

    if acc_frac < ACCURACY_LOW:
        direction = "decrease"
        reason = f"Accuracy {acc}% < {ACCURACY_LOW*100}% threshold"
    elif acc_frac > ACCURACY_HIGH:
        direction = "increase"
        reason = f"Accuracy {acc}% > {ACCURACY_HIGH*100}% threshold"
    else:
        return None  # no adjustment needed

    new_weight = calc_new_weight(current_weight, acc_frac, direction)

    # No change if rounding makes it same
    if abs(new_weight - current_weight) < 0.0001:
        return None

    return {
        "date":               datetime.now(timezone.utc).date().isoformat(),
        "source":             src,
        "old_weight":         round(current_weight, 4),
        "new_weight":         new_weight,
        "accuracy_7d_pct":    acc,
        "weighted_accuracy_7d_pct": stats.get("weighted_accuracy_pct"),
        "trades_7d":          stats.get("trades_count", 0),
        "wins_7d":            stats.get("wins", 0),
        "losses_7d":         stats.get("losses", 0),
        "avg_pnl_7d":        stats.get("avg_pnl", 0),
        "adjustment_pct":    round((new_weight - current_weight) * 100, 3),
        "direction":         direction,
        "adjustment_reason": reason,
        "timestamp":          datetime.now(timezone.utc).isoformat(),
    }


# ─── Main Refinement Loop ──────────────────────────────────────────────────────

def run_refinement_loop() -> dict:
    """
    Main entry point. Reads paper trades, calculates accuracies,
    adjusts weights in risk_policy.json, logs changes.

    Returns: {adjustments, accuracies, trades_analyzed, date}
    """
    print("=== Signal Refinement Loop ===\n")
    t0 = datetime.now(timezone.utc)

    # ── 1. Load data ──────────────────────────────────────────────────────────
    trades      = load_paper_trades()
    risk_policy = _load_json(RISK_POLICY_PATH)
    adjustments_log = _load_json(WEIGHT_ADJUSTMENTS)

    all_trades = trades if isinstance(trades, list) else []
    window_trades = get_trades_in_window(all_trades, LOOKBACK_DAYS)

    print(f"  Paper trades total: {len(all_trades)}")
    print(f"  Trades in {LOOKBACK_DAYS}-day window: {len(window_trades)}")

    # ── 2. Calculate accuracies ────────────────────────────────────────────────
    accuracies = calc_all_source_accuracies(all_trades, LOOKBACK_DAYS)

    print("\n  Signal source accuracies (7-day window):")
    for src, stats in accuracies.items():
        acc = stats.get("accuracy_pct")
        cnt = stats.get("trades_count", 0)
        if acc is not None:
            bar = "█" * int(acc / 5) + "░" * (20 - int(acc / 5))
            flag = "🔴" if acc < ACCURACY_LOW*100 else "🟢" if acc > ACCURACY_HIGH*100 else "🟡"
            print(f"    {flag} {src:<12s} {acc:>5.1f}% [{bar}] ({cnt} trades)")
        else:
            print(f"    ⚪ {src:<12s} {stats['reason']}")

    # ── 3. Load current weights from risk_policy ──────────────────────────────
    weights = risk_policy.get("signal_weights", {})

    # ── 4. Determine and apply adjustments ───────────────────────────────────
    adjustments = []
    for src in SIGNAL_SOURCES:
        current_weight = weights.get(src, 0.20)  # default 20%
        stats = accuracies.get(src, {})
        adj = determine_adjustment(src, current_weight, stats)
        if adj:
            adjustments.append(adj)

    # ── 5. Apply weight changes ───────────────────────────────────────────────
    for adj in adjustments:
        src = adj["source"]
        weights[src] = adj["new_weight"]

    risk_policy["signal_weights"] = weights
    _save_json(RISK_POLICY_PATH, risk_policy)

    # ── 6. Log to weight_adjustments.json ────────────────────────────────────
    if adjustments:
        if "adjustments" not in adjustments_log:
            adjustments_log["adjustments"] = []
        adjustments_log["adjustments"].extend(adjustments)
        _save_json(WEIGHT_ADJUSTMENTS, adjustments_log)

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()

    return {
        "date":               datetime.now(timezone.utc).date().isoformat(),
        "timestamp":          datetime.now(timezone.utc).isoformat(),
        "trades_analyzed":    len(window_trades),
        "total_trades":       len(all_trades),
        "lookback_days":      LOOKBACK_DAYS,
        "accuracies":         accuracies,
        "adjustments":        adjustments,
        "weights_after":      weights,
        "elapsed_sec":        round(elapsed, 2),
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = run_refinement_loop()

    print("\n=== Refinement Result ===\n")

    if not result["adjustments"]:
        print("  No weight adjustments this cycle.\n")
    else:
        print(f"  {len(result['adjustments'])} adjustment(s) applied:\n")
        for adj in result["adjustments"]:
            emoji = "⬆️" if adj["direction"] == "increase" else "⬇️"
            print(
                f"  {emoji} {adj['source']:<12s} "
                f"{adj['old_weight']*100:.1f}% → {adj['new_weight']*100:.1f}% "
                f"({adj['adjustment_pct']:+.2f}%) "
                f"[{adj['accuracy_7d_pct']}% WR, {adj['trades_7d']} trades]"
            )
            print(f"     Reason: {adj['adjustment_reason']}")

    print(f"\n  Weights after adjustment:")
    for src, w in result["weights_after"].items():
        print(f"    {src:<12s} {w*100:.1f}%")

    print(f"\n  Adjustments logged to: {WEIGHT_ADJUSTMENTS}")
    print(f"  Risk policy updated:   {RISK_POLICY_PATH}")
    print(f"\n✅ Refinement loop done in {result['elapsed_sec']}s")