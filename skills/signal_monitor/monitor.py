"""
Signal Monitor — detects signal changes for real-time alerts
Usage as module or standalone script
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/tmp/crypto-quant-ai")
sys.path.insert(0, "/home/vinny2times/.openclaw/workspace/quant-trading")

from skills.price_engine.coingecko import get_simple_price
from skills.signal_generator.generator import generate_signals, Direction

WATCHLIST = ["bitcoin", "ethereum", "solana", "binancecoin", "ripple", "dogecoin"]
WATCHLIST_SYMBOLS = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL",
    "binancecoin": "BNB", "ripple": "XRP", "dogecoin": "DOGE"
}
STATE_PATH = "/tmp/crypto-quant-ai/data/signal_state.json"
ENABLE_SHORT = True


def load_previous_state():
    """Load last known signals from disk."""
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_current_state(signals_dict):
    """Save current signals to disk."""
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(signals_dict, f, indent=2)


def detect_changes(current_signals, previous_state):
    """Detect meaningful signal changes."""
    alerts = []
    for sym, data in current_signals.items():
        prev = previous_state.get(sym)
        if prev is None:
            # First run — report all non-NEUTRAL as new
            if data["direction"] != "NEUTRAL":
                alerts.append({
                    "type": "new_signal",
                    "symbol": sym,
                    "direction": data["direction"],
                    "score": data["score"],
                    "price": data["price"],
                    "prev_direction": None,
                    "reason": data["reason"]
                })
        elif prev["direction"] != data["direction"]:
            alerts.append({
                "type": "flip",
                "symbol": sym,
                "direction": data["direction"],
                "score": data["score"],
                "price": data["price"],
                "prev_direction": prev["direction"],
                "reason": data["reason"]
            })
    return alerts


def format_alert(alert):
    """Format alert for Telegram/Discord."""
    sym = alert["symbol"]
    direction = alert["direction"]
    price = alert["price"]
    score = alert["score"]
    reason = alert["reason"]

    emoji = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}.get(direction, "⚡")
    prev = alert.get("prev_direction")
    flip_text = f" (was {prev})" if prev else ""

    sl_pct = 3.0
    tp_pct = 5.0
    if direction == "BUY":
        sl = price * (1 - sl_pct / 100)
        tp = price * (1 + tp_pct / 100)
    elif direction == "SELL":
        sl = price * (1 + sl_pct / 100)
        tp = price * (1 - tp_pct / 100)
    else:
        sl = tp = 0

    lines = [
        f"{emoji} **{sym} — {direction}**{flip_text}",
        f"Entry: ${price:,.2f}",
        f"Score: {score}/100",
        f"SL: ${sl:,.2f} (-{sl_pct}%) | TP: ${tp:,.2f} (+{tp_pct}%)",
        f"Reason: {reason}",
        f"_{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_"
    ]
    return "\n".join(lines)


def check_and_alert():
    """Main entry point — check prices, detect changes, return alerts."""
    prices = get_simple_price(WATCHLIST)
    signals = generate_signals(
        prices, symbol_map=WATCHLIST_SYMBOLS, enable_short=ENABLE_SHORT
    )

    current = {}
    for sig in signals:
        current[sig.symbol] = {
            "direction": sig.direction.value,
            "score": sig.score,
            "price": sig.price,
            "reason": getattr(sig, "reason", "")
        }

    previous = load_previous_state()
    alerts = detect_changes(current, previous)

    if alerts:
        save_current_state(current)

    return alerts, current


def send_telegram_alert(alert_text):
    """Send alert to LayeredUp Telegram channel."""
    token = "8764496280:AAEcxiXNNqbencWmvEo579T_fO5kl-uG1cs"
    chat_id = "-1003860627513"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": alert_text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        import requests
        r = requests.post(url, json=payload, timeout=15)
        return r.json().get("ok", False)
    except Exception as e:
        return False


if __name__ == "__main__":
    alerts, current = check_and_alert()
    if not alerts:
        print("No signal changes detected.")
        sys.exit(0)

    for alert in alerts:
        text = format_alert(alert)
        print(text)
        print("-" * 40)
        # Uncomment to actually send:
        # send_telegram_alert(text)
