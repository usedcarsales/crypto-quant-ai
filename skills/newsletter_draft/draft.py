"""
Newsletter Draft Generator — turns paper trading signals into a quant brief.
Part of the Signal-to-Newsletter pipeline.

Usage:
    from skills.newsletter_draft.draft import draft_brief
    signals = [...]  # from signal_generator
    brief = draft_brief(signals, prices, fear_greed=(25, "Fear"))
"""

import json
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
import os

from skills.signal_generator.generator import Signal, Direction


@dataclass
class Brief:
    headline: str
    summary: str
    table_md: str
    action_items: List[str]
    generated_at: str


TOP_HOLDINGS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]


def _rank_signals(signals: List[Signal]) -> List[Signal]:
    """Sort by score descending, then BUY > NEUTRAL > SELL."""
    def key(s: Signal):
        dir_order = {"BUY": 3, "NEUTRAL": 2, "SELL": 1}
        return (s.score, dir_order.get(s.direction.value, 0))
    return sorted(signals, key=key, reverse=True)


def _mood_from_fear_greed(value: int) -> Tuple[str, str]:
    """Return (emoji, description) for Fear & Greed."""
    if value >= 75:
        return ("🟢", "Extreme Greed — consider profit-taking")
    elif value >= 55:
        return ("🟡", "Greed — momentum is strong")
    elif value >= 45:
        return ("⚪", "Neutral — no edge from sentiment")
    elif value >= 25:
        return ("🟠", "Fear — possible mean-reversion zone")
    else:
        return ("🔴", "Extreme Fear — contrarian opportunity")


def _headline(signals: List[Signal], fg_value: int) -> str:
    buys = sum(1 for s in signals if s.direction == Direction.BUY)
    sells = sum(1 for s in signals if s.direction == Direction.SELL)
    fg_emoji, fg_mood = _mood_from_fear_greed(fg_value)
    return f"{fg_emoji} {fg_mood} | {buys} BUY, {sells} SELL"


def draft_brief(
    signals: List[Signal],
    prices: Dict[str, dict],
    fear_greed: Tuple[Optional[int], str] = (None, "Unknown"),
    trending: List[str] = None,
    open_positions: List[dict] = None,
    stats: dict = None
) -> Brief:
    """
    Generate a quant brief from signals and market data.
    Returns a Brief dataclass with markdown-ready fields.
    """
    fg_value, fg_label = fear_greed
    fg_value = fg_value or 50
    now_et = datetime.now().strftime("%Y-%m-%d %I:%M %p ET")

    lines = []
    lines.append(f"# 🎯 QuantAlpha Brief — {now_et}")
    lines.append("")
    lines.append(f"**{_headline(signals, fg_value)}**")
    lines.append(f"*Fear & Greed: {fg_value} ({fg_label})*")
    lines.append("")

    # Summary paragraph
    ranked = _rank_signals(signals)
    top = ranked[0] if ranked else None
    summary = "Markets are mixed with no clear directional edge."
    if top and top.direction == Direction.BUY:
        summary = f"**{top.symbol}** leads bullish momentum with a score of {top.score}/100. Consider adding to long exposure."
    elif top and top.direction == Direction.SELL:
        summary = f"**{top.symbol}** flashes a SELL signal at {top.score}/100. Risk-off posture recommended."
    lines.append(f"**Summary:** {summary}")
    lines.append("")

    # Signals table
    lines.append("## Signals")
    lines.append("")
    lines.append("| Asset | Direction | Score | Price | Reason |")
    lines.append("|-------|-----------|-------|-------|--------|")
    for s in ranked:
        emoji = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}[s.direction.value]
        lines.append(f"| {s.symbol} | {emoji} {s.direction.value} | {s.score} | ${s.price:,.2f} | {s.reason} |")
    lines.append("")

    # Trending
    if trending:
        lines.append(f"**Trending:** {', '.join(trending[:10])}")
        lines.append("")

    # Open positions snapshot
    if open_positions:
        lines.append("## Active Positions")
        lines.append("")
        lines.append("| Asset | Direction | Entry | Unrealized |")
        lines.append("|-------|-----------|-------|------------|")
        for pos in open_positions:
            unrealized = pos.get("pnl", 0)
            lines.append(f"| {pos.get('symbol','').upper()} | {pos.get('direction','?')} | ${pos.get('entry_price',0):,.2f} | ${unrealized:+.2f} |")
        lines.append("")

    # Portfolio stats
    if stats:
        lines.append("## Portfolio")
        lines.append(f"- Value: ${stats.get('value',0):,.2f} | P&L: ${stats.get('total_pnl',0):+.2f}")
        lines.append(f"- Win Rate: {stats.get('win_rate',0):.1f}% | Max DD: {stats.get('max_drawdown_pct',0):.2f}%")
        lines.append("")

    # Action items
    actions = []
    buys = [s for s in signals if s.direction == Direction.BUY]
    if buys:
        actions.append(f"Consider LONG in: {', '.join(s.symbol for s in buys[:2])}")
    sells = [s for s in signals if s.direction == Direction.SELL]
    if sells:
        actions.append(f"SHORT candidates: {', '.join(s.symbol for s in sells[:2])}")
    if fg_value < 20:
        actions.append("Mean-reversion alert: extreme fear detected. Oversold bounce possible.")
    if fg_value > 75:
        actions.append("Profit-taking alert: extreme greed detected. Tighten stops.")

    if actions:
        lines.append("## Action Items")
        lines.append("")
        for i, a in enumerate(actions, 1):
            lines.append(f"{i}. {a}")
        lines.append("")

    lines.append("---")
    lines.append("*Generated by Clawd QuantAlpha Signal-to-Newsletter pipeline*")

    full_md = "\n".join(lines)

    return Brief(
        headline=_headline(signals, fg_value),
        summary=summary,
        table_md=full_md,
        action_items=actions,
        generated_at=datetime.now(timezone.utc).isoformat()
    )


def save_brief(brief: Brief, filename: str = None):
    """Save the brief to the memory and newsletter directories."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fname = filename or f"{date_str}-quantalpha-brief.md"

    # Primary save location
    out_dir = "/home/vinny2times/.openclaw/workspace/quant-trading/logs/newsletter_drafts"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, fname)
    with open(out_path, "w") as f:
        f.write(brief.table_md)

    # Also save to memory for operator visibility
    mem_path = f"/home/vinny2times/.openclaw/workspace/memory/{fname}"
    with open(mem_path, "w") as f:
        f.write(brief.table_md)

    return out_path


if __name__ == "__main__":
    # Demo/test run
    demo_signals = [
        Signal(symbol="BTC", direction=Direction.BUY, score=78, reason="Momentum: +3.2%", price=75000),
        Signal(symbol="ETH", direction=Direction.NEUTRAL, score=50, reason="Momentum: -0.1%", price=2300),
        Signal(symbol="SOL", direction=Direction.SELL, score=25, reason="Momentum: -4.1%", price=80),
    ]
    brief = draft_brief(demo_signals, {}, fear_greed=(18, "Extreme Fear"))
    print(brief.table_md)
    path = save_brief(brief, "demo-brief.md")
    print(f"\nSaved to: {path}")
