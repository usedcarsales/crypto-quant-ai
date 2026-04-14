"""
Sentiment Engine Module
Phase 1, Task 1.6 — Sentiment Data
Multi-source sentiment: CoinGecko search, GitHub trends, DeFiLlama flows.
API keys where required, free tiers where available.
"""

import requests
import time
from datetime import datetime, timezone

# ─── CoinGecko (Free, no key for basic) ───────────────────────────────────────
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# ─── GitHub (Free, no key for basic) ─────────────────────────────────────────
GITHUB_BASE = "https://api.github.com"

# ─── Reddit (blocked by robots — using GitHub as proxy) ───────────────────────
# Reddit is blocked. Using GitHub trending as social proxy for developer/market interest.

LAST_CALL = 0
MIN_INTERVAL = 1.5


def _cg_get(endpoint: str, params: dict = None) -> dict:
    """CoinGecko GET with rate limiting."""
    global LAST_CALL
    elapsed = time.time() - LAST_CALL
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    LAST_CALL = time.time()
    resp = requests.get(f"{COINGECKO_BASE}/{endpoint}", params=params, timeout=15)
    if resp.status_code == 429:
        return {"error": "rate_limited", "retry_after": resp.headers.get("Retry-After")}
    resp.raise_for_status()
    return resp.json()


def _gh_get(endpoint: str, params: dict = None) -> dict:
    """GitHub GET with unauthenticated fallback."""
    global LAST_CALL
    elapsed = time.time() - LAST_CALL
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    LAST_CALL = time.time()
    headers = {"Accept": "application/vnd.github.v3+json"}
    resp = requests.get(f"{GITHUB_BASE}/{endpoint}", params=params, headers=headers, timeout=15)
    if resp.status_code == 403:
        return {"error": "github_rate_limit", "raw": resp.text[:200]}
    resp.raise_for_status()
    return resp.json()


# ─── CoinGecko Sentiment ──────────────────────────────────────────────────────

def get_coin_sentiment(coin_id: str) -> dict:
    """
    Get sentiment metrics for a coin: social score, sentiment, spam signals.
    CoinGecko free tier — limited but usable.
    """
    try:
        data = _cg_get(f"coins/{coin_id}", params={
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "true",
            "developer_data": "false",
            "sparkline": "false",
        })
        if "error" in data:
            return data
        cdata = data.get("community_data", {}) or {}
        mdata = data.get("market_data", {}) or {}
        return {
            "coin_id": coin_id,
            "twitter_followers": cdata.get("twitter_followers", 0) or 0,
            "reddit_subscribers": cdata.get("reddit_subscribers", 0) or 0,
            "reddit_accounts_active_48h": cdata.get("reddit_accounts_active_48h", 0) or 0,
            "telegram_channel_user_count": cdata.get("telegram_channel_user_count", 0) or 0,
            "facebook_likes": cdata.get("facebook_likes", 0) or 0,
            "price_change_24h": mdata.get("price_change_percentage_24h", 0) or 0,
            "price_change_7d": mdata.get("price_change_percentage_7d", 0) or 0,
            "market_cap_rank": mdata.get("market_cap_rank", 0) or 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "CoinGecko free tier",
        }
    except Exception as e:
        return {"coin_id": coin_id, "error": str(e)}


def get_trending_searches() -> dict:
    """
    Get trending coins on CoinGecko (search volume spike = sentiment signal).
    """
    try:
        data = _cg_get("search/trending")
        if "error" in data:
            return data
        coins = data.get("coins", [])
        result = []
        for item in coins[:10]:
            coin = item.get("item", {})
            result.append({
                "id": coin.get("id", ""),
                "name": coin.get("name", ""),
                "symbol": coin.get("symbol", "").upper(),
                "market_cap_rank": coin.get("market_cap_rank", 0) or 0,
                "score": item.get("score", 0) or 0,
                "price_btc": coin.get("thumb", ""),
            })
        return {
            "trending": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "CoinGecko search API",
        }
    except Exception as e:
        return {"error": str(e)}


def get_global_sentiment() -> dict:
    """
    Get global crypto market sentiment: fear/greed via market cap dominance,
    volume spikes, BTC dominance.
    """
    try:
        data = _cg_get("global")
        if "error" in data:
            return data
        g = data.get("data", {})
        return {
            "active_cryptocurrencies": g.get("active_cryptocurrencies", 0) or 0,
            "btc_dominance": g.get("market_cap_percentage", {}).get("btc", 0) or 0,
            "eth_dominance": g.get("market_cap_percentage", {}).get("eth", 0) or 0,
            "total_market_cap": g.get("total_market_cap", {}).get("usd", 0) or 0,
            "total_volume_24h": g.get("total_volume", {}).get("usd", 0) or 0,
            "market_cap_change_24h": g.get("market_cap_change_percentage_24h_usd", 0) or 0,
            "fear_greed_score": None,  # CG doesn't provide this — would need alternative source
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "CoinGecko global API",
        }
    except Exception as e:
        return {"error": str(e)}


# ─── GitHub Trending (Developer Sentiment Proxy) ───────────────────────────────

def get_github_trending_repos(language: str = "python", period: str = "daily") -> dict:
    """
    Get trending crypto repos on GitHub.
    High star velocity on trading bots, DeFi, yield farms = smart money interest.
    Period: daily, weekly, monthly
    """
    try:
        params = {"q": f"crypto OR trading OR defi OR yield farm language:{language}",
                  "sort": "stars", "order": "desc", "per_page": 10}
        if period == "weekly":
            params["q"] += " created:>2026-04-07"
        elif period == "monthly":
            params["q"] += " created:>2026-03-14"

        data = _gh_get("search/repositories", params=params)
        if "error" in data:
            return data
        repos = []
        for repo in data.get("items", [])[:10]:
            repos.append({
                "name": repo.get("name", ""),
                "full_name": repo.get("full_name", ""),
                "description": repo.get("description", ""),
                "stars": repo.get("stargazers_count", 0) or 0,
                "forks": repo.get("forks_count", 0) or 0,
                "language": repo.get("language", ""),
                "created_at": repo.get("created_at", ""),
                "pushed_at": repo.get("pushed_at", ""),
                "url": repo.get("html_url", ""),
            })
        return {
            "repos": repos,
            "period": period,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "GitHub API",
        }
    except Exception as e:
        return {"error": str(e)}


def get_crypto_github_activity(coin_id: str) -> dict:
    """
    Get GitHub activity for a crypto project's repo.
    Use CoinGecko's coin ID to find their GitHub and query activity.
    """
    try:
        coin_data = _cg_get(f"coins/{coin_id}", params={
            "developer_data": "true",
            "community_data": "false",
            "market_data": "false",
        })
        if "error" in coin_data:
            return coin_data
        dev = coin_data.get("developer_data", {}) or {}
        return {
            "coin_id": coin_id,
            "stars": dev.get("stars", 0) or 0,
            "subscribers": dev.get("subscribers", 0) or 0,
            "forks": dev.get("forks", 0) or 0,
            "total_issues": dev.get("total_issues", 0) or 0,
            "closed_issues": dev.get("closed_issues", 0) or 0,
            "commit_activity_4w": dev.get("commit_activity_4_weeks", []),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "CoinGecko developer data",
        }
    except Exception as e:
        return {"coin_id": coin_id, "error": str(e)}


# ─── Fear & Greed Index (Alternative Sources) ─────────────────────────────────

def get_fear_greed(cpip_api_key: str = None) -> dict:
    """
    Alternative.me Fear & Greed Index — no API key needed.
    Returns current fear/greed score (0-100).
    """
    try:
        resp = requests.get(
            "https://api.alternative.me/fng/?limit=1",
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            item = data.get("data", [{}])[0]
            return {
                "value": int(item.get("value", 0)),
                "classification": item.get("value_classification", ""),
                "timestamp": item.get("timestamp", ""),
                "source": "alternative.me",
            }
    except Exception:
        pass
    return {"value": None, "classification": "unavailable", "source": "alternative.me"}


# ─── Sentiment Score Combiner ─────────────────────────────────────────────────

def get_sentiment_score(symbol: str, coin_id: str = None) -> dict:
    """
    Combine all available sentiment signals into a single score 0-100.
    0 = extreme fear, 50 = neutral, 100 = extreme greed.
    """
    score = 50  # neutral baseline
    signals = []

    # Fear/Greed
    fg = get_fear_greed()
    if fg.get("value") is not None:
        signals.append({"source": "fear_greed", "value": fg["value"]})
        score = fg["value"]

    # CoinGecko trending
    try:
        trending = get_trending_searches()
        if "trending" in trending:
            signals.append({"source": "trending_coins", "count": len(trending["trending"])})
    except Exception:
        pass

    # Global market sentiment
    try:
        g = get_global_sentiment()
        if "total_market_cap" in g:
            change = g.get("market_cap_change_24h", 0)
            if change > 5:
                score = min(100, score + 10)
                signals.append({"source": "market_bullish", "change_24h": change})
            elif change < -5:
                score = max(0, score - 10)
                signals.append({"source": "market_bearish", "change_24h": change})
    except Exception:
        pass

    return {
        "symbol": symbol,
        "sentiment_score": score,
        "signals": signals,
        "interpretation": _interpret(score),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _interpret(score: int) -> str:
    if score <= 20:
        return "Extreme Fear — capitulation, potential buy signal"
    elif score <= 40:
        return "Fear — undervalued conditions"
    elif score <= 60:
        return "Neutral — no clear directional bias"
    elif score <= 80:
        return "Greed — overvalued conditions, caution on new longs"
    else:
        return "Extreme Greed — bubble territory, reduce exposure"


# ─── Formatters ───────────────────────────────────────────────────────────────

def format_sentiment_report(symbol: str, coin_id: str = None) -> str:
    """Build a human-readable sentiment report."""
    report = get_sentiment_score(symbol, coin_id)
    fg = get_fear_greed()
    trending = get_trending_searches()
    global_s = get_global_sentiment()

    lines = [
        f"**Sentiment Report — {symbol}**",
        f"Score: **{report['sentiment_score']}/100** ({report['interpretation']})",
        f"Fear & Greed: **{fg.get('value', 'N/A')} — {fg.get('classification', 'N/A')}**",
    ]

    if "trending" in trending and trending["trending"]:
        top = trending["trending"][0]
        lines.append(f"Trending: **{top['name']} ({top['symbol']})** #1 on CoinGecko")

    if "total_market_cap" in global_s:
        lines.append(
            f"Global: ${global_s['total_market_cap']/1e12:.1f}T | "
            f"24h: {global_s.get('market_cap_change_24h', 0):+.1f}%"
        )
        lines.append(f"BTC Dom: **{global_s.get('btc_dominance', 0):.1f}%**")

    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing Sentiment module...")

    fg = get_fear_greed()
    print(f"Fear & Greed: {fg}")

    trending = get_trending_searches()
    print(f"Trending coins: {len(trending.get('trending', []))} returned")

    gs = get_global_sentiment()
    print(f"Global sentiment: {gs}")

    score = get_sentiment_score("BTC")
    print(f"BTC sentiment score: {score['sentiment_score']} — {score['interpretation']}")

    github = get_github_trending_repos(language="python", period="weekly")
    print(f"GitHub trending repos: {len(github.get('repos', []))} returned")

    print("✅ Sentiment module loaded")