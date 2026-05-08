# Bug Report — Signal History / Trade Journal Divergence

**Date:** 2026-05-07 21:10 ET
**Severity:** Medium — blocks new trade signals
**Channel:** #quant-trading (cron run)

## Problem
`trade_signals.py` checks `signal_history.json` for open positions. `paper_trader.py` checks `trade_journal.json` for open positions. When positions are closed by paper trader (SL/TP hit), they are removed from trade journal but NOT updated in signal history.

This causes `generate_signal()` to reject all new signals with "Max open positions reached (3/3)" even though the paper portfolio shows 0 open positions.

## Affected Signals (stale OPEN entries)
1. BTC May 5 01:05 — actually closed May 6 via TAKE_PROFIT (trade journal)
2. SOL May 5 17:09 — actually never executed (no trade journal entry)
3. BTC May 6 13:02 — actually closed May 7 via STOP_LOSS (trade journal)

## Fix Applied
Manually updated signal_history.json to mark all 3 as CLOSED with reason "sync_fix_2026-05-07".

## Root Cause
The `execute_signal()` function in `trade_signals.py` adds the signal to history with status OPEN. But when `paper_trader.py` closes a position (via SL/TP), it only updates the trade journal and risk manager — it does NOT sync back to signal_history.json.

## Prevention
Need to add a sync step in `paper_trader.py` `close_position()` or `check_and_close_positions()` that updates the corresponding signal in signal history.

## File: `/tmp/crypto-quant-ai/.bugs/2026-05-07-signal-history-sync.md`
