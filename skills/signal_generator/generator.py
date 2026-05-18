"""
Signal Generator — generates BUY / SELL / NEUTRAL signals from price data.
Uses simple momentum + RSI-style overbought/oversold logic.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum
import json
import os

class Direction(Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"

@dataclass
class Signal:
    symbol: str
    direction: Direction
    score: int  # 0-100
    reason: str
    price: float

# Score thresholds
BUY_THRESHOLD = 70
SELL_THRESHOLD = 30

# 24h change thresholds for momentum component
STRONG_BULL = 5.0
BULL = 2.0
BEAR = -2.0
STRONG_BEAR = -5.0

def _momentum_score(change_pct: float) -> int:
    """Map 24h change to a 0-100 momentum score."""
    if change_pct >= STRONG_BULL:
        return 85
    elif change_pct >= BULL:
        return 70
    elif change_pct > BEAR:
        return 50
    elif change_pct > STRONG_BEAR:
        return 30
    else:
        return 15

# Momentum lookback thresholds (multi-timeframe)
def _multi_tf_score(prices: Dict[str, dict], cid: str) -> int:
    """
    Compute a composite momentum score using multiple timeframes if available.
    Falls back to 24h change if no extra data.
    """
    data = prices.get(cid, {})
    chg = data.get("usd_24h_change", 0) or 0
    base = _momentum_score(chg)

    # If we have 1h change data, blend it (30% weight)
    chg_1h = data.get("usd_1h_change")
    if chg_1h is not None:
        h1 = _momentum_score(chg_1h)
        base = int(base * 0.7 + h1 * 0.3)

    return max(0, min(100, base))

def generate_signals(prices: Dict[str, dict], symbol_map: Dict[str, str] = None,
                     enable_short: bool = False) -> List[Signal]:
    """
    prices: {coingecko_id: {"usd": float, "usd_24h_change": float, ...}, ...}
    symbol_map: {coingecko_id: "TICKER", ...} — optional mapping for display symbols
    enable_short: if True, SELL signals map to SHORT positions (else NEUTRAL)
    Returns list of Signal objects.
    """
    signals = []
    for cid, data in prices.items():
        price = data.get("usd", 0)
        chg = data.get("usd_24h_change", 0) or 0
        score = _multi_tf_score(prices, cid)

        if score >= BUY_THRESHOLD:
            direction = Direction.BUY
            reason = f"Momentum: +{chg:.2f}% (strong bullish)"
        elif score <= SELL_THRESHOLD:
            if enable_short:
                direction = Direction.SELL
                reason = f"Momentum: {chg:.2f}% (bearish → SHORT)"
            else:
                direction = Direction.NEUTRAL
                reason = f"Momentum: {chg:.2f}% (bearish, shorts disabled)"
        else:
            direction = Direction.NEUTRAL
            reason = f"Momentum: {chg:.2f}% (neutral range)"

        # Override: if Fear & Greed < 20 (extreme fear), flip SELL/NEUTRAL to BUY (mean reversion)
        fg_path = os.path.join(os.path.dirname(__file__), "../../logs/last_fear_greed.json")
        if os.path.exists(fg_path):
            try:
                with open(fg_path) as f:
                    fg = json.load(f)
                fg_val = fg.get("value", 50)
                if fg_val < 20 and direction in (Direction.SELL, Direction.NEUTRAL):
                    direction = Direction.BUY
                    score = max(score, 65)
                    reason += " | EXTREME FEAR mean-reversion boost"
                # Extreme greed > 75: flip BUY to NEUTRAL (take profits)
                elif fg_val > 75 and direction == Direction.BUY:
                    direction = Direction.NEUTRAL
                    score = min(score, 55)
                    reason += " | EXTREME GREED profit-taking signal"
            except Exception:
                pass

        symbol = symbol_map.get(cid, cid.upper()) if symbol_map else cid.upper()
        signals.append(Signal(
            symbol=symbol,
            direction=direction,
            score=score,
            reason=reason,
            price=price
        ))
    return signals

def format_signals(signals: List[Signal]) -> str:
    lines = ["## Trade Signals", ""]
    lines.append("| Asset | Direction | Score | Price | Reason |")
    lines.append("|-------|-----------|-------|-------|--------|")
    for s in signals:
        emoji = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}[s.direction.value]
        lines.append(f"| {s.symbol} | {emoji} {s.direction.value} | {s.score} | ${s.price:,.2f} | {s.reason} |")
    return "\n".join(lines)
