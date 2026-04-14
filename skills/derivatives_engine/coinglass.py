"""
CoinGlass Derivatives Data Module
Phase 1, Task 1.5 — Derivatives Data
Free tier: basic access available, no auth required for some endpoints
"""

import requests
import time
from datetime import datetime, timezone

BASE_URL = "https://open-api.coinglass.com/public/v2"

LAST_CALL = 0
MIN_INTERVAL = 2.0

def _get(endpoint: str, params: dict = None, headers: dict = None) -> dict:
    """Rate-limited GET request."""
    global LAST_CALL
    elapsed = time.time() - LAST_CALL
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    LAST_CALL = time.time()
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ─── Funding Rates ────────────────────────────────────────────────────────────

def get_funding_rates() -> dict:
    """
    Get funding rates for all perpetual futures.
    Funding rate arbitrage opportunity: when funding > 0.05%, collect by taking opposite side.
    """
    return _get("funding_rate", headers={"Accept": "application/json"})


def get_exchange_funding(exchange: str = "binance") -> dict:
    """
    Get funding rates for a specific exchange.
    exchanges: binance, bybit, okx, huobi, gate, bitget, woo
    """
    params = {"exchange": exchange}
    return _get("funding_rate", params=params, headers={"Accept": "application/json"})


# ─── Open Interest ────────────────────────────────────────────────────────────

def get_open_interest() -> dict:
    """
    Get aggregate open interest across all exchanges and pairs.
    OI spikes confirm trends or flag incoming volatility.
    """
    return _get("open_interest", headers={"Accept": "application/json"})


def get_exchange_open_interest(exchange: str) -> dict:
    """Get OI for a specific exchange."""
    params = {"exchange": exchange}
    return _get("open_interest", params=params, headers={"Accept": "application/json"})


# ─── Liquidations ─────────────────────────────────────────────────────────────

def get_liquidation_stats() -> dict:
    """
    Get 24h liquidation data across all pairs.
    Liquidation clusters = key levels where cascading liquidations trigger.
    """
    return _get("liquidations", headers={"Accept": "application/json"})


def get_liquidationheatmap(symbol: str = "BTC") -> dict:
    """
    Get liquidation heatmap for a symbol.
    Shows concentration of long/short liquidations at price levels.
    """
    params = {"symbol": symbol}
    return _get("liquidation_heatmap", params=params, headers={"Accept": "application/json"})


# ─── Long/Short Ratio ────────────────────────────────────────────────────────

def get_long_short_ratio(exchange: str = "binance") -> dict:
    """
    Get long/short ratio for an exchange.
    When 80%+ are long, be the 20% — contrarian signal.
    """
    params = {"exchange": exchange}
    return _get("long_short_ratios", params=params, headers={"Accept": "application/json"})


# ─── Volume ───────────────────────────────────────────────────────────────────

def get_volume() -> dict:
    """Get trading volume across exchanges."""
    return _get("volume", headers={"Accept": "application/json"})


# ─── Top Traders ─────────────────────────────────────────────────────────────

def get_top_traders_position(exchange: str = "binance") -> dict:
    """
    Get top traders' long/short positions.
    Useful for following smart money positioning.
    """
    params = {"exchange": exchange}
    return _get("topTradersPosition", params=params, headers={"Accept": "application/json"})


# ─── Aggregated Market Summary ──────────────────────────────────────────────

def get_market_summary() -> dict:
    """
    Get aggregated market data: funding, OI, liquidations, volume.
    Single endpoint for top-level market health check.
    """
    return _get("market_summary", headers={"Accept": "application/json"})


# ─── Formatters ───────────────────────────────────────────────────────────────

def format_funding_opportunities(data: dict) -> list:
    """
    Parse funding rates and flag arbitrage opportunities.
    Returns pairs where funding > 0.05% (8-hour window).
    """
    opportunities = []
    try:
        items = data.get("data", []) or data.get("result", [])
        for item in items:
            rate = float(item.get("fundingRate", 0) or 0)
            if abs(rate) > 0.0005:  # > 0.05%
                opportunities.append({
                    "symbol": item.get("symbol", ""),
                    "exchange": item.get("exchange", ""),
                    "funding_rate": rate,
                    "funding_rate_pct": round(rate * 100, 4),
                    "annualized": round(rate * 3 * 365, 2),  # 3x daily
                    "direction": "long" if rate < 0 else "short",
                    "edge": "collect funding" if rate < 0 else "pay funding",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
    except (ValueError, TypeError):
        pass
    return sorted(opportunities, key=lambda x: x["funding_rate_pct"], reverse=True)


def format_liquidation_levels(data: dict) -> list:
    """
    Parse liquidation data into price clusters.
    Returns: [{price_level, long_liq, short_liq, total_liq}]
    """
    levels = []
    try:
        items = data.get("data", []) or data.get("result", []) or []
        for item in items:
            levels.append({
                "price": float(item.get("price", 0) or 0),
                "long_liquidations": float(item.get("longLiquidation", 0) or 0),
                "short_liquidations": float(item.get("shortLiquidation", 0) or 0),
                "total": float(item.get("totalLiquidation", 0) or 0),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    except (ValueError, TypeError):
        pass
    return sorted(levels, key=lambda x: x["total"], reverse=True)


if __name__ == "__main__":
    print("Testing CoinGlass module...")

    # Test funding rates
    try:
        fr = get_funding_rates()
        print(f"Funding rates response keys: {list(fr.keys()) if isinstance(fr, dict) else type(fr)}")
    except Exception as e:
        print(f"Funding rates: {e}")

    # Test liquidation stats
    try:
        liq = get_liquidation_stats()
        print(f"Liquidation stats: {type(liq)}")
    except Exception as e:
        print(f"Liquidations: {e}")

    # Test market summary
    try:
        ms = get_market_summary()
        print(f"Market summary keys: {list(ms.keys()) if isinstance(ms, dict) else type(ms)}")
    except Exception as e:
        print(f"Market summary: {e}")

    print("✅ CoinGlass module loaded — some endpoints may require API key")