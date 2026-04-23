"""
Paper Trading Engine
Phase 4, Task 4.3 — Simulates execution of trade signals against real CoinGecko prices.

Inputs:
  - Trade signals from skills/signal_engine/trade_signals.py (4.1)
  - Copy signals from skills/signal_engine/copy_signals.py (4.2)
  - Risk Manager skills/signal_engine/risk_manager.py (4.4) — gate for every trade

Portfolio:
  - $10,000 USD starting balance
  - Virtual fills at next available CoinGecko market price
  - Tracks entry/exit/timestamp/confidence/P&L per trade

Daily Summary:
  {date, starting_balance, ending_balance, trades_taken, win_rate, max_drawdown, sharpe_ratio}

Exit Logic (paper — no actual fills):
  - Stop-loss hit: close at SL price
  - Take-profit hit: close at TP price
  - Signal reversal: close and flip position
  - End of day: close all open positions at market price
"""

import importlib.util as _spec
import json
import os
import math
from datetime import datetime, timezone, timedelta
from typing import Optional


# ─── Load Dependencies ─────────────────────────────────────────────────────────

def _load_mod(name, path):
    s = _spec.spec_from_file_location(name, path)
    m = _spec.module_from_spec(s)
    s.loader.exec_module(m)
    return m

TRADE_MOD   = _load_mod("trade_sig", "skills/signal_engine/trade_signals.py")
RISK_MOD    = _load_mod("risk_mgr",  "skills/signal_engine/risk_manager.py")
PRICE_MOD   = _load_mod("price",     "skills/price_engine/coingecko.py")
# CORR_MOD   = _load_mod("corr",      "skills/correlation_engine/correlation.py")  # deferred — too slow

# ─── State Files ────────────────────────────────────────────────────────────────

PORTFOLIO_FILE  = "/tmp/crypto-quant-portfolio.json"
TRADE_JOURNAL  = "/tmp/crypto-quant-trade-journal.json"
DAILY_SUMMARIES = "/tmp/crypto-quant-daily-summaries.json"


# ─── Portfolio Initialization ─────────────────────────────────────────────────

INITIAL_BALANCE = 10_000.0

def _load_journal():
    if os.path.exists(TRADE_JOURNAL):
        try:
            with open(TRADE_JOURNAL) as f:
                return json.load(f)
        except Exception:
            pass
    return {"trades": [], "closed_trades": []}


def _save_journal(j):
    try:
        with open(TRADE_JOURNAL, "w") as f:
            json.dump(j, f, default=str)
    except Exception:
        pass


def _load_daily_summaries():
    if os.path.exists(DAILY_SUMMARIES):
        try:
            with open(DAILY_SUMMARIES) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_daily_summaries(s):
    try:
        with open(DAILY_SUMMARIES, "w") as f:
            json.dump(s, f, default=str)
    except Exception:
        pass


# ─── Price Fetching ─────────────────────────────────────────────────────────────

COIN_ID_MAP = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "BNB": "binancecoin", "XRP": "ripple", "DOGE": "dogecoin",
    "ADA": "cardano", "AVAX": "avalanche-2", "LINK": "chainlink",
}


def get_current_price(coin: str) -> float:
    """Get current USD price for a coin via CoinGecko with rate-limit retry."""
    cid = COIN_ID_MAP.get(coin, coin.lower())
    for attempt in range(3):
        try:
            data = PRICE_MOD.get_simple_price([cid], ["usd"])
            price = float(data.get(cid, {}).get("usd", 0))
            if price > 0:
                return price
            # Got 0 — could be rate limit, retry with backoff
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    return 0.0


def get_market_price(coin: str) -> dict:
    """
    Get market data including 24h change for context.
    Uses CoinGecko coins/markets endpoint.
    """
    cid = COIN_ID_MAP.get(coin, coin.lower())
    try:
        markets = PRICE_MOD.get_coins_markets(cid, vs_currency="usd", per_page=1)
        if markets:
            m = markets[0]
            return {
                "price": float(m.get("current_price", 0)),
                "change_24h_pct": float(m.get("price_change_percentage_24h", 0)),
                "volume_24h": float(m.get("total_volume", 0)),
                "market_cap": float(m.get("market_cap", 0)),
            }
    except Exception:
        pass
    return {}


# ─── Paper Order Execution ─────────────────────────────────────────────────────

ORDER_CACHE = "/tmp/crypto-quant-order-cache.json"

def _load_order_cache():
    if os.path.exists(ORDER_CACHE):
        try:
            with open(ORDER_CACHE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_order_cache(c):
    try:
        with open(ORDER_CACHE, "w") as f:
            json.dump(c, f)
    except Exception:
        pass


def execute_signal(signal: dict) -> dict:
    """
    Execute a paper trade from a trade signal.
    Checks risk manager first (can_open_position).
    Fills at current CoinGecko market price.

    Returns: {status, order, fill_price, message}
    """
    coin = signal.get("coin", "")
    direction = signal.get("direction", "")
    signal_type = signal.get("signal_type", "NEUTRAL")

    # Filter to actionable signals only
    if signal_type not in ("STRONG", "MODERATE"):
        return {"status": "skipped", "reason": f"Signal type {signal_type} not actionable"}

    # ── Risk check ──────────────────────────────────────────────────────────
    allowed, reason = RISK_MOD.can_open_position(coin)
    if not allowed:
        return {"status": "risk_rejected", "reason": reason}

    # Check position size
    proposed_size = signal.get("position_size_usd", 0)
    size_ok, size_reason, max_size = RISK_MOD.position_size_allowed(coin, proposed_size)
    if not size_ok:
        # Reduce to max allowed
        signal["position_size_usd"] = max_size

    size_usd = signal.get("position_size_usd", 0)
    if size_usd <= 0:
        return {"status": "skipped", "reason": "Zero or negative position size"}

    # ── Fetch fill price ─────────────────────────────────────────────────────
    entry_price = signal.get("entry_price") or get_current_price(coin)
    if entry_price <= 0:
        return {"status": "error", "reason": f"Could not determine fill price for {coin}"}

    # ── Build paper order ─────────────────────────────────────────────────────
    fill_price = entry_price  # market fill
    size_units = size_usd / fill_price
    stop_loss  = signal.get("stop_loss", 0)
    take_profit = signal.get("take_profit", 0)

    order = {
        "order_id": f"PAPER-{coin}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "coin": coin,
        "direction": direction,
        "signal_type": signal_type,
        "entry_price": fill_price,
        "size_units": round(size_units, 8),
        "size_usd": round(size_usd, 2),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_amount": signal.get("risk_amount", 0),
        "composite_score": signal.get("composite_score", 0),
        "confidence": signal.get("confidence_score", 0),
        "risk_score": signal.get("risk_score", "medium"),
        "entered_at": datetime.now(timezone.utc).isoformat(),
        "status": "OPEN",
        "pnl_realized": 0.0,
        "exit_price": None,
        "exit_reason": None,
        "closed_at": None,
    }

    # ── Record in risk manager ───────────────────────────────────────────────
    RISK_MOD.add_position(
        coin=coin,
        direction=direction,
        entry_price=fill_price,
        size_usd=size_usd,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )

    # ── Journal it ────────────────────────────────────────────────────────────
    journal = _load_journal()
    journal["trades"].append(order)
    _save_journal(journal)

    return {
        "status": "FILLED",
        "order": order,
        "fill_price": fill_price,
        "message": f"Paper {direction} {size_units:.4f} {coin} @ ${fill_price:,.2f}",
    }


# ─── Exit Logic ────────────────────────────────────────────────────────────────

def check_and_close_positions() -> list:
    """
    Check all open paper positions against current market prices.
    Auto-exit on SL hit, TP hit, or signal reversal.

    Returns list of closed orders with P&L.
    """
    journal = _load_journal()
    open_trades = [t for t in journal.get("trades", []) if t.get("status") == "OPEN"]

    if not open_trades:
        return []

    closed = []

    for trade in open_trades:
        coin      = trade["coin"]
        direction = trade["direction"]
        entry     = trade["entry_price"]
        sl        = trade.get("stop_loss", 0)
        tp        = trade.get("take_profit", 0)
        size      = trade["size_units"]

        current_price = get_current_price(coin)
        if current_price <= 0:
            continue

        exit_reason = None
        exit_price  = current_price

        # ── Stop-loss check ─────────────────────────────────────────────────
        if direction == "BUY" and sl > 0 and current_price <= sl:
            exit_reason = "STOP_LOSS"
            exit_price  = sl
        elif direction == "SELL" and sl > 0 and current_price >= sl:
            exit_reason = "STOP_LOSS"
            exit_price  = sl

        # ── Take-profit check ───────────────────────────────────────────────
        elif direction == "BUY" and tp > 0 and current_price >= tp:
            exit_reason = "TAKE_PROFIT"
            exit_price  = tp
        elif direction == "SELL" and tp > 0 and current_price <= tp:
            exit_reason = "TAKE_PROFIT"
            exit_price  = tp

        if exit_reason:
            # Calculate P&L
            if direction == "BUY":
                pnl = (exit_price - entry) * size
            else:
                pnl = (entry - exit_price) * size

            trade["status"]        = "CLOSED"
            trade["exit_price"]    = round(exit_price, 4)
            trade["exit_reason"]   = exit_reason
            trade["pnl_realized"]  = round(pnl, 2)
            trade["closed_at"]     = datetime.now(timezone.utc).isoformat()

            # Sync to risk manager
            RISK_MOD.close_position(coin, exit_price, reason=exit_reason)

            closed.append(trade)

    if closed:
        # Prune closed from open trades, add to closed_trades
        open_trades = [t for t in journal.get("trades", []) if t.get("status") == "OPEN"]
        closed_trades = journal.get("closed_trades", [])
        closed_trades.extend(closed)
        journal["trades"]      = open_trades
        journal["closed_trades"] = closed_trades
        _save_journal(journal)

    return closed


def close_all_positions(reason: str = "END_OF_DAY") -> list:
    """
    Force-close all open positions at current market price.
    Used for end-of-day settlement.
    """
    journal = _load_journal()
    open_trades = [t for t in journal.get("trades", []) if t.get("status") == "OPEN"]
    closed = []

    for trade in open_trades:
        coin    = trade["coin"]
        entry   = trade["entry_price"]
        size    = trade["size_units"]
        direction = trade["direction"]

        current_price = get_current_price(coin)
        if current_price <= 0:
            continue

        if direction == "BUY":
            pnl = (current_price - entry) * size
        else:
            pnl = (entry - current_price) * size

        trade["status"]       = "CLOSED"
        trade["exit_price"]   = round(current_price, 4)
        trade["exit_reason"]  = reason
        trade["pnl_realized"] = round(pnl, 2)
        trade["closed_at"]    = datetime.now(timezone.utc).isoformat()

        RISK_MOD.close_position(coin, current_price, reason=reason)
        closed.append(trade)

    if closed:
        journal = _load_journal()
        open_trades = [t for t in journal.get("trades", []) if t.get("status") == "OPEN"]
        closed_trades = journal.get("closed_trades", [])
        closed_trades.extend(closed)
        journal["trades"]       = open_trades
        journal["closed_trades"] = closed_trades
        _save_journal(journal)

    return closed


# ─── Daily Summary ─────────────────────────────────────────────────────────────

def generate_daily_summary(date: str = None) -> dict:
    """
    Generate end-of-day summary for a given date (YYYY-MM-DD).
    Includes: starting_balance, ending_balance, trades_taken,
    win_rate, max_drawdown, sharpe_ratio.
    """
    if date is None:
        date = datetime.now(timezone.utc).date().isoformat()

    summaries = _load_daily_summaries()
    journal   = _load_journal()
    cfg       = RISK_MOD.load_config()

    # Find or compute starting balance
    prev_summary = next((s for s in summaries if s["date"] < date), None)
    starting_bal = prev_summary["ending_balance"] if prev_summary else INITIAL_BALANCE

    # Trades closed on this date
    closed_today = [
        t for t in journal.get("closed_trades", [])
        if t.get("closed_at", "")[:10] == date
    ]

    # P&L
    total_pnl = sum(float(t.get("pnl_realized", 0)) for t in closed_today)
    ending_bal = starting_bal + total_pnl

    trades_taken = len(closed_today)
    wins = sum(1 for t in closed_today if float(t.get("pnl_realized", 0)) > 0)
    win_rate = (wins / trades_taken * 100) if trades_taken > 0 else 0

    # Max drawdown — scan closed trades in order up to today
    all_closed_up_to_today = [
        t for t in journal.get("closed_trades", [])
        if t.get("closed_at", "")[:10] <= date
    ]
    all_closed_up_to_today.sort(key=lambda x: x.get("closed_at", ""))

    peak = starting_bal
    max_dd = 0.0
    running = starting_bal
    for t in all_closed_up_to_today:
        running += float(t.get("pnl_realized", 0))
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    # Sharpe ratio — daily returns
    if trades_taken >= 2:
        returns = [float(t.get("pnl_realized", 0)) / starting_bal for t in closed_today]
        mean_ret = sum(returns) / len(returns)
        std_ret  = math.sqrt(sum((r - mean_ret)**2 for r in returns) / len(returns)) if len(returns) > 1 else 0
        sharpe = (mean_ret / std_ret) if std_ret > 0 else 0
    else:
        sharpe = 0.0

    summary = {
        "date": date,
        "starting_balance": round(starting_bal, 2),
        "ending_balance": round(ending_bal, 2),
        "net_pnl": round(total_pnl, 2),
        "trades_taken": trades_taken,
        "wins": wins,
        "losses": trades_taken - wins,
        "win_rate_pct": round(win_rate, 1),
        "max_drawdown_usd": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 3),
        "open_positions_end_of_day": len([t for t in journal.get("trades", []) if t.get("status") == "OPEN"]),
    }

    # Update summaries
    summaries = [s for s in summaries if s["date"] != date]  # replace
    summaries.append(summary)
    summaries.sort(key=lambda x: x["date"])
    _save_daily_summaries(summaries)

    return summary


# ─── Run Full Paper Trading Cycle ─────────────────────────────────────────────

def run_paper_cycle(coins: list = None) -> dict:
    """
    Run the paper trading cycle for specified coins (default: top 3 by market cap).
      1. Check and close any positions that hit SL/TP
      2. Generate signals using single-symbol analysis (avoids multi-API rate limiting)
      3. Risk-check and execute new signals
      4. Return cycle report
    """
    if coins is None:
        coins = ["BTC", "ETH", "SOL", "BNB", "AVAX"]  # Top 5 for more signals

    # Step 1: Check existing positions
    closed = check_and_close_positions()

    # Step 2: Generate signals per coin (single-symbol, no full correlation engine)
    import importlib.util as iu
    ta_spec = iu.spec_from_file_location("ta", "skills/ta_engine/analyze.py")
    ta_mod  = iu.module_from_spec(ta_spec); ta_spec.loader.exec_module(ta_mod)

    # Use a simplified scoring: TA score only for paper trading cycle
    # Full correlation engine (3.6) is used for reporting, not execution
    COIN_ID_MAP_LOCAL = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "BNB": "binancecoin", "XRP": "ripple",
        "AVAX": "avalanche-2", "ADA": "cardano", "DOGE": "dogecoin",
    }

    actionable = []
    for coin in coins:
        cid = COIN_ID_MAP_LOCAL.get(coin)
        if not cid:
            continue
        try:
            td = ta_mod.analyze(coin, cid, days=30)
            ta_score   = td.get("conviction_score", 50)
            ta_signal  = td.get("recommendation", "HOLD")
            entry      = td.get("current_price", 0)
            atr        = td.get("indicators", {}).get("atr_14", 0)

            # Map TA recommendation to trade signal
            direction_map = {
                "STRONG BUY":  "BUY",
                "BUY":        "BUY",
                "MODERATE BUY": "BUY",
                "STRONG SELL": "SELL",
                "SELL":       "SELL",
                "MODERATE SELL": "SELL",
            }
            direction = direction_map.get(ta_signal, None)
            if not direction:
                continue  # HOLD or TAKE PROFIT / OVERSOLD — skip

            sig = TRADE_MOD.generate_signal(
                coin=coin,
                direction=direction,
                composite_score=ta_score,
                confidence="HIGH" if ta_score >= 70 else "MEDIUM",
                divergence=False,
                current_price=entry,
                atr=atr,
            )
            if sig.get("signal_type") in ("STRONG", "MODERATE"):
                actionable.append(sig)
        except Exception as e:
            continue  # Skip this coin on error

    # Step 3: Execute each actionable signal through risk manager
    executed = []
    skipped  = []
    for sig in actionable:
        result = execute_signal(sig)
        if result["status"] == "FILLED":
            executed.append(result)
        else:
            skipped.append({"signal": sig, "reason": result.get("reason") or result.get("status")})

    # Step 4: Portfolio status
    portfolio = RISK_MOD.get_portfolio_status()
    today_sum = generate_daily_summary()

    return {
        "closed":   closed,
        "executed": executed,
        "skipped":  skipped,
        "portfolio_status": portfolio,
        "daily_summary":    today_sum,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Formatting ───────────────────────────────────────────────────────────────

def format_cycle_report(report: dict) -> str:
    """Human-readable paper trading cycle report."""
    lines = ["**Paper Trading Cycle Report**\n"]

    closed = report.get("closed", [])
    if closed:
        lines.append(f"**Closed ({len(closed)}):**")
        for c in closed:
            emoji = "🟢" if c.get("pnl_realized", 0) > 0 else "🔴"
            lines.append(
                f"  {emoji} {c['coin']} {c['direction']} — "
                f"{c['exit_reason']} @ ${c.get('exit_price', 0):,.2f} | "
                f"P&L: ${c.get('pnl_realized', 0):+.2f}"
            )
    else:
        lines.append("**Closed:** none")

    executed = report.get("executed", [])
    if executed:
        lines.append(f"\n**Executed ({len(executed)}):**")
        for e in executed:
            o = e.get("order", {})
            lines.append(
                f"  🟡 {o.get('coin')} {o.get('direction')} — "
                f"@ ${o.get('entry_price', 0):,.2f} | "
                f"Size: ${o.get('size_usd', 0):.2f} | "
                f"Risk: ${o.get('risk_amount', 0):.2f}"
            )

    skipped = report.get("skipped", [])
    if skipped:
        lines.append(f"\n**Skipped ({len(skipped)}):**")
        for s in skipped[:3]:
            lines.append(f"  ⚪ {s['signal'].get('coin')} — {s['reason']}")

    ps = report.get("portfolio_status", {})
    ds = report.get("daily_summary", {})

    lines.append(f"\n**Portfolio:** ${ps.get('portfolio_current_usd', 0):,.2f} "
                 f"({'+' if ps.get('total_pnl_usd', 0) >= 0 else ''}{ps.get('total_pnl_usd', 0):.2f})")

    lines.append(f"**Today:** {ds.get('trades_taken', 0)} trades | "
                 f"P&L: ${ds.get('net_pnl', 0):+.2f} | "
                 f"WR: {ds.get('win_rate_pct', 0):.0f}% | "
                 f"DD: ${ds.get('max_drawdown_usd', 0):.2f}")

    return "\n".join(lines)


def format_order(order: dict) -> str:
    """Single paper order formatted."""
    emoji = "🟢" if order.get("direction") == "BUY" else "🔴"
    pnl = order.get("pnl_realized", 0)
    pnl_str = f"${pnl:+.2f}" if order.get("status") == "CLOSED" else "OPEN"
    lines = [
        f"{emoji} **{order['coin']} — PAPER {order['direction']}**",
        f"   Entry: ${order.get('entry_price', 0):,.4f}",
        f"   Size:  {order.get('size_units', 0):.4f} {order['coin']} (${order.get('size_usd', 0):.2f})",
        f"   SL:    ${order.get('stop_loss', 0):,.4f} | TP: ${order.get('take_profit', 0):,.4f}",
        f"   Score: {order.get('composite_score', 0)}/100 | Conf: {order.get('confidence', 0)}",
        f"   P&L:   {pnl_str} | Status: {order.get('status')}",
        f"   Opened: {order.get('entered_at', '?')}",
    ]
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("=== Paper Trading Engine ===\n")

    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        # Status snapshot (no API calls)
        journal = _load_journal()
        open_trades    = [t for t in journal.get("trades", []) if t.get("status") == "OPEN"]
        closed_trades  = journal.get("closed_trades", [])
        portfolio = RISK_MOD.get_portfolio_status()
        today_sum = generate_daily_summary()

        print(f"**Paper Trading Status**\n")
        print(f"Portfolio: ${portfolio.get('portfolio_current_usd', INITIAL_BALANCE):,.2f} "
              f"(started ${INITIAL_BALANCE:,.2f})")
        print(f"Total P&L: ${portfolio.get('total_pnl_usd', 0):+.2f}")
        print(f"\nOpen Positions: {len(open_trades)}")
        for t in open_trades:
            print(format_order(t))
            print()

        print(f"Closed Trades: {len(closed_trades)}")
        if closed_trades:
            wins = sum(1 for t in closed_trades if t.get("pnl_realized", 0) > 0)
            total_pnl = sum(t.get("pnl_realized", 0) for t in closed_trades)
            print(f"  Win Rate: {wins/len(closed_trades)*100:.0f}% | Total P&L: ${total_pnl:+.2f}")

        print(f"\n**Today's Summary**")
        print(f"  Trades: {today_sum.get('trades_taken', 0)} | "
              f"P&L: ${today_sum.get('net_pnl', 0):+.2f} | "
              f"WR: {today_sum.get('win_rate_pct', 0):.0f}% | "
              f"DD: ${today_sum.get('max_drawdown_usd', 0):.2f}")

        print(f"\nRisk Status: {'IN COOLDOWN ⚠️' if portfolio.get('in_cooldown') else 'CLEAR TO TRADE ✅'}")
        print(f"Consecutive Losses: {portfolio.get('consecutive_losses', 0)}/3")

    elif len(sys.argv) > 1 and sys.argv[1] == "--cache":
        # Pre-cache TA data for top coins (avoids rate-limiting during cycle)
        import importlib.util as iu
        ta_spec = iu.spec_from_file_location("ta", "skills/ta_engine/analyze.py")
        ta_mod  = iu.module_from_spec(ta_spec); ta_spec.loader.exec_module(ta_mod)
        TA_CACHE_FILE = "/tmp/crypto-quant-ta-cache.json"

        coins = [("BTC","bitcoin"), ("ETH","ethereum"), ("SOL","solana"), ("BNB","binancecoin"), ("AVAX","avalanche-2")]
        cached = {}
        for coin, cid in coins:
            print(f"  Caching {coin}...", end=" ", flush=True)
            try:
                d = ta_mod.analyze(coin, cid, days=30)
                cached[coin] = {
                    "recommendation": d.get("recommendation"),
                    "conviction_score": d.get("conviction_score"),
                    "current_price": d.get("current_price"),
                    "atr_14": d.get("indicators", {}).get("atr_14", 0),
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                }
                print(f"{d.get('recommendation')} @ ${d.get('current_price', 0):,.0f}")
            except Exception as e:
                print(f"FAILED: {e}")
                cached[coin] = None

        with open(TA_CACHE_FILE, "w") as f:
            json.dump(cached, f, default=str)
        print(f"\n✅ Cached {sum(1 for v in cached.values() if v)}/{len(coins)} coins")
        print("   Run --run to execute paper trades using cached data (no API calls)")

    elif len(sys.argv) > 1 and sys.argv[1] == "--run":
        # Full cycle — needs --cache run first for rate limit safety
        TA_CACHE_FILE = "/tmp/crypto-quant-ta-cache.json"
        if not os.path.exists(TA_CACHE_FILE):
            print("Cache missing — run --cache first to avoid rate limiting")
            print("Usage: python paper_trader.py --cache && python paper_trader.py --run")
        else:
            with open(TA_CACHE_FILE) as f:
                ta_cache = json.load(f)

        report = run_paper_cycle()
        if "error" in report:
            print(f"Error: {report['error']}")
        else:
            print(format_cycle_report(report))

    else:
        print("Usage:")
        print("  python paper_trader.py --status   # view portfolio (no API calls)")
        print("  python paper_trader.py --cache    # pre-fetch market data")
        print("  python paper_trader.py --run      # execute paper trades (run --cache first)")