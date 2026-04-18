"""
Daily Quant Brief Generator
Phase 6 — Market Intelligence Report Engine

Synthesizes all Phase 1-4 modules into a concise, actionable market intelligence report.
Designed for automated Discord posting and future premium signal subscription.

Output formats:
  - markdown (Discord-ready)
  - json (programmatic)
  - html (email/web)

Revenue model: Free tier (Discord daily) → Premium tier (real-time signals, custom coins, deeper analysis)
"""

import importlib.util as _spec
import json
import os
import sys
from datetime import datetime, timezone, timedelta

# Ensure project root is in Python path for module imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ─── Module Loader ─────────────────────────────────────────────────────────────

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


# ─── Core Coins ────────────────────────────────────────────────────────────────

MAJOR_COINS = ["bitcoin", "ethereum", "solana", "binancecoin", "avalanche-2"]
MAJOR_SYMBOLS = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", 
                  "binancecoin": "BNB", "avalanche-2": "AVAX"}


# ─── Data Collection ───────────────────────────────────────────────────────────

def collect_market_data(coins=None):
    """Collect current market data for major coins."""
    coins = coins or MAJOR_COINS
    price_mod = get_price_engine()
    if not price_mod:
        return {"error": "Price engine unavailable", "prices": {}}
    
    try:
        prices = price_mod.get_simple_price(coins, ["usd"])
        return {"prices": prices, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"error": f"Price fetch failed: {e}", "prices": {}}


def collect_ta_signals(coins=None):
    """Collect technical analysis signals."""
    coins = coins or MAJOR_COINS
    ta_mod = get_ta_engine()
    if not ta_mod:
        return {"error": "TA engine unavailable"}
    
    results = {}
    for coin_id in coins:
        symbol = MAJOR_SYMBOLS.get(coin_id, coin_id.upper())
        try:
            analysis = ta_mod.analyze_coin(coin_id)
            if analysis and not isinstance(analysis, dict) or (isinstance(analysis, dict) and "error" not in analysis):
                results[symbol] = analysis
            else:
                results[symbol] = {"error": "No data"}
        except Exception as e:
            results[symbol] = {"error": str(e)}
    
    return results


def collect_onchain_data():
    """Collect on-chain health and DeFi data."""
    results = {}
    
    # Health scorer
    health_mod = get_health_scorer()
    if health_mod:
        try:
            health = health_mod.score_all_chains()
            results["health"] = health
        except Exception as e:
            results["health"] = {"error": str(e)}
    
    # DeFi scanner
    defi_mod = get_defi_scanner()
    if defi_mod:
        try:
            defi = defi_mod.scan_opportunities()
            results["defi"] = defi
        except Exception as e:
            results["defi"] = {"error": str(e)}
    
    return results


def collect_sentiment():
    """Collect social and derivatives sentiment."""
    results = {}

    # Social alpha — use get_global_sentiment() which is the actual function name
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

    # Derivatives
    derivs_mod = get_derivatives()
    if derivs_mod:
        try:
            derivs = derivs_mod.analyze_derivatives_sentiment()
            results["derivatives"] = derivs
        except Exception as e:
            results["derivatives"] = {"error": str(e)}

    return results


def collect_smart_money():
    """Collect whale/smart money data."""
    mod = get_smart_money()
    if not mod:
        return {"error": "Smart money module unavailable"}
    try:
        # Use get_smart_money_signal() — the actual function name
        result = mod.get_smart_money_signal()
        if result and isinstance(result, dict):
            return result
        # Fallback to analyze_whale_flows if it exists
        if hasattr(mod, 'analyze_whale_flows'):
            return mod.analyze_whale_flows()
        return result
    except Exception as e:
        return {"error": str(e)}


def collect_trade_signals(coins=None):
    """Generate trade signals for major coins."""
    coins = coins or MAJOR_COINS
    sig_mod = get_trade_signals()
    if not sig_mod:
        return {"error": "Signal engine unavailable"}
    
    results = {}
    for coin_id in coins:
        symbol = MAJOR_SYMBOLS.get(coin_id, coin_id.upper())
        try:
            signal = sig_mod.generate_signal(coin_id)
            results[symbol] = signal
        except Exception as e:
            results[symbol] = {"error": str(e)}
    
    return results


# ─── Report Generation ──────────────────────────────────────────────────────────

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
    """Format price data for display."""
    if not price_data or coin_id not in price_data:
        return "N/A"
    data = price_data[coin_id]
    price = data.get("usd", 0)
    change_24h = data.get("usd_24h_change", 0)
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


def generate_brief(format="markdown", coins=None):
    """
    Generate a complete daily market intelligence brief.
    
    Args:
        format: "markdown", "json", or "html"
        coins: list of coin IDs to analyze (default: major coins)
    
    Returns:
        Formatted brief string
    """
    coins = coins or MAJOR_COINS
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M UTC")
    date_str = now.strftime("%A, %B %d, %Y")
    
    # ─── Collect all data ──────────────────────────────────────────────────────
    print("📊 Collecting market data...")
    market = collect_market_data(coins)
    
    print("📈 Running technical analysis...")
    ta_signals = collect_ta_signals(coins)
    
    print("⛓️  Analyzing on-chain data...")
    onchain = collect_onchain_data()
    
    print("💬 Gathering sentiment...")
    sentiment = collect_sentiment()
    
    print("🐋 Tracking smart money...")
    smart_money = collect_smart_money()
    
    print("🎯 Generating trade signals...")
    trade_sigs = collect_trade_signals(coins)
    
    # ─── Correlation engine (composite scores) ─────────────────────────────────
    print("🔗 Loading composite scores...")
    composite_scores = {}

    # Priority 1: Use cached quant-scores.json (fast, no API calls)
    try:
        with open("/tmp/quant-scores.json") as f:
            cached = json.load(f)
        for sym, data in cached.items():
            composite_scores[sym] = data
    except Exception:
        pass

    # Priority 2: Run correlation engine only for coins not in cache (slow)
    if composite_scores:
        print(f"   Loaded {len(composite_scores)} cached scores")
    else:
        corr_mod = get_correlation()
        if corr_mod:
            for coin_id in coins:
                symbol = MAJOR_SYMBOLS.get(coin_id, coin_id.upper())
                try:
                    result = corr_mod.score_composite(symbol, coin_id=coin_id)
                    if result and isinstance(result, dict):
                        composite_scores[symbol] = result
                except Exception:
                    pass
    
    # ─── Scanner (hot coins) ───────────────────────────────────────────────────
    print("🔍 Scanning for hot coins...")
    scan_mod = get_scanner()
    hot_coins = []
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
        "market": market,
        "ta_signals": ta_signals,
        "onchain": onchain,
        "sentiment": sentiment,
        "smart_money": smart_money,
        "trade_signals": trade_sigs,
        "composite_scores": composite_scores,
        "hot_coins": hot_coins,
    }
    
    if format == "json":
        return json.dumps(report_data, indent=2, default=str)
    elif format == "html":
        return _generate_html_brief(report_data)
    else:
        return _generate_markdown_brief(report_data)


def _generate_markdown_brief(data):
    """Generate Discord-ready markdown brief."""
    lines = []
    now = data["timestamp"]
    date_str = data["date"]
    
    lines.append(f"# 📊 Crypto Quant Daily Brief")
    lines.append(f"**{date_str}** — {now}")
    lines.append(f"*Powered by Particulate LLC Crypto Quant AI*")
    lines.append("")
    
    # ─── Executive Summary ─────────────────────────────────────────────────────
    lines.append("## 🎯 Executive Summary")
    
    # Get composite scores for summary
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
    if prices:
        for coin_id in MAJOR_COINS:
            symbol = MAJOR_SYMBOLS.get(coin_id, coin_id)
            price_str = _format_price(prices, coin_id)
            lines.append(f"- **{symbol}**: {price_str}")
    else:
        lines.append("- Price data unavailable")
    
    lines.append("")
    
    # ─── Trade Signals ──────────────────────────────────────────────────────────
    lines.append("## 🎯 Trade Signals")
    trade_sigs = data.get("trade_signals", {})
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
    
    lines.append("")
    
    # ─── On-Chain Intelligence ──────────────────────────────────────────────────
    lines.append("## ⛓️ On-Chain Intelligence")
    onchain = data.get("onchain", {})
    
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
    
    lines.append("")
    
    # ─── Sentiment ─────────────────────────────────────────────────────────────
    lines.append("## 💬 Sentiment Overview")
    sentiment = data.get("sentiment", {})
    
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
    
    lines.append("")
    
    # ─── Smart Money ────────────────────────────────────────────────────────────
    lines.append("## 🐋 Smart Money")
    sm = data.get("smart_money", {})
    if sm and isinstance(sm, dict) and "error" not in sm:
        flows = sm.get("flows", sm.get("whale_flows", []))
        if isinstance(flows, list) and flows:
            lines.append("**Whale Activity:**")
            for flow in flows[:3]:
                if isinstance(flow, dict):
                    wallet = flow.get("wallet", flow.get("label", "?"))
                    direction = flow.get("direction", flow.get("action", "?"))
                    amount = flow.get("amount_usd", flow.get("value", 0))
                    coin = flow.get("coin", flow.get("token", "?"))
                    emoji = "🟢" if "buy" in str(direction).lower() else "🔴"
                    lines.append(f"  - {emoji} {wallet[:16]}... {direction} ${amount:,.0f} {coin}")
        elif "signal" in sm:
            lines.append(f"- Signal: {sm['signal']}")
        else:
            lines.append("- No significant whale activity detected")
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
    
    # ─── Risk Disclaimer ────────────────────────────────────────────────────────
    lines.append("---")
    lines.append("⚠️ *Not financial advice. Signals are for educational purposes. Always DYOR.*")
    lines.append("*Generated by Particulate LLC Crypto Quant AI v6.0*")
    
    return "\n".join(lines)


def _generate_html_brief(data):
    """Generate HTML brief for email/web."""
    # Simplified HTML version
    md = _generate_markdown_brief(data)
    # Convert markdown to basic HTML
    html = md.replace("\n", "<br>\n")
    html = html.replace("## ", "<h2>")
    html = html.replace("---", "<hr>")
    html = html.replace("**", "<strong>", 1)  # This is simplistic — use proper MD parser in production
    
    return f"""<!DOCTYPE html>
<html>
<head><title>Crypto Quant Daily Brief</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 700px; margin: 0 auto; padding: 20px; }}
h1 {{ color: #1a1a2e; }}
h2 {{ color: #16213e; border-bottom: 2px solid #0f3460; }}
</style>
</head>
<body>
{_generate_markdown_brief(data).replace('<br>', '\n')}
</body>
</html>"""


# ─── CLI Entry Point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate Crypto Quant Daily Brief")
    parser.add_argument("--format", choices=["markdown", "json", "html"], default="markdown")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument("--coins", nargs="+", default=MAJOR_COINS, help="Coin IDs to analyze")
    args = parser.parse_args()
    
    print(f"🚀 Generating Daily Brief ({args.format})...")
    brief = generate_brief(format=args.format, coins=args.coins)
    
    if args.output:
        with open(args.output, "w") as f:
            f.write(brief)
        print(f"✅ Brief saved to {args.output}")
    else:
        print(brief)
    
    print(f"\n✅ Brief generated at {datetime.now(timezone.utc).isoformat()}")