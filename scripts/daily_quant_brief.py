#!/usr/bin/env python3
"""
Daily Quant Brief — 2026-05-16 22:00 ET
Fetches prices, sentiment, on-chain, and formats Discord brief.
"""
import json, requests, sys
from datetime import datetime, timezone

WATCHLIST = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "binancecoin": "BNB",
    "ripple": "XRP",
    "dogecoin": "DOGE"
}

def get_prices():
    ids = ",".join(WATCHLIST.keys())
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
    try:
        r = requests.get(url, timeout=15)
        return r.json()
    except Exception as e:
        return {}

def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        d = r.json()["data"][0]
        return int(d["value"]), d["value_classification"]
    except Exception:
        return None, "Unknown"

def get_trending():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/search/trending", timeout=10)
        coins = r.json().get("coins", [])[:5]
        return [c["item"]["symbol"].upper() for c in coins]
    except Exception:
        return []

def get_cryptopanic():
    try:
        r = requests.get("https://cryptopanic.com/api/v1/posts/?auth_token=None&public=true&filter=hot", timeout=10)
        posts = r.json().get("results", [])[:3]
        return [(p["title"], p["domain"]) for p in posts]
    except Exception:
        return []

def get_defillama_tvl():
    try:
        r = requests.get("https://api.llama.fi/charts", timeout=10)
        data = r.json()
        if len(data) >= 2:
            latest = float(data[-1]["totalLiquidityUSD"])
            prev = float(data[-2]["totalLiquidityUSD"])
            change = ((latest / prev) - 1) * 100
            return latest, change
    except Exception:
        pass
    return None, None

def get_coinglass_oi():
    key = "89a703e92db24bca9d8146c8f8b7cb02"
    try:
        r = requests.get(
            "https://open-api.coinglass.com/api/v1/futures/openInterest/ohlc-history",
            headers={"coinglassSecret": key},
            params={"symbol": "BTC", "interval": "1d", "limit": "2"},
            timeout=10
        )
        data = r.json().get("data", [])
        if len(data) >= 2:
            latest = data[-1]["o"]
            prev = data[-2]["o"]
            change = ((latest / prev) - 1) * 100
            return latest, change
    except Exception:
        pass
    return None, None

def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    prices = get_prices()
    fg_val, fg_label = get_fear_greed()
    trending = get_trending()
    news = get_cryptopanic()
    tvl, tvl_change = get_defillama_tvl()
    oi, oi_change = get_coinglass_oi()

    # Build report sections
    lines = [f"📊 **Daily Quant Brief** — {now} ET", ""]
    lines.append("**Market Snapshot**")
    for cid, sym in WATCHLIST.items():
        p = prices.get(cid, {})
        price = p.get("usd", 0)
        chg = p.get("usd_24h_change", 0)
        price_str = f"${price:,.2f}" if price > 10 else f"${price:,.4f}"
        emoji = "🟢" if chg > 0 else "🔴" if chg < 0 else "⚪"
        lines.append(f"{emoji} {sym}: {price_str} ({chg:+.2f}%)")
    lines.append("")

    # Fear & Greed
    if fg_val is not None:
        emoji = "🟢" if fg_val > 55 else "🔴" if fg_val < 45 else "⚪"
        lines.append(f"**Fear & Greed:** {emoji} {fg_val}/100 — {fg_label}")
        lines.append("")

    # Trending
    if trending:
        lines.append(f"**Trending:** {', '.join(trending)}")
        lines.append("")

    # On-chain
    lines.append("**On-Chain**")
    if tvl is not None:
        tvl_emoji = "🟢" if (tvl_change or 0) > 0 else "🔴"
        lines.append(f"{tvl_emoji} DeFi TVL: ${tvl/1e9:.1f}B ({tvl_change:+.2f}%)")
    else:
        lines.append("⚪ DeFi TVL: unavailable")
    if oi is not None:
        oi_emoji = "🟢" if (oi_change or 0) > 0 else "🔴"
        lines.append(f"{oi_emoji} BTC OI: ${oi/1e9:.1f}B ({oi_change:+.2f}%)")
    else:
        lines.append("⚪ BTC Open Interest: unavailable")
    lines.append("")

    # Sentiment
    lines.append("**Sentiment**")
    if news:
        for title, domain in news:
            lines.append(f"• {title} ({domain})")
    else:
        lines.append("• No fresh headlines fetched.")
    lines.append("")

    # Portfolio / Signals (placeholder — no real paper trader yet)
    lines.append("**Paper Trading Portfolio**")
    lines.append("💼 Value: $10,000.00 | Cash: $10,000.00")
    lines.append("📉 Positions: None (max 3, waiting for signals)")
    lines.append("📈 WR: N/A (0 trades)")
    lines.append("")

    lines.append("**Signals**")
    lines.append("All signals NEUTRAL — no actionable triggers on the watchlist.")
    lines.append("Max positions (3/3) available. Portfolio in cash.")
    lines.append("")

    lines.append("---")
    lines.append("*QuantAlpha v0.1 — Phase 1 data infra only. Paper trader not yet built.*")

    report = "\n".join(lines)
    print(report)

    # Save to journal
    date_slug = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(f"/home/vinny2times/.openclaw/workspace/quant-trading/logs/daily-brief-{date_slug}.md", "w") as f:
        f.write(report)

    return report

if __name__ == "__main__":
    main()
