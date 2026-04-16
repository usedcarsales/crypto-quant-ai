"""
Fast-Screen Scanner Layer
Abnormal activity detection across top 100 coins by volume.
Triggers: Volume spike, RSI extremes, Price momentum.
Feeds: correlation_engine → candidate_signals.json

No API keys needed — CoinGecko free tier.
"""

import os
import json
import time
import math
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Optional

# ─── CoinGecko Markets (top 100 by volume) ────────────────────────────────────
COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
HEADERS = {"User-Agent": "CryptoQuantBot/1.0 (by Servius)"}

# ─── Volume cache: symbol → {ts, volume_24h} for rolling avg ─────────────────
_VOL_CACHE_FILE = "/tmp/crypto-quant-volume-cache.json"
_VOL_CACHE: dict = {}
_LOADED = False

def _load_vol_cache():
    global _VOL_CACHE, _LOADED
    if _LOADED:
        return
    _LOADED = True
    try:
        with open(_VOL_CACHE_FILE) as f:
            raw = json.load(f)
        cutoff = time.time() - 172800  # 48h stale
        _VOL_CACHE = {k: v for k, v in raw.items() if v.get("ts", 0) > cutoff}
    except (FileNotFoundError, json.JSONDecodeError):
        _VOL_CACHE = {}

def _save_vol_cache():
    try:
        with open(_VOL_CACHE_FILE, "w") as f:
            json.dump(_VOL_CACHE, f)
    except Exception:
        pass


# ─── RSI Calculation ─────────────────────────────────────────────────────────
def calc_rsi(closes: list, period: int = 14) -> Optional[float]:
    """Calculate RSI from a list of close prices."""
    if len(closes) < period + 1:
        return None
    closes = [float(c) for c in closes]
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)


def get_rsi(coin_id: str, days: int = 14) -> Optional[float]:
    """Fetch OHLCV from CoinGecko and calculate 14-day RSI."""
    try:
        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc",
            params={"vs_currency": "usd", "days": days},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        ohlc_data = r.json()
        if not ohlc_data:
            return None
        closes = [c[4] for c in ohlc_data]  # close price is 5th element
        return calc_rsi(closes, 14)
    except Exception:
        return None


# ─── Fetch Top Coins ─────────────────────────────────────────────────────────
def fetch_top_coins(n: int = 100, vs_currency: str = "usd") -> list[dict]:
    """
    Fetch top N coins by volume from CoinGecko.
    Returns list of coin dicts with market data.
    """
    _load_vol_cache()
    results = []
    per_page = 100
    pages = (n + per_page - 1) // per_page

    for page in range(1, pages + 1):
        try:
            r = requests.get(
                COINGECKO_MARKETS,
                params={
                    "vs_currency": vs_currency,
                    "order": "volume_desc",
                    "per_page": per_page,
                    "page": page,
                    "sparkline": "false",
                    "price_change_percentage": "1h,24h,7d",
                },
                headers=HEADERS,
                timeout=20,
            )
            if r.status_code != 200:
                break
            results.extend(r.json())
            time.sleep(0.7)  # be polite to CoinGecko free tier
        except Exception:
            break

    return results[:n]


# ─── Core Screening Logic ─────────────────────────────────────────────────────
def screen_coin(coin: dict, vol_cache: dict) -> Optional[dict]:
    """
    Apply all 3 triggers to a single coin.
    Returns candidate dict if any trigger fires, else None.
    """
    symbol    = coin["symbol"].upper()
    coin_id   = coin["id"]
    price_1h  = coin.get("price_change_percentage_1h_in_currency") or 0
    price_24h = coin.get("price_change_percentage_24h_in_currency") or 0
    price_7d  = coin.get("price_change_percentage_7d_in_currency") or 0
    volume    = coin.get("total_volume", 0)
    mcap      = coin.get("market_cap", 0)
    rank      = coin.get("market_cap_rank", 999)
    image     = coin.get("image", "")
    name      = coin.get("name", "")

    triggers = []
    score = 0.0

    # ── Trigger 1: Volume Spike ─────────────────────────────────────────────
    # Compare today's 24h volume to yesterday's (cached from 24h ago)
    cached = vol_cache.get(symbol.lower(), {})
    prev_vol = cached.get("volume_24h", 0)
    vol_ratio = volume / prev_vol if prev_vol > 0 else 0.0

    if prev_vol > 0 and volume > prev_vol * 2:
        triggers.append(f"VOL_SPIKE:{vol_ratio:.1f}x")
        score += 2.5
    elif prev_vol > 0 and volume > prev_vol * 1.5:
        triggers.append(f"VOL_RISING:{vol_ratio:.1f}x")
        score += 1.0

    # ── Trigger 2: RSI Extremes ───────────────────────────────────────────────
    # Will be filled in by `screen_coins()` after batch fetch

    # ── Trigger 3: Price Momentum ─────────────────────────────────────────────
    if price_1h and abs(price_1h) > 3:
        triggers.append(f"PRICE_1H:{price_1h:+.2f}%")
        score += 1.5 * (abs(price_1h) / 3)  # scale by magnitude

    if price_24h and price_24h > 5:
        triggers.append(f"PRICE_24H:{price_24h:+.2f}%")
        score += 1.0

    if price_7d and price_7d < -15:
        triggers.append(f"DEEP_CORRECTION:{price_7d:+.2f}%")
        score += 1.5  # potential bounce setup

    # ── Base score: normalize volume relative to mcap ─────────────────────────
    if mcap > 0:
        vol_mcap_ratio = volume / mcap
        if vol_mcap_ratio > 0.10:
            score += 1.0  # high turnover relative to mcap

    if not triggers:
        return None

    return {
        "symbol":       symbol,
        "coin_id":      coin_id,
        "name":         name,
        "rank":         rank,
        "image":        image,
        "price":        coin.get("current_price", 0),
        "price_1h":     round(price_1h, 3),
        "price_24h":    round(price_24h, 3),
        "price_7d":     round(price_7d, 3),
        "volume_24h":   volume,
        "mcap":         mcap,
        "triggers":     triggers,
        "raw_score":    round(score, 2),
        "rsi":          None,  # filled in later
        "rsi_triggered": False,
    }


def screen_coins(top_coins: list[dict], vol_cache: dict) -> list[dict]:
    """
    Screen all top coins for abnormal activity.
    Fills in RSI for coins that already have 1+ trigger.
    Returns sorted list of candidates.
    """
    candidates = []
    for coin in top_coins:
        cand = screen_coin(coin, vol_cache)
        if cand:
            candidates.append(cand)

    # Sort by score descending
    candidates.sort(key=lambda x: x["raw_score"], reverse=True)

    return candidates


def enrich_with_rsi(candidates: list[dict], limit: int = 30) -> list[dict]:
    """
    For top N candidates by score, fetch live RSI and update their trigger list.
    Caps at `limit` to avoid CoinGecko rate limiting.
    """
    scored = [c for c in candidates if c["rsi"] is None]
    scored = scored[:limit]

    for cand in scored:
        coin_id = cand["coin_id"]
        rsi = get_rsi(coin_id, days=14)
        if rsi is not None:
            cand["rsi"] = rsi
            if rsi < 30:
                cand["rsi_triggered"] = True
                cand["triggers"].append(f"RSI_OVERSOLD:{rsi}")
                cand["raw_score"] += 2.0
            elif rsi > 70:
                cand["rsi_triggered"] = True
                cand["triggers"].append(f"RSI_OVERBOUGHT:{rsi}")
                cand["raw_score"] += 1.0

        time.sleep(0.5)  # polite rate limit

    # Re-sort after RSI enrichment
    candidates.sort(key=lambda x: x["raw_score"], reverse=True)
    return candidates


# ─── Full Scan Pipeline ───────────────────────────────────────────────────────
CANDIDATES_FILE = "/tmp/crypto-quant-candidates.json"
_SCAN_CACHE: dict = {}
_CACHE_TTL  = 900  # 15 minutes

def scan_all(n: int = 100, rsi_enrich: bool = True) -> dict:
    """
    Full scanner pipeline:
      1. Fetch top N coins by volume
      2. Apply 3-trigger screen
      3. Enrich top candidates with live RSI
      4. Save to candidate_signals.json
    Returns scan result dict.
    """
    global _SCAN_CACHE, _VOL_CACHE
    _load_vol_cache()

    # Fetch top N coins
    top_coins = fetch_top_coins(n=n)
    if not top_coins:
        return {"error": "failed_to_fetch_top_coins", "timestamp": datetime.now(timezone.utc).isoformat()}

    # Update volume cache for next run
    now = time.time()
    for coin in top_coins:
        sym = coin["symbol"].upper()
        _VOL_CACHE[sym.lower()] = {"ts": now, "volume_24h": coin.get("total_volume", 0)}
    _save_vol_cache()

    # Screen coins
    candidates = screen_coins(top_coins, _VOL_CACHE)

    # RSI enrichment for top candidates
    if rsi_enrich and candidates:
        candidates = enrich_with_rsi(candidates, limit=30)

    # Build result
    result = {
        "scan_timestamp":  datetime.now(timezone.utc).isoformat(),
        "coins_scanned":   len(top_coins),
        "candidates_found": len(candidates),
        "candidates":       candidates,
        "top_triggered":    candidates[:10] if candidates else [],
    }

    # Save to file
    try:
        with open(CANDIDATES_FILE, "w") as f:
            json.dump(result, f, indent=2, default=str)
    except Exception:
        pass

    _SCAN_CACHE = result
    return result


def load_candidates() -> dict:
    """Load most recent scan results from cache or file."""
    if _SCAN_CACHE:
        return _SCAN_CACHE
    try:
        with open(CANDIDATES_FILE) as f:
            data = json.load(f)
        ts = datetime.fromisoformat(data["scan_timestamp"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age < _CACHE_TTL:
            _SCAN_CACHE = data
            return data
    except (FileNotFoundError, (KeyError, ValueError)):
        pass
    return {"error": "no_recent_scan", "candidates": []}


def get_candidates_by_trigger(trigger_prefix: str) -> list[dict]:
    """Filter candidates by trigger prefix, e.g. 'RSI_OVERSOLD' or 'VOL_SPIKE'."""
    data = load_candidates()
    if "error" in data:
        return []
    return [
        c for c in data.get("candidates", [])
        if any(t.startswith(trigger_prefix) for t in c.get("triggers", []))
    ]


# ─── Opportunity Scoring ──────────────────────────────────────────────────────
def score_opportunity(cand: dict) -> float:
    """
    Composite opportunity score (0-100) for a candidate.
    Based on: trigger strength, RSI edge, momentum magnitude, market cap rank.
    """
    score = cand.get("raw_score", 0)

    # Rank factor: smaller mcap = higher potential for moves
    rank = cand.get("rank", 999)
    if rank <= 10:
        score *= 0.8   # large caps are stable
    elif rank <= 50:
        score *= 1.1   # mid caps have more room
    elif rank <= 100:
        score *= 1.3   # smaller caps = bigger moves possible
    else:
        score *= 0.5

    # RSI edge bonus
    rsi = cand.get("rsi")
    if rsi and rsi < 25:
        score *= 1.3   # very oversold = high bounce potential
    elif rsi and rsi < 35:
        score *= 1.15
    elif rsi and rsi > 80:
        score *= 0.7   # very overbought = mean reversion risk

    return round(min(max(score, 0), 100), 1)


# ─── Discord Formatter ────────────────────────────────────────────────────────
def format_scan_report(data: dict, limit: int = 10) -> str:
    """Format scan results for Discord output."""
    if "error" in data and data["error"] != "no_recent_scan":
        return f"❌ Scanner error: {data['error']}"

    candidates = data.get("candidates", [])
    if not candidates:
        return (
            "**🔍 Scanner Report**\n"
            f"Scanned **{data.get('coins_scanned', 0)}** coins.\n"
            "**No abnormal activity detected** — market may be in equilibrium.\n"
            f"_{data.get('scan_timestamp', '')}_"
        )

    top = candidates[:limit]
    lines = [
        f"**🔍 Scanner Report** | Scanned **{data['coins_scanned']}** coins | "
        f"**{data['candidates_found']}** flagged",
        "",
    ]

    # Group by trigger type
    rsi_os   = [c for c in top if any("RSI_OVERSOLD" in t for t in c["triggers"])]
    rsi_ob   = [c for c in top if any("RSI_OVERBOUGHT" in t for t in c["triggers"])]
    vol_spike= [c for c in top if any("VOL_SPIKE" in t for t in c["triggers"])]
    momentum  = [c for c in top if any("PRICE_1H" in t for t in c["triggers"])]
    deep_corr = [c for c in top if any("DEEP_CORRECTION" in t for t in c["triggers"])]

    if rsi_os:
        lines.append("**🟢 RSI Oversold (potential bounce):**")
        for c in rsi_os[:3]:
            rsi = c.get("rsi", "?")
            lines.append(f"  {c['symbol']:8s} RSI:{rsi:5s} | 1h:{c['price_1h']:+.2f}% | 24h:{c['price_24h']:+.2f}% | score:{c['raw_score']:.1f}")
        lines.append("")

    if deep_corr:
        lines.append("**🟡 Deep Correction (oversold bounce setup):**")
        for c in deep_corr[:3]:
            lines.append(f"  {c['symbol']:8s} 7d:{c['price_7d']:+.2f}% | vol: ${c['volume_24h']/1e6:.0f}M | score:{c['raw_score']:.1f}")
        lines.append("")

    if momentum:
        lines.append("**🔥 1H Momentum (>3% move):**")
        for c in momentum[:5]:
            lines.append(f"  {c['symbol']:8s} 1h:{c['price_1h']:+.2f}% | vol: ${c['volume_24h']/1e6:.0f}M | score:{c['raw_score']:.1f}")
        lines.append("")

    if vol_spike:
        lines.append("**📊 Volume Spikes (>2x avg):**")
        for c in vol_spike[:3]:
            for t in c["triggers"]:
                if "VOL" in t:
                    vol_tag = t
            lines.append(f"  {c['symbol']:8s} {vol_tag} | mcap: ${c['mcap']/1e9:.1f}B | score:{c['raw_score']:.1f}")
        lines.append("")

    if rsi_ob:
        lines.append("**🔴 RSI Overbought (caution):**")
        for c in rsi_ob[:3]:
            lines.append(f"  {c['symbol']:8s} RSI:{c.get('rsi','?')} | 1h:{c['price_1h']:+.2f}% | 24h:{c['price_24h']:+.2f}%")

    lines.append("")
    lines.append(f"_Scan: {data.get('scan_timestamp', '')}_")

    return "\n".join(lines)


def format_alert_summary(candidates: list[dict]) -> str:
    """One-line summary of top opportunities for quick reporting."""
    if not candidates:
        return "No scanner candidates."
    top = candidates[:5]
    parts = [f"**{c['symbol']}**" for c in top]
    return f"Top alerts: {', '.join(parts)} | {len(candidates)} total candidates"


# ─── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Crypto Scanner — Fast Screen ===\n")
    result = scan_all(n=100, rsi_enrich=True)
    if "error" not in result:
        print(f"Scanned: {result['coins_scanned']} coins")
        print(f"Candidates: {result['candidates_found']}")
        print()
        print(format_scan_report(result))
    else:
        print(f"Error: {result}")
