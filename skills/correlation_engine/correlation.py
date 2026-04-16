"""
Cross-Signal Correlation Engine
Phase 3, Task 3.6 — Combines all Phase 2 + Phase 3 signals into composite trade conviction

Weights (configurable in config/phase3_weights.json):
  TA Score:            35%
  On-Chain Health:     20%
  Smart Money Flow:    20%
  DeFi Opportunity:   15%
  Social Sentiment:    10%

Scanner Layer (Phase 4):
  - Scans top 100 coins by volume every 15 min
  - Triggers: volume spike >2x, RSI extremes, >3% 1h move
  - Feeds candidates into correlation engine for conviction scoring
  - Coins not in COIN_CONFIG get lightweight TA + scanner scoring
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

# Scanner — loaded lazily so correlation engine still works if scanner unavailable
_SCANNER_MOD = None

def _get_scanner():
    global _SCANNER_MOD
    if _SCANNER_MOD is None:
        try:
            _SCANNER_MOD = _load_mod("scan_mod", "skills/scanner_engine/scanner.py")
        except Exception:
            pass
    return _SCANNER_MOD


# ─── Weights ──────────────────────────────────────────────────────────────────

DEFAULT_WEIGHTS = {
    "ta_weight":                0.35,
    "onchain_health_weight":    0.20,
    "smart_money_weight":       0.20,
    "defi_opportunity_weight":   0.15,
    "social_sentiment_weight":   0.10,
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


# ─── TA Cache (for --quick mode) ─────────────────────────────────────────────
TA_CACHE_FILE = "/tmp/crypto-quant-ta-cache.json"
_TA_CACHE     = {}

def _load_ta_cache():
    global _TA_CACHE
    if os.path.exists(TA_CACHE_FILE):
        try:
            with open(TA_CACHE_FILE) as f:
                _TA_CACHE = json.load(f)
        except Exception:
            pass

def _get_ta_cached(symbol):
    """Return cached TA data dict for a symbol, or None if not cached."""
    return _TA_CACHE.get(symbol.upper())


# ─── Signal Normalizers ────────────────────────────────────────────────────────

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
    """
    Smart money signal normalizer.
    Uses get_smart_money_signal() from wallet_engine when available,
    which includes Arkham flow data for institutional wallets.
    Falls back to watchlist balance delta ratio.
    """
    try:
        sig_fn = getattr(WL_MOD, "get_smart_money_signal", None)
        if sig_fn:
            sm = sig_fn()
            if "error" not in sm:
                return float(sm.get("score", 50))
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
    """
    Social sentiment normalizer.
    NOW uses RSS aggregator (7 sources) as primary input,
    with CoinGecko mcap as secondary fallback.
    """
    try:
        g = SOC_MOD.get_global_sentiment()
        if "error" not in g:
            combined = g.get("combined_score", 50)
            return round(float(combined), 1)
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
    if score >= 70:    return "BUY"
    elif score <= 35:  return "SELL"
    return "NEUTRAL"


# CoinGecko ID map — common symbols → API IDs
COIN_ID_MAP = {
    "BTC": "bitcoin",      "ETH": "ethereum",       "SOL": "solana",
    "BNB": "binancecoin",  "AVAX": "avalanche-2",   "LINK": "chainlink",
    "UNI": "uniswap",      "AAVE": "aave",           "LIDO": "lido-staked-ether",
    "XRP": "ripple",      "DOGE": "dogecoin",       "ADA": "cardano",
}


def score_composite(symbol, coin_id=None, weights=None, chain="ETH",
                    scanner_candidates=None):
    """
    Full conviction score for a single coin.

    scanner_candidates: list of scanner candidate dicts from scan_all().
                         Coins in this list get a momentum boost added to composite.
    """
    if weights is None:
        weights = load_weights()

    if coin_id is None:
        coin_id = COIN_ID_MAP.get(symbol.upper(), symbol.lower())

    cached = _get_ta_cached(symbol)
    if cached is not None:
        _load_ta_cache()
        ta_data = _get_ta_cached(symbol) or cached
    else:
        ta_data = TA_MOD.analyze(symbol=symbol, coin_id=coin_id, days=30)

    ta_score      = _norm_ta(ta_data)
    onchain_score = _norm_onchain()
    smart_score   = _norm_smart_money()
    defi_score    = _norm_defi()
    social_score  = _norm_social()

    # ── Scanner momentum boost ──────────────────────────────────────────────
    # If this coin is flagged by the scanner, boost its composite score
    scanner_boost = 0.0
    scanner_triggers = []
    if scanner_candidates:
        sym_upper = symbol.upper()
        for c in scanner_candidates:
            if c.get("symbol", "").upper() == sym_upper:
                raw = c.get("raw_score", 0)
                # raw_score 0-15 → up to 18 point boost (scales with trigger strength)
                scanner_boost = min(raw * 1.2, 18)
                scanner_triggers = c.get("triggers", [])
                break

    # Weighted composite
    composite = (
        ta_score        * weights.get("ta_weight",               0.35) +
        onchain_score  * weights.get("onchain_health_weight",    0.20) +
        smart_score    * weights.get("smart_money_weight",       0.20) +
        defi_score     * weights.get("defi_opportunity_weight",  0.15) +
        social_score   * weights.get("social_sentiment_weight",  0.10)
    ) + scanner_boost
    composite = round(min(max(composite, 0), 100), 1)

    # ── RSI Safety Guard ─────────────────────────────────────────────────────
    # Extract RSI from ta_data
    rsi_value = None
    if ta_data and "indicators" in ta_data:
        rsi_value = ta_data["indicators"].get("rsi_14")
    elif ta_data and isinstance(ta_data, dict):
        rsi_value = ta_data.get("rsi_14") or ta_data.get("rsi")

    rsi_guard = None
    rsi_signal_override = None
    rsi_composite_override = None
    rsi_confidence_adjust = None

    if rsi_value is not None:
        if rsi_value >= 80:
            # HARD BLOCK — overbought, no execution regardless of composite
            rsi_guard = "HARD_BLOCK"
            rsi_signal_override = "NEUTRAL"
            rsi_composite_override = 35  # push below execution threshold
            composite = 35
            rsi_confidence_adjust = "low"
        elif rsi_value >= 70:
            # SOFT WARNING — overbought zone, require extra confirmation
            # Apply 15-point penalty; need composite ≥ 75 BEFORE penalty to override
            if composite < 75:
                rsi_guard = "SOFT_WARNING"
                composite = max(0, composite - 15)
                composite = round(composite, 1)
                rsi_confidence_adjust = "medium"
        elif rsi_value < 30:
            # BUY OPPORTUNITY — oversold, great entry point
            rsi_guard = "BUY_OPPORTUNITY"
            composite = min(100, composite + 8)
            composite = round(composite, 1)
            rsi_confidence_adjust = "high"
        else:
            rsi_guard = "NORMAL"
    else:
        rsi_guard = "RSI_UNAVAILABLE"

    # Re-evaluate signal after RSI guard
    if rsi_signal_override:
        signal = rsi_signal_override
    else:
        if composite >= 70:    signal = "BUY"
        elif composite <= 35:  signal = "SELL"
        else:                  signal = "NEUTRAL"

    # Confidence: low stddev = aligned signals = high confidence
    all_scores = [ta_score, onchain_score, smart_score, defi_score, social_score]
    sd = _stddev(all_scores)
    if rsi_confidence_adjust:
        # RSI guard overrides normal confidence calculation
        confidence = rsi_confidence_adjust
    elif sd > 25:    confidence = "low"
    elif sd > 15:    confidence = "medium"
    else:            confidence = "high"

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
        "scanner_boost":      round(scanner_boost, 2),
        "scanner_triggers":   scanner_triggers,
        "rsi":                rsi_value,
        "rsi_guard":           rsi_guard,
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


def score_all(weights=None, run_scanner: bool = True):
    """
    Score all configured coins + run the scanner for high-potential alerts.

    Returns (correlation_results, scanner_results).
    - correlation_results: full conviction scores for COIN_CONFIG coins
    - scanner_results: raw scanner data (for reporting alerts)

    Set run_scanner=False to skip scanner (e.g., paper trader already cached).
    """
    # Run scanner once — shared across all coin scores
    scan_data = {}
    scanner_candidates = []
    if run_scanner:
        scanner_mod = _get_scanner()
        if scanner_mod:
            try:
                scan_result = scanner_mod.scan_all(n=100, rsi_enrich=True)
                if scan_result and "error" not in scan_result:
                    scan_data = scan_result
                    scanner_candidates = scan_data.get("candidates", [])
            except Exception:
                pass  # scanner failure doesn't block correlation scoring

    # Score COIN_CONFIG coins with scanner context
    results = []
    for symbol, cfg in COIN_CONFIG.items():
        try:
            r = score_composite(
                symbol=symbol,
                coin_id=cfg["coin_id"],
                weights=weights,
                chain=cfg["chain"],
                scanner_candidates=scanner_candidates,
            )
            results.append(r)
        except Exception as e:
            results.append({
                "symbol": symbol, "error": str(e),
                "composite_score": 50.0, "signal": "NEUTRAL",
                "ta_score": 50, "onchain_score": 50,
                "smart_money_score": 50, "defi_score": 50, "social_score": 50,
                "scanner_boost": 0, "scanner_triggers": [],
                "confidence": "unknown", "divergence": False,
                "signal_breakdown": {},
            })

    # Sort by composite score
    results.sort(key=lambda x: x["composite_score"], reverse=True)

    # ── Scanner-only candidates ───────────────────────────────────────────────
    # Coins the scanner caught that aren't in COIN_CONFIG
    scored_symbols = {r["symbol"] for r in results}
    scanner_only = [
        c for c in scanner_candidates
        if c.get("symbol", "").upper() not in scored_symbols
    ]

    scanner_only_results = []
    for cand in scanner_only[:20]:  # cap at 20 to avoid rate limiting
        sym = cand.get("symbol", "")
        coin_id = cand.get("coin_id", sym.lower())
        try:
            ta_data = TA_MOD.analyze(symbol=sym, coin_id=coin_id, days=30)
            ta_score = _norm_ta(ta_data)
            scanner_raw = cand.get("raw_score", 0)

            # Lightweight composite: TA (40%) + market avg (25%) + smart money (20%)
            # + scanner momentum (15%)
            composite = (
                ta_score            * 0.40 +
                50                  * 0.25 +
                50                  * 0.20 +
                scanner_raw * 3.0   * 0.15
            )
            composite = round(min(max(composite, 0), 100), 1)

            # ── RSI Safety Guard (scanner-only coins) ──────────────────────────
            # Extract RSI: cached scanner RSI or from TA analysis
            rsi_value = cand.get("rsi")
            if rsi_value is None and ta_data and "indicators" in ta_data:
                rsi_value = ta_data["indicators"].get("rsi_14")

            rsi_guard = None
            if rsi_value is not None:
                if rsi_value >= 80:
                    # HARD BLOCK — overbought, no execution regardless of composite
                    rsi_guard = "HARD_BLOCK"
                    composite = 35
                elif rsi_value >= 70:
                    # SOFT WARNING — require extra confirmation
                    if composite < 75:
                        rsi_guard = "SOFT_WARNING"
                        composite = max(0, composite - 15)
                        composite = round(composite, 1)
                elif rsi_value < 30:
                    # BUY OPPORTUNITY — oversold, great entry
                    rsi_guard = "BUY_OPPORTUNITY"
                    composite = min(100, composite + 8)
                    composite = round(composite, 1)
                else:
                    rsi_guard = "NORMAL"
            else:
                rsi_guard = "RSI_UNAVAILABLE"

            signal = "BUY" if composite >= 70 else "SELL" if composite <= 35 else "NEUTRAL"

            # Scanner-only coins with strong momentum get tagged as HIGH POTENTIAL
            # even if conviction < 70 (reported as alerts, not auto-traded)
            # BUT RSI oversold must be genuine (not RSI overbought which is a warning)
            high_potential = (
                (rsi_guard == "BUY_OPPORTUNITY") or
                (cand.get("rsi_triggered") and rsi_guard != "HARD_BLOCK") or
                (scanner_raw >= 8 and rsi_guard not in ("HARD_BLOCK","SOFT_WARNING")) or
                (composite >= 55 and any("RSI_OVERSOLD" in t for t in cand.get("triggers", [])))
            )

            scanner_only_results.append({
                "symbol":              sym.upper(),
                "coin_id":             coin_id,
                "composite_score":     composite,
                "signal":              signal,
                "confidence":          "low",  # low confidence due to limited signals
                "divergence":          True,   # limited data = divergence by default
                "signal_breakdown":    {"TA": _sig(ta_score), "Scanner": "boost"},
                "ta_score":           round(ta_score, 1),
                "onchain_score":      50,
                "smart_money_score":  50,
                "defi_score":         50,
                "social_score":        50,
                "scanner_only":       True,
                "high_potential":      high_potential,
                "scanner_triggers":   cand.get("triggers", []),
                "scanner_raw_score":  scanner_raw,
                "rsi":                rsi_value,
                "rsi_guard":           rsi_guard,
                "price_1h":           cand.get("price_1h"),
                "price_24h":          cand.get("price_24h"),
                "price_7d":           cand.get("price_7d"),
                "rank":               cand.get("rank"),
                "weights_used":       weights,
                "timestamp":          datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass

    scanner_only_results.sort(key=lambda x: x["composite_score"], reverse=True)

    # Attach scanner metadata to return
    scan_data["scanner_only_results"] = scanner_only_results

    return results, scan_data


# ─── Formatters ─────────────────────────────────────────────────────────────

def format_composite_report(symbol=None, coin_id=None):
    if symbol:
        r = score_composite(symbol=symbol, coin_id=coin_id)
        emoji  = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "🟡"}.get(r["signal"], "⚪")
        conf_e = {"high": "✅", "medium": "⚠️", "low": "❌"}.get(r["confidence"], "?")
        div_t  = " ⚠️ DIVERGENCE" if r["divergence"] else ""
        w = r["weights_used"]
        scan_line = ""
        if r.get("scanner_boost", 0) > 0:
            trig = ", ".join(r.get("scanner_triggers", [])[:3])
            scan_line = f"  📡 Scanner: **+{r['scanner_boost']}/100** [{trig}]\n"
        lines = [
            f"{emoji} **{symbol.upper()} — {r['signal']}** ({r['composite_score']}/100) {conf_e}{div_t}",
            f"  TA:          {r['ta_score']}/100 → {r['signal_breakdown']['TA']}",
            f"  On-Chain:     {r['onchain_score']}/100 → {r['signal_breakdown']['OnChain']}",
            f"  Smart Money:  {r['smart_money_score']}/100 → {r['signal_breakdown']['SmartMoney']}",
            f"  DeFi:         {r['defi_score']}/100 → {r['signal_breakdown']['DeFi']}",
            f"  Social:       {r['social_score']}/100 → {r['signal_breakdown']['Social']}",
            f"{scan_line}  Weights: TA {int(w['ta_weight']*100)}% | OC {int(w['onchain_health_weight']*100)}% | "
            f"SM {int(w['smart_money_weight']*100)}% | DeFi {int(w['defi_opportunity_weight']*100)}% | "
            f"Soc {int(w['social_sentiment_weight']*100)}%",
            f"_Confidence: {r['confidence'].upper()} | Divergence: {r['divergence']}_",
        ]
        return "\n".join(lines)
    else:
        results, scan_data = score_all()
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
            sb_str = f" 📡+{r.get('scanner_boost',0):.0f}" if r.get("scanner_boost", 0) > 0 else ""
            lines.append(
                f"{emoji} {r['symbol']:5s} **{score:5.1f}/100** {conf_e}{div_s}{sb_str}  "
                f"TA {ta_s:.0f} | OC {oc_s:.0f} | SM {sm_s:.0f} | DeFi {df_s:.0f} | Soc {so_s:.0f}"
            )

        # Append scanner-only high-potential alerts
        scan_only = scan_data.get("scanner_only_results", [])
        hp = [c for c in scan_only if c.get("high_potential")]
        if hp:
            lines.append("\n**📡 High-Potential Alerts (not in core config):**")
            for c in hp[:5]:
                emoji = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "🟡"}.get(c.get("signal", "NEUTRAL"), "⚪")
                trig = ", ".join(c.get("scanner_triggers", [])[:2])
                rsi_s = f" RSI:{c['rsi']}" if c.get("rsi") else ""
                lines.append(
                    f"  {emoji} {c['symbol']:5s} **{c['composite_score']:5.1f}/100** "
                    f"(HP) | {trig}{rsi_s}"
                )
        return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    print("=== Cross-Signal Correlation Engine ===\n")

    quick = "--quick" in sys.argv
    if quick:
        _load_ta_cache()
        print("Using cached TA data (--quick mode — no API calls)\n")

    r = score_composite("BTC")
    emoji  = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "🟡"}.get(r["signal"], "⚪")
    conf_e = {"high": "✅", "medium": "⚠️", "low": "❌"}.get(r["confidence"], "?")
    div_t  = " ⚠️ DIVERGENCE" if r["divergence"] else ""
    w = r["weights_used"]
    scan_line = ""
    if r.get("scanner_boost", 0) > 0:
        trig = ", ".join(r.get("scanner_triggers", [])[:3])
        scan_line = f"  📡 Scanner: **+{r['scanner_boost']}/100** [{trig}]\n"
    print(
        f"{emoji} **BTC — {r['signal']}** ({r['composite_score']}/100) {conf_e}{div_t}\n"
        f"  TA:          {r['ta_score']}/100 → {r['signal_breakdown']['TA']}\n"
        f"  On-Chain:     {r['onchain_score']}/100 → {r['signal_breakdown']['OnChain']}\n"
        f"  Smart Money:  {r['smart_money_score']}/100 → {r['signal_breakdown']['SmartMoney']}\n"
        f"  DeFi:         {r['defi_score']}/100 → {r['signal_breakdown']['DeFi']}\n"
        f"  Social:       {r['social_score']}/100 → {r['signal_breakdown']['Social']}\n"
        f"{scan_line}  Weights: TA {int(w['ta_weight']*100)}% | OC {int(w['onchain_health_weight']*100)}% | "
        f"SM {int(w['smart_money_weight']*100)}% | DeFi {int(w['defi_opportunity_weight']*100)}% | "
        f"Soc {int(w['social_sentiment_weight']*100)}%\n"
        f"  Confidence: {r['confidence'].upper()} | Divergence: {r['divergence']}"
    )
    if quick:
        print("\n✅ Correlation Engine (--quick) — no new API calls")
    else:
        print("\n✅ Correlation Engine working")
