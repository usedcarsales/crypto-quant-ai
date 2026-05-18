# Signal Monitor

Real-time signal change detection for trading alerts.

## What it does

- Polls CoinGecko every N minutes for price data
- Runs signal generator on fresh prices
- Compares to previous signals stored on disk
- **Only alerts when a signal CHANGES** (e.g., NEUTRAL → BUY, BUY → SELL)
- Formats clean Telegram-ready messages with entry/SL/TP

## Why this matters

Our existing cron runs at fixed times (9 AM, 1 PM, 9 PM ET). Crypto trades 24/7. A signal could flip at 3 AM and we'd miss it until the next check. This bridges that gap.

## Premium monetization path

1. **Free tier:** Daily digest (existing cron) — posted to public channels
2. **Premium tier ($29/mo):** Real-time alerts via Telegram bot when signals flip — instant entry/SL/TP
3. **Pro tier ($99/mo):** Full automation — bot auto-paper-trades the signals and reports P&L

## Files

- `skills/signal_monitor/monitor.py` — detection + formatting engine
- `data/signal_state.json` — persists last known signals

## Usage

```bash
cd /tmp/crypto-quant-ai
venv/bin/python skills/signal_monitor/monitor.py
```

To enable live Telegram alerts, uncomment the `send_telegram_alert()` call in `__main__`.

## Cron setup (every 30 minutes)

```bash
openclaw cron add --name "signal-monitor" --cron "*/30 * * * *" --tz "America/New_York" --message "cd /tmp/crypto-quant-ai && venv/bin/python skills/signal_monitor/monitor.py" --channel "discord" --to "1493490316865437736" --session isolated --announce
```

## Future: Full automation

Phase 2: Connect to a real exchange API (Kraken, Coinbase) and execute the signals automatically. Phase 3: Run a private Telegram bot where subscribers get instant alerts with one-tap "copy trade" buttons.
