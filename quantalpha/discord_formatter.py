"""
QuantAlpha Discord Embed Formatter

Creates rich Discord embed objects for the free-tier daily brief.
Designed for OpenClaw message tool compatibility.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

FREE_COINS = ["bitcoin", "ethereum", "solana"]


def _signal_color(signal: str) -> int:
    """Map signal to Discord embed color (integer)."""
    s = str(signal).upper()
    if "BUY" in s and "STRONG" in s:
        return 0x00C853  # Bright green
    elif "BUY" in s:
        return 0x4CAF50  # Green
    elif "SELL" in s and "STRONG" in s:
        return 0xFF1744  # Bright red
    elif "SELL" in s:
        return 0xF44336  # Red
    else:
        return 0xFFC107  # Amber/neutral


def format_discord_embed(report_data: Dict, coins: List[str] = None) -> Dict:
    """
    Generate Discord embed payload for the free-tier QuantAlpha brief.
    
    Returns a dict compatible with Discord message embeds.
    """
    if coins is None:
        coins = FREE_COINS
    
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%A, %B %d, %Y")
    
    scores = report_data.get("composite_scores", {})
    prices = report_data.get("prices", {})
    
    # Determine overall market signal for embed color
    avg_score = 0
    count = 0
    for symbol, sd in list(scores.items())[:3]:
        if isinstance(sd, dict):
            try:
                avg_score += float(sd.get("composite_score", 0))
                count += 1
            except (TypeError, ValueError):
                pass
    avg_score = avg_score / count if count > 0 else 50
    
    if avg_score >= 65:
        color = 0x4CAF50  # Green
        market_emoji = "🟢"
    elif avg_score >= 45:
        color = 0xFFC107  # Amber
        market_emoji = "🟡"
    else:
        color = 0xF44336  # Red
        market_emoji = "🔴"
    
    # Build embed fields
    fields = []
    
    # Market Snapshot
    snapshot_lines = []
    for symbol, sd in list(scores.items())[:3]:
        if isinstance(sd, dict):
            score = sd.get("composite_score", 0)
            signal = sd.get("signal", "N/A")
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0
            
            if "BUY" in str(signal).upper():
                emoji = "🟢"
            elif "SELL" in str(signal).upper():
                emoji = "🔴"
            else:
                emoji = "⚪"
            snapshot_lines.append(f"{emoji} **{symbol}**: {signal} — {score:.0f}/100")
    
    if snapshot_lines:
        fields.append({
            "name": "🎯 Market Snapshot",
            "value": "\n".join(snapshot_lines),
            "inline": False,
        })
    
    # Prices
    price_lines = []
    for coin_id in coins[:3]:
        price_data = prices.get(coin_id, {})
        if isinstance(price_data, dict) and price_data.get("usd"):
            price = price_data["usd"]
            change = price_data.get("usd_24h_change", 0)
            symbol = price_data.get("symbol", coin_id).upper()
            change_str = f"+{change:.1f}%" if change >= 0 else f"{change:.1f}%"
            price_lines.append(f"**{symbol}**: ${price:,.2f} ({change_str})")
    
    if price_lines:
        fields.append({
            "name": "💰 Prices",
            "value": "\n".join(price_lines),
            "inline": True,
        })
    
    # RSI Alerts (if any in top 3)
    rsi_lines = []
    for symbol, sd in list(scores.items())[:3]:
        if isinstance(sd, dict):
            rsi = sd.get("rsi", 50)
            try:
                rsi = float(rsi)
            except (TypeError, ValueError):
                continue
            if rsi < 30:
                rsi_lines.append(f"📉 **{symbol}** RSI {rsi:.0f} — OVERSOLD ⚡")
            elif rsi > 70:
                rsi_lines.append(f"📈 **{symbol}** RSI {rsi:.0f} — OVERBOUGHT ⚠️")
    
    if rsi_lines:
        fields.append({
            "name": "⚡ RSI Alerts",
            "value": "\n".join(rsi_lines),
            "inline": True,
        })
    
    # CTA
    fields.append({
        "name": "🔒 Want More?",
        "value": "Premium: 20-coin matrix, whale alerts, RSI notifications\n👉 [Upgrade — $29/mo](https://particulatellc.com/quantalpha)",
        "inline": False,
    })
    
    embed = {
        "title": f"📊 QuantAlpha Daily Brief — {market_emoji} Market",
        "description": f"**{date_str}** — AI-powered crypto intelligence",
        "color": color,
        "fields": fields,
        "footer": {
            "text": "Particulate LLC QuantAlpha v0.1 • Not financial advice • DYOR"
        },
        "timestamp": now.isoformat(),
    }
    
    return embed


def format_discord_message(report_data: Dict, coins: List[str] = None) -> str:
    """
    Generate a simple Discord text message for the free-tier brief.
    Use when embeds are not available.
    """
    from quantalpha.formatter import format_free_brief
    return format_free_brief(report_data, coins)
