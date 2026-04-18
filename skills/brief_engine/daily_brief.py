"""
Daily Quant Brief Generator
Phase 6 — Market Intelligence Report Engine

Synthesizes all Phase 1-4 modules into a concise, actionable market intelligence report.
Designed for automated Discord posting and future premium signal subscription.

Output formats:
  - markdown (Discord-ready)
  - json (programmatic)
  - html (email/web)

Changelog (2026-04-18):
  - FIX #2: Price data now works for all coins (was only showing BTC)
  - FIX #3: Smart money section handles empty data gracefully
  - FIX #4: Graceful degradation — brief generates even if engines fail
  - FEAT #5: --dry-run flag uses cached data instead of live API calls
  - FEAT #6: --coins flag to specify which coins to analyze
"""

import importlib.util as _spec
import json
import os
import sys
import copy
from datetime import datetime, timezone, timedelta

# Ensure project root is in Python path for module imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ─── Cache Directory ──────────────────────────────────────────────────────────

CACHE_DIR = os.path.join(PROJECT_ROOT, "data", "brief_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


# ─── Module Loader ────────────────────────────────────────────────────────────

def _load_mod(name, path):
    # Resolve relative paths from project root
    if not os.path.isabs(path):
        path = os.path.join(PROJECT_ROOT, path)
    s = _spec.spec_from_file_location(name, path)
    m = _spec.module_from_spec(s)
    s.loader.exec_module(m)
    return m

# Lazy imports — only load what we need, handle failures gracefully
_modules = {}

def _get_module(name, path):
    if name not in _modules:
        try:
            _modules[name] = _load_mod(name, path)
        except Exception as e:
            print(f"⚠️  Failed to load {name}: {e}")
            _modules[name] = None
    return _modules[name]

def get_price_engine():
    return _get_module("price", "skills/price_engine/coingecko.py")

def get_ta_engine():
    return _get_module("ta", "skills/ta_engine/analyze.py")

def get_health_scorer():
    return _get_module("health", "skills/onchain_engine/health_scorer.py")

def get_defi_scanner():
    return _get_module("defi", "skills/onchain_engine/defi_scanner.py")

def get_smart_money():
    return _get_module("smart", "skills/wallet_engine/smart_money.py")

def get_sentiment():
    return _get_module("sentiment", "skills/sentiment_engine/social_alpha.py")

def get_derivatives():
    return _get_module("derivs", "skills/derivatives_engine/sentiment.py")

def get_correlation():
    return _get_module("corr", "skills/correlation_engine/correlation.py")

def get_trade_signals():
    return _get_module("signals", "skills/signal_engine/trade_signals.py")

def get_scanner():
    return _get_module("scanner", "skills/scanner_engine/scanner.py")


# ─── Core Coins ──────────────────────────────────────────────────────────────

MAJOR_COINS = ["bitcoin", "ethereum", "solana", "binancecoin", "avalanche-2"]
MAJOR_SYMBOLS = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", 
                  "binancecoin": "BNB", "avalanche-2": "AVAX"}

# Reverse lookup: symbol → coin_id
SYMBOL_TO_ID = {v: k for k, v in MAJOR_SYMBOLS.items()}

# Additional known CoinGecko IDs for popular coins (for --coins flag)
KNOWN_COIN_IDS = {
    "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
    "bnb": "binancecoin", "avax": "avalanche-2",
    "xrp": "ripple", "ada": "cardano", "doge": "dogecoin",
    "dot": "polkadot", "matic": "matic-network", "link": "chainlink",
    "uni": "uniswap", "atom": "cosmos", "ltc": "litecoin",
    "near": "near", "apt": "aptos", "arb": "arbitrum",
    "op": "optimism", "sui": "sui",
}


def resolve_coin_ids(coins_input):
    """
    Resolve a mixed list of coin IDs and symbols to CoinGecko IDs.
    Handles: ["bitcoin", "BTC", "eth", "avalanche-2", "AVAX"]
    Returns: list of valid CoinGecko coin IDs
    """
    resolved = []
    for c in coins_input:
        c_lower = c.lower().strip()
        # Already a CoinGecko ID
        if c_lower in MAJOR_COINS:
            resolved.append(c_lower)
        # Symbol → ID via KNOWN_COIN_IDS
        elif c_lower in KNOWN_COIN_IDS:
            resolved.append(KNOWN_COIN_IDS[c_lower])
        # Symbol → ID via MAJOR_SYMBOLS reverse lookup
        elif c.upper() in SYMBOL_TO_ID:
            resolved.append(SYMBOL_TO_ID[c.upper()])
        # Assume it's already a valid CoinGecko ID (user knows what they're doing)
        else:
            resolved.append(c_lower)
    return resolved


# ─── Cache Helpers ────────────────────────────────────────────────────────────

def _cache_path(section, coins=None):
    """Generate cache file path for a data section."""
    coin_suffix = "_".join(sorted(coins or []))[:50]
    return os.path.join(CACHE_DIR, f"{section}_{coin_suffix}.json")


def _save_cache(section, data, coins=None):
    """Save data to cache file."""
    path = _cache_path(section, coins)
    try:
        with open(path, "w") as f:
            json.dump({
                "data": data,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            }, f, indent=2, default=str)
    except Exception as e:
        print(f"⚠️  Cache write failed for {section}: {e}")


def _load_cache(section, coins=None, max_age_hours=24):
    """
    Load cached data if available and not too old.
    Returns (data, age_hours) or (None, None) if cache miss.
    """
    path = _cache_path(section, coins)
    if not os.path.exists(path):
        return None, None
    try:
        with open(path) as f:
            cached = json.load(f)
        cached_at = datetime.fromisoformat(cached["cached_at"])
        age = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600
        if age > max_age_hours:
            return None, age  # Stale
        return cached["data"], age
    except Exception:
        return None, None


# ─── Data Collection (with graceful degradation) ─────────────────────────────

def _safe_collect(label, func, *args, **kwargs):
    """
    Wrapper that catches ANY exception from a data collector.
    Returns (data, success_bool). Never raises — brief always generates.
    """
    try:
        result = func(*args, **kwargs)
        return result, True
    except Exception as e:
        print(f"⚠️  {label} failed: {e}")
        return {"error": f"{label} collection failed: {e}", "_section_failed": True}, False


def collect_market_data(coins=None, dry_run=False):
    """Collect current market data for major coins."""
    coins = coins or MAJOR_COINS
    
    # Dry-run: try cache first
    if dry_run:
        cached, age = _load_cache("market_data", coins, max_age_hours=48)
        if cached is not None:
            print(f"   📦 Using cached market data ({age:.1f}h old)")
            return cached
    
    price_mod = get_price_engine()
    if not price_mod:
        return {"error": "Price engine unavailable", "prices": {}, "_section_failed": True}
    
    try:
        prices = price_mod.get_simple_price(coins, ["usd"])
        result = {"prices": prices, "timestamp": datetime.now(timezone.utc).isoformat()}
        _save_cache("market_data", result, coins)
        return result
    except Exception as e:
        return {"error": f"Price fetch failed: {e}", "prices": {}, "_section_failed": True}


def collect_ta_signals(coins=None, dry_run=False):
    """Collect technical analysis signals."""
    coins = coins or MAJOR_COINS
    
    if dry_run:
        cached, age = _load_cache("ta_signals", coins, max_age_hours=48)
        if cached is not None:
            print(f"   📦 Using cached TA signals ({age:.1f}h old)")
            return cached
    
    ta_mod = get_ta_engine()
    if not ta_mod:
        return {"error": "TA engine unavailable", "_section_failed": True}
    
    results = {}
    for coin_id in coins:
        symbol = MAJOR_SYMBOLS.get(coin_id, coin_id.upper())
        try:
            analysis = ta_mod.analyze_coin(coin_id)
            if analysis and (not isinstance(analysis, dict) or "error" not in analysis):
                results[symbol] = analysis
            else:
                results[symbol] = {"error": "No data"}
        except Exception as e:
            results[symbol] = {"error": str(e)}
    
    _save_cache("ta_signals", results, coins)
    return results


def collect_onchain_data(dry_run=False):
    """Collect on-chain health and DeFi data."""
    if dry_run:
        cached, age = _load_cache("onchain_data", max_age_hours=48)
        if cached is not None:
            print(f"   📦 Using cached on-chain data ({age:.1f}h old)")
            return cached
    
    results = {}
    
    health_mod = get_health_scorer()
    if health_mod:
        try:
            health = health_mod.score_all_chains()
            results["health"] = health
        except Exception as e:
            results["health"] = {"error": str(e)}
    
    defi_mod = get_defi_scanner()
    if defi_mod:
        try:
            defi = defi_mod.scan_opportunities()
            results["defi"] = defi
        except Exception as e:
            results["defi"] = {"error": str(e)}
    
    _save_cache("onchain_data", results)
    return results


def collect_sentiment(dry_run=False):
    """Collect social and derivatives sentiment."""
    if dry_run:
        cached, age = _load_cache("sentiment", max_age_hours=48)
        if cached is not None:
            print(f"   📦 Using cached sentiment data ({age:.1f}h old)")
            return cached
    
    results = {}

    sent_mod = get_sentiment()
    if sent_mod:
        try:
            if hasattr(sent_mod, 'get_global_sentiment'):
                social = sent_mod.get_global_sentiment()
            elif hasattr(sent_mod, 'analyze_sentiment'):
                social = sent_mod.analyze_sentiment()
            else:
                social = None
            results["social"] = social
        except Exception as e:
            results["social"] = {"error": str(e)}

    derivs_mod = get_derivatives()
    if derivs_mod:
        try:
            derivs = derivs_mod.analyze_derivatives_sentiment()
            results["derivatives"] = derivs
        except Exception as e:
            results["derivatives"] = {"error": str(e)}

    _save_cache("sentiment", results)
    return results


def collect_smart_money(dry_run=False):
    """Collect whale/smart money data."""
    if dry_run:
        cached, age = _load_cache("smart_money", max_age_hours=48)
        if cached is not None:
            print(f"   📦 Using cached smart money data ({age:.1f}h old)")
            return cached
    
    mod = get_smart_money()
    if not mod:
        return {"error": "Smart money module unavailable", "_section_failed": True}
    
    try:
        # Try the main function first
        if hasattr(mod, 'get_smart_money_signal'):
            result = mod.get_smart_money_signal()
        elif hasattr(mod, 'analyze_whale_flows'):
            result = mod.analyze_whale_flows()
        else:
            return {"error": "No compatible smart money function found", "_section_failed": True}
        
        if result and isinstance(result, dict):
            # If the result has no useful data (empty signals, no_data source),
            # still return it — the formatter will handle it gracefully
            _save_cache("smart_money", result)
            return result
        
        return {"score": 50.0, "signal": "NEUTRAL", "whale_signals": [], 
                "source": "no_data", "_note": "No significant whale activity detected"}
    except Exception as e:
        return {"error": str(e), "_section_failed": True}


def _load_composite_scores(coins=None):
    """Load composite scores from /tmp/quant-scores.json or correlation engine."""
    coins = coins or MAJOR_COINS
    scores = {}
    
    # Priority 1: cached quant-scores.json (fast, no API calls)
    try:
        with open("/tmp/quant-scores.json") as f:
            cached = json.load(f)
        for sym, data in cached.items():
            scores[sym] = data
    except Exception:
        pass
    
    # Priority 2: Run correlation engine for missing coins (slow)
    if len(scores) < len(coins) and not os.environ.get("QUANT_DRY_RUN"):
        corr_mod = get_correlation()
        if corr_mod:
            for coin_id in coins:
                symbol = MAJOR_SYMBOLS.get(coin_id, coin_id.upper())
                if symbol not in scores:
                    try:
                        result = corr_mod.score_composite(symbol, coin_id=coin_id)
                        if result and isinstance(result, dict):
                            scores[symbol] = result
                    except Exception:
                        pass
    
    return scores


def collect_trade_signals(coins=None, dry_run=False, composite_scores=None):
    """Generate trade signals for major coins. Requires composite_scores dict."""
    coins = coins or MAJOR_COINS
    composite_scores = composite_scores or {}
    
    if dry_run:
        cached, age = _load_cache("trade_signals", coins, max_age_hours=48)
        if cached is not None:
            print(f"   📦 Using cached trade signals ({age:.1f}h old)")
            return cached
    
    sig_mod = get_trade_signals()
    if not sig_mod:
        return {"error": "Signal engine unavailable", "_section_failed": True}
    
    results = {}
    for coin_id in coins:
        symbol = MAJOR_SYMBOLS.get(coin_id, coin_id.upper())
        try:
            # Get composite score for this coin
            score_data = composite_scores.get(symbol, {})
            cs = score_data.get("composite_score", score_data.get("score")) if score_data else None
            direction = score_data.get("signal", score_data.get("recommendation", "NEUTRAL")) if score_data else None
            confidence = score_data.get("confidence") if score_data else None
            divergence = score_data.get("divergence") if score_data else None
            
            signal = sig_mod.generate_signal(
                coin_id,
                composite_score=cs,
                direction=direction,
                confidence=confidence,
                divergence=divergence,
            )
            results[symbol] = signal
        except Exception as e:
            results[symbol] = {"error": str(e)}
    
    _save_cache("trade_signals", results, coins)
    return results


# ─── Report Generation ───────────────────────────────────────────────────────

def _emoji_for_signal(signal_str):
    """Return emoji for signal direction."""
    s = signal_str.upper() if isinstance(signal_str, str) else ""
    if "STRONG BUY" in s or "BUY" in s:
        return "🟢"
    elif "MODERATE BUY" in s:
        return "📈"
    elif "SELL" in s:
        return "🔴"
    elif "NEUTRAL" in s:
        return "⚪"
    return "📊"


def _format_price(price_data, coin_id):
    """
    Format price data for display.
    FIX #2: Handles both dict format from CoinGecko simple/price
    and the case where coin_id might not be in the response.
    """
    if not price_data or not isinstance(price_data, dict):
        return "N/A"
    
    data = price_data.get(coin_id)
    if not data or not isinstance(data, dict):
        return "N/A"
    
    price = data.get("usd")
    if price is None or price == 0:
        return "N/A"
    
    change_24h = data.get("usd_24h_change", 0) or 0
    change_str = f"+{change_24h:.2f}%" if change_24h >= 0 else f"{change_24h:.2f}%"
    return f"${price:,.2f} ({change_str})"


def _format_confidence(score):
    """Format confidence score with label. Handles both string and numeric inputs."""
    # Handle string confidence from correlation engine ("high", "medium", "low")
    if isinstance(score, str):
        s = score.strip().lower()
        if s in ("high", "very_high", "strong"):
            return "🟢 HIGH"
        elif s in ("medium", "moderate"):
            return "🟡 MODERATE"
        elif s in ("low", "weak"):
            return "🔴 LOW"
        else:
            return f"⚪ {score}"
    # Handle numeric confidence (0-100 scale)
    try:
        score = float(score)
    except (TypeError, ValueError):
        return f"⚪ {score}"
    if score >= 70:
        return f"🟢 HIGH ({score:.0f}/100)"
    elif score >= 50:
        return f"🟡 MODERATE ({score:.0f}/100)"
    else:
        return f"🔴 LOW ({score:.0f}/100)"


def generate_brief(format="markdown", coins=None, dry_run=False):
    """
    Generate a complete daily market intelligence brief.
    
    Args:
        format: "markdown", "json", or "html"
        coins: list of coin IDs or symbols to analyze (default: major coins)
        dry_run: if True, use cached data instead of live API calls
    
    Returns:
        Formatted brief string
    
    FIX #4: Graceful degradation — each section is collected independently.
    If any engine fails, the brief still generates with available sections.
    """
    coins = resolve_coin_ids(coins) if coins else MAJOR_COINS
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M UTC")
    date_str = now.strftime("%A, %B %d, %Y")
    
    if dry_run:
        print("📦 DRY-RUN MODE — using cached data where available")
    
    # Track which sections failed for the degradation notice
    failed_sections = []
    
    # ─── Collect all data (with graceful degradation) ────────────────────────
    print("📊 Collecting market data...")
    market, ok = _safe_collect("Market data", collect_market_data, coins, dry_run)
    if not ok:
        failed_sections.append("market_prices")
    
    print("📈 Running technical analysis...")
    ta_signals, ok = _safe_collect("TA signals", collect_ta_signals, coins, dry_run)
    if not ok:
        failed_sections.append("technical_analysis")
    
    print("⛓️  Analyzing on-chain data...")
    onchain, ok = _safe_collect("On-chain data", collect_onchain_data, dry_run)
    if not ok:
        failed_sections.append("onchain_intelligence")
    
    print("💬 Gathering sentiment...")
    sentiment, ok = _safe_collect("Sentiment", collect_sentiment, dry_run)
    if not ok:
        failed_sections.append("sentiment")
    
    print("🐋 Tracking smart money...")
    smart_money, ok = _safe_collect("Smart money", collect_smart_money, dry_run)
    if not ok:
        failed_sections.append("smart_money")
    
    print("🔗 Loading composite scores...")
    composite_scores = _load_composite_scores(coins)
    if composite_scores:
        print(f"   Loaded {len(composite_scores)} composite scores")
    
    print("🎯 Generating trade signals...")
    trade_sigs, ok = _safe_collect("Trade signals", collect_trade_signals, coins, dry_run, composite_scores)
    if not ok:
        failed_sections.append("trade_signals")
    
    # ─── Scanner (hot coins) ───────────────────────────────────────────────────
    print("🔍 Scanning for hot coins...")
    hot_coins = []
    if not dry_run:
        scan_mod = get_scanner()
        if scan_mod:
            try:
                scan_result = scan_mod.scan_all(n=20, rsi_enrich=False)
                if scan_result and isinstance(scan_result, dict):
                    hot_coins = scan_result.get("alerts", scan_result.get("hot_coins", scan_result.get("opportunities", [])))[:5]
                elif scan_result and isinstance(scan_result, list):
                    hot_coins = scan_result[:5]
            except Exception:
                pass
    
    # ─── Build report ──────────────────────────────────────────────────────────
    report_data = {
        "timestamp": timestamp,
        "date": date_str,
        "_coins": coins,
        "market": market,
        "ta_signals": ta_signals,
        "onchain": onchain,
        "sentiment": sentiment,
        "smart_money": smart_money,
        "trade_signals": trade_sigs,
        "composite_scores": composite_scores,
        "hot_coins": hot_coins,
        "failed_sections": failed_sections,
        "dry_run": dry_run,
    }
    
    if format == "json":
        return json.dumps(report_data, indent=2, default=str)
    elif format == "html":
        return _generate_html_brief(report_data)
    else:
        return _generate_markdown_brief(report_data)


def _generate_markdown_brief(data):
    """Generate Discord-ready markdown brief with graceful degradation."""
    lines = []
    now = data["timestamp"]
    date_str = data["date"]
    dry_run = data.get("dry_run", False)
    failed = data.get("failed_sections", [])
    
    mode_label = " [DRY-RUN]" if dry_run else ""
    lines.append(f"# 📊 Crypto Quant Daily Brief{mode_label}")
    lines.append(f"**{date_str}** — {now}")
    lines.append(f"*Powered by Particulate LLC Crypto Quant AI*")
    lines.append("")
    
    # ─── Executive Summary ─────────────────────────────────────────────────────
    lines.append("## 🎯 Executive Summary")
    
    composites = data.get("composite_scores", {})
    if composites:
        for symbol, score_data in composites.items():
            if isinstance(score_data, dict):
                score = score_data.get("composite_score", score_data.get("score", 0))
                signal = score_data.get("signal", "NEUTRAL")
                confidence = score_data.get("confidence", 0)
                emoji = _emoji_for_signal(signal)
                lines.append(f"- **{symbol}**: {emoji} {signal} — Score {score:.0f}/100 ({_format_confidence(confidence)})")
    else:
        lines.append("- Composite scores unavailable (modules still loading)")
    
    lines.append("")
    
    # ─── Market Overview ────────────────────────────────────────────────────────
    lines.append("## 💰 Market Prices")
    market = data.get("market", {})
    prices = market.get("prices", {})
    coins_in_brief = data.get("_coins", MAJOR_COINS)
    
    if prices and isinstance(prices, dict) and not market.get("_section_failed"):
        for coin_id in coins_in_brief:
            symbol = MAJOR_SYMBOLS.get(coin_id, coin_id.upper())
            price_str = _format_price(prices, coin_id)
            lines.append(f"- **{symbol}**: {price_str}")
    elif market.get("error"):
        lines.append(f"- ⚠️ Price data unavailable: {market['error']}")
    else:
        lines.append("- Price data unavailable")
    
    lines.append("")
    
    # ─── Trade Signals ──────────────────────────────────────────────────────────
    lines.append("## 🎯 Trade Signals")
    trade_sigs = data.get("trade_signals", {})
    if isinstance(trade_sigs, dict) and "error" not in trade_sigs:
        for symbol, sig in trade_sigs.items():
            if isinstance(sig, dict) and "error" not in sig:
                direction = sig.get("direction", sig.get("signal", "NEUTRAL"))
                confidence = sig.get("confidence", 0)
                entry = sig.get("entry_price", sig.get("entry", "N/A"))
                sl = sig.get("stop_loss", sig.get("sl", "N/A"))
                tp = sig.get("take_profit", sig.get("tp", "N/A"))
                rr = sig.get("risk_reward", sig.get("rr", "N/A"))
                emoji = _emoji_for_signal(direction)
                
                if isinstance(entry, (int, float)):
                    entry = f"${entry:,.2f}"
                if isinstance(sl, (int, float)):
                    sl = f"${sl:,.2f}"
                if isinstance(tp, (int, float)):
                    tp = f"${tp:,.2f}"
                
                lines.append(f"- **{symbol}** {emoji} {direction} (conf: {_format_confidence(confidence)})")
                lines.append(f"  Entry: {entry} | SL: {sl} | TP: {tp} | R/R: {rr}")
            elif isinstance(sig, dict) and "error" in sig:
                lines.append(f"- **{symbol}**: ⚠️ {sig['error']}")
    elif isinstance(trade_sigs, dict) and trade_sigs.get("_section_failed"):
        lines.append("- ⚠️ Trade signal engine unavailable")
    else:
        lines.append("- No trade signals available")
    
    lines.append("")
    
    # ─── On-Chain Intelligence ──────────────────────────────────────────────────
    lines.append("## ⛓️ On-Chain Intelligence")
    onchain = data.get("onchain", {})
    
    if onchain and not onchain.get("_section_failed"):
        # Health
        health = onchain.get("health", {})
        if health and isinstance(health, dict) and "error" not in health:
            top_chains = health.get("top_chains", health.get("chains", []))
            if isinstance(top_chains, list) and top_chains:
                lines.append("**Top Chains:**")
                for chain in top_chains[:3]:
                    if isinstance(chain, dict):
                        name = chain.get("name", "?")
                        tvl = chain.get("tvl", 0)
                        score = chain.get("health_score", chain.get("score", 0))
                        lines.append(f"  - {name}: ${tvl/1e9:.1f}B TVL, Health {score:.0f}/100")
            overall = health.get("overall_health", health.get("market_health", ""))
            if overall:
                lines.append(f"**Market Health:** {overall}")
        
        # DeFi
        defi = onchain.get("defi", {})
        if defi and isinstance(defi, dict) and "error" not in defi:
            opportunities = defi.get("opportunities", defi.get("top_protocols", []))
            if isinstance(opportunities, list) and opportunities:
                lines.append("**Top DeFi Opportunities:**")
                for opp in opportunities[:3]:
                    if isinstance(opp, dict):
                        name = opp.get("name", opp.get("protocol", "?"))
                        signal = opp.get("signal", opp.get("opportunity_signal", ""))
                        score = opp.get("score", opp.get("opportunity_score", 0))
                        emoji = _emoji_for_signal(signal)
                        lines.append(f"  - {emoji} {name}: {signal} (score: {score:.0f})")
    else:
        lines.append("- ⚠️ On-chain data unavailable")
    
    lines.append("")
    
    # ─── Sentiment ─────────────────────────────────────────────────────────────
    lines.append("## 💬 Sentiment Overview")
    sentiment = data.get("sentiment", {})
    
    if sentiment and not sentiment.get("_section_failed"):
        social = sentiment.get("social", {})
        if social and isinstance(social, dict) and "error" not in social:
            market_sent = social.get("market_sentiment", social.get("sentiment", ""))
            if market_sent:
                lines.append(f"- **Social Sentiment:** {market_sent}")
            trending = social.get("trending", social.get("trending_coins", []))
            if trending:
                if isinstance(trending, list) and len(trending) > 0:
                    names = [t.get("name", t) if isinstance(t, dict) else t for t in trending[:5]]
                    lines.append(f"- **Trending:** {', '.join(names)}")
        
        derivs = sentiment.get("derivatives", {})
        if derivs and isinstance(derivs, dict) and "error" not in derivs:
            market_sig = derivs.get("market_signal", derivs.get("signal", ""))
            score = derivs.get("market_score", derivs.get("composite_score", 0))
            if market_sig:
                lines.append(f"- **Derivatives Signal:** {market_sig} ({score:.0f}/100)")
    else:
        lines.append("- ⚠️ Sentiment data unavailable")
    
    lines.append("")
    
    # ─── Smart Money ────────────────────────────────────────────────────────────
    lines.append("## 🐋 Smart Money")
    sm = data.get("smart_money", {})
    
    # FIX #3: Handle all smart money states gracefully
    if sm and isinstance(sm, dict) and "error" not in sm:
        flows = sm.get("flows", sm.get("whale_flows", sm.get("whale_signals", [])))
        
        if isinstance(flows, list) and len(flows) > 0:
            lines.append("**Whale Activity:**")
            for flow in flows[:3]:
                if isinstance(flow, dict):
                    wallet = flow.get("wallet", flow.get("label", flow.get("address", "?")))
                    direction = flow.get("direction", flow.get("action", "?"))
                    amount = flow.get("amount_usd", flow.get("value", flow.get("amount", 0)))
                    coin = flow.get("coin", flow.get("token", "?"))
                    emoji = "🟢" if "buy" in str(direction).lower() else "🔴"
                    # Truncate wallet address for display
                    wallet_display = wallet[:16] + "..." if len(str(wallet)) > 16 else wallet
                    if isinstance(amount, (int, float)):
                        lines.append(f"  - {emoji} {wallet_display} {direction} ${amount:,.0f} {coin}")
                    else:
                        lines.append(f"  - {emoji} {wallet_display} {direction} {coin}")
        elif "signal" in sm:
            # Smart money has an aggregate signal but no individual flows
            score = sm.get("score", "?")
            source = sm.get("source", "?")
            net_flow = sm.get("net_flow_usd")
            lines.append(f"- **Aggregate Signal:** {sm['signal']} (score: {score})")
            if net_flow is not None:
                lines.append(f"- **Net Flow:** ${net_flow:,.0f}")
            lines.append(f"- Source: {source}")
        else:
            # Valid response but no useful data — not an error, just quiet
            lines.append("- No significant whale activity detected")
    elif sm and isinstance(sm, dict) and sm.get("error"):
        lines.append(f"- ⚠️ Smart money data unavailable: {sm['error']}")
    else:
        lines.append("- Smart money data unavailable")
    
    lines.append("")
    
    # ─── Hot Coins ─────────────────────────────────────────────────────────────
    if data.get("hot_coins"):
        lines.append("## 🔥 Hot Coins (Scanner)")
        for hc in data["hot_coins"][:5]:
            if isinstance(hc, dict):
                name = hc.get("name", hc.get("symbol", "?"))
                reason = hc.get("reason", hc.get("alert_type", ""))
                change = hc.get("price_change_24h", hc.get("change_24h", 0))
                lines.append(f"- **{name}**: {reason} ({change:+.1f}%)")
            else:
                lines.append(f"- {hc}")
        lines.append("")
    
    # ─── Degradation Notice ────────────────────────────────────────────────────
    if failed:
        lines.append("## ⚠️ Data Availability Notice")
        lines.append(f"The following sections had errors and may show limited data:")
        for section in failed:
            label = section.replace("_", " ").title()
            lines.append(f"- {label}")
        lines.append("")
    
    # ─── Risk Disclaimer ────────────────────────────────────────────────────────
    lines.append("---")
    lines.append("⚠️ *Not financial advice. Signals are for educational purposes. Always DYOR.*")
    lines.append("*Generated by Particulate LLC Crypto Quant AI v6.0*")
    
    return "\n".join(lines)


def _generate_html_brief(data):
    """Generate HTML brief for email/web."""
    # Simplified HTML version — use proper markdown parser in production
    md = _generate_markdown_brief(data)
    
    return f"""<!DOCTYPE html>
<html>
<head><title>Crypto Quant Daily Brief</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 700px; margin: 0 auto; padding: 20px; color: #1a1a2e; }}
h1 {{ color: #1a1a2e; border-bottom: 3px solid #0f3460; padding-bottom: 10px; }}
h2 {{ color: #16213e; border-bottom: 2px solid #0f3460; padding-bottom: 5px; }}
strong {{ color: #0f3460; }}
hr {{ border: none; border-top: 1px solid #ccc; margin: 20px 0; }}
em {{ color: #666; }}
</style>
</head>
<body>
<pre style="white-space: pre-wrap; font-family: inherit;">{md}</pre>
</body>
</html>"""


# ─── CLI Entry Point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate Crypto Quant Daily Brief")
    parser.add_argument("--format", choices=["markdown", "json", "html"], default="markdown",
                        help="Output format (default: markdown)")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument("--coins", nargs="+", default=None,
                        help="Coin IDs or symbols to analyze (default: BTC ETH SOL BNB AVAX). "
                             "Examples: --coins BTC ETH, --coins bitcoin cardano dogecoin")
    parser.add_argument("--dry-run", action="store_true",
                        help="Use cached data instead of live API calls (safe for offline testing)")
    parser.add_argument("--post", action="store_true",
                        help="Post the brief to Discord after generating (QuantAlpha free tier)")
    parser.add_argument("--channel", default=None,
                        help="Discord channel ID for --post (default: QuantAlpha free-tier channel)")
    args = parser.parse_args()
    
    coin_label = ", ".join(args.coins) if args.coins else "MAJOR_COINS"
    mode_label = " (dry-run)" if args.dry_run else ""
    print(f"🚀 Generating Daily Brief ({args.format}) — coins: {coin_label}{mode_label}...")
    
    # For --post, always generate JSON internally for the post module
    if args.post:
        # Generate JSON data for the post module
        brief = generate_brief(format="json", coins=args.coins, dry_run=args.dry_run)
        report_data = json.loads(brief)
        
        # Also generate markdown for stdout display
        md_brief = _generate_markdown_brief(report_data)
        if args.output:
            with open(args.output, "w") as f:
                f.write(md_brief)
            print(f"✅ Brief saved to {args.output}")
        else:
            print(md_brief)
        
        # Post to Discord
        from quantalpha.discord_post import post_brief_to_discord, QUANTALPHA_CHANNEL_ID
        channel = args.channel or QUANTALPHA_CHANNEL_ID
        
        # Free tier: limit to top 3 coins
        from quantalpha.discord_formatter import FREE_COINS
        post_coins = FREE_COINS  # Always use free-tier coins for Discord post
        
        print(f"\n📬 Posting to Discord channel {channel}...")
        post_result = post_brief_to_discord(
            report_data=report_data,
            channel_id=channel,
            coins=post_coins,
            dry_run=args.dry_run,
        )
        
        if post_result["status"] == "posted":
            print(f"✅ Posted to Discord! (method: {post_result.get('method')})")
        elif post_result["status"] == "simulated":
            print(f"📦 Dry-run — Discord post simulated (not sent)")
        else:
            print(f"❌ Discord post failed: {post_result.get('error')}")
    else:
        brief = generate_brief(format=args.format, coins=args.coins, dry_run=args.dry_run)
        
        if args.output:
            with open(args.output, "w") as f:
                f.write(brief)
            print(f"✅ Brief saved to {args.output}")
        else:
            print(brief)
    
    print(f"\n✅ Brief generated at {datetime.now(timezone.utc).isoformat()}")