# Crypto Quant AI — Servius & Clawd

> **Mission:** Build an autonomous quantitative trading system that finds edges, exploits inefficiencies, and generates profit across any chain, any token, any market condition.

## Project Status
- **Phase:** 1 — Data Infrastructure
- **Started:** 2026-04-14
- **Paper Trading Target:** $10,000 virtual portfolio
- **Live Trading Target:** Operator approval required (see Phase 5 prerequisites)

## Directory Structure
```
crypto-quant/
├── README.md                 # This file — project overview
├── config/
│   ├── crypto-data-sources.json   # API provider configs, rate limits, auth
│   └── risk_policy.json           # Risk management parameters
├── data/
│   ├── price/                # OHLCV data cache
│   ├── onchain/              # On-chain metrics cache
│   ├── wallets/              # Smart money watchlist
│   ├── derivatives/         # Funding, OI, liquidations
│   └── sentiment/            # Social/news data cache
├── skills/
│   ├── ta_engine/            # Technical analysis engine (Phase 2)
│   ├── onchain_analyzer/     # On-chain metrics (Phase 3)
│   ├── copy_tracker/         # Whale/smart money copy trading (Phase 3)
│   ├── sentiment_scorer/     # Sentiment analysis (Phase 3)
│   ├── signal_generator/     # Trade signal generation (Phase 4)
│   ├── paper_trader/         # Paper trading system (Phase 4)
│   └── executor/              # Live execution engine (Phase 5)
├── logs/
│   ├── trading_journal.md    # Every trade, every lesson
│   └── performance/          # Weekly performance reports
├── scripts/
│   ├── setup_env.sh          # Python env setup
│   └── data_fetchers/        # API data fetching scripts
└── tests/
    └── (unit tests for each module)
```

## Phases (from roadmap)
1. **Data Infrastructure** — Connect all data sources via API
2. **Technical Analysis Engine** — Indicators, patterns, multi-timeframe
3. **On-Chain & Sentiment Intelligence** — Smart money, DeFi, derivatives
4. **Signal Generation & Paper Trading** — Prove profitability on paper
5. **Live Execution** — Real money with guardrails (operator approval required)

## Hard Rules
- NEVER give an AI agent API keys with withdrawal permissions
- Paper trade first — no exceptions
- Kill switch is mandatory and non-negotiable
- Start in Mode 1 (manual approval for every trade)
- All API keys saved to TOOLS.md immediately
- Tax tracking from day one