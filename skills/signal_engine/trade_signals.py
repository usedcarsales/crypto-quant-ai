"""
Trade Signal Generator
Phase 4, Task 4.1 — Takes correlation engine output → produces actionable trade signals

Input:
  - Correlation engine output (skills/correlation_engine/correlation.py)
  - risk_policy.json rules

Output:
  - Trade signals: {coin, direction, entry, stop_loss, take_profit, confidence, risk_score}
  - Signal thresholds:
      confidence ≥ 70 → STRONG BUY/SELL
      50-69           → MODERATE BUY/SELL
      < 50            → NEUTRAL (no trade)
  - Stop-loss: ATR-based (1.5x ATR from entry)
  - Take-profit: 2:1 minimum risk/reward
"""

import importlib.util as _spec
import json
import os
from datetime import datetime, timezone
from typing import Optional


# ─── Load Dependencies ─────────────────────────────────────────────────────────

def _load_mod(name, path):
    s = _spec.spec_from_file_location(name, path)
    m = _spec.module_from_spec(s)
    s.loader.exec_module(m)
    return m

CORR_MOD = _load_mod("corr", "skills/correlation_engine/correlation.py")


# ─── Config ───────────────────────────────────────────────────────────────────

CONFIG_DIR = "config"
RISK_POLICY_FILE = f"{CONFIG_DIR}/risk_policy.json"


def load_risk_policy():
    if os.path.exists(RISK_POLICY_FILE):
        with open(RISK_POLICY_FILE) as f:
            return json.load(f)
    return {
        "max_position_size_usd": 1000,
        "max_daily_loss_usd": 100,
        "min_confidence_to_trade": 45,
        "strong_signal_threshold": 70,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_min_ratio": 2.0,
        "cooldown_minutes": 60,
        "max_positions_open": 3,
        "max_trades_per_day": 5,
        "risk_per_trade_pct": 0.01,
    }


# ─── ATR Stop-Loss / Take-Profit ──────────────────────────────────────────────

def calc_stop_loss(entry_price: float, atr: float, multiplier: float = 1.5) -> float:
    """Return stop-loss price given entry and ATR."""
    sl_distance = atr * multiplier
    return round(entry_price - sl_distance, 4)


def calc_take_profit(entry_price: float, stop_loss: float, min_ratio: float = 2.0) -> float:
    """Return take-profit price given entry, stop-loss, and minimum risk/reward ratio."""
    risk = entry_price - stop_loss
    reward = risk * min_ratio
    return round(entry_price + reward, 4)


# ─── Position Sizing ───────────────────────────────────────────────────────────

def calc_position_size(entry: float, stop_loss: float, risk_usd: float, risk_pct: float = 0.01) -> dict:
    """
    Calculate position size based on risk amount and risk percentage of portfolio.
    Returns: {size_usd, size_units, risk_amount, risk_pct_actual}
    """
    risk_per_unit = abs(entry - stop_loss)
    if risk_per_unit == 0:
        return {"size_usd": 0, "size_units": 0, "risk_amount": 0, "risk_pct_actual": 0}

    # Risk dollar amount
    risk_amount = min(risk_usd, entry * risk_pct * 10)  # cap at 1% of hypothetical $10k portfolio
    size_usd = (risk_amount / risk_per_unit) * entry
    size_units = size_usd / entry
    risk_pct_actual = (risk_amount / (entry * size_units)) if entry * size_units > 0 else 0

    return {
        "size_usd": round(size_usd, 2),
        "size_units": round(size_units, 6),
        "risk_amount": round(risk_amount, 2),
        "risk_pct_actual": round(risk_pct_actual * 100, 2),
    }


# ─── Core Signal Generator ────────────────────────────────────────────────────

SIGNAL_HISTORY_FILE = "/tmp/crypto-quant-signal-history.json"

def _load_history():
    if os.path.exists(SIGNAL_HISTORY_FILE):
        try:
            with open(SIGNAL_HISTORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"signals": [], "daily_trades": [], "last_trade_time": None}


def _save_history(history):
    try:
        with open(SIGNAL_HISTORY_FILE, "w") as f:
            json.dump(history, f, default=str)
    except Exception:
        pass


def generate_signal(
    coin: str,
    direction: str = None,
    composite_score: float = None,
    confidence: str = None,
    divergence: bool = None,
    current_price: float = None,
    atr: float = None,
    risk_policy: dict = None,
) -> dict:
    """
    Generate a trade signal from correlation engine output.

    Args:
        coin:           e.g. "BTC", "ETH"
        direction:      "BUY" / "SELL" / "NEUTRAL" (from correlation engine)
        composite_score: 0-100 composite score
        confidence:     "high" / "medium" / "low"
        divergence:     True if signals disagree
        current_price:  Current price for entry calculation
        atr:            ATR value for stop-loss calculation
        risk_policy:    Override risk policy dict

    Returns:
        {
          coin, direction, signal_type (STRONG/MODERATE/NEUTRAL),
          entry_price, stop_loss, take_profit,
          confidence_score, risk_score (low/medium/high),
          position_size_usd, risk_amount,
          timestamp, reason
        }
    """
    if risk_policy is None:
        risk_policy = load_risk_policy()

    history = _load_history()

    # ── 1. Validate composite score ────────────────────────────────────────────
    if composite_score is None:
        return {"coin": coin, "error": "No composite score provided", "signal": "NEUTRAL"}

    # ── 2. Check cooldown ─────────────────────────────────────────────────────
    last_time = history.get("last_trade_time")
    cooldown_sec = risk_policy.get("cooldown_minutes", 60) * 60
    if last_time:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last_time)).total_seconds()
        if elapsed < cooldown_sec:
            return {
                "coin": coin,
                "signal": "NEUTRAL",
                "reason": f"Cooldown active ({int(cooldown_sec - elapsed)}s remaining)",
                "direction": "NEUTRAL",
            "composite_score": composite_score,
            }

    # ── 3. Check daily trade count ─────────────────────────────────────────────
    today = datetime.now(timezone.utc).date().isoformat()
    daily_trades = history.get("daily_trades", [])
    today_trades = [t for t in daily_trades if t.get("date") == today]
    if len(today_trades) >= risk_policy.get("max_trades_per_day", 5):
        return {
            "coin": coin,
            "signal": "NEUTRAL",
            "reason": f"Daily trade limit reached ({len(today_trades)}/{risk_policy.get('max_trades_per_day', 5)})",
            "direction": "NEUTRAL",
            "composite_score": composite_score,
        }

    # ── 4. Check open positions ────────────────────────────────────────────────
    open_pos = [s for s in history.get("signals", []) if s.get("status") == "OPEN"]
    if len(open_pos) >= risk_policy.get("max_positions_open", 3):
        return {
            "coin": coin,
            "signal": "NEUTRAL",
            "reason": f"Max open positions reached ({len(open_pos)}/{risk_policy.get('max_positions_open', 3)})",
            "direction": "NEUTRAL",
            "composite_score": composite_score,
        }

    # ── 5. Confidence threshold ────────────────────────────────────────────────
    min_conf = risk_policy.get("min_confidence_to_trade", 45)
    strong_thresh = risk_policy.get("strong_signal_threshold", 70)

    # Map confidence string to numeric
    conf_map = {"high": 85, "medium": 65, "low": 40}
    conf_numeric = conf_map.get(confidence, 50)

    if conf_numeric < min_conf:
        return {
            "coin": coin,
            "direction": direction or "NEUTRAL",
            "signal": "NEUTRAL",
            "reason": f"Confidence {conf_numeric} < minimum {min_conf}",
            "composite_score": composite_score,
        }

    # ── 6. Divergence check ─────────────────────────────────────────────────────
    if divergence and conf_numeric < strong_thresh:
        return {
            "coin": coin,
            "direction": direction or "NEUTRAL",
            "signal": "NEUTRAL",
            "reason": f"Divergence detected — skipping (confidence {conf_numeric} below strong threshold {strong_thresh})",
            "composite_score": composite_score,
            "divergence": True,
        }

    # ── 7. Direction determination ──────────────────────────────────────────────
    if composite_score >= strong_thresh:
        signal_type = "STRONG"
        actual_direction = "BUY" if direction == "BUY" else "SELL"
    elif composite_score >= min_conf:
        signal_type = "MODERATE"
        actual_direction = "BUY" if composite_score >= 50 else "SELL"
    else:
        return {
            "coin": coin,
            "direction": direction or "NEUTRAL",
            "signal": "NEUTRAL",
            "reason": f"Composite score {composite_score} below minimum {min_conf}",
            "composite_score": composite_score,
        }

    # ── 8. Price and ATR ────────────────────────────────────────────────────────
    if current_price is None:
        # Get current price from TA module
        coin_id_map = {
            "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
            "BNB": "binancecoin", "XRP": "ripple", "DOGE": "dogecoin",
            "ADA": "cardano", "AVAX": "avalanche-2", "LINK": "chainlink",
        }
        cid = coin_id_map.get(coin, coin.lower())
        price_data = price_mod.get_simple_price([cid], ["usd"])
        current_price = price_data.get(cid, {}).get("usd") if price_data else None

    if current_price is None:
        return {"coin": coin, "error": "Could not determine entry price", "signal": "NEUTRAL"}

    # ── 9. ATR ─────────────────────────────────────────────────────────────────
    if atr is None:
        try:
            ta_spec = _spec.spec_from_file_location("ta", "skills/ta_engine/analyze.py")
            ta_mod = _spec.module_from_spec(ta_spec)
            ta_spec.loader.exec_module(ta_mod)
            ta_data = ta_mod.analyze(coin, coin_id_map.get(coin, coin.lower()), days=30)
            atr = ta_data.get("indicators", {}).get("atr_14")
        except Exception:
            atr = current_price * 0.015  # fallback: 1.5% ATR approximation

    if atr is None or atr == 0:
        atr = current_price * 0.015

    # ── 10. Stop-loss and take-profit ──────────────────────────────────────────
    sl_multiplier = risk_policy.get("stop_loss_atr_multiplier", 1.5)
    tp_ratio = risk_policy.get("take_profit_min_ratio", 2.0)

    if actual_direction == "BUY":
        stop_loss = calc_stop_loss(current_price, atr, sl_multiplier)
        take_profit = calc_take_profit(current_price, stop_loss, tp_ratio)
    else:  # SELL
        stop_loss = round(current_price + atr * sl_multiplier, 4)
        take_profit = round(current_price - atr * tp_ratio, 4)

    # ── 11. Risk scoring ────────────────────────────────────────────────────────
    # Risk score: low/medium/high based on ATR distance as % of entry
    sl_distance_pct = abs(current_price - stop_loss) / current_price * 100

    if sl_distance_pct < 1.0:    risk_score = "low"
    elif sl_distance_pct < 2.5:  risk_score = "medium"
    else:                         risk_score = "high"

    # ── 12. Position sizing ─────────────────────────────────────────────────────
    max_pos = risk_policy.get("max_position_size_usd", 1000)
    risk_per_trade = risk_policy.get("risk_per_trade_pct", 0.01)

    risk_usd = min(max_pos * risk_per_trade, risk_policy.get("max_daily_loss_usd", 100))
    pos = calc_position_size(current_price, stop_loss, risk_usd, risk_per_trade)
    size_usd = min(pos["size_usd"], max_pos)

    # ── 13. Build signal ─────────────────────────────────────────────────────────
    signal = {
        "coin": coin,
        "direction": actual_direction,
        "signal_type": signal_type,
        "entry_price": round(current_price, 4),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward_ratio": round((take_profit - current_price) / (current_price - stop_loss), 2)
                           if actual_direction == "BUY" else
                           round((current_price - take_profit) / (stop_loss - current_price), 2),
        "composite_score": round(composite_score, 1),
        "confidence_score": conf_numeric,
        "risk_score": risk_score,
        "position_size_usd": size_usd,
        "position_size_units": round(size_usd / current_price, 6),
        "risk_amount": round(abs(current_price - stop_loss) * (size_usd / current_price), 2),
        "atr_used": round(atr, 4),
        "divergence": divergence,
        "reason": _build_reason(signal_type, actual_direction, composite_score, conf_numeric, divergence),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "OPEN",
    }

    # ── 14. Save to history ─────────────────────────────────────────────────────
    if "daily_trades" not in history:
        history["daily_trades"] = []
    if "last_trade_time" not in history:
        history["last_trade_time"] = None
    history["signals"].append(signal)
    history["daily_trades"].append({"date": today, "coin": coin, "direction": actual_direction})
    history["last_trade_time"] = datetime.now(timezone.utc).isoformat()
    _save_history(history)

    return signal


def _build_reason(sig_type: str, direction: str, composite: float, conf: int, divergence: bool) -> str:
    parts = [
        f"{sig_type} {direction}",
        f"composite {composite:.0f}/100",
        f"confidence {conf}",
    ]
    if divergence:
        parts.append("DIVERGENCE WARNING")
    return " | ".join(parts)


# ─── Convenience: All Coins ────────────────────────────────────────────────────

def generate_all_signals() -> list:
    """
    Run correlation engine for all configured coins,
    then generate trade signals for each.
    Returns list of signals (including NEUTRAL skips with reason).
    """
    try:
        results = CORR_MOD.score_all()
    except Exception as e:
        return [{"error": str(e)}]

    signals = []
    for r in results:
        coin = r.get("symbol", r.get("coin", "UNKNOWN"))
        sig = generate_signal(
            coin=coin,
            direction=r.get("signal"),
            composite_score=r.get("composite_score"),
            confidence=r.get("confidence"),
            divergence=r.get("divergence"),
            current_price=r.get("ta_data", {}).get("current_price"),
        )
        sig["coin"] = coin
        signals.append(sig)

    return signals


# ─── Signal History & Stats ────────────────────────────────────────────────────

def get_open_positions() -> list:
    """Return all open (unfilled/active) trade signals."""
    history = _load_history()
    return [s for s in history.get("signals", []) if s.get("status") == "OPEN"]


def close_signal(coin: str, reason: str = "manual") -> dict:
    """Close an open position by marking it closed."""
    history = _load_history()
    for s in history["signals"]:
        if s.get("coin") == coin and s.get("status") == "OPEN":
            s["status"] = "CLOSED"
            s["close_reason"] = reason
            s["close_time"] = datetime.now(timezone.utc).isoformat()
            _save_history(history)
            return s
    return {"error": f"No open position found for {coin}"}


def get_daily_pnl() -> dict:
    """Calculate daily P&L from closed signals."""
    history = _load_history()
    today = datetime.now(timezone.utc).date().isoformat()
    closed_today = [
        s for s in history.get("signals", [])
        if s.get("status") == "CLOSED"
        and s.get("close_time", "").startswith(today)
    ]
    if not closed_today:
        return {"date": today, "trades": 0, "pnl_usd": 0, "wins": 0, "losses": 0}

    pnl = sum(float(s.get("pnl_usd", 0)) for s in closed_today)
    wins = sum(1 for s in closed_today if float(s.get("pnl_usd", 0)) > 0)
    return {
        "date": today,
        "trades": len(closed_today),
        "pnl_usd": round(pnl, 2),
        "wins": wins,
        "losses": len(closed_today) - wins,
    }


# ─── Formatting ───────────────────────────────────────────────────────────────

def format_signal(sig: dict) -> str:
    """Human-readable trade signal."""
    if "error" in sig and sig.get("signal") == "NEUTRAL" and "reason" in sig:
        return f"⚪ **{sig['coin']}** — NEUTRAL ({sig.get('reason', 'thresholds not met')})"

    emoji_dir = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}.get(sig.get("direction"), "⚪")
    sig_type = sig.get("signal_type", "NEUTRAL")
    confidence = sig.get("confidence_score", 0)

    risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(sig.get("risk_score", "?"), "?")

    lines = [
        f"{emoji_dir} **{sig['coin']} — {sig_type} {sig.get('direction')}**",
        f"   Entry: ${sig.get('entry_price', 0):,.4f}",
        f"   Stop:  ${sig.get('stop_loss', 0):,.4f} (ATR {sig.get('atr_used', 0):,.4f})",
        f"   TP:    ${sig.get('take_profit', 0):,.4f} (R/R {sig.get('risk_reward_ratio', 0):.1f}:1)",
        f"   Score: {sig.get('composite_score', 0)}/100 | Conf: {confidence} | Risk: {risk_icon} {sig.get('risk_score', '?').upper()}",
        f"   Size: ${sig.get('position_size_usd', 0):.2f} ({sig.get('position_size_units', 0):.4f} {sig['coin']}) | Risk: ${sig.get('risk_amount', 0):.2f}",
        f"   Reason: {sig.get('reason', 'n/a')}",
    ]
    return "\n".join(lines)


def format_all_signals(signals: list) -> str:
    """Formatted summary of all signals."""
    lines = ["**Trade Signal Matrix**\n"]
    for s in signals:
        if s.get("signal") not in ("NEUTRAL", "STRONG", "MODERATE") and "error" in s:
            lines.append(f"⚠️ {s['coin']}: {s['error']}")
        elif s.get("signal") in ("STRONG", "MODERATE"):
            lines.append(format_signal(s))
        else:
            lines.append(format_signal(s))
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Trade Signal Generator ===\n")

    # BTC single-symbol test (avoids multi-API rate limiting)
    import importlib.util as iu
    ta_spec = iu.spec_from_file_location("ta", "skills/ta_engine/analyze.py")
    ta_mod = iu.module_from_spec(ta_spec); ta_spec.loader.exec_module(ta_mod)
    ta_data = ta_mod.analyze("BTC", "bitcoin", 30)

    sig = generate_signal(
        coin="BTC",
        direction="BUY",
        composite_score=68,
        confidence="HIGH",
        divergence=False,
        current_price=ta_data.get("current_price"),
        atr=ta_data.get("indicators", {}).get("atr_14", 0),
    )
    print(format_signal(sig))

    stats = get_daily_pnl()
    print(f"\nDaily: {stats['trades']} trades | P&L: ${stats['pnl_usd']:.2f} | W: {stats['wins']} L: {stats['losses']}")
    print(f"Open positions: {len(get_open_positions())}")
    print("\n✅ Trade Signal Generator working")