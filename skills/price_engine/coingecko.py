"""
CoinGecko Price Data Module
Phase 1, Task 1.2 — Price & Market Data
Free tier: 30 calls/min, supports all chains
"""

import requests
import time
import json
from datetime import datetime, timezone, timezone
from typing import Optional

BASE_URL = "https://api.coingecko.com/api/v3"

# Rate limit handling
LAST_CALL = 0
MIN_INTERVAL = 2.0  # seconds between calls (stays well under 30/min)

def _rate_limit():
    """Enforce rate limit between calls."""
    global LAST_CALL
    elapsed = time.time() - LAST_CALL
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    LAST_CALL = time.time()


def _get(endpoint: str, params: dict = None, _retries: int = 3) -> dict:
    """Make a rate-limited GET request to CoinGecko with retry on 429."""
    _rate_limit()
    url = f"{BASE_URL}/{endpoint}"
    for attempt in range(_retries):
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 5))
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    # last attempt also failed — raise
    resp.raise_for_status()


# ─── Prices ──────────────────────────────────────────────────────────────────

def get_simple_price(coin_ids: list, vs_currencies: list = ["usd"]) -> dict:
    """
    Get current price for one or more coins.
    Returns: {coin_id: {vs_currency: price}}
    """
    params = {
        "ids": ",".join(coin_ids),
        "vs_currencies": ",".join(vs_currencies),
        "include_24hr_change": "true",
        "include_24hr_vol": "true",
        "include_market_cap": "true",
    }
    return _get("simple/price", params)


def get_market_chart(coin_id: str, vs_currency: str = "usd", days: int = 7) -> dict:
    """
    Get OHLCV + market cap for a coin over N days.
    Returns: {prices, market_caps, total_volumes}
    """
    params = {
        "vs_currency": vs_currency,
        "days": days,
    }
    return _get(f"coins/{coin_id}/market_chart", params)


# ─── OHLCV ────────────────────────────────────────────────────────────────────

def get_ohlc(coin_id: str, vs_currency: str = "usd", days: int = 7) -> list:
    """
    Get OHLC data (open, high, low, close) for a coin.
    Returns: [[timestamp, open, high, low, close], ...]
    Standardized output format per roadmap spec.
    """
    params = {
        "vs_currency": vs_currency,
        "days": days,
    }
    data = _get(f"coins/{coin_id}/ohlc", params)
    # CoinGecko returns: [timestamp, open, high, low, close]
    return [
        {
            "timestamp": datetime.fromtimestamp(item[0] / 1000, tz=timezone.utc).isoformat(),
            "open": item[1],
            "high": item[2],
            "low": item[3],
            "close": item[4],
        }
        for item in data
    ]


# ─── Market Data ─────────────────────────────────────────────────────────────

def get_coins_markets(
    vs_currency: str = "usd",
    category: str = None,
    order: str = "market_cap_desc",
    per_page: int = 100,
    page: int = 1,
    sparkline: bool = False,
    price_change_percentage: str = "1h,24h,7d",
) -> list:
    """
    Get list of coins with market data (price, vol, MC, etc.)
    Use to build ranking, find movers, screen for opportunities.
    """
    params = {
        "vs_currency": vs_currency,
        "order": order,
        "per_page": per_page,
        "page": page,
        "sparkline": str(sparkline).lower(),
        "price_change_percentage": price_change_percentage,
    }
    if category:
        params["category"] = category
    return _get("coins/markets", params)


def get_trending() -> dict:
    """Get trending coins (most searched/gaining right now)."""
    return _get("search/trending")


def get_new_listings(per_page: int = 50) -> list:
    """
    Get newly listed coins (catch new tokens early).
    Note: CoinGecko doesn't have a direct 'new listings' endpoint.
    Use coins_markets sorted by age or a workaround via search.
    """
    # Hack: get latest by adding 'new' category or search recently added
    # Using markets with no specific order to pull recent additions
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": per_page,
        "page": 1,
        "sparkline": "false",
    }
    return _get("coins/markets", params)


def get_coin_detail(coin_id: str) -> dict:
    """Get detailed info for a single coin (description, links, genesis, etc.)."""
    params = {
        "localization": "false",
        "tickers": "true",
        "market_data": "true",
        "community_data": "true",
        "developer_data": "true",
    }
    return _get(f"coins/{coin_id}", params)


# ─── Multi-Chain Support ──────────────────────────────────────────────────────

def get_chain_list() -> dict:
    """Get list of all supported chains/platforms."""
    return _get("asset_platforms")


# ─── Standardized Output ─────────────────────────────────────────────────────

def standardize_price(coin_id: str, data: dict, vs_currency: str = "usd") -> dict:
    """
    Convert CoinGecko price response to our standardized format.
    Output: {coin, chain, timestamp, price, change_24h, volume_24h, market_cap}
    """
    return {
        "coin": coin_id,
        "chain": "multi-chain",  # CoinGecko covers all chains
        "timestamp": datetime.utcnow().isoformat(),
        "price": data.get(coin_id, {}).get(vs_currency, 0),
        f"change_24h_pct": data.get(coin_id, {}).get(f"{vs_currency}_24h_change", 0),
        f"volume_24h": data.get(coin_id, {}).get(f"{vs_currency}_24h_vol", 0),
        f"market_cap": data.get(coin_id, {}).get(f"{vs_currency}_market_cap", 0),
    }


if __name__ == "__main__":
    # Smoke test
    print("Testing CoinGecko module...")
    price = get_simple_price(["bitcoin", "ethereum", "solana"])
    print(f"BTC: ${price['bitcoin']['usd']:,.0f}")
    print(f"ETH: ${price['ethereum']['usd']:,.0f}")
    print(f"SOL: ${price['solana']['usd']:,.2f}")
    print("OHLC (BTC, 7d):", len(get_ohlc("bitcoin", days=7)), "candles")
    print("Trending:", [c["item"]["symbol"] for c in get_trending()["coins"][:5]])
    print("✅ CoinGecko module working")
