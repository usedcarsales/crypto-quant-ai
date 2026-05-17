#!/usr/bin/env python3
"""
Unified Check — Paper Trading Pipeline (replaces afternoon_check.py + evening_check.py)

Usage:
    python unified_check.py [afternoon|evening]

Defaults to "afternoon" if no arg passed.
"""

import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/home/vinny2times/.openclaw/workspace/quant-trading")

from skills.price_engine.coingecko import get_simple_price, get_trending
from skills.signal_generator.generator import generate_signals, format_signals, Direction
from skills.paper_trader.trader import PaperTrader
import requests

WATCHLIST = ["bitcoin", "ethereum", "solana", "binancecoin", "ripple", "dogecoin"]
WATCHLIST_SYMBOLS = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL",
    "binancecoin": "BNB", "ripple": "XRP", "dogecoin": "DOGE"
}

# Enable SHORT signals
ENABLE_SHORT = True


def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        d = r.json()["data"][0]
        return int(d["value"]), d["value_classification"]
    except Exception:
        return None, "Unknown"


def main(check_type="afternoon"):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    now_et = datetime.now().strftime("%Y-%m-%d %I:%M %p ET")
    check_label = check_type.capitalize()
    cron_id = {
        "afternoon": "3d038fad-233f-4839-9e57-925f2f000dfc",
        "evening": "f890f449-22eb-4fbe-acf1-d78ddd4c4cef"
    }.get(check_type, "unknown")

    prices = get_simple_price(WATCHLIST)
    trending_raw = get_trending()
    trending = [c["item"]["symbol"].upper() for c in trending_raw.get("coins", [])[:10]]
    fg_val, fg_label = get_fear_greed()

    # Save fear & greed
    fg_path = "/home/vinny2times/.openclaw/workspace/quant-trading/logs/last_fear_greed.json"
    try:
        with open(fg_path, "w") as f:
            json.dump({"value": fg_val or 50, "label": fg_label, "time": now}, f)
    except Exception:
        pass

    signals = generate_signals(prices, symbol_map=WATCHLIST_SYMBOLS, enable_short=ENABLE_SHORT)
    trader = PaperTrader()
    # Create price dict keyed by lowercase SYMBOL (matches position symbols)
    price_dict = {sym.lower(): prices.get(cid, {}).get("usd", 0)
                  for cid, sym in WATCHLIST_SYMBOLS.items()}
    cycle_result = trader.check_cycle(price_dict)

    new_trades = []
    for sig in signals:
        if sig.direction == Direction.BUY:
            pos = trader.open_position(sig.symbol.lower(), "LONG", sig.price)
            if pos:
                new_trades.append(pos)
        elif sig.direction == Direction.SELL and ENABLE_SHORT:
            pos = trader.open_position(sig.symbol.lower(), "SHORT", sig.price)
            if pos:
                new_trades.append(pos)

    stats = trader.get_stats()

    lines = []
    lines.append(f"# 📊 Paper Trading {check_label} Check — {now_et}")
    lines.append("")
    lines.append(f"- Cron ID: {cron_id}")
    lines.append(f"- Pipeline: ✅ LIVE (unified_check + enable_short={ENABLE_SHORT})")
    lines.append("")

    lines.append("## Market Snapshot")
    lines.append("")
    lines.append("| Coin | Price | 24h Change | Signal | Score |")
    lines.append("|------|-------|------------|--------|-------|")
    for cid in WATCHLIST:
        sym = WATCHLIST_SYMBOLS[cid]
        p = prices.get(cid, {})
        price = p.get("usd", 0)
        chg = p.get("usd_24h_change", 0) or 0
        price_str = f"${price:,.2f}" if price > 10 else f"${price:,.4f}"
        chg_str = f"{chg:+.2f}%"
        sig = next((s for s in signals if s.symbol == sym), None)
        sig_str = f"{sig.direction.value} ({sig.score})" if sig else "N/A"
        lines.append(f"| {sym} | {price_str} | {chg_str} | {sig_str} |")
    lines.append("")

    if fg_val is not None:
        lines.append(f"**Fear & Greed:** {fg_val} ({fg_label})")
    lines.append("")
    lines.append(f"**Trending:** {', '.join(trending)}")
    lines.append("")

    lines.append("## Cycle Results")
    lines.append(f"- Closed positions: {len(cycle_result.get('closed', []))}")
    lines.append(f"- New trades: {len(new_trades)}")
    lines.append(f"- Portfolio Value: ${stats['value']:,.2f}")
    lines.append("")

    closed = cycle_result.get("closed", [])
    if closed:
        lines.append("### Closed Positions")
        lines.append("")
        lines.append("| Asset | Direction | Entry | Exit | Reason | P&L |")
        lines.append("|-------|-----------|-------|------|--------|-------|")
        for pos in closed:
            lines.append(
                f"| {pos['symbol'].upper()} | {pos['direction']} | "
                f"${pos['entry_price']:,.2f} | ${pos['exit_price']:,.2f} | "
                f"{pos['close_reason']} | ${pos['pnl']:.2f} ({pos['pnl_pct']:+.2f}%) |"
            )
        lines.append("")

    open_positions = [p for p in trader.data.get("positions", []) if p.get("status") == "open"]
    if open_positions:
        lines.append("### Open Positions")
        lines.append("")
        lines.append("| Asset | Direction | Entry | Current | Size | SL | TP | Unrealized |")
        lines.append("|-------|-----------|-------|---------|------|----|----|------------|")
        for pos in open_positions:
            sym = pos.get("symbol", "").upper()
            entry = pos.get("entry_price", 0)
            size = pos.get("size", 0)
            current = price_dict.get(pos.get("symbol", "").lower(), entry)
            qty = pos.get("quantity", 0)
            if pos.get("direction") == "SHORT":
                unrealized = (entry - current) * qty
            else:
                unrealized = (current - entry) * qty
            unrealized_pct = ((current / entry) - 1) * 100 if entry else 0
            if pos.get("direction") == "SHORT":
                unrealized_pct = -unrealized_pct
            sl = pos.get("stop_loss", 0)
            tp = pos.get("take_profit", 0)
            lines.append(
                f"| {sym} | {pos.get('direction', '?')} | ${entry:,.2f} | "
                f"${current:,.2f} | ${size:,.2f} | ${sl:,.2f} | ${tp:,.2f} | "
                f"${unrealized:+.2f} ({unrealized_pct:+.2f}%) |"
            )
        lines.append("")

    lines.append("## Cumulative Performance")
    lines.append(f"- Trades: {stats['total_trades']} | Open: {stats['open_positions']}")
    lines.append(f"- P&L: ${stats['total_pnl']:+.2f} | Win Rate: {stats['win_rate']:.1f}%")
    lines.append(f"- Max Drawdown: {stats['max_drawdown_pct']:.2f}%")
    lines.append(f"- Profit Factor: {stats['profit_factor']:.2f}")
    lines.append("")

    lines.append("## Risk Status")
    lines.append(f"- Cash: ${stats['cash']:,.2f}")
    lines.append(f"- Open slots: {3 - stats['open_positions']}/3")
    lines.append(f"- Consecutive losses: {stats['losses']}/3 (threshold: 3)")
    lines.append("")

    lines.append("---")
    lines.append(f"*{check_label} check complete. Cron: {cron_id}*")

    report = "\n".join(lines)
    print(report)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    memory_path = f"/home/vinny2times/.openclaw/workspace/memory/{date_str}-paper-trading-{check_type}.md"
    with open(memory_path, "w") as f:
        f.write(report)

    journal_path = "/home/vinny2times/.openclaw/workspace/quant-trading/logs/trading_journal.md"
    with open(journal_path, "a") as f:
        f.write("\n\n" + report + "\n")

    return report


if __name__ == "__main__":
    check_type = sys.argv[1] if len(sys.argv) > 1 else "afternoon"
    if check_type not in ("afternoon", "evening"):
        print("Usage: python unified_check.py [afternoon|evening]")
        sys.exit(1)
    main(check_type)
