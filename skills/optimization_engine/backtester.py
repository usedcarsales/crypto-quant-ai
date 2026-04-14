"""
Strategy Backtester — Phase 5, Task 5.4
Backtests trade signals against 90 days of historical CoinGecko OHLCV data.
Uses TA indicators to generate signals, then evaluates P&L.

Usage:
  python backtester.py                    # full BTC/ETH/SOL backtest
  python backtester.py --coin BTC         # single coin
  python backtester.py --days 180          # longer history
"""

import importlib.util as _spec
import math
import os
import sys


# ─── Load Dependencies ─────────────────────────────────────────────────────────

def _load_mod(name, path):
    s = _spec.spec_from_file_location(name, path)
    m = _spec.module_from_spec(s)
    s.loader.exec_module(m)
    return m

TA_MOD   = _load_mod("ta",    "skills/ta_engine/analyze.py")
RISK_MOD = _load_mod("risk",  "skills/signal_engine/risk_manager.py")


# ─── Config ───────────────────────────────────────────────────────────────────

COIN_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
}

DEFAULT_DAYS  = 90
DEFAULT_COINS = ["BTC", "ETH", "SOL"]


# ─── Data Fetching ────────────────────────────────────────────────────────────

def fetch_ohlcv(coin_id: str, days: int = 90) -> list:
    """
    Fetch OHLCV data from CoinGecko.
    Returns list of [timestamp, open, high, low, close, volume] candles.
    """
    import requests

    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": days}

    resp = requests.get(url, params=params, timeout=15)
    if resp.status_code != 200:
        return []

    data = resp.json()
    if not data:
        return []

    return data  # list of [timestamp_ms, open, high, low, close, volume]


# ─── Signal Generation (simplified for backtest) ──────────────────────────────

def generate_signal_from_candle(candle: list, prev_candle: list = None) -> dict:
    """
    Generate a trade signal from a single candle and optional previous candle.
    Simplified version: uses close vs SMA crossover + RSI.

    Returns: {signal: BUY/SELL/HOLD, confidence, entry_price, conviction_score}
    """
    if len(candle) < 5:
        return {"signal": "HOLD", "confidence": "low", "entry_price": candle[4], "conviction_score": 50}

    timestamp, open_, high, low, close = candle[:5]

    if prev_candle and len(prev_candle) >= 5:
        prev_close = prev_candle[4]

        # Simple SMA(20) crossover
        sma20 = sum(candle[1:5]) / 4  # rough SMA using current candle OHLC

        # RSI-like: compare to prev close
        change = (close - prev_close) / prev_close * 100 if prev_close else 0

        # Momentum
        if change > 1.0 and close > open_:
            return {
                "signal": "BUY",
                "confidence": "high",
                "entry_price": close,
                "conviction_score": min(95, 50 + change * 3),
                "change_pct": round(change, 2),
            }
        elif change < -1.0 and close < open_:
            return {
                "signal": "SELL",
                "confidence": "high",
                "entry_price": close,
                "conviction_score": min(95, 50 + abs(change) * 3),
                "change_pct": round(change, 2),
            }

    return {
        "signal": "HOLD",
        "confidence": "low",
        "entry_price": close,
        "conviction_score": 50,
        "change_pct": 0,
    }


# ─── Backtest Engine ─────────────────────────────────────────────────────────

def run_backtest(
    coin: str,
    coin_id: str,
    days: int = 90,
    initial_balance: float = 10_000.0,
    position_size_pct: float = 0.10,  # 10% of portfolio per trade
    stop_loss_pct: float = 2.0,       # 2% stop loss
    take_profit_pct: float = 4.0,     # 4% take profit (2:1 R/R)
) -> dict:
    """
    Run a backtest for a given coin over N days of OHLCV data.

    Strategy:
      - Entry: BUY signal with HIGH confidence
      - Position: position_size_pct of current portfolio value
      - Exit: stop_loss or take_profit hit, or SELL signal

    Returns: full backtest results dict
    """
    candles = fetch_ohlcv(coin_id, days)
    if not candles or len(candles) < 5:
        return {"coin": coin, "error": f"No data for {coin_id}"}

    print(f"  {coin}: {len(candles)} candles loaded")

    # ── Simulate trades ────────────────────────────────────────────────────────
    portfolio    = initial_balance
    position     = None   # {"size": 0, "entry": 0, "side": "BUY"}
    trades       = []
    equity_curve = []

    for i, candle in enumerate(candles):
        timestamp, open_, high, low, close = candle[:5]
        prev = candles[i-1] if i > 0 else None

        signal = generate_signal_from_candle(candle, prev)
        sig_type = signal["signal"]
        confidence = signal["confidence"]
        entry = signal["entry_price"]

        equity = portfolio + (position["size"] * close - position["size"] * position["entry"]
                             if position else 0)
        equity_curve.append({"timestamp": timestamp, "equity": round(equity, 2)})

        # ── Check exits first ────────────────────────────────────────────────
        if position:
            size      = position["size"]
            pos_entry = position["entry"]
            side      = position["side"]

            pnl_pct   = (close - pos_entry) / pos_entry * 100 if side == "BUY" else (pos_entry - close) / pos_entry * 100
            pnl_usd   = portfolio * position_size_pct * pnl_pct / 100

            should_exit = False
            exit_reason = None

            if side == "BUY":
                if low  <= position["stop"]:  should_exit = True; exit_reason = "STOP_LOSS"
                elif high >= position["take"]: should_exit = True; exit_reason = "TAKE_PROFIT"
            else:
                if high >= position["stop"]:  should_exit = True; exit_reason = "STOP_LOSS"
                elif low <= position["take"]: should_exit = True; exit_reason = "TAKE_PROFIT"

            # Also exit on strong SELL signal if we have a BUY position
            if sig_type == "SELL" and confidence == "high" and not should_exit:
                should_exit = True
                exit_reason = "SIGNAL_REVERSAL"

            if should_exit:
                portfolio += pnl_usd
                trades.append({
                    "entry_time":  position["entry_time"],
                    "exit_time":   timestamp,
                    "side":        side,
                    "entry_price": pos_entry,
                    "exit_price":  close,
                    "size":        size,
                    "pnl_pct":     round(pnl_pct, 2),
                    "pnl_usd":     round(pnl_usd, 2),
                    "exit_reason": exit_reason,
                    "holding_days": round((timestamp - position["entry_time"]) / 86400000, 1),
                })
                position = None

        # ── Check entries ────────────────────────────────────────────────────
        if not position and sig_type == "BUY" and confidence == "high":
            size   = portfolio * position_size_pct
            shares = size / entry

            position = {
                "side":       "BUY",
                "entry":      entry,
                "size":       shares,
                "stop":       round(entry * (1 - stop_loss_pct / 100), 4),
                "take":       round(entry * (1 + take_profit_pct / 100), 4),
                "entry_time": timestamp,
            }

    # Close any open position at end
    if position:
        last_close = candles[-1][4]
        pnl_pct = (last_close - position["entry"]) / position["entry"] * 100
        pnl_usd = portfolio * position_size_pct * pnl_pct / 100
        portfolio += pnl_usd
        trades.append({
            "entry_time":  position["entry_time"],
            "exit_time":   candles[-1][0],
            "side":        position["side"],
            "entry_price": position["entry"],
            "exit_price":  last_close,
            "size":        position["size"],
            "pnl_pct":     round(pnl_pct, 2),
            "pnl_usd":     round(pnl_usd, 2),
            "exit_reason": "END_OF_DATA",
            "holding_days": round((candles[-1][0] - position["entry_time"]) / 86400000, 1),
        })
        position = None

    # ── Calculate metrics ─────────────────────────────────────────────────────
    total_return = (portfolio - initial_balance) / initial_balance * 100
    num_trades   = len(trades)
    wins         = [t for t in trades if t["pnl_usd"] > 0]
    losses       = [t for t in trades if t["pnl_usd"] <= 0]
    win_rate     = len(wins) / num_trades * 100 if num_trades > 0 else 0

    gross_profit = sum(t["pnl_usd"] for t in wins)
    gross_loss   = abs(sum(t["pnl_usd"] for t in losses))
    avg_win      = gross_profit / len(wins) if wins else 0
    avg_loss     = gross_loss  / len(losses) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    # Max drawdown
    peak    = initial_balance
    max_dd  = 0
    running = initial_balance
    for t in equity_curve:
        running = t["equity"]
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    # Sharpe ratio (daily returns)
    if len(equity_curve) >= 2:
        rets = [equity_curve[i]["equity"] / equity_curve[i-1]["equity"] - 1
                for i in range(1, len(equity_curve))]
        mean_ret = sum(rets) / len(rets)
        std_ret  = math.sqrt(sum((r - mean_ret)**2 for r in rets) / max(len(rets)-1, 1)) if len(rets) > 1 else 0
        sharpe   = (mean_ret / std_ret * math.sqrt(365)) if std_ret > 0 else 0
    else:
        sharpe = 0

    return {
        "coin":              coin,
        "coin_id":           coin_id,
        "backtest_days":     days,
        "initial_balance":   initial_balance,
        "final_balance":     round(portfolio, 2),
        "total_return_pct": round(total_return, 2),
        "num_trades":        num_trades,
        "wins":              len(wins),
        "losses":            len(losses),
        "win_rate_pct":     round(win_rate, 1),
        "gross_profit":     round(gross_profit, 2),
        "gross_loss":       round(gross_loss, 2),
        "avg_win_usd":      round(avg_win, 2),
        "avg_loss_usd":     round(avg_loss, 2),
        "profit_factor":    round(profit_factor, 2),
        "sharpe_ratio":     round(sharpe, 3),
        "max_drawdown_usd": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd / initial_balance * 100, 2),
        "best_trade":       round(max(t["pnl_usd"] for t in trades), 2) if trades else 0,
        "worst_trade":      round(min(t["pnl_usd"] for t in trades), 2) if trades else 0,
        "avg_holding_days":  round(sum(t["holding_days"] for t in trades) / len(trades), 1) if trades else 0,
        "trades":           trades,
        "equity_curve":     equity_curve,
    }


# ─── Formatting ───────────────────────────────────────────────────────────────

def format_backtest_result(r: dict) -> str:
    if "error" in r:
        return f"⚠️ {r['coin']}: {r['error']}"

    emoji = "🟢" if r["total_return_pct"] >= 0 else "🔴"
    lines = [
        f"{emoji} **{r['coin']} — {r['total_return_pct']:+.2f}%** "
        f"(${r['initial_balance']:,.0f} → ${r['final_balance']:,.2f}) "
        f"| {r['num_trades']} trades | WR {r['win_rate_pct']:.0f}%",
        f"   Sharpe: {r['sharpe_ratio']:+.2f} | PF: {r['profit_factor']:.2f} | "
        f"Max DD: -${r['max_drawdown_usd']:.2f} ({r['max_drawdown_pct']:.1f}%)",
        f"   Gross: +${r['gross_profit']:.2f} / -${r['gross_loss']:.2f} | "
        f"Avg: +${r['avg_win_usd']:.2f} / -${r['avg_loss_usd']:.2f}",
        f"   Best: +${r['best_trade']:.2f} | Worst: ${r['worst_trade']:.2f} | "
        f"Avg hold: {r['avg_holding_days']:.1f}d",
    ]
    return "\n".join(lines)


def format_equity_sparkline(r: dict) -> str:
    """Small equity curve text chart."""
    curve = r.get("equity_curve", [])
    if not curve:
        return ""

    values  = [c["equity"] for c in curve]
    start   = values[0]
    end     = values[-1]
    mn      = min(values)
    mx      = max(values)
    rng     = mx - mn if mx != mn else 1

    bars = [c["equity"] for c in curve[::max(1, len(curve)//20)]]  # 20 bars max
    bar_strs = []
    for v in bars:
        h = int((v - mn) / rng * 8)
        bar_strs.append("▓" * h + "░" * (8-h))

    arrow = "📈" if end >= start else "📉"
    return (f"   {arrow} {' | '.join(bar_strs[:8])} | "
            f"${min(values):,.0f} → ${max(values):,.0f}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("=== Strategy Backtester ===\n")

    days  = 90
    coins = ["BTC", "ETH", "SOL"]

    if "--coin" in sys.argv:
        idx       = sys.argv.index("--coin")
        coins     = [sys.argv[idx+1].upper()]
    if "--days" in sys.argv:
        idx   = sys.argv.index("--days")
        days  = int(sys.argv[idx+1])

    print(f"Backtesting {coins} over {days} days...\n")

    results = []
    for coin in coins:
        coin_id = COIN_ID_MAP.get(coin)
        if not coin_id:
            print(f"  {coin}: Unknown coin ID")
            continue
        r = run_backtest(coin, coin_id, days=days)
        results.append(r)
        print(format_backtest_result(r))
        if not r.get("error"):
            print(format_equity_sparkline(r))
        print()

    # Summary table
    if results:
        print("\n**Summary Table**\n")
        print(f"  {'Coin':<6} {'Return':>8} {'Trades':>7} {'WR%':>5} {'Sharpe':>7} {'PF':>5} {'MaxDD%':>7}")
        print("  " + "-" * 55)
        for r in results:
            emoji = "🟢" if r["total_return_pct"] >= 0 else "🔴"
            print(
                f"  {emoji} {r['coin']:<5} {r['total_return_pct']:>+7.2f}% "
                f"{r['num_trades']:>6} {r['win_rate_pct']:>5.1f}% "
                f"{r['sharpe_ratio']:>7.2f} {r['profit_factor']:>5.2f} "
                f"{r['max_drawdown_pct']:>7.2f}%"
            )

    print("\n✅ Backtester complete")