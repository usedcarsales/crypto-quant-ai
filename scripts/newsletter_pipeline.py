"""
Signal-to-Newsletter Pipeline — automates quant brief creation from market data.

Runs the full pipeline: prices → signals → brief → save → optional Discord post.

Usage (standalone):
    python -m scripts.newsletter_pipeline

Usage (imported):
    from skills.newsletter_pipeline.pipeline import run_pipeline
    brief_path = run_pipeline(post_to_discord=True, channel_id="...")
"""

import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/home/vinny2times/.openclaw/workspace/quant-trading")

from skills.price_engine.coingecko import get_simple_price, get_trending
from skills.signal_generator.generator import generate_signals, Direction
from skills.paper_trader.trader import PaperTrader
from skills.newsletter_draft.draft import draft_brief, save_brief
import requests

WATCHLIST = ["bitcoin", "ethereum", "solana", "binancecoin", "ripple", "dogecoin"]
WATCHLIST_SYMBOLS = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL",
    "binancecoin": "BNB", "ripple": "XRP", "dogecoin": "DOGE"
}


def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        d = r.json()["data"][0]
        return int(d["value"]), d["value_classification"]
    except Exception:
        return None, "Unknown"


def run_pipeline(post_to_discord: bool = False, channel_id: str = None) -> str:
    """
    Run the full signal-to-newsletter pipeline.
    Returns path to the saved brief file.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Fetch data
    prices = get_simple_price(WATCHLIST)
    trending_raw = get_trending()
    trending = [c["item"]["symbol"].upper() for c in trending_raw.get("coins", [])[:10]]
    fg_val, fg_label = get_fear_greed()

    # Save fear & greed for signal generator reference
    fg_path = "/home/vinny2times/.openclaw/workspace/quant-trading/logs/last_fear_greed.json"
    try:
        with open(fg_path, "w") as f:
            json.dump({"value": fg_val or 50, "label": fg_label, "time": now}, f)
    except Exception:
        pass

    # Generate signals (with SHORT enabled)
    signals = generate_signals(prices, symbol_map=WATCHLIST_SYMBOLS, enable_short=True)

    # Get portfolio state
    trader = PaperTrader()
    price_dict = {cid: data.get("usd", 0) for cid, data in prices.items()}
    trader.check_cycle(price_dict)  # update any closed positions
    stats = trader.get_stats()
    open_positions = [p for p in trader.data.get("positions", []) if p.get("status") == "open"]

    # Draft brief
    brief = draft_brief(
        signals=signals,
        prices=prices,
        fear_greed=(fg_val, fg_label),
        trending=trending,
        open_positions=open_positions,
        stats=stats
    )

    # Save
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fname = f"{date_str}-quantalpha-brief.md"
    out_path = save_brief(brief, fname)

    print(f"📰 Brief saved: {out_path}")
    print(f"📊 Headline: {brief.headline}")
    print(f"✅ Actions: {len(brief.action_items)}")

    return out_path


if __name__ == "__main__":
    run_pipeline()
