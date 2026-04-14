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

import requests
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional


# ─── Arkham API ───────────────────────────────────────────────────────────────
ARKHAM_BASE = "https://api.arakham.io/v1"
ARKHAM_KEY  = ""

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
    if not ARKHAM_KEY:
        return {"error": "no_arkham_key"}
    try:
        resp = requests.get(
            f"{ARKHAM_BASE}/entity/{address}",
            headers={"X-API-Key": ARKHAM_KEY},
            timeout=10,
        )
        if resp.ok:
            return resp.json()
        return {"error": f"arkham_{resp.status_code}"}
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
                "confidence":   _confidence(entry["type"], abs(pct_chg)),
                "timestamp":    datetime.now(timezone.utc).isoformat(),
            }
            signals.append(sig)
            entry["signals"].append(sig)

        WATCHLIST[addr] = entry

    return signals


def _confidence(wallet_type, pct_change):
    if wallet_type in ("exchange", "institutional") and pct_change > 1:
        return "high"
    elif wallet_type == "whale" and pct_change > 5:
        return "high"
    elif wallet_type == "degen":
        return "low"
    return "medium"


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
