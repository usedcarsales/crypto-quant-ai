"""
Performance Dashboard
Phase 4, Task 4.5 — Read-only analytics from the trade journal and daily summaries.

Displays:
  - Portfolio performance (total P&L, win rate, Sharpe, max drawdown)
  - Per-coin breakdown
  - Signal quality analysis (which signal sources perform best)
  - Trade history with full P&L timeline
  - Daily equity curve

Usage:
  python performance_dashboard.py              # full report
  python performance_dashboard.py --coins      # per-coin breakdown
  python performance_dashboard.py --equity     # equity curve data
  python performance_dashboard.py --signals     # signal source analysis
"""

import json
import math
import os
import sys
from datetime import datetime, timezone


# ─── File Paths ────────────────────────────────────────────────────────────────

PORTFOLIO_FILE   = "/tmp/crypto-quant-portfolio.json"
TRADE_JOURNAL    = "/tmp/crypto-quant-trade-journal.json"
DAILY_SUMMARIES  = "/tmp/crypto-quant-daily-summaries.json"
INITIAL_BALANCE  = 10_000.0


# ─── Data Loading ──────────────────────────────────────────────────────────────

def load_all():
    portfolio   = json.load(open(PORTFOLIO_FILE))   if os.path.exists(PORTFOLIO_FILE)   else {}
    journal     = json.load(open(TRADE_JOURNAL))     if os.path.exists(TRADE_JOURNAL)   else {}
    summaries   = json.load(open(DAILY_SUMMARIES))    if os.path.exists(DAILY_SUMMARIES) else []
    return portfolio, journal, summaries


def load_summaries():
    return json.load(open(DAILY_SUMMARIES)) if os.path.exists(DAILY_SUMMARIES) else []


def load_journal():
    return json.load(open(TRADE_JOURNAL)) if os.path.exists(TRADE_JOURNAL) else {}


def load_portfolio():
    return json.load(open(PORTFOLIO_FILE)) if os.path.exists(PORTFOLIO_FILE) else {}


# ─── Core Metrics ─────────────────────────────────────────────────────────────

def calc_all_metrics():
    """
    Calculate all performance metrics from trade journal + daily summaries.
    Returns a comprehensive metrics dict.
    """
    journal   = load_journal()
    summaries = load_summaries()
    portfolio = load_portfolio()

    all_trades   = journal.get("closed_trades", [])
    open_trades  = journal.get("trades", [])
    current_bal  = portfolio.get("current_usd", INITIAL_BALANCE)

    # ── Basic counts ────────────────────────────────────────────────────────
    total_trades    = len(all_trades)
    winning_trades  = [t for t in all_trades if float(t.get("pnl_realized", 0)) > 0]
    losing_trades   = [t for t in all_trades if float(t.get("pnl_realized", 0)) < 0]
    breakeven       = [t for t in all_trades if float(t.get("pnl_realized", 0)) == 0]
    win_count       = len(winning_trades)
    loss_count      = len(losing_trades)

    # ── P&L ────────────────────────────────────────────────────────────────
    total_pnl    = sum(float(t.get("pnl_realized", 0)) for t in all_trades)
    gross_profit = sum(float(t.get("pnl_realized", 0)) for t in winning_trades)
    gross_loss   = abs(sum(float(t.get("pnl_realized", 0)) for t in losing_trades))
    avg_win      = gross_profit / win_count if win_count else 0
    avg_loss     = gross_loss  / loss_count if loss_count else 0
    win_rate     = win_count  / total_trades * 100 if total_trades else 0
    loss_rate    = loss_count / total_trades * 100 if total_trades else 0
    profit_factor = gross_profit / gross_loss if gross_loss else 0

    # ── Return metrics ─────────────────────────────────────────────────────
    total_return_pct = (current_bal - INITIAL_BALANCE) / INITIAL_BALANCE * 100
    annualized_trades = total_trades / max(len(summaries), 1) * 365 if summaries else 0

    # ── Risk metrics ───────────────────────────────────────────────────────
    returns = [float(t.get("pnl_realized", 0)) / INITIAL_BALANCE for t in all_trades]
    mean_ret = sum(returns) / len(returns) if returns else 0
    std_ret  = math.sqrt(sum((r - mean_ret)**2 for r in returns) / max(len(returns)-1, 1)) if len(returns) > 1 else 0
    sharpe   = (mean_ret / std_ret * math.sqrt(365)) if std_ret > 0 else 0

    # Max drawdown
    peak    = INITIAL_BALANCE
    max_dd  = 0.0
    running = INITIAL_BALANCE
    for t in sorted(all_trades, key=lambda x: x.get("closed_at", "")):
        running += float(t.get("pnl_realized", 0))
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd
    max_dd_pct = max_dd / INITIAL_BALANCE * 100

    # ── Streak ────────────────────────────────────────────────────────────
    current_streak_wins = 0
    current_streak_losses = 0
    for t in reversed(all_trades):
        pnl = float(t.get("pnl_realized", 0))
        if pnl > 0:
            if current_streak_losses == 0:
                current_streak_wins += 1
            else:
                break
        elif pnl < 0:
            if current_streak_wins == 0:
                current_streak_losses += 1
            else:
                break

    # ── Expectancy ────────────────────────────────────────────────────────
    expectancy = (win_rate/100 * avg_win) - (loss_rate/100 * avg_loss) if total_trades else 0
    expectancy_per_trade = total_pnl / total_trades if total_trades else 0

    # ── Time in market ────────────────────────────────────────────────────
    # Approximate — sum of hours between entry and exit
    total_hours = 0
    for t in all_trades:
        try:
            entry = datetime.fromisoformat(t.get("entered_at", "2020-01-01"))
            exit_t = datetime.fromisoformat(t.get("closed_at", "2020-01-01"))
            total_hours += (exit_t - entry).total_seconds() / 3600
        except Exception:
            pass
    avg_hours_per_trade = total_hours / total_trades if total_trades else 0

    return {
        "portfolio_current_usd": round(current_bal, 2),
        "portfolio_initial_usd": INITIAL_BALANCE,
        "total_pnl_usd":        round(total_pnl, 2),
        "total_return_pct":     round(total_return_pct, 2),
        "total_trades":        total_trades,
        "open_trades":         len(open_trades),
        "win_count":           win_count,
        "loss_count":          loss_count,
        "breakeven_count":     len(breakeven),
        "win_rate_pct":        round(win_rate, 1),
        "loss_rate_pct":       round(loss_rate, 1),
        "gross_profit":        round(gross_profit, 2),
        "gross_loss":          round(gross_loss, 2),
        "avg_win_usd":        round(avg_win, 2),
        "avg_loss_usd":       round(avg_loss, 2),
        "profit_factor":       round(profit_factor, 2),
        "expectancy_per_trade": round(expectancy_per_trade, 2),
        "sharpe_ratio":        round(sharpe, 3),
        "max_drawdown_usd":   round(max_dd, 2),
        "max_drawdown_pct":   round(max_dd_pct, 2),
        "current_streak_wins":  current_streak_wins,
        "current_streak_losses": current_streak_losses,
        "avg_hours_per_trade": round(avg_hours_per_trade, 1),
        "days_active":        len(summaries),
    }


# ─── Per-Coin Breakdown ───────────────────────────────────────────────────────

def calc_per_coin():
    """Break down performance by coin."""
    journal = load_journal()
    all_trades = journal.get("closed_trades", [])

    by_coin = {}
    for t in all_trades:
        coin = t.get("coin", "UNKNOWN")
        if coin not in by_coin:
            by_coin[coin] = {"trades": [], "pnl": 0, "wins": 0, "losses": 0}
        by_coin[coin]["trades"].append(t)
        pnl = float(t.get("pnl_realized", 0))
        by_coin[coin]["pnl"] += pnl
        if pnl > 0:   by_coin[coin]["wins"]  += 1
        elif pnl < 0: by_coin[coin]["losses"] += 1

    results = []
    for coin, d in by_coin.items():
        trades = d["trades"]
        pnl    = d["pnl"]
        wins   = d["wins"]
        losses = d["losses"]
        total  = wins + losses
        results.append({
            "coin":           coin,
            "total_trades":   total,
            "wins":           wins,
            "losses":         losses,
            "win_rate_pct":   round(wins/total*100, 1) if total else 0,
            "total_pnl_usd":  round(pnl, 2),
            "avg_pnl_usd":    round(pnl/total, 2) if total else 0,
            "best_trade":     round(max(float(t.get("pnl_realized", 0)) for t in trades), 2) if trades else 0,
            "worst_trade":    round(min(float(t.get("pnl_realized", 0)) for t in trades), 2) if trades else 0,
        })

    results.sort(key=lambda x: x["total_pnl_usd"], reverse=True)
    return results


# ─── Signal Source Analysis ───────────────────────────────────────────────────

def calc_signal_source_performance():
    """
    Which signal source (STRONG/MODERATE) produces the best results.
    """
    journal = load_journal()
    all_trades = journal.get("closed_trades", [])

    by_type = {}
    for t in all_trades:
        st = t.get("signal_type", "UNKNOWN")
        if st not in by_type:
            by_type[st] = {"trades": [], "pnl": 0}
        by_type[st]["trades"].append(t)
        by_type[st]["pnl"] += float(t.get("pnl_realized", 0))

    results = []
    for sig_type, d in by_type.items():
        trades = d["trades"]
        pnl    = d["pnl"]
        wins   = sum(1 for t in trades if float(t.get("pnl_realized", 0)) > 0)
        results.append({
            "signal_type":     sig_type,
            "total_trades":    len(trades),
            "wins":            wins,
            "losses":          len(trades) - wins,
            "win_rate_pct":    round(wins/len(trades)*100, 1) if trades else 0,
            "total_pnl_usd":   round(pnl, 2),
            "avg_pnl_usd":     round(pnl/len(trades), 2) if trades else 0,
        })

    results.sort(key=lambda x: x["avg_pnl_usd"], reverse=True)
    return results


# ─── Equity Curve ─────────────────────────────────────────────────────────────

def get_equity_curve():
    """
    Return equity curve as list of {date, balance} from daily summaries.
    """
    summaries = load_summaries()
    if not summaries:
        return [{"date": datetime.now(timezone.utc).date().isoformat(),
                 "balance": INITIAL_BALANCE}]

    curve = [{"date": INITIAL_BALANCE, "balance": INITIAL_BALANCE}]
    running = INITIAL_BALANCE
    for s in sorted(summaries, key=lambda x: x.get("date", "")):
        running = s.get("ending_balance", running)
        curve.append({"date": s.get("date"), "balance": round(running, 2)})

    return curve[1:]  # remove the placeholder first entry


# ─── Formatting ───────────────────────────────────────────────────────────────

def format_metrics(m: dict) -> str:
    """Format core metrics as a readable report."""

    # Win/loss bar
    wr = m["win_rate_pct"]
    bar_len = 20
    win_bar  = "█" * int(wr / 100 * bar_len)
    loss_bar = "░" * (bar_len - len(win_bar))

    pnl_emoji = "🟢" if m["total_pnl_usd"] >= 0 else "🔴"

    lines = [
        "**📊 Performance Dashboard**\n",
        f"  Portfolio: ${m['portfolio_current_usd']:,.2f} "
        f"({'+' if m['total_pnl_usd'] >= 0 else ''}{m['total_pnl_usd']:.2f} / "
        f"{'+' if m['total_return_pct'] >= 0 else ''}{m['total_return_pct']:.2f}%)\n",

        f"  Trades: {m['total_trades']} closed | {m['open_trades']} open | "
        f"{m['days_active']} days active\n",

        f"  {pnl_emoji} P&L: ${m['total_pnl_usd']:+.2f} "
        f"| Gross: +${m['gross_profit']:.2f} / -${m['gross_loss']:.2f} "
        f"| PF: {m['profit_factor']:.2f}\n",

        f"  Win Rate: {m['win_rate_pct']:.1f}% [{win_bar}{loss_bar}] {m['loss_rate_pct']:.1f}% Loss\n",
        f"  Avg Win: ${m['avg_win_usd']:+.2f} | Avg Loss: -${m['avg_loss_usd']:.2f} "
        f"| E/trade: ${m['expectancy_per_trade']:+.2f}\n",

        f"  Sharpe: {m['sharpe_ratio']:+.2f} | Max DD: -${m['max_drawdown_usd']:.2f} "
        f"(-{m['max_drawdown_pct']:.1f}%)\n",

        f"  Streak: 🟢 {m['current_streak_wins']}W / 🔴 {m['current_streak_losses']}L "
        f"| Avg hold: {m['avg_hours_per_trade']:.1f}h\n",
    ]
    return "".join(lines)


def format_per_coin(coins: list) -> str:
    """Per-coin breakdown table."""
    if not coins:
        return "  No closed trades yet.\n"

    lines = ["\n**Per-Coin Breakdown**\n"]
    lines.append(f"  {'Coin':<6} {'Trades':>6} {'WR%':>5} {'P&L':>10} {'Avg':>8} {'Best':>10} {'Worst':>10}")
    lines.append("  " + "-" * 60)
    for c in coins:
        emoji = "🟢" if c["total_pnl_usd"] >= 0 else "🔴"
        lines.append(
            f"  {emoji} {c['coin']:<6} {c['total_trades']:>6} {c['win_rate_pct']:>5.1f}% "
            f"${c['total_pnl_usd']:>+9.2f} ${c['avg_pnl_usd']:>+7.2f} "
            f"${c['best_trade']:>+9.2f} ${c['worst_trade']:>+9.2f}"
        )
    return "\n".join(lines)


def format_signal_sources(sources: list) -> str:
    """Signal source performance table."""
    if not sources:
        return "  No closed trades yet.\n"

    lines = ["\n**Signal Source Performance**\n"]
    lines.append(f"  {'Source':<12} {'Trades':>6} {'WR%':>5} {'P&L':>10} {'Avg/trade':>10}")
    lines.append("  " + "-" * 50)
    for s in sources:
        emoji = "🟢" if s["avg_pnl_usd"] >= 0 else "🔴"
        lines.append(
            f"  {emoji} {s['signal_type']:<12} {s['total_trades']:>6} "
            f"{s['win_rate_pct']:>5.1f}% ${s['total_pnl_usd']:>+9.2f} ${s['avg_pnl_usd']:>+8.2f}"
        )
    return "\n".join(lines)


def format_equity_curve(curve: list) -> str:
    """Simple text equity curve."""
    if not curve or len(curve) < 2:
        return "\n**Equity Curve:** Not enough data yet.\n"

    lines = ["\n**Equity Curve**\n"]
    start = curve[0]["balance"]
    current = curve[-1]["balance"]
    change_pct = (current - start) / start * 100
    emoji = "🟢" if change_pct >= 0 else "🔴"

    # Simple sparkline
    values = [c["balance"] for c in curve]
    min_v  = min(values)
    max_v  = max(values)
    range_v = max_v - min_v if max_v != min_v else 1

    for c in curve:
        bar_len = int((c["balance"] - min_v) / range_v * 20)
        bar = "▓" * bar_len + "░" * (20 - bar_len)
        lines.append(f"  {c['date']} |{bar}| ${c['balance']:,.2f}")

    lines.append(f"\n  {emoji} Net: {'+' if change_pct >= 0 else ''}{change_pct:.2f}% from start")
    return "\n".join(lines)


def format_trade_history(n: int = 10) -> str:
    """Last N trades in detail."""
    journal = load_journal()
    all_trades = sorted(journal.get("closed_trades", []),
                        key=lambda x: x.get("closed_at", ""), reverse=True)[:n]

    if not all_trades:
        return "\n**Trade History:** No closed trades yet.\n"

    lines = [f"\n**Last {min(n, len(all_trades))} Trades**\n"]
    for t in all_trades:
        emoji = "🟢" if float(t.get("pnl_realized", 0)) > 0 else "🔴"
        pnl   = float(t.get("pnl_realized", 0))
        exit_reason = t.get("exit_reason", "—")
        closed = t.get("closed_at", "—")[:16]

        lines.append(
            f"  {emoji} {t.get('coin')} {t.get('direction')} "
            f"@ ${t.get('entry_price', 0):,.2f} → ${t.get('exit_price', 0):,.2f} "
            f"| {exit_reason} | ${pnl:+.2f} | {closed}"
        )
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Performance Dashboard ===\n")

    args = sys.argv[1:] if len(sys.argv) > 1 else []

    if "--coins" in args:
        coins = calc_per_coin()
        print(format_per_coin(coins))
        print("\n✅ Dashboard loaded")

    elif "--equity" in args:
        curve = get_equity_curve()
        print(format_equity_curve(curve))
        print("\n✅ Dashboard loaded")

    elif "--signals" in args:
        sources = calc_signal_source_performance()
        print(format_signal_sources(sources))
        print("\n✅ Dashboard loaded")

    elif "--trades" in args:
        n = int(args[0]) if args and args[0].isdigit() else 10
        print(format_trade_history(n))
        print("\n✅ Dashboard loaded")

    else:
        # Full report
        m      = calc_all_metrics()
        coins  = calc_per_coin()
        srcs   = calc_signal_source_performance()
        curve  = get_equity_curve()

        print(format_metrics(m))
        print(format_per_coin(coins))
        print(format_signal_sources(srcs))
        print(format_equity_curve(curve))
        print(format_trade_history(5))
        print("\n✅ Dashboard loaded")

    print("\nUsage:")
    print("  python performance_dashboard.py           # full report")
    print("  python performance_dashboard.py --coins   # per-coin")
    print("  python performance_dashboard.py --equity  # equity curve")
    print("  python performance_dashboard.py --signals  # signal source analysis")
    print("  python performance_dashboard.py --trades   # trade history")