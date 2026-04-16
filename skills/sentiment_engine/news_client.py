"""
Crypto News Sentiment Client
Phase 1, Task 1.6 — Sentiment Data (free tier)
Multi-source RSS news aggregation with keyword-based sentiment scoring.
No API keys required. All endpoints are free RSS feeds.

Sources: CoinTelegraph, CoinDesk, Decrypt, Bitcoin Magazine,
         CryptoSlate, NewsBTC, The Block
"""

import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Optional
from collections import Counter

import requests

# ─── RSS Sources ────────────────────────────────────────────────────────────────
RSS_FEEDS = {
    "cointelegraph":  "https://cointelegraph.com/rss",
    "coindesk":       "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "decrypt":        "https://decrypt.co/feed",
    "bitcoinmagazine": "https://bitcoinmagazine.com/.rss/full/",
    "cryptoslate":    "https://cryptoslate.com/feed/",
    "newsbtc":        "https://www.newsbtc.com/feed/",
    "theblock":       "https://www.theblock.co/rss.xml",
}

SOURCE_WEIGHTS = {
    "coindesk": 1.2,       # established, high credibility
    "theblock": 1.2,       # institutional-grade
    "cointelegraph": 1.0,  # large audience
    "decrypt": 1.0,        # good analysis
    "bitcoinmagazine": 0.9,
    "cryptoslate": 0.8,
    "newsbtc": 0.7,        # often promotional
}

# ─── Caching ────────────────────────────────────────────────────────────────────
_CACHE: dict = {}
_CACHE_TTL = 300          # 5 min for headlines
_LAST_CALL = 0
_MIN_INTERVAL = 0.5       # 500ms between requests

# ─── Sentiment Lexicon ──────────────────────────────────────────────────────────
BULLISH_WORDS = {
    "surge", "soar", "rally", "bullish", "breakout", "moon", "pump",
    "gain", "rise", "climb", "skyrocket", "all-time high", "ath",
    "adoption", "approve", "approved", "approval", "upgrade", "milestone",
    "buy", "accumulate", "whale buy", "institutional", "etf approved",
    "bull run", "recovery", "outperform", "positive", "growth",
    "partnership", "launch", "stake", "accumulate",
}

BEARISH_WORDS = {
    "crash", "dump", "bearish", "plunge", "collapse", "hack", "hacked",
    "exploit", "rug pull", "scam", "ban", "banned", "regulation",
    "sec", "lawsuit", "fraud", "bankrupt", "insolvency", "liquidate",
    "sell-off", "selloff", "decline", "drop", "fall", "fear",
    "risk", "warning", "caution", "uncertainty", "volatile",
    "delist", "delisted", "restrict", "crackdown", "penalty",
}

# Coin name → aliases for keyword matching
COIN_ALIASES = {
    "BTC": ["bitcoin", "btc", "satoshi", "sats"],
    "ETH": ["ethereum", "eth", "ether", "vitalik"],
    "SOL": ["solana", "sol"],
    "DOGE": ["dogecoin", "doge"],
    "XRP": ["xrp", "ripple"],
    "ADA": ["cardano", "ada"],
    "AVAX": ["avalanche", "avax"],
    "DOT": ["polkadot", "dot"],
    "LINK": ["chainlink", "link"],
    "MATIC": ["polygon", "matic"],
    "SHIB": ["shiba", "shib"],
    "LTC": ["litecoin", "ltc"],
    "UNI": ["uniswap", "uni"],
    "AAVE": ["aave"],
    "ARB": ["arbitrum", "arb"],
    "OP": ["optimism", "op"],
}


def _rate_limit():
    global _LAST_CALL
    elapsed = time.time() - _LAST_CALL
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _LAST_CALL = time.time()


def _fetch_rss(url: str) -> list[dict]:
    """Fetch and parse an RSS feed into a list of article dicts."""
    _rate_limit()
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "CryptoQuantBot/1.0"})
        if r.status_code != 200:
            return []

        root = ET.fromstring(r.text)
        items = root.findall(".//item")

        # Atom fallback
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//atom:entry", ns)

        articles = []
        for item in items:
            title = (
                item.findtext("title")
                or item.findtext("{http://www.w3.org/2005/Atom}title")
                or ""
            )
            description = (
                item.findtext("description")
                or item.findtext("{http://www.w3.org/2005/Atom}summary")
                or item.findtext("content")
                or ""
            )
            link = (
                item.findtext("link")
                or (item.find("{http://www.w3.org/2005/Atom}link") or {}).get("href", "")
                or ""
            )
            pub_date = (
                item.findtext("pubDate")
                or item.findtext("{http://www.w3.org/2005/Atom}published")
                or item.findtext("{http://www.w3.org/2005/Atom}updated")
                or ""
            )

            # Strip HTML from description
            clean_desc = re.sub(r"<[^>]+>", "", description).strip()

            articles.append({
                "title": title.strip(),
                "description": clean_desc[:500],
                "url": link,
                "published": pub_date,
            })

        return articles

    except Exception:
        return []


# ─── Sentiment Scoring ──────────────────────────────────────────────────────────
def _score_sentiment(text: str) -> dict:
    """
    Score text for bullish/bearish sentiment.
    Returns {score: -1 to +1, bullish_hits, bearish_hits, matched_terms}
    """
    lower = text.lower()
    bullish = []
    bearish = []

    for word in BULLISH_WORDS:
        if word in lower:
            bullish.append(word)

    for word in BEARISH_WORDS:
        if word in lower:
            bearish.append(word)

    total = len(bullish) + len(bearish)
    if total == 0:
        score = 0.0
    else:
        score = (len(bullish) - len(bearish)) / total

    return {
        "score": round(score, 3),
        "bullish_hits": len(bullish),
        "bearish_hits": len(bearish),
        "bullish_terms": bullish[:5],
        "bearish_terms": bearish[:5],
    }


def _coin_matches(text: str, coin: str) -> bool:
    """Check if text mentions a coin or its aliases."""
    aliases = COIN_ALIASES.get(coin.upper(), [coin.lower()])
    lower = text.lower()
    return any(alias in lower for alias in aliases)


# ─── Public API Functions ──────────────────────────────────────────────────────

def get_coin_news(
    coin: str,
    hours: int = 24,
    limit: int = 20,
) -> dict:
    """
    Get recent news for a specific coin with sentiment scores.
    coin: ticker like 'BTC', 'ETH', 'SOL'
    hours: lookback window
    limit: max articles to return
    """
    cache_key = f"coin_news|{coin}|{hours}"
    cached = _CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _CACHE_TTL:
        return cached["data"]

    all_articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    for source_name, url in RSS_FEEDS.items():
        for art in _fetch_rss(url):
            # Check coin match
            combined = f"{art['title']} {art['description']}"
            if not _coin_matches(combined, coin):
                continue

            # Score sentiment
            sentiment = _score_sentiment(combined)
            weight = SOURCE_WEIGHTS.get(source_name, 1.0)

            all_articles.append({
                "source": source_name,
                "source_weight": weight,
                "title": art["title"],
                "description": art["description"][:200],
                "url": art["url"],
                "published": art["published"],
                "sentiment": sentiment,
            })

    # Sort by relevance (sentiment magnitude * source weight)
    all_articles.sort(
        key=lambda a: (abs(a["sentiment"]["score"]) * a["source_weight"]),
        reverse=True,
    )

    # Aggregate sentiment
    if all_articles:
        weighted_scores = [
            a["sentiment"]["score"] * a["source_weight"] for a in all_articles
        ]
        avg_sentiment = round(
            sum(weighted_scores) / sum(a["source_weight"] for a in all_articles), 3
        )
        bullish_count = sum(1 for a in all_articles if a["sentiment"]["score"] > 0)
        bearish_count = sum(1 for a in all_articles if a["sentiment"]["score"] < 0)
        neutral_count = len(all_articles) - bullish_count - bearish_count
    else:
        avg_sentiment = 0.0
        bullish_count = bearish_count = neutral_count = 0

    result = {
        "coin": coin.upper(),
        "source": "rss_aggregator",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": hours,
        "total_articles": len(all_articles),
        "sentiment": {
            "avg_score": avg_sentiment,
            "label": _sentiment_label(avg_sentiment),
            "bullish": bullish_count,
            "bearish": bearish_count,
            "neutral": neutral_count,
        },
        "articles": all_articles[:limit],
    }

    _CACHE[cache_key] = {"data": result, "ts": time.time()}
    return result


def get_trending_news(
    hours: int = 6,
    limit: int = 15,
) -> dict:
    """
    Get trending crypto news across all coins.
    Returns top articles by sentiment magnitude (most controversial/impactful).
    """
    cache_key = f"trending|{hours}"
    cached = _CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _CACHE_TTL:
        return cached["data"]

    all_articles = []

    for source_name, url in RSS_FEEDS.items():
        for art in _fetch_rss(url):
            combined = f"{art['title']} {art['description']}"
            sentiment = _score_sentiment(combined)
            weight = SOURCE_WEIGHTS.get(source_name, 1.0)

            # Detect mentioned coins
            mentioned = []
            for ticker, aliases in COIN_ALIASES.items():
                if any(a in combined.lower() for a in aliases):
                    mentioned.append(ticker)

            all_articles.append({
                "source": source_name,
                "source_weight": weight,
                "title": art["title"],
                "description": art["description"][:200],
                "url": art["url"],
                "published": art["published"],
                "sentiment": sentiment,
                "coins_mentioned": mentioned,
            })

    # Sort by impact (sentiment magnitude * weight)
    all_articles.sort(
        key=lambda a: (abs(a["sentiment"]["score"]) * a["source_weight"]),
        reverse=True,
    )

    # Coin frequency analysis
    coin_counter = Counter()
    for art in all_articles:
        for coin in art["coins_mentioned"]:
            coin_counter[coin] += 1

    result = {
        "source": "rss_aggregator",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": hours,
        "total_articles": len(all_articles),
        "top_coins": coin_counter.most_common(10),
        "articles": all_articles[:limit],
    }

    _CACHE[cache_key] = {"data": result, "ts": time.time()}
    return result


def get_market_sentiment(hours: int = 6) -> dict:
    """
    Aggregate market-wide sentiment from all sources.
    Returns overall bullish/bearish reading + top narratives.
    """
    trending = get_trending_news(hours=hours, limit=100)

    articles = trending.get("articles", [])
    if not articles:
        return {
            "source": "rss_aggregator",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sentiment_score": 0,
            "label": "neutral",
            "articles_analyzed": 0,
        }

    weighted = [
        a["sentiment"]["score"] * a["source_weight"] for a in articles
    ]
    total_weight = sum(a["source_weight"] for a in articles)
    avg = round(sum(weighted) / total_weight, 3) if total_weight else 0

    bullish = sum(1 for a in articles if a["sentiment"]["score"] > 0.2)
    bearish = sum(1 for a in articles if a["sentiment"]["score"] < -0.2)

    # Top bullish/bearish narratives
    top_bullish = [
        a["title"] for a in articles if a["sentiment"]["score"] > 0.3
    ][:5]
    top_bearish = [
        a["title"] for a in articles if a["sentiment"]["score"] < -0.3
    ][:5]

    return {
        "source": "rss_aggregator",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "articles_analyzed": len(articles),
        "sentiment_score": avg,
        "label": _sentiment_label(avg),
        "bullish_articles": bullish,
        "bearish_articles": bearish,
        "top_coins": trending.get("top_coins", [])[:5],
        "top_bullish": top_bullish,
        "top_bearish": top_bearish,
    }


def _sentiment_label(score: float) -> str:
    if score >= 0.5: return "very_bullish"
    if score >= 0.2: return "bullish"
    if score >= -0.2: return "neutral"
    if score >= -0.5: return "bearish"
    return "very_bearish"


# ─── Discord Formatters ────────────────────────────────────────────────────────
def format_coin_news(data: dict) -> str:
    if "error" in data:
        return f"❌ Error: {data['error']}"

    coin = data.get("coin", "?")
    s = data.get("sentiment", {})
    articles = data.get("articles", [])

    label_emoji = {
        "very_bullish": "🟢🟢",
        "bullish": "🟢",
        "neutral": "🟡",
        "bearish": "🔴",
        "very_bearish": "🔴🔴",
    }.get(s.get("label", "neutral"), "🟡")

    lines = [
        f"**📰 {coin} News Sentiment** {label_emoji}",
        f"  Score: **{s.get('avg_score', 0):.2f}** ({s.get('label', '?')})",
        f"  🟢 Bullish: {s.get('bullish', 0)} | 🔴 Bearish: {s.get('bearish', 0)} | 🟡 Neutral: {s.get('neutral', 0)}",
    ]

    if articles:
        lines.append("  **Top headlines:**")
        for a in articles[:5]:
            s_score = a["sentiment"]["score"]
            arrow = "↑" if s_score > 0.1 else ("↓" if s_score < -0.1 else "→")
            lines.append(f"    {arrow} _{a['title'][:80]}_ [{a['source']}]")

    return "\n".join(lines)


def format_market_sentiment(data: dict) -> str:
    label_emoji = {
        "very_bullish": "🟢🟢",
        "bullish": "🟢",
        "neutral": "🟡",
        "bearish": "🔴",
        "very_bearish": "🔴🔴",
    }.get(data.get("label", "neutral"), "🟡")

    lines = [
        f"**📊 Market Sentiment** {label_emoji}",
        f"  Score: **{data.get('sentiment_score', 0):.2f}** ({data.get('label', '?')})",
        f"  Articles analyzed: {data.get('articles_analyzed', 0)}",
    ]

    top_coins = data.get("top_coins", [])
    if top_coins:
        lines.append("  **Most mentioned:** " + " | ".join(f"{c}({n})" for c, n in top_coins[:5]))

    for label, key in [("🟢 Bullish", "top_bullish"), ("🔴 Bearish", "top_bearish")]:
        items = data.get(key, [])
        if items:
            lines.append(f"  {label}:")
            for t in items[:3]:
                lines.append(f"    • _{t[:80]}_")

    return "\n".join(lines)