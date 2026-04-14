"""
On-Chain Health Scorer
Phase 3, Task 3.1 — Scoring model 0-100
Uses DeFiLlama data: TVL trends, chain health, protocol flows
"""

import importlib.util as _il
_spec = _il.spec_from_file_location("dl_mod", "skills/onchain_engine/defillama.py")
_dl = _il.module_from_spec(_spec)
_spec.loader.exec_module(_dl)
get_chains    = _dl.get_chains
get_protocols = _dl.get_protocols

from datetime import datetime, timezone


# ─── Scoring Helpers ────────────────────────────────────────────────────────────

def _tvl_change_score(change_pct):
    if change_pct is None:
        return 12.5
    if change_pct >= 10:   return 25.0
    elif change_pct >= 5:  return 20.0
    elif change_pct >= 2:  return 16.0
    elif change_pct >= 0:  return 13.0
    elif change_pct >= -2: return 10.0
    elif change_pct >= -5: return 6.0
    elif change_pct >= -10: return 3.0
    else:                   return 0.0


def _vol_score(change_1d, change_7d):
    if change_1d is None and change_7d is None:
        return 7.5
    d1 = change_1d or 0
    d7 = change_7d or 0
    if abs(d1) > 20:
        return max(0.0, 7.0 - (abs(d1) - 20) * 0.3)
    if -5 <= d7 <= 15:
        return 15.0
    elif -10 <= d7 < -5:
        return 10.0
    elif 15 < d7 <= 25:
        return 11.0
    elif d7 > 25:
        return 6.0
    else:
        return 4.0


def _tvl_score(tvl):
    if not tvl: return 0.0
    if tvl >= 10_000_000_000: return 20.0
    elif tvl >= 1_000_000_000: return 17.0
    elif tvl >= 500_000_000:   return 14.0
    elif tvl >= 100_000_000:   return 11.0
    elif tvl >= 10_000_000:    return 7.0
    elif tvl >= 1_000_000:     return 4.0
    else:                       return 1.0


def _cat_score(category):
    if not category: return 7.5
    c = category.lower()
    if c in ("lending", "borrow", "cdp"):          return 8.0
    elif c in ("dex", "exchange"):                  return 12.0
    elif c in ("yield", "yield aggregator"):        return 9.0
    elif c in ("pool", "staking", "staking pool"):  return 11.0
    elif c in ("bridge", "cross-chain"):             return 7.0
    elif c in ("insurance",):                       return 10.0
    elif c in ("derivatives", "derivative"):         return 8.0
    elif c in ("cex",):                             return 13.0
    elif c in ("yield farm", "degens"):              return 4.0
    else:                                           return 10.0


def _flow(change_1d, change_7d):
    d1 = change_1d or 0
    d7 = change_7d or 0
    if d1 > 5 and d7 > 10:  return "strong_inflow"
    elif d1 > 2 or d7 > 5:  return "inflow"
    elif d1 < -5 and d7 < -10: return "strong_outflow"
    elif d1 < -2 or d7 < -5: return "outflow"
    elif -2 <= d1 <= 2 and -5 <= d7 <= 5: return "stable"
    return "mixed"


def _fmt(val):
    """Safe string formatter for None values."""
    if val is None:
        return "N/A"
    return f"{val:+.1f}%"


# ─── Protocol Scoring ─────────────────────────────────────────────────────────

def score_protocol(protocol_data):
    tvl      = protocol_data.get("tvl") or 0
    change_1d = protocol_data.get("change_1d")
    change_7d = protocol_data.get("change_7d")
    category  = protocol_data.get("category", "")

    ts = _tvl_score(tvl)
    cs = _tvl_change_score(change_7d)
    vs = _vol_score(change_1d, change_7d)
    cats = _cat_score(category)

    total = ts + cs + vs + cats
    return {
        "protocol":     protocol_data.get("name", "Unknown"),
        "slug":         protocol_data.get("slug", ""),
        "chain":        protocol_data.get("chain", "Unknown"),
        "category":     category,
        "tvl_usd":      round(tvl, 2),
        "health_100":   round(min(total / 75 * 100, 100), 1),
        "tvl_score":    round(ts, 1),
        "change_score": round(cs, 1),
        "vol_score":    round(vs, 1),
        "cat_score":   round(cats, 1),
        "tvl_trend_7d": change_7d,
        "tvl_trend_1d": change_1d,
        "flow_signal":  _flow(change_1d, change_7d),
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    }


def score_all_protocols(min_tvl=1_000_000):
    protos = get_protocols()
    scored = []
    for p in protos:
        if (p.get("tvl") or 0) < min_tvl:
            continue
        try:
            scored.append(score_protocol(p))
        except Exception:
            pass
    scored.sort(key=lambda x: x["health_100"], reverse=True)
    return scored


# ─── Chain Scoring ─────────────────────────────────────────────────────────────

def score_all_chains():
    chains = get_chains()
    scored = []
    for c in chains:
        tvl = c.get("tvl") or 0
        # /chains endpoint has no change_1d/change_7d — use TVL only
        ts = _tvl_score(tvl)
        total = ts + 20.0  # 20 pts TVL + neutral defaults
        scored.append({
            "chain":        c.get("name", "Unknown"),
            "gecko_id":     c.get("gecko_id"),
            "tvl_usd":      round(tvl, 2),
            "health_score": round(min(total / 40 * 100, 100), 1),
            "tvl_score":    round(ts, 1),
            "tvl_trend_7d": None,
            "tvl_trend_1d": None,
            "flow_signal":  "unknown",
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        })
    scored.sort(key=lambda x: x["health_score"], reverse=True)
    return scored


# ─── Convenience Functions ─────────────────────────────────────────────────────

def top_protocols(n=20, min_tvl=10_000_000):
    return score_all_protocols(min_tvl=min_tvl)[:n]


def top_chains(n=10):
    return score_all_chains()[:n]


def top_inflows(n=20):
    all_p = score_all_protocols(min_tvl=5_000_000)
    return [p for p in all_p if p["flow_signal"] in ("inflow", "strong_inflow")][:n]


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== On-Chain Health Scorer ===")

    chains = score_all_chains()
    print(f"\nTop 10 Chains by Health Score:")
    for c in chains[:10]:
        print(f"  {c['chain']:20s} {c['health_score']:5.1f}/100  "
              f"TVL ${c['tvl_usd']/1e9:.2f}B")

    protos = top_protocols(n=10)
    print(f"\nTop 10 Protocols:")
    for p in protos:
        print(f"  {p['protocol'][:30]:30s} {p['health_100']:5.1f}/100  "
              f"TVL ${p['tvl_usd']/1e9:.2f}B  7d {_fmt(p['tvl_trend_7d'])}  {p['flow_signal']}")

    inflows = top_inflows(n=10)
    print(f"\nTop Inflow Signals:")
    for p in inflows:
        print(f"  {p['protocol'][:30]:30s} {p['flow_signal']:20s}  "
              f"7d {_fmt(p['tvl_trend_7d'])}")

    print("\n✅ Health Scorer working")
