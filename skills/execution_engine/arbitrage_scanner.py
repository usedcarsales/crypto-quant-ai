"""
Arbitrage Scanner — Phase 5, Task 5.3
Cross-exchange price spread detection.
Alert-only mode — does NOT auto-execute (latency makes real arb impractical).

Scans: Kraken, OKX, Bybit for top 20 pairs by volume.
Flags spreads ≥ 0.5% after estimated fees.
"""

import time
import ccxt
from datetime import datetime, timezone
from typing import Optional


# ─── Exchanges ────────────────────────────────────────────────────────────────

EXCHANGES = {
    "kraken": {"class": ccxt.kraken,  "enabled": True},
    "okx":    {"class": ccxt.okx,     "enabled": True},
    # "bybit" removed — 403 Forbidden
}

FEE_TIERS = {
    "kraken":  {"maker": 0.0016, "taker": 0.0026},
    "okx":     {"maker": 0.0008, "taker": 0.0010},
    "bybit":   {"maker": 0.0010, "taker": 0.0010},
}

MIN_SPREAD_PCT = 0.5  # minimum spread to flag (%)
MIN_NOTIONAL   = 100  # minimum trade size in USD


# ─── Exchange Loader ─────────────────────────────────────────────────────────

def _create_exchange(exchange_id: str, sandbox: bool = False) -> ccxt.Exchange:
    cfg = EXCHANGES.get(exchange_id)
    if not cfg or not cfg["enabled"]:
        raise ValueError(f"Exchange {exchange_id} not available")

    params = {"enableRateLimit": True}
    if sandbox and exchange_id == "okx":
        params["testnet"] = True

    ex_class = cfg["class"]
    exchange = ex_class(params)

    if sandbox and exchange_id == "kraken":
        exchange.set_sandbox_mode(True)

    return exchange


def _get_markets(exchange_id: str, sandbox: bool = False) -> dict:
    """Load and return markets dict for an exchange."""
    exchange = _create_exchange(exchange_id, sandbox)
    exchange.load_markets()
    return exchange.markets


# ─── Core Scanner ─────────────────────────────────────────────────────────────

def get_top_pairs(n: int = 20) -> list:
    """
    Get top N pairs by 24h volume across exchanges.
    Returns list of (symbol, total_24h_volume_usd).
    """
    # Use Kraken as reference (works without auth)
    kraken = _create_exchange("kraken")
    kraken.load_markets()

    pairs = []
    for symbol, m in kraken.markets.items():
        if not m.get("active") or m.get("type") != "spot":
            continue
        vol = m.get("quoteVolume", 0) or 0
        if vol > 0:
            pairs.append((symbol, vol))

    pairs.sort(key=lambda x: x[1], reverse=True)
    return pairs[:n]


def scan_pair_cross_exchange(pair: str, exchanges: list = None) -> list:
    """
    Scan a single pair across all available exchanges.
    Returns list of {exchange, bid, ask, spread_pct, last} for each exchange.
    """
    if exchanges is None:
        exchanges = ["kraken", "okx", "bybit"]

    results = []

    for ex_id in exchanges:
        try:
            ex = _create_exchange(ex_id)
            ticker = ex.fetch_ticker(pair)
            bid  = ticker.get("bid") or 0
            ask  = ticker.get("ask") or 0
            last = ticker.get("last") or 0
            base_vol = ticker.get("baseVolume") or 0
            quote_vol = ticker.get("quoteVolume") or 0

            if bid > 0 and ask > 0:
                spread_pct = (ask - bid) / ask * 100
                results.append({
                    "exchange":   ex_id,
                    "pair":       pair,
                    "bid":        bid,
                    "ask":        ask,
                    "last":       last,
                    "spread_pct": round(spread_pct, 4),
                    "base_volume": round(base_vol, 4),
                    "quote_volume": round(quote_vol, 2),
                    "timestamp":  datetime.now(timezone.utc).isoformat(),
                })
        except Exception:
            continue

    return results


def find_arbitrage_opportunities(pairs: list = None, exchanges: list = None) -> list:
    """
    Main scan — find cross-exchange arbitrage opportunities.
    An opportunity = buy on one exchange, sell on another with spread ≥ MIN_SPREAD_PCT.

    Returns list of:
      {pair, buy_exchange, sell_exchange, spread_pct,
       estimated_profit_usd, fees_estimated, buy_price, sell_price}
    """
    if pairs is None:
        pairs = [p[0] for p in get_top_pairs(20)]
    if exchanges is None:
        exchanges = ["kraken", "okx", "bybit"]

    opportunities = []

    for pair in pairs:
        # Fetch all exchange prices for this pair simultaneously
        tickers = scan_pair_cross_exchange(pair, exchanges)
        if len(tickers) < 2:
            continue

        # For each pair of exchanges, check if arb exists
        for i, t1 in enumerate(tickers):
            for t2 in tickers[i+1:]:
                # t1: buy at ask, sell at bid
                # t2: buy at ask, sell at bid
                buy_on   = t1["ask"] < t2["bid"]  # buy on ex1, sell on ex2
                sell_on  = t2["ask"] < t1["bid"]  # buy on ex2, sell on ex1

                if buy_on:
                    spread_pct = (t2["bid"] - t1["ask"]) / t1["ask"] * 100
                    opp = _calc_arb(
                        pair=pair,
                        buy_exchange=t1["exchange"],
                        sell_exchange=t2["exchange"],
                        buy_price=t1["ask"],
                        sell_price=t2["bid"],
                        spread_pct=spread_pct,
                    )
                    if opp:
                        opportunities.append(opp)

                if sell_on:
                    spread_pct = (t1["bid"] - t2["ask"]) / t2["ask"] * 100
                    opp = _calc_arb(
                        pair=pair,
                        buy_exchange=t2["exchange"],
                        sell_exchange=t1["exchange"],
                        buy_price=t2["ask"],
                        sell_price=t1["bid"],
                        spread_pct=spread_pct,
                    )
                    if opp:
                        opportunities.append(opp)

        time.sleep(0.3)  # be respectful of rate limits

    # Deduplicate and sort by profit
    seen = set()
    unique = []
    for o in opportunities:
        key = (o["pair"], o["buy_exchange"], o["sell_exchange"])
        if key not in seen:
            seen.add(key)
            unique.append(o)

    unique.sort(key=lambda x: x["estimated_profit_usd"], reverse=True)
    return unique


def _calc_arb(pair: str, buy_exchange: str, sell_exchange: str,
              buy_price: float, sell_price: float, spread_pct: float) -> Optional[dict]:
    """
    Calculate arbitrage economics after fees.
    Returns dict if profitable after fees, else None.
    """
    buy_fee  = FEE_TIERS.get(buy_exchange,  {}).get("taker", 0.001)
    sell_fee = FEE_TIERS.get(sell_exchange, {}).get("taker", 0.001)

    # Gross spread
    gross_profit_pct = spread_pct

    # Fees: buy fee + sell fee
    total_fee_pct = (buy_fee + sell_fee) * 100  # in percent

    # Net profit after fees
    net_profit_pct = gross_profit_pct - total_fee_pct

    if net_profit_pct < MIN_SPREAD_PCT:
        return None

    # Estimate profit for $1000 trade
    notional    = max(MIN_NOTIONAL, 1000)
    gross_profit_usd = notional * gross_profit_pct / 100
    fees_usd        = notional * total_fee_pct / 100
    net_profit_usd  = gross_profit_usd - fees_usd

    return {
        "pair":                  pair,
        "buy_exchange":          buy_exchange,
        "sell_exchange":         sell_exchange,
        "buy_price":             round(buy_price, 6),
        "sell_price":            round(sell_price, 6),
        "spread_pct":            round(spread_pct, 4),
        "gross_profit_pct":      round(gross_profit_pct, 4),
        "fees_pct":              round(total_fee_pct, 4),
        "net_profit_pct":        round(net_profit_pct, 4),
        "estimated_profit_usd":  round(net_profit_usd, 2),
        "notional_used_usd":     notional,
        "gross_profit_usd":      round(gross_profit_usd, 2),
        "fees_estimated_usd":    round(fees_usd, 2),
        "alert":                "BUY" if net_profit_pct >= MIN_SPREAD_PCT else "SKIP",
        "timestamp":            datetime.now(timezone.utc).isoformat(),
    }


# ─── Scan Runner ─────────────────────────────────────────────────────────────

def run_scan(pairs: list = None, exchanges: list = None) -> dict:
    """
    Run a full arbitrage scan.
    Returns summary dict with all opportunities found.
    """
    if pairs is None:
        pairs = [p[0] for p in get_top_pairs(20)]

    print(f"Scanning {len(pairs)} pairs across {exchanges or ['kraken','okx','bybit']}...")

    t0 = time.time()
    opps = find_arbitrage_opportunities(pairs, exchanges)
    elapsed = time.time() - t0

    # Summary
    alert_opps = [o for o in opps if o.get("alert") == "BUY"]

    return {
        "scanned_pairs":   len(pairs),
        "opportunities":   opps,
        "alert_opportunities": alert_opps,
        "scan_time_sec":  round(elapsed, 1),
        "exchanges_used": exchanges or ["kraken", "okx", "bybit"],
        "timestamp":       datetime.now(timezone.utc).isoformat(),
    }


# ─── Formatting ──────────────────────────────────────────────────────────────

def format_opportunity(o: dict) -> str:
    """Human-readable arbitrage opportunity."""
    pct = o["net_profit_pct"]
    emoji = "🟢" if pct >= 1.0 else "🟡" if pct >= 0.5 else "⚪"
    lines = [
        f"{emoji} **{o['pair']}** — ARB ALERT",
        f"   Buy  on {o['buy_exchange']:8s} @ ${o['buy_price']:,.6f}",
        f"   Sell on {o['sell_exchange']:8s} @ ${o['sell_price']:,.6f}",
        f"   Gross spread: {o['spread_pct']:.3f}% | Fees: {o['fees_pct']:.3f}%",
        f"   **Net profit: {o['net_profit_pct']:.3f}% = ~${o['estimated_profit_usd']:.2f}/1k**",
    ]
    return "\n".join(lines)


def format_scan_report(report: dict) -> str:
    """Format full scan report."""
    opps  = report.get("alert_opportunities", [])
    lines = [
        f"**🔍 Arbitrage Scan Report**\n",
        f"  Scanned: {report['scanned_pairs']} pairs | "
        f"Exchanges: {', '.join(report['exchanges_used'])} | "
        f"Time: {report['scan_time_sec']}s\n",
    ]

    if not opps:
        lines.append("  No arbitrage opportunities found (all spreads < 0.5% after fees).\n")
    else:
        lines.append(f"  **{len(opps)} opportunity(s) found:**\n\n")
        for o in opps[:10]:
            lines.append(format_opportunity(o))
            lines.append("\n")

    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("=== Arbitrage Scanner ===\n")

    exchanges = ["kraken", "okx", "bybit"]
    pairs     = None

    if "--pairs" in sys.argv:
        idx = sys.argv.index("--pairs")
        pairs = sys.argv[idx+1].split(",")

    report = run_scan(pairs=pairs, exchanges=exchanges)
    print(format_scan_report(report))
    print("✅ Arbitrage scan complete")