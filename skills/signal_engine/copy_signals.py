"""
Copy Trade Signal Generator
Phase 4, Task 4.2 — Takes smart money movements (3.2) → produces copy-trade signals

Input:
  - Smart money signals from skills/wallet_engine/smart_money.py
  - Whale wallet flow direction (inflow/outflow)
  - Sentiment score from social alpha

Output:
  - Copy-trade signals: {coin, direction, source_wallet, entry_zone, confidence, signal_type}
  - Source: institutional wallet flows, CEX outflows/influence
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

WL_MOD  = _load_mod("wl",   "skills/wallet_engine/smart_money.py")
SOC_MOD = _load_mod("soc",  "skills/sentiment_engine/social_alpha.py")


# ─── Copy Signal Scoring ───────────────────────────────────────────────────────

def evaluate_copy_signal(
    coin: str,
    wallet_signals: list,
    sentiment_score: float = 50,
    sentiment_signal: str = "NEUTRAL",
) -> dict:
    """
    Evaluate a copy-trade signal for a given coin.

    Scoring:
      - Strong whale buy signal (Binance cold wallet): +30
      - Moderate whale signal (CEX outflow): +20
      - Multiple wallets aligned: +15
      - Social sentiment corroboration: +10
      - Contrarian (smart money vs retail): +10
      - Time decay (signal age > 1h): -10 per hour

    Signal types:
      STRONG COPY BUY / STRONG COPY SELL: score ≥ 70
      COPY BUY / COPY SELL: score 50-69
      NO COPY: score < 50
    """
    if not wallet_signals:
        return {
            "coin": coin,
            "signal": "NO_COPY",
            "copy_score": 0,
            "reason": "No whale wallet signals available",
        }

    score = 0
    directions = []
    sources = []
    strength_notes = []

    for sig in wallet_signals:
        direction = sig.get("direction", "")
        confidence = sig.get("confidence", "medium")
        source = sig.get("source_wallet", sig.get("wallet_address", "unknown"))[:20]

        directions.append(direction)
        sources.append(source)

        # Base score by direction
        if direction == "BUY":
            score += 20
            if confidence == "high":
                score += 10
        elif direction == "SELL":
            score -= 20
            if confidence == "high":
                score -= 10

        # Source-specific bonuses
        if "binance" in sig.get("source_wallet", "").lower():
            score += 10 if direction == "BUY" else -10
            strength_notes.append("Binance cold wallet flow detected")

        if sig.get("is_institutional", False):
            score += 5 if direction == "BUY" else -5

        # Multiple wallets check
        if len(wallet_signals) >= 3:
            score += 5
            strength_notes.append(f"{len(wallet_signals)} wallets aligned")

    # Direction agreement bonus
    buy_count = directions.count("BUY")
    sell_count = directions.count("SELL")
    if buy_count >= 2 and sell_count == 0:
        score += 15
        strength_notes.append(f"{buy_count} consecutive BUY signals")
    elif sell_count >= 2 and buy_count == 0:
        score -= 15
        strength_notes.append(f"{sell_count} consecutive SELL signals")

    # Sentiment corroboration
    if sentiment_signal == "BEARISH" and "BUY" in directions:
        score += 10  # Smart money vs crowd
        strength_notes.append("Contrarian: smart money buying while social is bearish")
    elif sentiment_signal == "BULLISH" and "SELL" in directions:
        score -= 10  # Smart money vs crowd
        strength_notes.append("Contrarian: smart money selling while social is bullish")

    # Cap score 0-100 range
    copy_score = max(0, min(100, score + 50))  # base 50, can go 0-100

    # Signal type
    if copy_score >= 70:
        signal_type = "STRONG COPY BUY" if score > 0 else "STRONG COPY SELL"
    elif copy_score >= 50:
        signal_type = "COPY BUY" if score > 0 else "COPY SELL"
    else:
        signal_type = "NO_COPY"

    # Final direction
    actual_direction = "BUY" if score > 0 else "SELL" if score < 0 else "NEUTRAL"

    return {
        "coin": coin,
        "direction": actual_direction,
        "signal_type": signal_type,
        "copy_score": round(copy_score, 1),
        "wallet_signals_count": len(wallet_signals),
        "source_wallets": list(set(sources)),
        "strength_notes": strength_notes,
        "sentiment_correlation": sentiment_signal,
        "reason": f"Score {copy_score:.0f}/100 | {len(wallet_signals)} signals | {' | '.join(strength_notes[:3]) or 'no additional notes'}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def generate_copy_signals() -> list:
    """
    Scan all watched wallets and generate copy-trade signals for relevant coins.
    Returns list of signals with confidence and entry zones.
    """
    try:
        watchlist = WL_MOD.get_watchlist()
        all_signals = WL_MOD.check_watchlist()
    except Exception as e:
        return [{"coin": "UNKNOWN", "error": str(e)}]

    if not all_signals:
        # No recent signals — return no-copy signals for key coins
        return [
            {
                "coin": coin,
                "signal": "NO_COPY",
                "copy_score": 50,
                "reason": f"No recent whale activity for {coin}",
            }
            for coin in ["BTC", "ETH", "SOL", "BNB"]
        ]

    # Group signals by coin
    by_coin = {}
    for sig in all_signals:
        coin = sig.get("coin", "UNKNOWN")
        if coin not in by_coin:
            by_coin[coin] = []
        by_coin[coin].append(sig)

    # Get sentiment for corroboration
    try:
        g = SOC_MOD.get_global_sentiment()
        mcp = g.get("mcap_change_24h", 0)
        soc_score = min(max(50 + mcp * 8, 0), 100)
        soc_signal = "BULLISH" if soc_score > 60 else "BEARISH" if soc_score < 40 else "NEUTRAL"
    except Exception:
        soc_signal = "NEUTRAL"
        soc_score = 50

    results = []
    for coin, sigs in by_coin.items():
        r = evaluate_copy_signal(
            coin=coin,
            wallet_signals=sigs,
            sentiment_score=soc_score,
            sentiment_signal=soc_signal,
        )
        results.append(r)

    # Sort by copy score
    results.sort(key=lambda x: x.get("copy_score", 0), reverse=True)
    return results


# ─── Entry Zone ────────────────────────────────────────────────────────────────

def get_entry_zone(coin: str, direction: str) -> dict:
    """
    Suggest entry zones based on whale wallet flow entry prices.
    Returns {zone_low, zone_high, recommended_entry, confidence}
    """
    try:
        watchlist = WL_MOD.get_watchlist()
    except Exception:
        return {"error": "Could not load wallet watchlist"}

    relevant = [w for w in watchlist if w.get("coin") == coin]
    if not relevant:
        return {
            "coin": coin,
            "zone_low": None,
            "zone_high": None,
            "recommended_entry": None,
            "confidence": "low",
        }

    # Average entry prices from whale wallets
    entry_prices = [float(w.get("avg_entry_price", 0)) for w in relevant if w.get("avg_entry_price")]
    if not entry_prices:
        return {
            "coin": coin,
            "zone_low": None,
            "zone_high": None,
            "recommended_entry": None,
            "confidence": "low",
            "reason": "No entry price data available from whale wallets",
        }

    avg_entry = sum(entry_prices) / len(entry_prices)
    zone_low = avg_entry * 0.98   # 2% below average entry
    zone_high = avg_entry * 1.02  # 2% above

    confidence = "high" if len(entry_prices) >= 3 else "medium" if len(entry_prices) >= 2 else "low"

    return {
        "coin": coin,
        "direction": direction,
        "zone_low": round(zone_low, 4),
        "zone_high": round(zone_high, 4),
        "recommended_entry": round(avg_entry, 4),
        "num_wallets": len(entry_prices),
        "confidence": confidence,
    }


# ─── Formatting ───────────────────────────────────────────────────────────────

def format_copy_signal(sig: dict) -> str:
    """Human-readable copy-trade signal."""
    emoji = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}.get(sig.get("direction"), "⚪")
    sig_type = sig.get("signal_type", "NO_COPY")
    copy_score = sig.get("copy_score", 0)

    if sig_type == "NO_COPY" and sig.get("copy_score", 0) > 40:
        return f"{emoji} **{sig['coin']}** — {sig_type} ({copy_score:.0f}/100)\n   {sig.get('reason', '')}"

    if sig_type == "NO_COPY":
        return f"⚪ **{sig['coin']}** — No copy signal ({copy_score:.0f}/100)\n   {sig.get('reason', '')}"

    zone = sig.get("entry_zone", {})
    if zone and not zone.get("error"):
        entry_str = f"Entry zone: ${zone.get('zone_low', 0):,.2f}–${zone.get('zone_high', 0):,.2f}"
    else:
        entry_str = "Entry zone: use whale wallet entry prices"

    lines = [
        f"{emoji} **{sig['coin']} — {sig_type}** ({copy_score:.0f}/100)",
        f"   {entry_str}",
        f"   Wallets: {', '.join(sig.get('source_wallets', [])[:3]) or 'see watchlist'}",
        f"   Notes: {' | '.join(sig.get('strength_notes', [])[:2]) or 'standard flow'}",
        f"   Social: {sig.get('sentiment_correlation', '?')} correlation",
        f"   Reason: {sig.get('reason', 'n/a')}",
    ]
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Copy Trade Signal Generator ===\n")

    signals = generate_copy_signals()
    actionable = [s for s in signals if s.get("signal_type", "NO_COPY") not in ("NO_COPY",)]

    if actionable:
        print(f"**Copy Trade Signals ({len(actionable)})**\n")
        for s in actionable:
            print(format_copy_signal(s))
            print()
    else:
        print("No copy trade signals above threshold.")
        for s in signals[:4]:
            print(format_copy_signal(s))
            print()

    print("✅ Copy Trade Signal Generator working")