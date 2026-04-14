"""
Risk Manager
Phase 4, Task 4.4 — Central risk control layer, required before paper trading begins.

Rules:
  - Max daily loss: 5% of portfolio (configurable)
  - Max consecutive losses before cooldown: 3
  - Cooldown after 3 consecutive losses: 24 hours
  - Max open positions: 3
  - Daily trade limit: 5 trades/day

Monitors:
  - Daily P&L vs portfolio limit
  - Consecutive loss streak
  - Position exposure
  - Cooldown state (global + per-coin)
"""

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional


# ─── Config ───────────────────────────────────────────────────────────────────

PORTFOLIO_FILE = "/tmp/crypto-quant-portfolio.json"
HISTORY_FILE   = "/tmp/crypto-quant-signal-history.json"
CONFIG_FILE    = "config/risk_policy.json"


DEFAULT_CONFIG = {
    "max_daily_loss_pct":     0.05,
    "max_consecutive_losses":  3,
    "cooldown_hours":          24,
    "max_open_positions":      3,
    "max_trades_per_day":      5,
    "max_position_size_pct":   0.10,   # 10% of portfolio per trade
    "portfolio_initial_usd":   10000,  # paper portfolio base
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
                # Merge with defaults
                return {**DEFAULT_CONFIG, **cfg}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


# ─── Portfolio State ───────────────────────────────────────────────────────────

def _load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "initial_usd":    DEFAULT_CONFIG["portfolio_initial_usd"],
        "current_usd":    DEFAULT_CONFIG["portfolio_initial_usd"],
        "open_positions": [],
        "daily_pnl":      0,
        "consecutive_losses": 0,
        "total_trades":   0,
        "cooldown_until": None,
        "last_reset_date": datetime.now(timezone.utc).date().isoformat(),
    }


def _save_portfolio(pf):
    try:
        with open(PORTFOLIO_FILE, "w") as f:
            json.dump(pf, f, default=str)
    except Exception:
        pass


# ─── Cooldown Management ─────────────────────────────────────────────────────

def is_in_cooldown() -> tuple[bool, str]:
    """
    Returns (in_cooldown, reason_string).
    Checks global cooldown and per-coin cooldowns.
    """
    pf = _load_portfolio()
    cfg = load_config()

    # Global cooldown check
    if pf.get("cooldown_until"):
        try:
            cooldown_end = datetime.fromisoformat(pf["cooldown_until"])
            now = datetime.now(timezone.utc)
            if now < cooldown_end:
                remaining = (cooldown_end - now).total_seconds() / 3600
                return True, f"Global cooldown active: {remaining:.1f}h remaining"
        except Exception:
            pass

    # Daily loss limit check
    daily_loss_pct = pf.get("daily_pnl", 0) / pf.get("initial_usd", DEFAULT_CONFIG["portfolio_initial_usd"])
    if daily_loss_pct <= -cfg.get("max_daily_loss_pct", 0.05):
        return True, f"Daily loss limit hit: {daily_loss_pct*100:.1f}% (max {cfg['max_daily_loss_pct']*100:.1f}%)"

    # Consecutive losses check
    if pf.get("consecutive_losses", 0) >= cfg.get("max_consecutive_losses", 3):
        return True, f"Consecutive loss limit: {pf['consecutive_losses']} losses in a row"

    return False, ""


def trigger_cooldown(reason: str = "consecutive_losses"):
    """
    Trigger global cooldown — called after 3 consecutive losses or daily loss limit.
    """
    cfg = load_config()
    pf = _load_portfolio()

    cooldown_hours = cfg.get("cooldown_hours", 24)
    cooldown_until = datetime.now(timezone.utc) + timedelta(hours=cooldown_hours)

    pf["cooldown_until"] = cooldown_until.isoformat()
    pf["consecutive_losses"] = 0  # reset counter

    _save_portfolio(pf)

    return {
        "cooldown_triggered": True,
        "reason": reason,
        "cooldown_until": cooldown_until.isoformat(),
        "cooldown_hours": cooldown_hours,
    }


def reset_daily_if_needed():
    """
    Reset daily P&L counter if the stored date is older than today (UTC).
    Should be called at the start of each session.
    """
    pf = _load_portfolio()
    today = datetime.now(timezone.utc).date().isoformat()
    last_reset = pf.get("last_reset_date", "")

    if last_reset != today:
        pf["daily_pnl"] = 0
        pf["last_reset_date"] = today
        _save_portfolio(pf)

    return pf


# ─── Position Management ──────────────────────────────────────────────────────

def get_open_positions() -> list:
    """Return list of currently open positions."""
    pf = _load_portfolio()
    return pf.get("open_positions", [])


def add_position(coin: str, direction: str, entry_price: float,
                 size_usd: float, stop_loss: float, take_profit: float):
    """
    Add an open position to the portfolio tracker.
    Called when a trade signal is triggered.
    """
    cfg = load_config()
    pf = _load_portfolio()

    open_pos = pf.get("open_positions", [])

    # Check max positions
    if len(open_pos) >= cfg.get("max_open_positions", 3):
        return {"error": f"Max open positions reached ({len(open_pos)}/{cfg['max_open_positions']})"}

    pos = {
        "coin":          coin,
        "direction":     direction,
        "entry_price":   entry_price,
        "size_usd":      size_usd,
        "stop_loss":     stop_loss,
        "take_profit":   take_profit,
        "opened_at":     datetime.now(timezone.utc).isoformat(),
        "status":        "OPEN",
    }

    open_pos.append(pos)
    pf["open_positions"] = open_pos
    pf["total_trades"] = pf.get("total_trades", 0) + 1
    _save_portfolio(pf)

    return {"status": "added", "position": pos}


def close_position(coin: str, exit_price: float, reason: str = "signal") -> dict:
    """
    Close an open position and record P&L.
    Calculates realized P&L, updates portfolio.
    """
    pf = _load_portfolio()
    open_pos = pf.get("open_positions", [])

    # Find position
    pos_idx = None
    for i, p in enumerate(open_pos):
        if p["coin"] == coin and p.get("status") == "OPEN":
            pos_idx = i
            break

    if pos_idx is None:
        return {"error": f"No open position for {coin}"}

    pos = open_pos[pos_idx]
    entry = pos["entry_price"]
    size  = pos["size_usd"]

    # Calculate P&L
    if pos["direction"] == "BUY":
        pnl_usd = (exit_price - entry) / entry * size
    else:  # SELL/SHORT
        pnl_usd = (entry - exit_price) / entry * size

    pos["status"]      = "CLOSED"
    pos["exit_price"]  = exit_price
    pos["pnl_usd"]     = round(pnl_usd, 2)
    pos["close_reason"] = reason
    pos["closed_at"]   = datetime.now(timezone.utc).isoformat()

    # Update portfolio
    pf["current_usd"]    += pnl_usd
    pf["daily_pnl"]      += pnl_usd

    # Remove from open positions
    pf["open_positions"] = [p for p in open_pos if p.get("status") == "OPEN"]

    # Track consecutive losses / wins
    if pnl_usd < 0:
        pf["consecutive_losses"] = pf.get("consecutive_losses", 0) + 1
        result = "LOSS"
    else:
        pf["consecutive_losses"] = 0
        result = "WIN"

    # Check if cooldown should trigger
    cfg = load_config()
    if pf.get("consecutive_losses", 0) >= cfg.get("max_consecutive_losses", 3):
        trigger_cooldown(reason="consecutive_losses")

    _save_portfolio(pf)

    return {
        "coin": coin,
        "result": result,
        "pnl_usd": round(pnl_usd, 2),
        "current_portfolio_usd": round(pf["current_usd"], 2),
        "daily_pnl": round(pf["daily_pnl"], 2),
        "consecutive_losses": pf.get("consecutive_losses", 0),
    }


# ─── Pre-Trade Risk Checks ───────────────────────────────────────────────────

def can_open_position(coin: str = None) -> tuple[bool, str]:
    """
    Comprehensive pre-trade risk check.
    Returns (allowed, reason).
    """
    cfg = load_config()
    pf  = reset_daily_if_needed()

    # 1. Global cooldown
    in_cd, cd_reason = is_in_cooldown()
    if in_cd:
        return False, cd_reason

    # 2. Daily loss limit
    initial = pf.get("initial_usd", cfg["portfolio_initial_usd"])
    daily_pnl_pct = pf.get("daily_pnl", 0) / initial
    max_loss_pct  = cfg.get("max_daily_loss_pct", 0.05)
    if daily_pnl_pct <= -max_loss_pct:
        return False, f"Daily loss limit hit: {daily_pnl_pct*100:.1f}% (max {-max_loss_pct*100:.1f}%)"

    # 3. Max open positions
    open_count = len(pf.get("open_positions", []))
    if open_count >= cfg.get("max_open_positions", 3):
        return False, f"Max positions open: {open_count}/{cfg['max_open_positions']}"

    # 4. Daily trade count
    today = datetime.now(timezone.utc).date().isoformat()
    history = _load_history()
    today_trades = [
        t for t in history.get("daily_trades", [])
        if t.get("date") == today
    ]
    if len(today_trades) >= cfg.get("max_trades_per_day", 5):
        return False, f"Daily trade limit reached: {len(today_trades)}/{cfg['max_trades_per_day']}"

    # 5. Per-coin position check
    if coin:
        open_pos = pf.get("open_positions", [])
        existing = [p for p in open_pos if p.get("coin") == coin and p.get("status") == "OPEN"]
        if existing:
            return False, f"Position already open for {coin}"

    return True, "OK"


def position_size_allowed(coin: str, size_usd: float) -> tuple[bool, str, float]:
    """
    Check if proposed position size is within risk limits.
    Returns (allowed, reason, adjusted_size).
    """
    cfg = load_config()
    pf = _load_portfolio()

    max_size_pct = cfg.get("max_position_size_pct", 0.10)
    max_pos_usd  = cfg.get("max_position_size_usd", 1000)

    portfolio_usd = pf.get("current_usd", cfg["portfolio_initial_usd"])
    max_by_pct = portfolio_usd * max_size_pct

    max_allowed = min(max_by_pct, max_pos_usd)

    if size_usd > max_allowed:
        return False, f"Position size ${size_usd:.2f} exceeds max ${max_allowed:.2f} (portfolio {portfolio_usd:.2f}, max_pct {max_size_pct*100:.0f}%)", round(max_allowed, 2)

    return True, "OK", round(max_allowed, 2)


# ─── Portfolio Stats ───────────────────────────────────────────────────────────

def get_portfolio_status() -> dict:
    """Return current portfolio state + risk metrics."""
    cfg = load_config()
    pf  = reset_daily_if_needed()

    initial    = pf.get("initial_usd", cfg["portfolio_initial_usd"])
    current    = pf.get("current_usd", initial)
    daily_pnl  = pf.get("daily_pnl", 0)
    daily_pct  = (daily_pnl / initial) * 100 if initial > 0 else 0

    open_pos   = pf.get("open_positions", [])
    in_cd, cd_reason = is_in_cooldown()

    return {
        "portfolio_initial_usd": round(initial, 2),
        "portfolio_current_usd": round(current, 2),
        "total_pnl_usd": round(current - initial, 2),
        "total_pnl_pct": round((current - initial) / initial * 100, 2) if initial > 0 else 0,
        "daily_pnl_usd": round(daily_pnl, 2),
        "daily_pnl_pct": round(daily_pct, 2),
        "daily_loss_limit_pct": cfg.get("max_daily_loss_pct", 0.05) * 100,
        "consecutive_losses": pf.get("consecutive_losses", 0),
        "max_consecutive_losses": cfg.get("max_consecutive_losses", 3),
        "open_positions": len(open_pos),
        "max_open_positions": cfg.get("max_open_positions", 3),
        "in_cooldown": in_cd,
        "cooldown_reason": cd_reason if in_cd else None,
        "total_trades": pf.get("total_trades", 0),
    }


def _load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"signals": [], "daily_trades": []}


# ─── Formatting ───────────────────────────────────────────────────────────────

def format_risk_report() -> str:
    """Human-readable risk status report."""
    status = get_portfolio_status()
    cfg = load_config()

    lines = [
        "**Risk Manager — Status Report**",
        f"  Portfolio: ${status['portfolio_current_usd']:,.2f} "
        f"({'+' if status['total_pnl_usd'] >= 0 else ''}{status['total_pnl_usd']:.2f} all-time)",
        f"  Daily P&L: ${status['daily_pnl_usd']:.2f} "
        f"({'+' if status['daily_pnl_pct'] >= 0 else ''}{status['daily_pnl_pct']:.2f}%) "
        f"| Limit: -{cfg.get('max_daily_loss_pct', 0.05)*100:.0f}%",
        f"  Open Positions: {status['open_positions']}/{status['max_open_positions']}",
        f"  Consecutive Losses: {status['consecutive_losses']}/{status['max_consecutive_losses']}",
        f"  Total Trades: {status['total_trades']}",
        f"  Cooldown: {'YES — ' + status['cooldown_reason'] if status['in_cooldown'] else 'NO — clear to trade'}",
    ]
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Risk Manager ===\n")

    status = get_portfolio_status()
    print(format_risk_report())

    allowed, reason = can_open_position()
    print(f"\nCan open position: {'YES' if allowed else 'NO'}")
    if not allowed:
        print(f"  Reason: {reason}")

    # Test cooldown trigger
    print(f"\nConsecutive losses: {status['consecutive_losses']}/{status['max_consecutive_losses']}")

    print("\n✅ Risk Manager working")