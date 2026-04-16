"""
Smart Money Engine — Whale & Copy Trading
Phase 3, Task 3.2 — Wallet clustering, behavior labeling, copy-trade signals
Uses: Arkham API (when available), block explorer APIs (free), on-chain heuristics
"""

import importlib.util as _il
_spec = _il.spec_from_file_location("wl_mod", "skills/wallet_engine/explorer.py")
_wl = _il.module_from_spec(_spec)
_spec.loader.exec_module(_wl)
get_eth_wallet = _wl.get_eth_wallet
get_btc_wallet = _wl.get_btc_wallet
get_sol_wallet = _wl.get_sol_wallet

import os
import requests
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional


# ─── Arkham API (Real Client) ────────────────────────────────────────────────
from skills.wallet_engine.arkham_client import (
    identify_wallet         as arkham_identify,
    search_entities         as arkham_search,
    track_entity_flows      as arkham_flows,
    get_address_intelligence as arkham_labels,   # renamed for clarity
    get_entity_intelligence as arkham_entity,
)
ARKHAM_KEY = os.environ.get("ARKHAM_API_KEY", "")

# Known institutional wallets — address: label
ARKHAM_WALLETS = {
    "binance_hot":   "0x28C6c06298d514Db089934071355E5743bf21d60",
    "binance_cold":  "0x21a31Ee1afC51d94C2efFcAAf2D3D3F7D2aBcDF1",
    "coinbase_hot":  "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    "kraken_btc":    "0x2675FC3169D2B7094528A2A63F27C7E9E0FbB1Ea",
    "ftx_alameda":   "0xc5edA3f7b47b46B8AdCeB6F0bC8dC5B84BbC6F4a",
    "japan_mtgox":   "1JapanMtGoxQbfN9rc3NNNWFN3V9qPt9W",
}

ARKHAM_LABELS = {
    "binance_hot":  {"label": "CEX Exchange Hot Wallet",   "type": "exchange",     "risk": "low"},
    "binance_cold": {"label": "CEX Exchange Cold Wallet",   "type": "exchange",     "risk": "low"},
    "coinbase_hot": {"label": "Coinbase Hot Wallet",         "type": "exchange",     "risk": "low"},
    "kraken_btc":   {"label": "Kraken BTC Wallet",           "type": "exchange",     "risk": "low"},
    "ftx_alameda":  {"label": "Alameda/FTX Associated",      "type": "institutional","risk": "high"},
    "japan_mtgox":  {"label": "Mt.Gox Bankruptcy Trustee",   "type": "institutional","risk": "medium"},
}


# ─── Wallet Behavior Classifier ────────────────────────────────────────────────

@dataclass
class WalletProfile:
    address:      str
    label:        str
    wallet_type:  str
    risk_level:   str
    avg_tx_size:  float
    tx_frequency: str
    last_active:  str
    inflow_count: int
    outflow_count: int
    net_flow:     float
    tags:         list
    source:       str


def classify_wallet(address, label=None, metadata=None):
    tags = []
    wallet_type = "unknown"
    risk_level  = "medium"

    if label:
        for key, meta in ARKHAM_LABELS.items():
            if label.lower() in key or key in label.lower():
                wallet_type = meta["type"]
                risk_level  = meta["risk"]
                tags.append(meta["label"])
                break
        else:
            tags.append(label)

    if metadata:
        avg = metadata.get("avg_tx_size", 0)
        txs = metadata.get("total_txs", 0)
        if avg > 10_000_000:
            wallet_type = "whale"
            risk_level  = "low"
            tags.append("whale")
        elif avg > 1_000_000:
            wallet_type = "institutional"
            risk_level  = "medium"
            tags.append("institutional")
        elif "dex" in str(label).lower() or "uniswap" in str(label).lower():
            wallet_type = "dex"
            risk_level  = "medium"
            tags.append("dex")
        elif txs > 1000 and avg < 10_000:
            wallet_type = "degen"
            risk_level  = "high"
            tags.append("degen")

    return WalletProfile(
        address=address,
        label=label or "Unlabeled",
        wallet_type=wallet_type,
        risk_level=risk_level,
        avg_tx_size=metadata.get("avg_tx_size", 0) if metadata else 0,
        tx_frequency=metadata.get("frequency", "unknown"),
        last_active=metadata.get("last_active", "unknown"),
        inflow_count=metadata.get("inflow_count", 0) if metadata else 0,
        outflow_count=metadata.get("outflow_count", 0) if metadata else 0,
        net_flow=metadata.get("net_flow_usd", 0) if metadata else 0,
        tags=tags,
        source="cluster",
    )


# ─── Arkham API ───────────────────────────────────────────────────────────────

def get_arkham_labels(address):
    """Get Arkham labels for an address using the real API client."""
    if not ARKHAM_KEY:
        return {"error": "no_arkham_key"}
    try:
        result = arkham_identify(address)
        if result.get("is_labeled"):
            return {
                "entity": result.get("primary_entity", ""),
                "type": result.get("wallet_type", ""),
                "risk": result.get("risk_level", ""),
                "labels": result.get("all_labels", []),
            }
        return {"error": "unlabeled"}
    except Exception as e:
        return {"error": str(e)}


# ─── Copy Trade Watchlist ─────────────────────────────────────────────────────

SIGNIFICANT_MOVE_USD = 100_000
WATCHLIST = {}


def add_to_watchlist(address, label, chain="ETH",
                      threshold_usd=SIGNIFICANT_MOVE_USD,
                      metadata=None):
    profile = classify_wallet(address, label, metadata)
    entry = {
        "address":   address,
        "label":     label or profile.label,
        "chain":     chain,
        "threshold": threshold_usd,
        "type":      profile.wallet_type,
        "risk":      profile.risk_level,
        "added_at":  datetime.now(timezone.utc).isoformat(),
        "last_balance_usd": None,
        "last_checked": None,
        "signals":   [],
    }
    WATCHLIST[address.lower()] = entry
    return entry


def remove_from_watchlist(address):
    return bool(WATCHLIST.pop(address.lower(), None))


def check_watchlist(address=None):
    signals = []
    wallets = [address] if address else list(WATCHLIST.keys())

    for addr in wallets:
        if addr not in WATCHLIST:
            continue
        entry = WATCHLIST[addr]
        chain = entry["chain"].upper()

        if chain == "ETH":
            data = get_eth_wallet(addr)
        elif chain == "BTC":
            data = get_btc_wallet(addr)
        elif chain == "SOL":
            data = get_sol_wallet(addr)
        else:
            continue

        if "error" in data:
            continue

        entry["last_checked"] = datetime.now(timezone.utc).isoformat()

        current_usd = data.get("balance_usd_estimate", 0)
        prev_usd    = entry.get("last_balance_usd") or current_usd
        delta_usd   = current_usd - prev_usd
        pct_chg     = (delta_usd / prev_usd * 100) if prev_usd > 0 else 0

        entry["last_balance_usd"] = current_usd

        # ── Arkham Enrichment ─────────────────────────────────────────────
        # If wallet is a known exchange/institution, pull live Arkham flows
        wallet_type = entry.get("type", "unknown")
        arkham_flow = None
        if ARKHAM_KEY and wallet_type in ("exchange", "institutional"):
            try:
                arkham_flow = arkham_flows(entry["label"].lower(), time_last="7d", usd_gte=10_000_000)
                if arkham_flow and "error" not in arkham_flow:
                    entry["_arkham_flows"] = arkham_flow
                    # Boost signal confidence if Arkham confirms flow direction
                    in_flow = arkham_flow.get("inflows_usd", 0)
                    out_flow = arkham_flow.get("outflows_usd", 0)
                    net = arkham_flow.get("net_flow_usd", 0)
                    if abs(net) > 50_000_000:
                        entry["_arkham_confirmed_direction"] = "buy" if net > 0 else "sell"
            except Exception:
                pass  # Arkham enrichment is best-effort — don't block on failure

        if abs(delta_usd) >= entry["threshold"]:
            direction = "BUY" if delta_usd > 0 else "SELL"
            sig = {
                "address":      addr,
                "label":        entry["label"],
                "wallet_type":  entry["type"],
                "chain":        chain,
                "direction":    direction,
                "amount_usd":   round(delta_usd, 2),
                "pct_change":   round(pct_chg, 2),
                "new_balance":  round(current_usd, 2),
                "threshold":    entry["threshold"],
                "confidence":   _confidence(entry["type"], abs(pct_chg), entry.get("_arkham_confirmed_direction")),
                "arkham_flow":  entry.get("_arkham_flows"),
                "timestamp":    datetime.now(timezone.utc).isoformat(),
            }
            signals.append(sig)
            entry["signals"].append(sig)

        WATCHLIST[addr] = entry

    return signals


def _confidence(wallet_type, pct_change, arkham_dir=None):
    # Arkham confirmation elevates confidence
    if arkham_dir and wallet_type in ("exchange", "institutional"):
        return "high"
    if wallet_type in ("exchange", "institutional") and pct_change > 1:
        return "high"
    elif wallet_type == "whale" and pct_change > 5:
        return "high"
    elif wallet_type == "degen":
        return "low"
    return "medium"


# ─── Arkham Integration ──────────────────────────────────────────────────────

def get_entity_flows(entity_name: str, hours: int = 168, min_usd: float = 1_000_000):
    """
    Get live capital flows for a named entity via Arkham.
    entity_name: 'binance', 'coinbase', 'galaxy-digital', etc.
    hours: lookback (default 7 days)
    min_usd: minimum USD transfer threshold
    """
    if not ARKHAM_KEY:
        return {"error": "no_arkham_key"}
    try:
        time_last = f"{hours}h" if hours <= 168 else "30d"
        result = arkham_flows(entity_name, time_last=time_last, usd_gte=min_usd)
        return result
    except Exception as e:
        return {"error": str(e)}


def get_smart_money_signal() -> dict:
    """
    Top-level smart money reading for the correlation engine.
    Returns: {score: 0-100, signal, whale_signals, institutional_signals}
    """
    signals = check_watchlist()

    if not signals:
        # No balance changes — use Arkham flows as fallback signal
        try:
            bnb_flow = arkham_flows("binance", time_last="24h", usd_gte=10_000_000)
            if bnb_flow and "error" not in bnb_flow:
                net = bnb_flow.get("net_flow_usd", 0)
                score = 50 + (net / 100_000_000 * 10)  # rough mapping
                score = max(0, min(100, score))
                return {
                    "score": round(score, 1),
                    "signal": "BUY" if score > 65 else "SELL" if score < 40 else "NEUTRAL",
                    "source": "arkham_flows",
                    "net_flow_usd": net,
                    "inflows_usd": bnb_flow.get("inflows_usd", 0),
                    "outflows_usd": bnb_flow.get("outflows_usd", 0),
                    "top_counterparties": bnb_flow.get("top_counterparties", [])[:5],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
        except Exception:
            pass
        return {"score": 50.0, "signal": "NEUTRAL", "whale_signals": [], "source": "no_data"}

    buys  = [s for s in signals if s["direction"] == "BUY"]
    sells = [s for s in signals if s["direction"] == "SELL"]
    total = len(signals)
    ratio = (len(buys) - len(sells)) / total if total > 0 else 0
    score = round(min(max(50 + ratio * 30, 0), 100), 1)

    return {
        "score": score,
        "signal": "BUY" if score > 65 else "SELL" if score < 40 else "NEUTRAL",
        "whale_signals": signals,
        "buy_count": len(buys),
        "sell_count": len(sells),
        "source": "wallet_engine",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Whale Alert ───────────────────────────────────────────────────────────────

def format_whale_alert(signal):
    emoji = {"exchange": "🏛️", "institutional": "🏛️", "whale": "🐋",
             "degen": "🐷", "dex": "🔄"}.get(signal["wallet_type"], "🐋")
    return (
        f"{emoji} **WHALE ALERT — {signal['direction']}**\n"
        f"Wallet: `{signal['address'][:12]}...` ({signal['label']})\n"
        f"Chain: **{signal['chain']}** | Type: {signal['wallet_type']}\n"
        f"Move: **${signal['amount_usd']:,.0f}** ({signal['pct_change']:+.1f}%)\n"
        f"New Balance: **${signal['new_balance']:,.0f}**\n"
        f"Confidence: **{signal['confidence'].upper()}**"
    )


# ─── Watchlist Management ─────────────────────────────────────────────────────

def get_watchlist():
    return list(WATCHLIST.values())


def setup_default_watchlist():
    for name, addr in ARKHAM_WALLETS.items():
        meta     = ARKHAM_LABELS.get(name, {})
        chain    = "BTC" if "btc" in name.lower() or "mtgox" in name else "ETH"
        add_to_watchlist(
            address=addr,
            label=meta.get("label", name),
            chain=chain,
            threshold_usd=1_000_000,
            metadata={"type": meta.get("type"), "risk": meta.get("risk")},
        )
    return len(WATCHLIST)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Smart Money Engine ===")

    n = setup_default_watchlist()
    print(f"Watchlist: {n} wallets loaded")

    print("\n--- Known wallet balances ---")
    test = [
        ("BTC", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "Satoshi"),
        ("ETH", "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "Vitalik"),
        ("ETH", "0x28C6c06298d514Db089934071355E5743bf21d60", "Binance Hot"),
    ]
    for chain, addr, name in test:
        if chain == "BTC":
            data = get_btc_wallet(addr)
        elif chain == "ETH":
            data = get_eth_wallet(addr)
        else:
            continue
        if "error" not in data:
            bal = data.get("balance_usd_estimate", 0)
            print(f"  {name}: ${bal:,.0f} ({chain})")

    print("\n✅ Smart Money Engine loaded")
