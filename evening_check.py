#!/usr/bin/env python3
"""
evening_check.py — Crypto Quant AI — Daily Paper Trading Orchestrator
Run via cron at 9 PM ET (paper-trading-evening).

Steps:
  1. Pre-cache TA data for all coins (avoids rate-limiting)
  2. Run paper trading cycle (check SL/TP, execute new signals)
  3. Generate daily summary
  4. Log to trading_journal.md
  5. Output Discord-ready report

Usage:
  cd /tmp/crypto-quant-ai && source venv/bin/activate && python evening_check.py
"""

import sys
import os
import json
import subprocess
from datetime import datetime, timezone, timedelta

# Ensure we're in the project root
os.chdir("/tmp/crypto-quant-ai")

# Add skills to path
sys.path.insert(0, "skills")
sys.path.insert(0, "skills/signal_engine")
sys.path.insert(0, "skills/ta_engine")
sys.path.insert(0, "skills/price_engine")
sys.path.insert(0, "skills/derivatives_engine")

# ─── Imports ──────────────────────────────────────────────────────────────────

import importlib.util as _spec

def _load_mod(name, path):
    s = _spec.spec_from_file_location(name, path)
    m = _spec.module_from_spec(s)
    s.loader.exec_module(m)
    return m

TA_MOD     = _load_mod("ta",     "skills/ta_engine/analyze.py")
PRICE_MOD  = _load_mod("price",  "skills/price_engine/coingecko.py")
SIGNAL_MOD = _load_mod("sig",    "skills/signal_engine/trade_signals.py")
RISK_MOD   = _load_mod("risk",   "skills/signal_engine/risk_manager.py")
PAPER_MOD  = _load_mod("paper",  "skills/signal_engine/paper_trader.py")

# ─── Config ───────────────────────────────────────────────────────────────────

COINS = ["BTC", "ETH", "SOL", "BNB", "AVAX"]
COIN_ID_MAP = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "BNB": "binancecoin", "AVAX": "avalanche-2",
}

TA_CACHE_FILE = "/tmp/crypto-quant-ta-cache.json"
REPORTS_DIR   = "/tmp/crypto-quant-ai/reports"
JOURNAL_FILE  = "/tmp/crypto-quant-ai/trading_journal.md"

# ─── Step 1: Cache TA Data ──────────────────────────────────────────────────────

def cache_ta_data():
    """Pre-fetch TA analysis for all coins to avoid rate limiting during cycle."""
    cached = {}
    for coin, cid in COIN_ID_MAP.items():
        try:
            d = TA_MOD.analyze(coin, cid, days=30)
            cached[coin] = {
                "recommendation": d.get("recommendation"),
                "conviction_score": d.get("conviction_score"),
                "current_price": d.get("current_price"),
                "atr_14": d.get("indicators", {}).get("atr_14", 0),
                "rsi_14": d.get("indicators", {}).get("rsi_14", 0),
                "cached_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            cached[coin] = None

    with open(TA_CACHE_FILE, "w") as f:
        json.dump(cached, f, default=str)

    success = sum(1 for v in cached.values() if v is not None)
    return success, len(COIN_ID_MAP)


# ─── Step 2: Run Paper Trading Cycle ────────────────────────────────────────────

def run_cycle():
    """Execute the full paper trading cycle using cached TA data."""
    with open(TA_CACHE_FILE) as f:
        ta_cache = json.load(f)
    return PAPER_MOD.run_paper_cycle(coins=COINS, ta_cache=ta_cache)


# ─── Step 3: Journal Logging ──────────────────────────────────────────────────

def log_to_journal(report: dict):
    """Append trade report to markdown trading journal."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M UTC")

    closed   = report.get("closed", [])
    executed = report.get("executed", [])
    skipped  = report.get("skipped", [])
    ps       = report.get("portfolio_status", {})
    ds       = report.get("daily_summary", {})

    lines = [
        f"## Evening Check — {date_str} {time_str}\n",
        f"**Portfolio:** ${ps.get('portfolio_current_usd', 10000):,.2f} "
        f"({'+' if ps.get('total_pnl_usd', 0) >= 0 else ''}{ps.get('total_pnl_usd', 0):.2f} all-time)\n",
        f"**Daily P&L:** ${ds.get('net_pnl', 0):+.2f} | "
        f"Trades: {ds.get('trades_taken', 0)} | "
        f"WR: {ds.get('win_rate_pct', 0):.0f}% | "
        f"Open: {ds.get('open_positions_end_of_day', 0)}\n",
    ]

    if closed:
        lines.append(f"**Closed ({len(closed)}):**\n")
        for c in closed:
            emoji = "🟢" if c.get("pnl_realized", 0) > 0 else "🔴"
            lines.append(
                f"- {emoji} **{c['coin']}** {c['exit_reason']} "
                f"@ ${c.get('exit_price', 0):,.2f} | "
                f"P&L: ${c.get('pnl_realized', 0):+.2f}\n"
            )

    if executed:
        lines.append(f"**Opened ({len(executed)}):**\n")
        for e in executed:
            o = e.get("order", {})
            lines.append(
                f"- 🟡 **{o.get('coin')}** {o.get('direction')} "
                f"@ ${o.get('entry_price', 0):,.2f} | "
                f"Size: ${o.get('size_usd', 0):.2f}\n"
            )

    if skipped:
        lines.append(f"**Skipped ({len(skipped)}):**\n")
        for s in skipped[:5]:
            lines.append(f"- ⚪ {s['signal'].get('coin')} — {s.get('reason')}\n")

    lines.append("---\n")

    # Write
    with open(JOURNAL_FILE, "a") as f:
        f.writelines(lines)

    return "".join(lines)


# ─── Step 4: Discord Report ─────────────────────────────────────────────────────

def build_discord_report(report: dict) -> str:
    """Build Discord-ready string from cycle report."""
    closed   = report.get("closed", [])
    executed = report.get("executed", [])
    skipped  = report.get("skipped", [])
    ps       = report.get("portfolio_status", {})
    ds       = report.get("daily_summary", {})

    lines = ["📊 **Evening Paper Trading Check**\n"]

    if closed:
        for c in closed:
            emoji = "🟢" if c.get("pnl_realized", 0) > 0 else "🔴"
            lines.append(
                f"{emoji} **{c['coin']}** {c['exit_reason']} @ "
                f"${c.get('exit_price', 0):,.2f} | "
                f"P&L: ${c.get('pnl_realized', 0):+.2f}"
            )

    if executed:
        for e in executed:
            o = e.get("order", {})
            lines.append(
                f"🟡 **{o.get('coin')}** {o.get('direction')} @ "
                f"${o.get('entry_price', 0):,.2f} | "
                f"Size: ${o.get('size_usd', 0):.2f}"
            )

    if skipped and not executed and not closed:
        for s in skipped[:2]:
            lines.append(f"⚪ {s['signal'].get('coin')} — {s.get('reason')}")

    lines.append(f"\n💰 **Portfolio:** ${ps.get('portfolio_current_usd', 10000):,.2f} "
                 f"({'+' if ps.get('total_pnl_usd', 0) >= 0 else ''}{ps.get('total_pnl_usd', 0):.2f})")
    lines.append(f"📈 Today: {ds.get('trades_taken', 0)} trades | "
                 f"P&L: ${ds.get('net_pnl', 0):+.2f} | "
                 f"WR: {ds.get('win_rate_pct', 0):.0f}%")
    lines.append(f"📍 Open: {ds.get('open_positions_end_of_day', 0)}/{ps.get('max_open_positions', 3)} | "
                 f"Cooldown: {'YES' if ps.get('in_cooldown') else 'NO'}")

    return "\n".join(lines)


# ─── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=== Crypto Quant AI — Evening Paper Trading Check ===\n")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"Time: {now}\n")

    # Step 1: Cache
    print("Step 1: Caching TA data...")
    ok, total = cache_ta_data()
    print(f"  Cached {ok}/{total} coins\n")

    # Step 2: Cycle
    print("Step 2: Running paper trading cycle...")
    report = run_cycle()

    if "error" in report:
        print(f"  Error: {report['error']}")
        return 1

    # Step 3: Journal
    print("Step 3: Logging to trading_journal.md...")
    md = log_to_journal(report)

    # Step 4: Discord report
    print("Step 4: Discord report:")
    discord_msg = build_discord_report(report)
    print("\n" + discord_msg)

    # Also save to file for cron capture
    report_file = f"{REPORTS_DIR}/evening_check_{datetime.now(timezone.utc).date().isoformat()}.md"
    with open(report_file, "w") as f:
        f.write(discord_msg)

    print(f"\nReport saved: {report_file}")
    print("✅ Evening check complete")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"❌ Evening check failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
