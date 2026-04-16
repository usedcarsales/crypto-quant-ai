"""
RSI Pullback Alert Engine
Phase 4 — Monitors RSI on tracked opportunities and fires BUY alerts at oversold entry.
Designed for 15-minute cron runs.
"""

import json, time, os, requests
from datetime import datetime, timezone
from typing import Optional

# ─── Config ───────────────────────────────────────────────────────────────────
ALERT_WATCHLIST_FILE = "/tmp/crypto-quant-alert-watchlist.json"
ALERT_HISTORY_FILE   = "/tmp/crypto-quant-alert-history.json"
CG_BASE              = "https://api.coingecko.com/api/v3"
HEADERS              = {"User-Agent": "CryptoQuantBot/1.0"}
RSI_PERIOD           = 14
RSI_BUY_THRESHOLD    = 35        # fire alert when RSI drops below this
RSI_SELL_THRESHOLD   = 70        # optional: RSI overbought alert
POLICY               = "paper"   # 'paper' = alert only | 'live' = execute

# ─── Default Watchlist ────────────────────────────────────────────────────────
DEFAULT_WATCHLIST = [
    # From scanner pipeline results (2026-04-16)
    {"symbol": "TIA",   "coin_id": "tia",          "rsi_triggered": False, "last_rsi": None, "added": "2026-04-16", "notes": "L1 data, clean setup"},
    {"symbol": "ARB",   "coin_id": "arbitrum",      "rsi_triggered": False, "last_rsi": None, "added": "2026-04-16", "notes": "L2 narrative intact"},
    {"symbol": "OP",    "coin_id": "optimism",      "rsi_triggered": False, "last_rsi": None, "added": "2026-04-16", "notes": "L2, BTC correl"},
    {"symbol": "WLD",   "coin_id": "worldcoin-wld", "rsi_triggered": False, "last_rsi": None, "added": "2026-04-16", "notes": "AI narrative"},
    {"symbol": "INJ",   "coin_id": "injective",     "rsi_triggered": False, "last_rsi": None, "added": "2026-04-16", "notes": "DeFi L1"},
    {"symbol": "NEIRO", "coin_id": "neiro-onetoken", "rsi_triggered": False, "last_rsi": None, "added": "2026-04-16", "notes": "Meme coin"},
    {"symbol": "FIL",   "coin_id": "filecoin",       "rsi_triggered": False, "last_rsi": None, "added": "2026-04-16", "notes": "Storage narrative"},
]


# ─── RSI Calculation ─────────────────────────────────────────────────────────
def calc_rsi(closes: list, period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    closes = [float(c) for c in closes]
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_g  = sum(gains) / period
    avg_l  = sum(losses) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return round(100 - 100 / (1 + rs), 2)


def fetch_rsi(coin_id: str, days: int = 14) -> Optional[float]:
    """Fetch OHLCV and compute 14-period RSI for a coin."""
    try:
        r = requests.get(
            f"{CG_BASE}/coins/{coin_id}/ohlc",
            params={"vs_currency": "usd", "days": days},
            headers=HEADERS,
            timeout=15,
        )
        if r.status_code == 429:
            return None  # rate limited
        if r.status_code != 200:
            return None
        ohlc = r.json()
        if not ohlc or len(ohlc) < 15:
            return None
        closes = [float(c[4]) for c in ohlc]
        return calc_rsi(closes, RSI_PERIOD)
    except Exception:
        return None


# ─── Watchlist Management ─────────────────────────────────────────────────────
def load_watchlist() -> list[dict]:
    if os.path.exists(ALERT_WATCHLIST_FILE):
        try:
            with open(ALERT_WATCHLIST_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_WATCHLIST.copy()


def save_watchlist(watchlist: list[dict]):
    try:
        with open(ALERT_WATCHLIST_FILE, "w") as f:
            json.dump(watchlist, f, indent=2)
    except Exception:
        pass


def add_coin(symbol: str, coin_id: str = None, notes: str = ""):
    """Add a coin to the RSI alert watchlist."""
    watchlist = load_watchlist()
    sym = symbol.upper()
    if any(w["symbol"] == sym for w in watchlist):
        return False  # already in watchlist
    watchlist.append({
        "symbol":         sym,
        "coin_id":        (coin_id or sym.lower()),
        "rsi_triggered":  False,
        "last_rsi":       None,
        "added":          datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "notes":          notes,
    })
    save_watchlist(watchlist)
    return True


def remove_coin(symbol: str):
    watchlist = load_watchlist()
    sym = symbol.upper()
    original = len(watchlist)
    watchlist = [w for w in watchlist if w["symbol"] != sym]
    save_watchlist(watchlist)
    return len(watchlist) < original


# ─── Alert History ────────────────────────────────────────────────────────────
def load_history() -> list[dict]:
    if os.path.exists(ALERT_HISTORY_FILE):
        try:
            with open(ALERT_HISTORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_history(history: list[dict]):
    try:
        with open(ALERT_HISTORY_FILE, "w") as f:
            json.dump(history[-100:], f, indent=2)  # keep last 100
    except Exception:
        pass


def record_alert(symbol: str, rsi: float, event: str, price: float = None):
    """Record an alert event in history."""
    history = load_history()
    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol":    symbol.upper(),
        "rsi":       rsi,
        "event":     event,  # "RSI_OVERSOLD" | "RSI_RECOVERY" | "ADDED" | "REMOVED"
        "price":     price,
    })
    save_history(history)


# ─── Core Alert Check ─────────────────────────────────────────────────────────
def check_alerts() -> dict:
    """
    Main cron entry point — check all watchlist coins for RSI triggers.
    Returns dict with {fired: [alerts], watched: [status], errors: []}
    """
    watchlist = load_watchlist()
    fired_alerts = []
    watched_status = []
    errors = []

    for entry in watchlist:
        sym  = entry["symbol"]
        cid  = entry.get("coin_id", sym.lower())
        prev_rsi = entry.get("last_rsi")

        rsi = fetch_rsi(cid, days=14)

        # Rate limited — skip this run, don't update last_rsi
        if rsi is None:
            watched_status.append({
                "symbol":   sym,
                "status":   "rate_limited",
                "last_rsi": prev_rsi,
                "notes":    entry.get("notes", ""),
            })
            time.sleep(1.5)
            continue

        entry["last_rsi"] = rsi
        was_triggered = entry.get("rsi_triggered", False)

        # Fire alert: RSI crossed below threshold (was above, now below)
        if rsi < RSI_BUY_THRESHOLD and not was_triggered:
            entry["rsi_triggered"] = True
            fired_alerts.append({
                "symbol":       sym,
                "rsi":          rsi,
                "prev_rsi":     prev_rsi,
                "threshold":    RSI_BUY_THRESHOLD,
                "coin_id":      cid,
                "notes":        entry.get("notes", ""),
                "fired_at":     datetime.now(timezone.utc).isoformat(),
            })
            record_alert(sym, rsi, "RSI_OVERSOLD")

        # Reset trigger when RSI recovers above threshold + 5 (avoid re-fire on minor bounces)
        elif rsi >= RSI_BUY_THRESHOLD + 5 and was_triggered:
            entry["rsi_triggered"] = False
            record_alert(sym, rsi, "RSI_RECOVERY")

        watched_status.append({
            "symbol":   sym,
            "status":   "triggered" if entry["rsi_triggered"] else "watching",
            "rsi":      rsi,
            "prev_rsi": prev_rsi,
            "notes":    entry.get("notes", ""),
        })

        time.sleep(1.5)  # CoinGecko rate limit

    save_watchlist(watchlist)

    return {
        "checked_at":  datetime.now(timezone.utc).isoformat(),
        "coins_checked": len(watchlist),
        "fired":       fired_alerts,
        "watched":     watched_status,
    }


# ─── Formatters ──────────────────────────────────────────────────────────────
def format_alert_report(result: dict) -> str:
    """Format alert check results for Discord."""
    fired = result.get("fired", [])
    watched = result.get("watched", [])
    checked = result.get("checked_at", "")

    lines = [f"**📡 RSI Pullback Monitor — {checked[:16]}Z**", ""]

    if not fired:
        lines.append("✅ No new alerts — all clear")
    else:
        lines.append(f"🚨 **BUY ALERTS FIRED ({len(fired)}):**")
        for a in fired:
            lines.append(
                f"  🚨 **{a['symbol']}** — RSI {a['prev_rsi']} → **{a['rsi']}** "
                f"(oversold, threshold {a['threshold']})"
            )
            if a.get("notes"):
                lines.append(f"       → {a['notes']}")
        lines.append("")

    # Watched status
    lines.append(f"**👀 Watched ({len(watched)} coins):**")
    triggered = [w for w in watched if w["status"] == "triggered"]
    watching = [w for w in watched if w["status"] == "watching"]
    limited  = [w for w in watched if w["status"] == "rate_limited"]

    for w in watched:
        rsi_s = f"{w['rsi']:.1f}" if w.get("rsi") else "n/a"
        if w["status"] == "triggered":
            lines.append(f"  🔴 {w['symbol']:8s} RSI: {rsi_s} **TRIGGERED** | {w.get('notes','')}")
        elif w["status"] == "rate_limited":
            lines.append(f"  ⏳ {w['symbol']:8s} RSI: {rsi_s} (rate limited) | {w.get('notes','')}")
        else:
            rsi_color = "🔴" if w.get("rsi", 99) > 65 else ("🟡" if w.get("rsi", 99) > 40 else "🟢")
            lines.append(f"  {rsi_color} {w['symbol']:8s} RSI: {rsi_s} | {w.get('notes','')}")

    return "\n".join(lines)


def format_alert_fired(alert: dict) -> str:
    """Format a single fired alert as a high-priority Discord message."""
    return (
        f"🚨 **RSI PULLBACK ALERT — {alert['symbol']}**\n"
        f"RSI dropped to **{alert['rsi']}** (below {alert['threshold']})\n"
        f"Previous RSI: {alert['prev_rsi']}\n"
        f"Threshold: {alert['threshold']}\n"
        f"Notes: {alert.get('notes', '—')}\n"
        f"⏰ Fired at: {alert['fired_at']}\n"
        f"@Clawd — <@1478941524199866418> — RSI pullback confirmed, reviewing..."
    )


# ─── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== RSI Pullback Alert Engine ===\n")
    result = check_alerts()
    print(format_alert_report(result))
    if result["fired"]:
        for a in result["fired"]:
            print("\n" + format_alert_fired(a))
