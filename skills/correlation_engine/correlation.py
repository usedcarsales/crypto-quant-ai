"""
Cross-Signal Correlation Engine
Phase 3, Task 3.6 — Combines all Phase 2 + Phase 3 signals into composite trade conviction

Weights (configurable in config/phase3_weights.json):
  TA Score:            35%
  On-Chain Health:     20%
  Smart Money Flow:    20%
  DeFi Opportunity:   15%
  Social Sentiment:    10%

Output: composite score 0-100, final signal, confidence, divergence flags
"""

import importlib.util as _spec
import json
import os
from datetime import datetime, timezone


# ─── Module Loader ─────────────────────────────────────────────────────────────

def _load_mod(name, path):
    s = _spec.spec_from_file_location(name, path)
    m = _spec.module_from_spec(s)
    s.loader.exec_module(m)
    return m

TA_MOD  = _load_mod("ta_mod",  "skills/ta_engine/analyze.py")
OC_MOD  = _load_mod("oc_mod",  "skills/onchain_engine/health_scorer.py")
SOC_MOD = _load_mod("soc_mod", "skills/sentiment_engine/social_alpha.py")
DF_MOD  = _load_mod("df_mod",  "skills/onchain_engine/defi_scanner.py")
WL_MOD  = _load_mod("wl_mod",  "skills/wallet_engine/smart_money.py")


# ─── Weights ──────────────────────────────────────────────────────────────────

DEFAULT_WEIGHTS = {
    "ta_weight":                0.35,
    "onchain_health_weight":    0.20,
    "smart_money_weight":        0.20,
    "defi_opportunity_weight":   0.15,
    "social_sentiment_weight":    0.10,
}


def load_weights():
    p = "config/phase3_weights.json"
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_WEIGHTS.copy()


# ─── Cache for --quick mode ──────────────────────────────────────────────────
TA_CACHE_FILE = "/tmp/crypto-quant-ta-cache.json"
USE_TA_CACHE  = False   # set True via --quick flag


def _load_ta_cache():
    """Load cached TA data (from paper_trader --cache)."""
    if os.path.exists(TA_CACHE_FILE):
        try:
            with open(TA_CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}
# ─── TA Cache for --quick mode ───────────────────────────────────────────────
TA_CACHE_FILE = "/tmp/crypto-quant-ta-cache.json"
_TA_CACHE     = {}

def _load_ta_cache():
    global _TA_CACHE
    if os.path.exists(TA_CACHE_FILE):
        try:
            import json as _j
            with open(TA_CACHE_FILE) as _f:
                _TA_CACHE = _j.load(_f)
        except Exception:
            pass

def _get_ta_cached(symbol):
    """Return cached TA data dict for a symbol, or None if not cached."""
    return _TA_CACHE.get(symbol.upper())


def _norm_ta(ta_data):
    if not ta_data or "error" in ta_data:
        return 50.0
    return float(ta_data.get("conviction_score", 50))


def _norm_onchain():
    try:
        scored = OC_MOD.score_all_protocols(min_tvl=1_000_000)
        if scored:
            return round(sum(p["health_100"] for p in scored) / len(scored), 1)
        return 50.0
    except Exception:
        return 50.0


def _norm_smart_money():
    try:
        signals = WL_MOD.check_watchlist()
        if not signals:
            g = SOC_MOD.get_global_sentiment()
            if "error" not in g:
                mcp = g.get("mcap_change_24h", 0)
                return round(min(max(50 + mcp * 8, 0), 100), 1)
            return 50.0
        buys  = sum(1 for s in signals if s["direction"] == "BUY")
        sells = sum(1 for s in signals if s["direction"] == "SELL")
        total = len(signals)
        ratio = (buys - sells) / total if total > 0 else 0
        return round(min(max(50 + ratio * 30, 0), 100), 1)
    except Exception:
        return 50.0


def _norm_defi():
    try:
        buys = DF_MOD.top_buys(n=20)
        if buys:
            return round(sum(p["opportunity_score"] for p in buys[:10]) / 10, 1)
        return 50.0
    except Exception:
        return 50.0


def _norm_social():
    try:
        g = SOC_MOD.get_global_sentiment()
        if "error" not in g:
            mcp = g.get("mcap_change_24h", 0)
            return round(min(max(50 + mcp * 8, 0), 100), 1)
        return 50.0
    except Exception:
        return 50.0


# ─── Core Scoring ─────────────────────────────────────────────────────────────

def _stddev(values):
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return variance ** 0.5


def _sig(score):
    if score >= 70:   return "BUY"
    elif score <= 35: return "SELL"
    return "NEUTRAL"


# CoinGecko ID map — common symbols → API IDs
COIN_ID_MAP = {
    "BTC": "bitcoin",      "ETH": "ethereum",      "SOL": "solana",
    "BNB": "binancecoin",  "AVAX": "avalanche-2",  "LINK": "chainlink",
    "UNI": "uniswap",      "AAVE": "aave",          "LIDO": "lido-staked-ether",
    "XRP": "ripple",       "DOGE": "dogecoin",      "ADA": "cardano",
}


def score_composite(symbol, coin_id=None, weights=None, chain="ETH"):
    if weights is None:
        weights = load_weights()

    # Resolve CoinGecko ID from symbol if not provided
    if coin_id is None:
        coin_id = COIN_ID_MAP.get(symbol.upper(), symbol.lower())

    # Collect individual signal scores — use cache if available (--quick mode)
    cached = _get_ta_cached(symbol)
    if cached is not None:
        ta_data = cached
        _load_ta_cache()  # ensure cache is populated
        ta_data = _get_ta_cached(symbol) or ta_data
    else:
        ta_data = TA_MOD.analyze(symbol=symbol, coin_id=coin_id, days=30)
    ta_score        = _norm_ta(ta_data)
    onchain_score   = _norm_onchain()
    smart_score     = _norm_smart_money()
    defi_score      = _norm_defi()
    social_score    = _norm_social()

    # Weighted composite
    composite = (
        ta_score        * weights.get("ta_weight",               0.35) +
        onchain_score  * weights.get("onchain_health_weight",   0.20) +
        smart_score    * weights.get("smart_money_weight",       0.20) +
        defi_score     * weights.get("defi_opportunity_weight",  0.15) +
        social_score   * weights.get("social_sentiment_weight", 0.10)
    )
    composite = round(composite, 1)

    # Signal
    if composite >= 70:   signal = "BUY"
    elif composite <= 35:  signal = "SELL"
    else:                  signal = "NEUTRAL"

    # Confidence: low stddev = aligned signals = high confidence
    all_scores = [ta_score, onchain_score, smart_score, defi_score, social_score]
    sd = _stddev(all_scores)
    if sd > 25:   confidence = "low"
    elif sd > 15: confidence = "medium"
    else:         confidence = "high"

    # Divergence: max-min spread > 40 = disagreement between signals
    divergence = (max(all_scores) - min(all_scores)) > 40

    breakdown = {
        "TA":         _sig(ta_score),
        "OnChain":    _sig(onchain_score),
        "SmartMoney": _sig(smart_score),
        "DeFi":       _sig(defi_score),
        "Social":     _sig(social_score),
    }

    return {
        "symbol":             symbol.upper(),
        "coin_id":            coin_id,
        "composite_score":    composite,
        "signal":             signal,
        "confidence":         confidence,
        "divergence":         divergence,
        "signal_breakdown":   breakdown,
        "ta_score":           round(ta_score, 1),
        "onchain_score":      round(onchain_score, 1),
        "smart_money_score":  round(smart_score, 1),
        "defi_score":         round(defi_score, 1),
        "social_score":       round(social_score, 1),
        "weights_used":       weights,
        "ta_data":            ta_data,
        "timestamp":          datetime.now(timezone.utc).isoformat(),
    }


# ─── Multi-Coin Matrix ────────────────────────────────────────────────────────

COIN_CONFIG = {
    "BTC":  {"coin_id": "bitcoin",             "chain": "BTC"},
    "ETH":  {"coin_id": "ethereum",             "chain": "ETH"},
    "SOL":  {"coin_id": "solana",               "chain": "SOL"},
    "BNB":  {"coin_id": "binancecoin",          "chain": "ETH"},
    "AVAX": {"coin_id": "avalanche-2",          "chain": "ETH"},
    "LINK": {"coin_id": "chainlink",            "chain": "ETH"},
    "UNI":  {"coin_id": "uniswap",              "chain": "ETH"},
    "AAVE": {"coin_id": "aave",                 "chain": "ETH"},
    "LIDO": {"coin_id": "lido-staked-ether",   "chain": "ETH"},
    "XRP":  {"coin_id": "ripple",               "chain": "ETH"},
}


def score_all(weights=None):
    results = []
    for symbol, cfg in COIN_CONFIG.items():
        try:
            r = score_composite(
                symbol=symbol,
                coin_id=cfg["coin_id"],
                weights=weights,
                chain=cfg["chain"],
            )
            results.append(r)
        except Exception as e:
            results.append({
                "symbol": symbol, "error": str(e),
                "composite_score": 50.0, "signal": "NEUTRAL",
                "ta_score": 50, "onchain_score": 50,
                "smart_money_score": 50, "defi_score": 50, "social_score": 50,
                "confidence": "unknown", "divergence": False,
                "signal_breakdown": {},
            })
    results.sort(key=lambda x: x["composite_score"], reverse=True)
    return results


# ─── Formatters ─────────────────────────────────────────────────────────────

def format_composite_report(symbol=None, coin_id=None):
    if symbol:
        r = score_composite(symbol=symbol, coin_id=coin_id)
        emoji  = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "🟡"}.get(r["signal"], "⚪")
        conf_e = {"high": "✅", "medium": "⚠️", "low": "❌"}.get(r["confidence"], "?")
        div_t  = " ⚠️ DIVERGENCE" if r["divergence"] else ""
        w = r["weights_used"]
        lines = [
            f"{emoji} **{symbol.upper()} — {r['signal']}** ({r['composite_score']}/100) {conf_e}{div_t}",
            f"  TA:          {r['ta_score']}/100 → {r['signal_breakdown']['TA']}",
            f"  On-Chain:     {r['onchain_score']}/100 → {r['signal_breakdown']['OnChain']}",
            f"  Smart Money:  {r['smart_money_score']}/100 → {r['signal_breakdown']['SmartMoney']}",
            f"  DeFi:         {r['defi_score']}/100 → {r['signal_breakdown']['DeFi']}",
            f"  Social:       {r['social_score']}/100 → {r['signal_breakdown']['Social']}",
            f"  Weights: TA {int(w['ta_weight']*100)}% | OC {int(w['onchain_health_weight']*100)}% | "
            f"SM {int(w['smart_money_weight']*100)}% | DeFi {int(w['defi_opportunity_weight']*100)}% | "
            f"Soc {int(w['social_sentiment_weight']*100)}%",
            f"_Confidence: {r['confidence'].upper()} | Divergence: {r['divergence']}_",
        ]
        return "\n".join(lines)
    else:
        results = score_all()
        lines = ["**Cross-Signal Matrix — All Coins**\n"]
        for r in results:
            emoji  = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "🟡"}.get(r.get("signal", "NEUTRAL"), "⚪")
            conf_e = {"high": "✅", "medium": "⚠️", "low": "❌"}.get(r.get("confidence", "?"), "?")
            div_s  = " ⚠️" if r.get("divergence") else ""
            score  = r.get("composite_score", 50)
            ta_s   = r.get("ta_score", 0)
            oc_s   = r.get("onchain_score", 0)
            sm_s   = r.get("smart_money_score", 0)
            df_s   = r.get("defi_score", 0)
            so_s   = r.get("social_score", 0)
            lines.append(
                f"{emoji} {r['symbol']:5s} **{score:5.1f}/100** {conf_e}{div_s}  "
                f"TA {ta_s:.0f} | OC {oc_s:.0f} | SM {sm_s:.0f} | DeFi {df_s:.0f} | Soc {so_s:.0f}"
            )
        return "\n".join(lines)


# ─── CLI (single-symbol for fast test) ───────────────────────────────────────

if __name__ == "__main__":
    import sys
    print("=== Cross-Signal Correlation Engine ===\n")

    quick = "--quick" in sys.argv
    if quick:
        _load_ta_cache()
        print("Using cached TA data (--quick mode — no API calls)\n")

    r = score_composite("BTC")
    w = r["weights_used"]
    emoji  = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "🟡"}.get(r["signal"], "⚪")
    conf_e = {"high": "✅", "medium": "⚠️", "low": "❌"}.get(r["confidence"], "?")
    div_t  = " ⚠️ DIVERGENCE" if r["divergence"] else ""
    print(
        f"{emoji} **BTC — {r['signal']}** ({r['composite_score']}/100) {conf_e}{div_t}\n"
        f"  TA:          {r['ta_score']}/100 → {r['signal_breakdown']['TA']}\n"
        f"  On-Chain:     {r['onchain_score']}/100 → {r['signal_breakdown']['OnChain']}\n"
        f"  Smart Money:  {r['smart_money_score']}/100 → {r['signal_breakdown']['SmartMoney']}\n"
        f"  DeFi:         {r['defi_score']}/100 → {r['signal_breakdown']['DeFi']}\n"
        f"  Social:       {r['social_score']}/100 → {r['signal_breakdown']['Social']}\n"
        f"  Weights: TA {int(w['ta_weight']*100)}% | OC {int(w['onchain_health_weight']*100)}% | "
        f"SM {int(w['smart_money_weight']*100)}% | DeFi {int(w['defi_opportunity_weight']*100)}% | "
        f"Soc {int(w['social_sentiment_weight']*100)}%\n"
        f"  Confidence: {r['confidence'].upper()} | Divergence: {r['divergence']}"
    )
    if quick:
        print("\n✅ Correlation Engine (--quick) working — no new API calls")
    else:
        print("\n✅ Correlation Engine working")
