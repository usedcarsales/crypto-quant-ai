"""
Social & News Alpha Engine
Phase 3, Task 3.5 — Sentiment scoring from social + on-chain signals
Sources: Reddit, CoinGecko, RSS news aggregator (7 sources, no API key)
Requires API key for: CryptoCompare news, LunarCrush, CoinMarketCap
"""

import requests
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional


# ─── RSS News Client (primary free sentiment source) ──────────────────────────
try:
    from skills.sentiment_engine.news_client import (
        get_market_sentiment as _rss_market,
        get_trending_news   as _rss_trending,
        get_coin_news       as _rss_coin,
        format_market_sentiment as _format_rss_market,
    )
    RSS_AVAILABLE = True
except Exception:
    RSS_AVAILABLE = False


# ─── API Keys (operator to fill in) ──────────────────────────────────────────
CRYPTOCOMPARE_KEY = ""   # https://min-api.cryptocompare.com — free tier available
LUNARCRUSH_KEY    = ""   # https://lunarcrush.com/developers
COINGECKO_KEY     = ""   # https://www.coingecko.com/api — free tier

COINGECKO_BASE    = "https://api.coingecko.com/api/v3"
REDDIT_URL        = "https://www.reddit.com/r/CryptoCurrency/hot.json?limit=25"
REDDIT_HEADERS    = {"User-Agent": "CryptoQuantBot/1.0 (by Servius on GPU rig)"}

# CoinGecko IDs for major assets
COIN_IDS = {
    "BTC":   "bitcoin",
    "ETH":   "ethereum",
    "SOL":   "solana",
    "BNB":   "binancecoin",
    "AVAX":  "avalanche-2",
    "LINK":  "chainlink",
    "UNI":   "uniswap",
    "AAVE":  "aave",
    "LIDO":  "lido-staked-ether",
    "XRP":   "ripple",
    "DOGE":  "dogecoin",
    "ADA":   "cardano",
}


# ─── Sentiment Scoring ─────────────────────────────────────────────────────────

POSITIVE_WORDS = {
    "bullish", "moon", "pump", "rally", "surge", "breakout",
    "soar", "soaring", "adoption", "upgrade", "partnership",
    "integration", "approval", "etf", "institutional", "growth",
    "launch", "listing", "win", "record", "all-time",
    "profit", "up", "higher", "bid", "long", "call",
    "hodl", "accumulate", "buy signal", "breakout", "divergence",
}

NEGATIVE_WORDS = {
    "bearish", "crash", "dump", "plunge", "sell", "fear",
    "hack", "exploit", "rug", "scam", "investigation", "ban",
    "regulation", "sec", "lawsuit", "collapse", "bankruptcy",
    "concern", "warning", "drop", "selloff", "red",
    "loss", "bleed", "freefall", "liquidated", "panic",
    "default", "fraud", "manipulation", "outflow", "rejected",
    "dump", "crash", "plunge", "bleed", "rug pull",
}

NEUTRAL_WORDS = {
    "stable", "consolidate", "flat", "sideways", "neutral",
    "support", "resistance", "watch", "monitor", "await",
    "holding", "range", "tight", "quiet",
}


@dataclass
class SentimentItem:
    title:       str
    source:      str
    sentiment:   str    # positive | negative | neutral
    score:       float  # -1 to +1
    upvotes:     int
    coin:        str    # detected coin
    url:         str = ""


def score_sentiment(text: str) -> tuple:
    """Returns (label, score_float)."""
    t = text.lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in t)
    neg = sum(1 for w in NEGATIVE_WORDS if w in t)
    neu = sum(1 for w in NEUTRAL_WORDS if w in t)

    raw = pos - neg
    total = pos + neg + neu + 1
    score = raw / total

    if score >= 0.12:  label = "positive"
    elif score <= -0.12: label = "negative"
    else:               label = "neutral"
    return label, round(score, 3)


def detect_coin(text: str) -> str:
    t = text.lower()
    mapping = [
        ("BTC",  ["bitcoin", "btc", "satoshi", "#bitcoin"]),
        ("ETH",  ["ethereum", "eth", "ether", "vitalik"]),
        ("SOL",  ["solana", "sol"]),
        ("BNB",  ["bnb", "binance"]),
        ("XRP",  ["ripple", "xrp", "sec "]),
        ("DOGE", ["dogecoin", "doge", "dogey"]),
        ("ADA",  ["cardano", "ada"]),
        ("AVAX", ["avalanche", "avax"]),
        ("LINK", ["chainlink", "link"]),
        ("UNI",  ["uniswap", "uni"]),
    ]
    for coin, keywords in mapping:
        if any(kw in t for kw in keywords):
            return coin
    return "GEN"


# ─── Reddit Social Feed ─────────────────────────────────────────────────────────

def get_reddit_sentiment(coin: str = None, limit: int = 25) -> dict:
    """
    Fetch hot posts from r/CryptoCurrency, score sentiment.
    Returns: {coin, sentiment, score, posts, top_post}
    """
    try:
        resp = requests.get(REDDIT_URL, headers=REDDIT_HEADERS, timeout=10)
        if not resp.ok:
            return {"error": f"reddit_{resp.status_code}"}

        data = resp.json()
        posts = data.get("data", {}).get("children", [])
        scored_posts = []

        for post in posts:
            pdata = post.get("data", {})
            title = pdata.get("title", "")
            if not title:
                continue

            detected = detect_coin(title)
            sentiment, s_score = score_sentiment(title)

            post_entry = {
                "title":    title,
                "coin":     detected,
                "sentiment": sentiment,
                "score":    s_score,
                "upvotes":  pdata.get("score", 0),
                "comments": pdata.get("num_comments", 0),
                "url":      f"https://reddit.com{pdata.get('permalink', '')}",
            }

            if coin and detected != coin and detected != "GEN":
                continue

            scored_posts.append(post_entry)

        if not scored_posts:
            return {"coin": coin or "ALL", "sentiment": "neutral", "score": 0.0,
                    "posts": [], "note": "no mentions in top 25 posts"}

        avg = sum(p["score"] for p in scored_posts) / len(scored_posts)
        top = max(scored_posts, key=lambda x: x["upvotes"])

        return {
            "coin":      coin or "ALL",
            "sentiment": "bullish" if avg > 0.1 else "bearish" if avg < -0.1 else "neutral",
            "score":     round(avg, 3),
            "posts":     scored_posts,
            "top_post":  top,
            "bullish_count": sum(1 for p in scored_posts if p["sentiment"] == "positive"),
            "bearish_count": sum(1 for p in scored_posts if p["sentiment"] == "negative"),
            "neutral_count": sum(1 for p in scored_posts if p["sentiment"] == "neutral"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        return {"error": str(e)}


# ─── CoinGecko Trending ────────────────────────────────────────────────────────

def get_trending_alert() -> dict:
    """
    Get what's trending on CoinGecko — social volume signal.
    Returns top trending coins by search volume score.
    """
    try:
        resp = requests.get(
            f"{COINGECKO_BASE}/search/trending",
            headers={"User-Agent": "CryptoQuantBot/1.0"},
            timeout=10,
        )
        if not resp.ok:
            return {"error": f"coingecko_{resp.status_code}"}

        d = resp.json()
        coins = d.get("coins", [])
        results = []
        for c in coins[:15]:
            item = c.get("item", {})
            results.append({
                "name":    item.get("name", ""),
                "symbol":  item.get("symbol", "").upper(),
                "rank":    item.get("market_cap_rank", 0) or 999,
                "score":   item.get("score", 0),
                "price_btc": item.get("price_btc", 0),
            })

        results.sort(key=lambda x: x["score"])
        return {"trending": results, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"error": str(e)}


# ─── CoinGecko Global Metrics ─────────────────────────────────────────────────

def get_global_sentiment() -> dict:
    """
    Get global market data as a broad sentiment signal.
    NOW ENRICHED with RSS news aggregator data (primary signal source).
    Returns: mcap_change_24h, volume_change, btc_dominance,
             rss_sentiment (from 7 RSS sources), combined_label
    """
    try:
        resp = requests.get(f"{COINGECKO_BASE}/global", timeout=10)
        if not resp.ok:
            return {"error": f"coingecko_{resp.status_code}"}

        d = resp.json().get("data", {})
        mcp = d.get("market_cap_change_percentage_24h_usd", 0)
        vcp = d.get("volume_change_percentage_24h_usd", 0)

        # CoinGecko-derived sentiment
        cg_sentiment = "bullish" if mcp > 2 else "bearish" if mcp < -2 else "neutral"

        # ── RSS News Sentiment (primary source) ────────────────────────────
        rss_sentiment_data = {}
        if RSS_AVAILABLE:
            try:
                rss_sentiment_data = _rss_market(hours=6)
            except Exception:
                pass

        rss_score = rss_sentiment_data.get("sentiment_score", 0)
        rss_label = rss_sentiment_data.get("label", "neutral")

        # Combine: RSS is primary (60%), CoinGecko mcap is secondary (40%)
        if rss_sentiment_data:
            combined_score = round(rss_score * 0.6 + mcp * 4 * 0.4, 3)
            # Normalize to 0-100 from score
            combined_norm = max(0, min(100, 50 + combined_score * 50))
        else:
            combined_norm = max(0, min(100, 50 + mcp * 8))
            combined_score = mcp

        if combined_norm >= 65:  combined_label = "bullish"
        elif combined_norm <= 40: combined_label = "bearish"
        else:                    combined_label = "neutral"

        result = {
            "mcap_change_24h":       round(mcp, 2),
            "vol_change_24h":        round(vcp, 2),
            "active_cryptos":        d.get("active_cryptocurrencies", 0),
            "btc_dominance":         round(d.get("market_cap_percentage", {}).get("btc", 0), 2),
            "global_sentiment":      combined_label,
            "rss_available":         RSS_AVAILABLE,
            "rss_sentiment":         rss_label,
            "rss_score":             rss_score,
            "rss_articles_analyzed": rss_sentiment_data.get("articles_analyzed", 0),
            "rss_bullish":           rss_sentiment_data.get("bullish_articles", 0),
            "rss_bearish":           rss_sentiment_data.get("bearish_articles", 0),
            "rss_top_bullish":       rss_sentiment_data.get("top_bullish", [])[:3],
            "rss_top_bearish":       rss_sentiment_data.get("top_bearish", [])[:3],
            "rss_top_coins":         rss_sentiment_data.get("top_coins", [])[:5],
            "combined_score":        round(combined_norm, 1),
            "timestamp":             datetime.now(timezone.utc).isoformat(),
        }
        return result

    except Exception as e:
        return {"error": str(e)}


# ─── Multi-Coin Social Matrix ─────────────────────────────────────────────────

def social_matrix(coins: list = None) -> dict:
    """
    Get social sentiment across multiple coins simultaneously.
    Coingecko IDs: BTC, ETH, SOL, BNB, AVAX, LINK, UNI, AAVE, LIDO, XRP, DOGE, ADA
    """
    if coins is None:
        coins = list(COIN_IDS.keys())

    results = {}
    for coin in coins:
        coin_id = COIN_IDS.get(coin, coin.lower())
        s = get_reddit_sentiment(coin=coin)
        results[coin] = s

    return results


# ─── Alert Formatters ─────────────────────────────────────────────────────────

def format_reddit_report(coin: str = None) -> str:
    """Reddit social sentiment report."""
    s = get_reddit_sentiment(coin=coin)
    if "error" in s:
        return f"⚠️ Reddit fetch failed: {s['error']}"

    emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(s["sentiment"], "⚪")
    lines = [
        f"{emoji} **Reddit Sentiment — {s['coin']}**",
        f"Score: **{s['score']:+.2f}** ({s['sentiment']})",
        f"Top 25 posts: 🟢 {s['bullish_count']} | 🔴 {s['bearish_count']} | 🟡 {s['neutral_count']}",
    ]
    if s.get("top_post"):
        t = s["top_post"]
        lines.append(f"🔥 Top: {t['title'][:70]}...")
    return "\n".join(lines)


def format_global_report() -> str:
    """Global market sentiment from CoinGecko."""
    g = get_global_sentiment()
    if "error" in g:
        return f"⚠️ Global fetch failed: {g['error']}"

    emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(g["global_sentiment"], "⚪")
    return (
        f"{emoji} **Global Market — {g['global_sentiment'].upper()}**\n"
        f"24h MCap Change: **{g['mcap_change_24h']:+.2f}%** | "
        f"Vol Change: **{g['vol_change_24h']:+.2f}%**\n"
        f"BTC Dominance: **{g['btc_dominance']:.1f}%** | "
        f"Active Cryptos: **{g['active_cryptos']:,}**"
    )


def format_trending_report() -> str:
    """What's hot on CoinGecko right now."""
    t = get_trending_alert()
    if "error" in t:
        return f"⚠️ Trending fetch failed: {t['error']}"

    coins = t.get("trending", [])[:7]
    lines = ["**🔥 CoinGecko Trending (Social Volume)**"]
    for c in coins:
        lines.append(f"  {c['name']} ({c['symbol']}) — Rank #{c['rank']}")
    return "\n".join(lines)


def format_social_digest(coin: str = None) -> str:
    """Combined social + market sentiment digest."""
    reddit = format_reddit_report(coin=coin)
    global_r = format_global_report()
    trending = format_trending_report()
    return f"{reddit}\n\n{global_r}\n\n{trending}"


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Social & News Alpha ===\n")

    # Global market
    g = get_global_sentiment()
    if "error" not in g:
        print(f"Global sentiment: {g['global_sentiment']}")
        print(f"  24h MCap: {g['mcap_change_24h']:+.2f}%")
        print(f"  24h Vol: {g['vol_change_24h']:+.2f}%")
        print(f"  BTC dom: {g['btc_dominance']:.1f}%")
    else:
        print(f"Global: {g}")

    print()

    # Reddit per coin
    for coin in ["BTC", "ETH", "SOL"]:
        s = get_reddit_sentiment(coin=coin)
        if "error" not in s:
            print(f"Reddit/{coin}: {s['sentiment']} ({s['score']:+.2f}) | "
                  f"🟢 {s['bullish_count']} 🔴 {s['bearish_count']}")
            if s.get("top_post"):
                print(f"  🔥 {s['top_post']['title'][:70]}")

    print("\n✅ Social Alpha module working")