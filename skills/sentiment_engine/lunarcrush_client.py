"""
LunarCrush Sentiment Client
Phase 1, Task 1.6 — Sentiment Data
Social intelligence: galaxy score, social dominance, sentiment, influencer signals.
"""

import os
import time
import hashlib
import json
from datetime import datetime, timezone
from typing import Literal, Optional

import requests

# ─── Config ───────────────────────────────────────────────────────────────────
LUNARCRUSH_BASE = "https://lunarcrush.com/api4"
API_KEY = os.getenv("LUNARCRUSH_API_KEY", "")
AUTH_HEADER = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}

# ─── Aggressive caching (free tier = 1,500 credits/month) ─────────────────────
_CACHE: dict = {}
_CACHE_TTL = 300          # 5 min for live data
_CACHE_TTL_LONG = 3600    # 1 hr for historical/listing data
LAST_CALL = 0
MIN_INTERVAL = 2.0        # space calls to 2 sec minimum


def _get(endpoint: str, params: dict = None, cache_ttl: int = _CACHE_TTL) -> dict:
    """LunarCrush GET with rate limiting + disk-backed memory cache."""
    global LAST_CALL

    # Build cache key from full request
    cache_key = f"{endpoint}|{json.dumps(params or {}, sort_keys=True)}"
    cached = _CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < cache_ttl:
        return cached["data"]

    # Rate limit
    elapsed = time.time() - LAST_CALL
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    LAST_CALL = time.time()

    url = f"{LUNARCRUSH_BASE}/{endpoint}"
    resp = requests.get(url, params=params, headers=AUTH_HEADER, timeout=15)

    if resp.status_code == 401:
        return {"error": "unauthorized", "detail": resp.text[:200]}
    if resp.status_code == 403:
        return {"error": "forbidden", "detail": resp.text[:200]}
    if resp.status_code == 429:
        return {"error": "rate_limited", "retry_after": resp.headers.get("Retry-After", "30")}
    if resp.status_code >= 500:
        return {"error": "server_error", "status": resp.status_code, "detail": resp.text[:200]}

    resp.raise_for_status()
    data = resp.json()

    _CACHE[cache_key] = {"data": data, "ts": time.time()}
    return data


# ─── Symbol normalization ───────────────────────────────────────────────────────
_COIN_SYMBOL_MAP = {
    "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
    "doge": "dogecoin", "xrp": "xrp", "ADA": "cardano",
    "DOT": "polkadot", "AVAX": "avalanche-2", "LINK": "chainlink",
    "MATIC": "matic-network", "SHIB": "shiba-inu",
}


def _normalize(symbol: str) -> str:
    """Coingecko-style symbol → LunarCrush topic name."""
    s = symbol.lower().strip()
    return _COIN_SYMBOL_MAP.get(s, s)


# ─── 1. Coin Overview ─────────────────────────────────────────────────────────
def get_coin_overview(
    coin: str,
    get_24h: bool = False,
) -> dict:
    """
    Galaxy score, social score, alt_rank, sentiment breakdown for a coin.
    Uses Coins List v2 to get ranked metrics, then enriches with topic data.
    """
    symbol = _normalize(coin)

    # Try topic endpoint first for rich social data
    topic_data = _get(
        f"public/topic/{symbol}/v1",
        cache_ttl=_CACHE_TTL,
    )

    if "error" in topic_data and topic_data["error"] == "endpoint not found":
        return {"error": f"coin_not_found", "coin": coin, "symbol": symbol}

    # Also get coins list for galaxy score + alt rank
    coins_data = _get(
        "public/coins",
        params={"symbol": symbol, "data_points": "1"},
        cache_ttl=_CACHE_TTL,
    )

    result = {
        "coin": coin,
        "symbol": symbol,
        "source": "lunarcrush",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Parse topic data (social activity)
    if "data" in topic_data:
        td = topic_data["data"]
        config = topic_data.get("config", {})

        result.update({
            "name": config.get("name", coin),
            "topic": config.get("topic", symbol),
            "topic_rank": td.get("topic_rank"),
            "interactions_24h": td.get("interactions_24h"),
            "num_contributors": td.get("num_contributors"),
            "num_posts": td.get("num_posts"),
            "trend": td.get("trend", "flat"),
            "types_sentiment": td.get("types_sentiment", {}),   # {tweet: 74, news: 76, ...}
        })

        # Weighted average sentiment (0-100)
        sentiments = td.get("types_sentiment", {})
        weights = td.get("types_interactions", {})
        if sentiments:
            total_w = sum(weights.values())
            if total_w > 0:
                weighted = sum(sentiments[k] * weights[k] for k in sentiments if k in weights)
                result["sentiment_avg"] = round(weighted / total_w, 2)
            else:
                result["sentiment_avg"] = round(sum(sentiments.values()) / len(sentiments), 2) if sentiments else 50

    # Parse coins list (galaxy score, alt rank)
    if "data" in coins_data and isinstance(coins_data["data"], list):
        for c in coins_data["data"]:
            if isinstance(c, dict) and c.get("symbol", "").lower() == symbol.lower():
                result.update({
                    "galaxy_score": c.get("galaxy_score"),
                    "alt_rank": c.get("alt_rank"),
                    "social_dominance": c.get("social_dominance"),
                    "market_cap": c.get("market_cap"),
                    "price": c.get("price"),
                    "volume_24h": c.get("volume_24h"),
                })
                break

    return result


# ─── 2. Coin Time Series ───────────────────────────────────────────────────────
def get_coin_time_series(
    coin: str,
    days: int = 7,
    bucket: Literal["hour", "day"] = "day",
) -> dict:
    """
    Historical social + price metrics for a coin.
    days: 1-365 (spacing interval auto-computes from range)
    bucket: 'hour' or 'day'
    """
    symbol = _normalize(coin)

    # Compute unix timestamps
    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = end_ts - (days * 86400)

    data = _get(
        f"public/topic/{symbol}/time-series/v2",
        params={
            "bucket": bucket,
            "start": start_ts,
            "end": end_ts,
        },
        cache_ttl=_CACHE_TTL_LONG,
    )

    if "error" in data:
        return {"error": data["error"], "coin": coin, "symbol": symbol}

    config = data.get("config", {})
    rows = data.get("data", [])

    parsed = []
    for pt in rows:
        if not isinstance(pt, dict):
            continue
        parsed.append({
            "time":          pt.get("time"),
            "datetime":      datetime.fromtimestamp(pt.get("time", 0), tz=timezone.utc).isoformat(),
            "galaxy_score":  pt.get("galaxy_score"),
            "alt_rank":      pt.get("alt_rank"),
            "sentiment":     pt.get("sentiment"),
            "interactions":  pt.get("interactions"),
            "contributors": pt.get("contributors_active"),
            "posts":        pt.get("posts_active"),
            "spam":         pt.get("spam"),
            "close":        pt.get("close"),
            "volume_24h":   pt.get("volume_24h"),
            "market_cap":   pt.get("market_cap"),
            "social_dominance": pt.get("social_dominance"),
        })

    return {
        "coin": coin,
        "symbol": symbol,
        "bucket": bucket,
        "start": start_ts,
        "end": end_ts,
        "data_points": len(parsed),
        "source": "lunarcrush",
        "series": parsed,
    }


# ─── 3. Trending Coins ────────────────────────────────────────────────────────
def get_trending_coins(limit: int = 20) -> dict:
    """
    Top coins by social activity/interactions.
    Uses coins list sorted by interactions or galaxy_score.
    """
    data = _get(
        "public/coins",
        params={
            "sort": "galaxy_score",   # proprietary score = social signal
            "order": "desc",
            "limit": limit,
            "data_points": "1",
        },
        cache_ttl=_CACHE_TTL,
    )

    if "error" in data:
        return {"error": data["error"], "source": "lunarcrush"}

    coins = []
    for c in (data.get("data") or []):
        if not isinstance(c, dict):
            continue
        coins.append({
            "symbol":           c.get("symbol", ""),
            "name":             c.get("name", ""),
            "galaxy_score":    c.get("galaxy_score"),
            "alt_rank":         c.get("alt_rank"),
            "social_dominance": c.get("social_dominance"),
            "price":            c.get("price"),
            "market_cap":       c.get("market_cap"),
            "interactions_24h": c.get("interactions_24h"),
        })

    return {
        "source": "lunarcrush",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "coins": coins,
    }


# ─── 4. Influencer Signals ─────────────────────────────────────────────────────
def get_influencer_signals(
    coin: str,
    limit: int = 10,
) -> dict:
    """
    Top influencer posts and overall influencer sentiment for a coin.
    Returns recent posts + sentiment from LunarCrush topic/creators data.
    """
    symbol = _normalize(coin)

    # Get topic data (overall sentiment breakdown)
    topic_data = _get(
        f"public/topic/{symbol}/v1",
        cache_ttl=_CACHE_TTL,
    )

    # Get top creators for this topic
    creators_data = _get(
        f"public/topic/{symbol}/creators/v1",
        params={"limit": limit},
        cache_ttl=_CACHE_TTL,
    )

    # Get recent posts for this topic
    posts_data = _get(
        f"public/topic/{symbol}/posts/v1",
        params={"limit": limit},
        cache_ttl=_CACHE_TTL,
    )

    result = {
        "coin": coin,
        "symbol": symbol,
        "source": "lunarcrush",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Sentiment breakdown
    if "data" in topic_data:
        td = topic_data["data"]
        result["interactions_24h"] = td.get("interactions_24h")
        result["num_contributors"] = td.get("num_contributors")
        result["trend"] = td.get("trend", "flat")
        result["sentiment_by_source"] = td.get("types_sentiment", {})
        result["sentiment_detail"] = td.get("types_sentiment_detail", {})

    # Top creators
    creators = []
    if "data" in creators_data:
        for cr in (creators_data["data"] or [])[:limit]:
            if not isinstance(cr, dict):
                continue
            creators.append({
                "username":   cr.get("username", ""),
                "type":       cr.get("type", ""),
                "followers":  cr.get("followers"),
                "influence":  cr.get("influence"),
            })
    result["top_creators"] = creators

    # Recent posts
    posts = []
    if "data" in posts_data:
        for p in (posts_data["data"] or [])[:limit]:
            if not isinstance(p, dict):
                continue
            posts.append({
                "type":       p.get("type", ""),
                "content":    p.get("content", p.get("text", ""))[:500],
                "sentiment":  p.get("sentiment"),
                "interactions": p.get("interactions"),
                "url":        p.get("url", ""),
                "created":    p.get("created"),
            })
    result["recent_posts"] = posts

    return result


# ─── 5. Market-wide Sentiment Snapshot ─────────────────────────────────────────
def get_market_sentiment() -> dict:
    """
    Aggregate market sentiment across top coins.
    Returns average sentiment, Fear/Greed proxy, social volume.
    """
    trending = get_trending_coins(limit=50)

    if "error" in trending:
        return trending

    coins = trending.get("coins", [])
    sentiment_scores = [c.get("galaxy_score", 0) for c in coins if c.get("galaxy_score")]

    return {
        "source": "lunarcrush",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "coins_analyzed": len(coins),
        "avg_galaxy_score": round(sum(sentiment_scores) / len(sentiment_scores), 2) if sentiment_scores else 0,
        "top_coin": coins[0] if coins else None,
        "sentiment_label": _score_to_label(
            sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 50
        ),
    }


def _score_to_label(score: float) -> str:
    if score >= 75: return "Extreme Greed"
    if score >= 60: return "Greed"
    if score >= 55: return "Neutral"
    if score >= 40: return "Fear"
    return "Extreme Fear"


# ─── Discord Formatters ────────────────────────────────────────────────────────
def format_coin_overview(overview: dict) -> str:
    if "error" in overview:
        return f"❌ Error: {overview['error']}"

    symbol = overview.get("symbol", "?")
    gs = overview.get("galaxy_score")
    ar = overview.get("alt_rank")
    sa = overview.get("sentiment_avg")
    rank = overview.get("topic_rank")
    trend = overview.get("trend", "?")

    gs_str = f"**{gs}/100**" if gs is not None else "N/A"
    ar_str = f"**#{ar}**" if ar is not None else "N/A"
    sa_str = f"**{sa}%**" if sa is not None else "N/A"

    trend_emoji = {"up": "📈", "down": "📉", "flat": "➡️"}.get(trend, "➡️")

    return (
        f"**🔍 LunarCrush: {symbol.upper()}**\n"
        f"  Galaxy Score: {gs_str}  |  Alt Rank: {ar_str}\n"
        f"  Sentiment: {sa_str}  |  Topic Rank: **{rank}**  {trend_emoji}\n"
        f"  24h Interactions: **{overview.get('interactions_24h', 'N/A'):,}**"
    )


def format_trending(Trending: dict) -> str:
    if "error" in Trending:
        return f"❌ Error: {Trending['error']}"

    coins = Trending.get("coins", [])
    if not coins:
        return "❌ No trending data"

    lines = ["**📊 Trending Coins (LunarCrush Galaxy Score)**"]
    for i, c in enumerate(coins[:10], 1):
        gs = c.get("galaxy_score", 0) or 0
        ar = c.get("alt_rank") or "?"
        symbol = c.get("symbol", "?").upper()
        price = c.get("price")
        price_str = f"${price:,.2f}" if price else "?"
        lines.append(f"  {i}. **{symbol}** — Score: **{gs}** | Rank: **{ar}** | {price_str}")

    return "\n".join(lines)


def format_influencer_signals(signals: dict) -> str:
    if "error" in signals:
        return f"❌ Error: {signals['error']}"

    symbol = signals.get("symbol", "?").upper()
    sentiment = signals.get("sentiment_avg", signals.get("sentiment_by_source", {}).get("tweet"))
    trend = signals.get("trend", "?")
    interactions = signals.get("interactions_24h", 0)

    trend_emoji = {"up": "📈", "down": "📉", "flat": "➡️"}.get(trend, "➡️")

    posts = signals.get("recent_posts", [])
    top_post = posts[0] if posts else None

    return (
        f"**👥 Influencer Signals: {symbol}**\n"
        f"  Sentiment: **{sentiment}%**  |  Trend: {trend_emoji}\n"
        f"  24h Interactions: **{interactions:,}**"
        + (f"\n  Top Post: _{top_post.get('content', '')[:120]}..._" if top_post else "")
    )