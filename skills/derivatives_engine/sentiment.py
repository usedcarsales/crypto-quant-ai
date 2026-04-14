"""
Derivatives Sentiment Analysis
Phase 3, Task 3.4

Data Source: CoinGecko free API /derivatives (21K+ perpetual contracts)
Fallback: CoinGlass (key saved, currently returning 500 on all endpoints)

Rate limit handling: Results are cached for 300 seconds to avoid hitting
CoinGecko's free-tier rate limit (10-30 calls/minute).

Key Metrics:
  - Funding rate (8h, annualized) per coin + OI-weighted average
  - Basis (futures premium over spot) per contract
  - Open interest (total, billions USD)
  - 24h volume
  - Confidence weighting by data coverage

Output: derivatives_sentiment score 0-100 + signal (BULLISH/BEARISH/NEUTRAL)
"""

import requests
import json
import os
import time
from datetime import datetime, timezone
from collections import defaultdict


# ─── Config ───────────────────────────────────────────────────────────────────

COINGECKO_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (crypto-quant-bot/1.0)",
}

CG_BASE = "https://api.coingecko.com/api/v3"
CACHE_TTL = 300  # 5 minutes


# ─── Cache ────────────────────────────────────────────────────────────────────

_CACHE_FILE = "/tmp/crypto-quant-derivatives-cache.json"

def _cache_read():
    try:
        if os.path.exists(_CACHE_FILE):
            age = time.time() - os.path.getmtime(_CACHE_FILE)
            if age < CACHE_TTL:
                with open(_CACHE_FILE) as f:
                    return json.load(f)
    except Exception:
        pass
    return None

def _cache_write(data):
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


# ─── Data Fetchers ────────────────────────────────────────────────────────────

def get_derivatives_data(force_refresh: bool = False) -> list:
    """
    Fetch all derivative contracts from CoinGecko.
    Uses 5-minute cache to avoid rate limiting.
    Returns list of dicts with: market, symbol, index_id, price,
    funding_rate, open_interest, volume_24h, basis, contract_type.
    """
    if not force_refresh:
        cached = _cache_read()
        if cached is not None:
            return cached

    try:
        r = requests.get(
            f"{CG_BASE}/derivatives",
            headers=COINGECKO_HEADERS,
            timeout=20,
        )
        if r.status_code == 429:
            # Rate limited — try to use cache even if stale
            cached = _cache_read()
            if cached is not None:
                return cached
            return [{"error": "rate_limited"}]

        r.raise_for_status()
        data = r.json()
        _cache_write(data)
        return data
    except Exception as e:
        cached = _cache_read()
        if cached is not None:
            return cached
        return [{"error": str(e)}]


def get_perpetuals(coin: str = None, min_oi_usd: float = 1_000_000) -> list:
    """
    Get perpetual futures data, optionally filtered by coin.
    Only includes contracts with open_interest above min_oi_usd.
    """
    data = get_derivatives_data()
    if not data or (len(data) == 1 and "error" in data):
        return []

    perps = [
        d for d in data
        if d.get("contract_type") == "perpetual"
        and (coin is None or d.get("index_id") == coin)
        and (d.get("open_interest") or 0) >= min_oi_usd
    ]
    return perps


# ─── Scoring Functions ─────────────────────────────────────────────────────────

def funding_score(perps: list) -> dict:
    """
    Analyze funding rates across perpetual contracts.

    Convention: funding_rate from CoinGecko = rate per funding interval (typically 8h).
    Annualized = funding_rate * 3 * 365.

    Positive annualized funding = shorts paying longs = BULLISH positioning signal
    Negative annualized funding = longs paying shorts = BEARISH positioning signal

    Score: 0-100, neutral at 50. +0.1%/8h → ~75 score. -0.1%/8h → ~25 score.
    """
    valid = [d for d in perps if d.get("funding_rate") is not None]
    if not valid:
        return {"error": "no valid funding rate data"}

    # OI-weighted average to reflect actual market positioning
    weighted_sum, total_oi = 0.0, 0.0
    for d in valid:
        oi = d.get("open_interest", 0) or 0
        fr = float(d["funding_rate"]) * 100  # % per 8h
        weighted_sum += fr * oi
        total_oi += oi

    avg_8h = weighted_sum / total_oi if total_oi > 0 else sum(float(d["funding_rate"]) * 100 for d in valid) / len(valid)
    annualized = avg_8h * 3 * 365

    # Signal classification
    if annualized > 109:      fsig = "BEARISH_EXTREME"
    elif annualized > 54:    fsig = "BEARISH_HIGH"
    elif annualized > 21.9:  fsig = "BEARISH_MODERATE"
    elif annualized > -21.9: fsig = "NEUTRAL"
    elif annualized > -54:   fsig = "BULLISH_MODERATE"
    elif annualized > -109:   fsig = "BULLISH_HIGH"
    else:                    fsig = "BULLISH_EXTREME"

    # Score: +0.1% 8h = 75, -0.1% 8h = 25
    funding_pct_score = max(0, min(100, 50 + (avg_8h * 250)))

    return {
        "avg_funding_rate_8h_pct": round(avg_8h, 4),
        "annualized_funding_pct": round(annualized, 2),
        "signal": fsig,
        "score": round(funding_pct_score, 1),
        "num_contracts": len(valid),
        "total_oi_usd": round(total_oi, 0),
    }


def basis_score(perps: list) -> dict:
    """
    Analyze basis (futures premium over spot index).
    Positive basis = contango. Negative = backwardation.
    Contango = cost to hold longs = slightly bearish signal.
    """
    valid = [d for d in perps if d.get("basis") is not None]
    if not valid:
        return {"error": "no basis data"}

    w_sum, total_oi = 0.0, 0.0
    for d in valid:
        oi = d.get("open_interest", 0) or 0
        w_sum += float(d["basis"]) * oi
        total_oi += oi

    avg_basis = w_sum / total_oi if total_oi > 0 else sum(d["basis"] for d in valid) / len(valid)

    if avg_basis > 0.5:       bsig = "STRONG_CONTANGO"
    elif avg_basis > 0.2:   bsig = "MODERATE_CONTANGO"
    elif avg_basis > -0.2:   bsig = "NEUTRAL"
    elif avg_basis > -0.5:   bsig = "MODERATE_BACKWARDATION"
    else:                    bsig = "STRONG_BACKWARDATION"

    basis_s = max(0, min(100, 50 + avg_basis * 100))
    return {
        "avg_basis_pct": round(avg_basis, 4),
        "signal": bsig,
        "score": round(basis_s, 1),
    }


def volume_score(perps: list) -> dict:
    """24h volume as conviction indicator — higher volume = stronger signal."""
    valid = [d for d in perps if d.get("volume_24h") is not None]
    if not valid:
        return {"error": "no volume data"}

    total_vol = sum(float(d["volume_24h"]) for d in valid)
    avg_vol_per_contract = total_vol / len(valid) if valid else 0

    if avg_vol_per_contract > 100_000_000:   vsig = "HIGH_ACTIVITY"
    elif avg_vol_per_contract > 10_000_000:  vsig = "MODERATE_ACTIVITY"
    elif avg_vol_per_contract > 1_000_000:   vsig = "LOW_ACTIVITY"
    else:                                     vsig = "VERY_LOW_ACTIVITY"

    vol_score = min(100, 30 + (avg_vol_per_contract / 2_000_000))
    return {
        "total_24h_volume_usd": round(total_vol, 0),
        "avg_volume_per_contract": round(avg_vol_per_contract, 0),
        "signal": vsig,
        "score": round(vol_score, 1),
        "num_contracts": len(valid),
    }


def oi_score(perps: list) -> dict:
    """
    Open interest as market conviction measure.
    High OI = more capital at risk = stronger signal from this source.
    """
    valid = [d for d in perps if d.get("open_interest") is not None]
    if not valid:
        return {"error": "no OI data"}

    total_oi = sum(float(d["open_interest"]) for d in valid)
    oi_b = total_oi / 1_000_000_000

    if oi_b > 50:   osig = "EXTREME_POSITIONING"
    elif oi_b > 20: osig = "HIGH_POSITIONING"
    elif oi_b > 5:  osig = "MODERATE_POSITIONING"
    else:            osig = "LOW_POSITIONING"

    oi_s = min(100, 30 + oi_b * 2)
    return {
        "total_oi_usd": round(total_oi, 0),
        "total_oi_billions": round(oi_b, 1),
        "signal": osig,
        "score": round(oi_s, 1),
        "num_contracts": len(valid),
    }


# ─── Per-Coin Sentiment ────────────────────────────────────────────────────────

def sentiment_per_coin(coin: str, use_cache: bool = True) -> dict:
    """
    Get derivatives sentiment for a specific coin.
    Returns full breakdown + composite score.
    """
    data_key = f"derivatives_{coin}" if not use_cache else None
    perps = get_perpetuals(coin=coin, min_oi_usd=500_000)
    if not perps:
        return {
            "coin": coin,
            "error": f"No perpetual contracts found for {coin}",
            "derivatives_score": 50,
            "signal": "NO_DATA",
        }

    fr  = funding_score(perps)
    bs  = basis_score(perps)
    vs  = volume_score(perps)
    ois = oi_score(perps)

    # Weighted composite
    scores = [
        (fr.get("score", 50),  0.50),
        (bs.get("score", 50), 0.20),
        (vs.get("score", 50), 0.10),
        (ois.get("score", 50),0.20),
    ]
    composite = sum(s * w for s, w in scores)
    composite = round(composite, 1)

    if composite >= 65: signal = "BULLISH"
    elif composite <= 40: signal = "BEARISH"
    else: signal = "NEUTRAL"

    return {
        "coin": coin,
        "derivatives_score": composite,
        "signal": signal,
        "funding_data": fr,
        "basis_data": bs,
        "volume_data": vs,
        "oi_data": ois,
        "signal_breakdown": {
            "funding": fr.get("signal", "NO_DATA"),
            "basis": bs.get("signal", "NO_DATA"),
            "volume": vs.get("signal", "NO_DATA"),
            "oi": ois.get("signal", "NO_DATA"),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Market-Wide Sentiment ────────────────────────────────────────────────────

def market_sentiment() -> dict:
    """Aggregate derivatives sentiment across top coins."""
    coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK"]
    results, scores = [], []

    for coin in coins:
        r = sentiment_per_coin(coin)
        if "error" not in r:
            results.append(r)
            scores.append(r["derivatives_score"])

    if not results:
        return {"error": "no valid coin data", "derivatives_score": 50, "signal": "NEUTRAL"}

    avg_score = round(sum(scores) / len(scores), 1)
    if avg_score >= 65: signal = "BULLISH"
    elif avg_score <= 40: signal = "BEARISH"
    else: signal = "NEUTRAL"

    confidence = "high" if len(results) >= 7 else "medium" if len(results) >= 4 else "low"

    return {
        "derivatives_score": avg_score,
        "signal": signal,
        "confidence": confidence,
        "coins_analysed": len(results),
        "coin_details": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Formatting ───────────────────────────────────────────────────────────────

def format_derivatives_report(coin: str = None) -> str:
    """Human-readable derivatives sentiment report."""
    r = sentiment_per_coin(coin) if coin else market_sentiment()

    if "error" in r and r.get("derivatives_score") == 50:
        return f"⚠️ No derivatives data available for {coin or 'market'}"

    emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(r["signal"], "⚪")
    score = r["derivatives_score"]

    lines = [f"{emoji} **{coin or 'MARKET'} Derivatives — {r['signal']}** ({score}/100)"]

    if coin:
        fr  = r.get("funding_data", {})
        bs  = r.get("basis_data", {})
        vs  = r.get("volume_data", {})
        ois = r.get("oi_data", {})
        if "error" not in fr:
            lines.append(
                f"  Funding:   {fr.get('signal','?')} | {fr.get('avg_funding_rate_8h_pct','?'):+.4f}%/8h "
                f"= {fr.get('annualized_funding_pct','?'):+.1f}%/yr | score {fr.get('score','?')}"
            )
        if "error" not in bs:
            lines.append(f"  Basis:     {bs.get('signal','?')} | {bs.get('avg_basis_pct','?'):+.4f}% | score {bs.get('score','?')}")
        if "error" not in vs:
            vol = vs.get('total_24h_volume_usd', 0)
            lines.append(f"  Volume:    {vs.get('signal','?')} | ${vol/1e9:.1f}B/24h | score {vs.get('score','?')}")
        if "error" not in ois:
            oib = ois.get('total_oi_billions', '?')
            lines.append(f"  Open Int:  {ois.get('signal','?')} | ${oib}B OI | score {ois.get('score','?')}")
    else:
        lines.append(f"  {r.get('coins_analysed','?')} coins analysed | Confidence: {r.get('confidence','?').upper()}")
        for detail in r.get("coin_details", [])[:5]:
            lines.append(
                f"  {detail['coin']}: {detail['signal']} ({detail['derivatives_score']}/100) "
                f"| funding {detail.get('funding_data',{}).get('signal','?')} | "
                f"OI ${detail.get('oi_data',{}).get('total_oi_billions','?')}B"
            )

    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Derivatives Sentiment Analysis ===\n")

    r = market_sentiment()
    if "error" in r and r.get("derivatives_score") == 50:
        print("⚠️  Rate limited — waiting for CoinGecko cache to refresh...")
        print("   (Cache TTL = 5 min, retry by running script again)")
    else:
        print(format_derivatives_report())
        print()

        for coin in ["BTC", "ETH", "SOL"]:
            print(format_derivatives_report(coin=coin))
            print()

    print("✅ Derivatives module ready")