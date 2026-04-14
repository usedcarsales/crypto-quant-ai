"""
DeFi Opportunity Scanner
Phase 3, Task 3.3 — Yield opportunity detection + emerging protocol flags
Uses DeFiLlama protocol data + TVL change signals
"""

import importlib.util as _il
_spec = _il.spec_from_file_location("dl_mod", "skills/onchain_engine/defillama.py")
_dl = _il.module_from_spec(_spec)
_spec.loader.exec_module(_dl)
get_protocols = _dl.get_protocols
get_chains    = _dl.get_chains

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional


# ─── Opportunity Scoring ────────────────────────────────────────────────────────

def score_opportunity(protocol: dict) -> dict:
    """
    Score a protocol for DeFi yield/investment opportunity.
    Returns: {
        protocol, chain, tvl, tvl_change_24h, tvl_change_7d,
        opportunity_score (0-100), signal: BUY|SELL|NEUTRAL
    }
    """
    tvl         = protocol.get("tvl") or 0
    change_1d   = protocol.get("change_1d")
    change_7d   = protocol.get("change_7d")
    category    = protocol.get("category", "")
    name        = protocol.get("name", "Unknown")
    slug        = protocol.get("slug", "")
    chain       = protocol.get("chain", "Unknown")

    # ── Component 1: TVL Health (0-30 pts)
    if tvl >= 1_000_000_000:
        tvl_pts = 30
    elif tvl >= 500_000_000:
        tvl_pts = 26
    elif tvl >= 100_000_000:
        tvl_pts = 22
    elif tvl >= 10_000_000:
        tvl_pts = 16
    elif tvl >= 1_000_000:
        tvl_pts = 10
    else:
        tvl_pts = 4

    # ── Component 2: TVL Trend Direction (0-25 pts)
    # High APY + growing TVL = quality opportunity
    # High APY + shrinking TVL = possible rug/harvest exploit
    trend_pts = 12.5  # neutral baseline
    if change_7d is not None and change_1d is not None:
        combined = change_7d + change_1d  # directional bias
        if combined >= 30:    trend_pts = 25.0
        elif combined >= 15:  trend_pts = 21.0
        elif combined >= 5:   trend_pts = 17.0
        elif combined >= 0:    trend_pts = 14.0
        elif combined >= -5:  trend_pts = 11.0
        elif combined >= -15: trend_pts = 6.0
        else:                 trend_pts = 0.0

    # ── Component 3: Category Risk Adjustment (0-20 pts)
    cat_pts = 10.0  # baseline
    cat_lower = category.lower()
    if cat_lower in ("lending", "cdp", "borrow"):
        cat_pts = 8.0   # higher risk — dependency on collateral health
    elif cat_lower in ("yield", "yield aggregator", "yield farm"):
        cat_pts = 5.0   # high risk of impermanent loss / rug
    elif cat_lower in ("liquid staking", "liquid restaking", "restaking"):
        cat_pts = 13.0  # strong TVL retention, popular category
    elif cat_lower in ("dex", "exchange"):
        cat_pts = 15.0  # volume-driven, stable if TVL growing
    elif cat_lower in ("bridge", "cross-chain"):
        cat_pts = 7.0   # hack history, bridge risk
    elif cat_lower in ("cex"):
        cat_pts = 18.0  # high trust, institutional-grade

    # ── Component 4: Momentum (surge detection) (0-25 pts)
    momentum_pts = 12.5
    if change_1d is not None:
        if change_1d >= 20:   momentum_pts = 25.0  # explosive, may be unsustainable
        elif change_1d >= 10: momentum_pts = 20.0  # strong momentum
        elif change_1d >= 5:  momentum_pts = 17.0
        elif change_1d >= 0: momentum_pts = 14.0
        elif change_1d >= -5: momentum_pts = 9.0
        elif change_1d >= -10: momentum_pts = 5.0
        else:                 momentum_pts = 1.0

    total = tvl_pts + trend_pts + cat_pts + momentum_pts
    raw_score = min(total / 100 * 100, 100)  # normalize to 0-100

    # ── Signal Derivation
    if raw_score >= 70 and trend_pts >= 15:
        signal = "BUY"
    elif raw_score <= 35 or trend_pts <= 5:
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    # Surge flag — TVL > 20% in 24h
    surge_flag = change_1d is not None and change_1d >= 20

    # New entry flag — listedAt within last 7 days (approx based on 7d change)
    is_new = change_7d is not None and change_7d >= 50 and tvl >= 10_000_000

    return {
        "protocol":          name,
        "slug":              slug,
        "chain":             chain,
        "category":          category,
        "tvl":               round(tvl, 2),
        "tvl_change_24h":    change_1d,
        "tvl_change_7d":     change_7d,
        "opportunity_score": round(raw_score, 1),
        "signal":            signal,
        "surge_flag":        surge_flag,
        "new_entry_flag":    is_new,
        # sub-scores for transparency
        "tvl_pts":           round(tvl_pts, 1),
        "trend_pts":         round(trend_pts, 1),
        "cat_pts":           round(cat_pts, 1),
        "momentum_pts":      round(momentum_pts, 1),
        "timestamp":         datetime.now(timezone.utc).isoformat(),
    }


def scan_opportunities(min_tvl: float = 5_000_000) -> list:
    """
    Scan all protocols for opportunities.
    Returns sorted list (highest opportunity first).
    """
    protos = get_protocols()
    results = []
    for p in protos:
        if (p.get("tvl") or 0) < min_tvl:
            continue
        try:
            scored = score_opportunity(p)
            results.append(scored)
        except Exception:
            pass

    results.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return results


def top_buys(n: int = 20, min_tvl: float = 10_000_000) -> list:
    """Top BUY signals by opportunity score."""
    return [
        p for p in scan_opportunities(min_tvl=min_tvl)
        if p["signal"] == "BUY"
    ][:n]


def top_surges(n: int = 10, min_tvl: float = 5_000_000) -> list:
    """Protocols with biggest 24h TVL surges."""
    all_p = scan_opportunities(min_tvl=min_tvl)
    return sorted(all_p, key=lambda x: x["tvl_change_24h"] or 0, reverse=True)[:n]


def new_entries(n: int = 10) -> list:
    """Protocols that look like recent entries (high 7d growth + mid TVL)."""
    all_p = scan_opportunities(min_tvl=1_000_000)
    return [p for p in all_p if p["new_entry_flag"]][:n]


# ─── Formatters ──────────────────────────────────────────────────────────────

def format_opportunity_report(n: int = 15) -> str:
    """Human-readable DeFi opportunity report."""
    buys   = top_buys(n=n)
    surges = top_surges(n=5)

    lines = [f"**DeFi Opportunity Report — {n} Top BUY Signals**\n"]

    for p in buys[:10]:
        flag = " 🚨 SURGE" if p["surge_flag"] else ""
        flag2 = " 🆕 NEW" if p["new_entry_flag"] else ""
        lines.append(
            f"  [{p['opportunity_score']:.0f}/100] **{p['protocol']}** ({p['chain']})\n"
            f"    TVL ${p['tvl']/1e6:.1f}M | 7d {p['tvl_change_7d']:+.1f}% | "
            f"24h {p['tvl_change_24h']:+.1f}%{flag}{flag2}"
        )

    if surges:
        lines.append(f"\n**🔥 24h TVL Surges — Risk On**")
        for p in surges[:5]:
            lines.append(
                f"  {p['protocol']} ({p['chain']}): "
                f"24h {p['tvl_change_24h']:+.1f}% → TVL ${p['tvl']/1e6:.1f}M"
            )

    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== DeFi Opportunity Scanner ===")

    buys = top_buys(n=20)
    print(f"\nTop BUY Signals ({len(buys)} found):")
    for p in buys[:10]:
        print(
            f"  [{p['opportunity_score']:.0f}/100] {p['protocol'][:35]:35s} "
            f"TVL ${p['tvl']/1e6:6.1f}M  "
            f"7d {p['tvl_change_7d']:+.1f}%  "
            f"24h {p['tvl_change_24h']:+.1f}%"
        )

    surges = top_surges(n=10)
    print(f"\n24h TVL Surges:")
    for p in surges:
        print(
            f"  {p['protocol'][:35]:35s} "
            f"24h {p['tvl_change_24h']:+.1f}%  "
            f"TVL ${p['tvl']/1e6:.1f}M"
        )

    print("\n✅ DeFi Scanner working")