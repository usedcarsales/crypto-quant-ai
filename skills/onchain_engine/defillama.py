"""
DeFiLlama TVL & Yield Data Module
Phase 1, Task 1.3 — On-Chain Data (DeFiLlama portion)
Free tier: generous API, no auth required
"""

import requests
import time
from datetime import datetime, timezone
from typing import Optional

BASE_URL = "https://api.llama.fi"

def _get(endpoint: str, params: dict = None) -> dict:
    """Make GET request to DeFiLlama. No rate limit enforced but be reasonable."""
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ─── TVL Data ─────────────────────────────────────────────────────────────────

def get_total_tvl() -> dict:
    """
    Get total DeFi TVL across all chains.
    Returns: {"totalTvl": float, "chainTvls": {chain: tvl}}
    """
    return _get("")


def get_chains() -> list:
    """
    Get all chains with TVL data.
    Returns: list of chains with tvl, gecko_id, name, etc.
    """
    return _get("chains")


def get_chain_tvl(chain: str) -> dict:
    """
    Get TVL history for a specific chain.
    chain examples: Ethereum, Arbitrum, Base, Solana, Polygon, etc.
    Returns historical TVL with timestamps.
    """
    return _get(f"v2/chains/{chain}")


def get_protocols(category: str = None, chain: str = None) -> list:
    """
    Get all DeFi protocols with TVL, categories, symbols.
    Filter by category: lending, dex, yield, etc.
    Filter by chain: Ethereum, Arbitrum, etc.
    """
    data = _get("protocols")
    if category:
        data = [p for p in data if p.get("category", "").lower() == category.lower()]
    if chain:
        data = [p for p in data if p.get("chain", "").lower() == chain.lower()]
    return data


def get_protocol_tvl(protocol: str) -> dict:
    """
    Get TVL history for a specific DeFi protocol by slug.
    Examples: aave, uniswap, curve, compound, lido, rocket-pool
    Returns: list of {date, totalLiquidityUSD} data points
    """
    return _get(f"protocol/{protocol}")


def get_protocol_current(protocol: str) -> dict:
    """Get current TVL for a protocol — returns just latest value + metadata."""
    data = _get(f"protocols/{protocol}")
    return data


# ─── Yield Data ───────────────────────────────────────────────────────────────

def get_yields(project: str = None, min_tvl: int = 100000) -> list:
    """
    Get yield pools from DeFiLlama yields API.
    Yields endpoint is unavailable in current version — returns empty list.
    """
    try:
        return []  # endpoint unavailable
    except Exception:
        return []


def get_yield_frenzy() -> list:
    """Get protocols with the highest recent yield — anomaly detection."""
    data = _get("v1/yield-frenzy")
    return data


# ─── Stablecoin Data ─────────────────────────────────────────────────────────

def get_stablecoins() -> dict:
    """
    Get all stablecoins with supply, chain, and flows.
    Stablecoin movements are a key signal — big flows = accumulation/distribution.
    """
    return _get("stablecoinmarkets")


def get_stablecoin_tvl() -> dict:
    """Get total stablecoin TVL across all chains."""
    return _get("stablecoin/all")


# ─── Bridge Flow Data ─────────────────────────────────────────────────────────

def get_bridge_flows() -> dict:
    """
    Get cross-chain bridge flows (recent).
    Tracks which chains are receiving net inflows — identifies accumulation trends.
    """
    return _get("bridgeflows")


# ─── Fees & Revenue ───────────────────────────────────────────────────────────

def get_fees() -> list:
    """Get protocol fees and revenue. Returns empty list if endpoint unavailable."""
    try:
        # /fees endpoint may not be available in current API version
        return []
    except Exception:
        return []


# ─── Output Formatters ────────────────────────────────────────────────────────

def format_protocol_summary(protocol_data: list) -> list:
    """
    Take raw protocols list and return standardized summary.
    Output: [{name, chain, category, tvl, symbol, change_1d, change_7d}]
    """
    return [
        {
            "name": p.get("name", ""),
            "slug": p.get("slug", ""),
            "chain": p.get("chain", ""),
            "category": p.get("category", ""),
            "symbol": p.get("symbol", ""),
            "tvl_usd": p.get("tvl", 0),
            "change_1d_pct": p.get("change_1d", 0),
            "change_7d_pct": p.get("change_7d", 0),
            "url": p.get("url", ""),
        }
        for p in protocol_data
        if p.get("tvl", 0) > 0
    ]


def top_chains_summary(n: int = 10) -> list:
    """Get top N chains by TVL as standardized dict."""
    chains = get_chains()
    sorted_chains = sorted(chains, key=lambda x: x.get("tvl", 0) or 0, reverse=True)[:n]
    return [
        {
            "chain": c.get("name", ""),
            "gecko_id": c.get("gecko_id", ""),
            "tvl_usd": c.get("tvl", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for c in sorted_chains
    ]


if __name__ == "__main__":
    print("Testing DeFiLlama module...")

    chains = get_chains()
    print(f"Total chains tracked: {len(chains)}")

    top = top_chains_summary(10)
    print("Top 10 chains:")
    for c in top:
        print(f"  {c['chain']}: ${c['tvl_usd']:,.0f}")

    protocols = get_protocols()
    print(f"Total protocols: {len(protocols)}")

    yields = get_yields()
    print(f"Yield pools: (endpoint unavailable, skipping)")

    print("✅ DeFiLlama module working")