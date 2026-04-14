# CRYPTO-QUANT-PROJECT.md — Ongoing Project Tracker

## Project: Crypto Quant AI Trading System
**Started:** 2026-04-14
**Owner:** Servius (executor) + Clawd (coordinator)
**Channel:** #quant-trading
**Goal:** Build autonomous quant trading system — Phases 1-5

---

## Phase Progress

### Phase 1: Data Infrastructure
- [x] 1.1 — API Account Setup & Key Management *(in progress — keys pending)*
- [x] 1.2 — Price & Market Data Module (CoinGecko) ✅ LIVE
- [ ] 1.3 — On-Chain Data Module (Glassnode, CryptoQuant, Dune, DeFiLlama)
- [ ] 1.4 — Wallet Tracking Module (Arkham, block explorers, smart money watchlist)
- [ ] 1.5 — Derivatives Data Module (Coinglass)
- [ ] 1.6 — Sentiment Data Module (LunarCrush, Santiment, CryptoPanic, Reddit/X)

### Phase 2: Technical Analysis Engine
- [ ] 2.1 — Core Technical Indicators
- [ ] 2.2 — Multi-Timeframe Analysis
- [ ] 2.3 — Chart Pattern Recognition
- [ ] 2.4 — Key Level Mapping
- [ ] 2.5 — Technical Score Generator

### Phase 3: On-Chain & Sentiment Intelligence
- [ ] 3.1 — On-Chain Health Scoring
- [ ] 3.2 — Whale & Smart Money Copy Trading
- [ ] 3.3 — DeFi Opportunity Scanner
- [ ] 3.4 — Derivatives Sentiment Analysis
- [ ] 3.5 — Social & News Alpha
- [ ] 3.6 — Cross-Signal Correlation Engine

### Phase 4: Signal Generation & Paper Trading
- [ ] 4.1 — Trade Signal Generator
- [ ] 4.2 — Copy Trade Signal Generator
- [ ] 4.3 — Arbitrage Scanner
- [ ] 4.4 — Risk Management Framework
- [ ] 4.5 — Paper Trading System ($10K virtual)
- [ ] 4.6 — Performance Analytics
- [ ] 4.7 — Signal Refinement Loop

### Phase 5: Live Execution (BLOCKED — requires all Phase 4 prereqs + operator approval)
- [ ] 5.1 — Exchange API Integration
- [ ] 5.2 — Order Execution
- [ ] 5.3 — Position Monitoring
- [ ] 5.4 — Kill Switch & Circuit Breakers
- [ ] 5.5 — Approval Modes (start Mode 1)

---

## Current Sprint
**Sprint 1:** Phase 1 — Data Infrastructure
**Focus:** 1.1 API accounts + 1.2 Price Data Module

### Sprint Tasks
1. Sign up for all free-tier API accounts (CoinGecko, Glassnode, CryptoQuant, Coinglass, DeFiLlama, etc.)
2. Store all API keys in TOOLS.md immediately
3. Build Python environment and core data fetching framework
4. Start with CoinGecko price module (free tier, most accessible)
5. Build standardized data format (JSON: timestamp, open, high, low, close, volume)

### Blockers
- Need operator to provide any existing exchange API keys they have
- Need operator to confirm which exchanges they already have accounts on

---

## Coordination Protocol (Servius ↔ Clawd)

### How We Work Together
1. **This file is the source of truth** for what phase we're in and what's next
2. **Servius does the building** — Python scripts, data pipelines, analysis engines
3. **Clawd coordinates** — reviews architecture, handles cross-project dependencies
4. **Both update this file** — when starting a task, mark it in-progress; when done, mark done with evidence
5. **Always pick up where we left off** — read CRYPTO-QUANT-PROJECT.md at session start, continue from current sprint

### Handoff Protocol
- When Servius finishes a module, push code to GitHub and note it here
- When Clawd needs changes, note them in #agent-comms or here
- If blocked, update the blockers section and ping the responsible party
- Never duplicate work — check this file before starting anything new

### Session Start Checklist
1. Read CRYPTO-QUANT-PROJECT.md → find current sprint and task
2. Read memory/YYYY-MM-DD.md → recent context
3. Check #quant-trading for operator messages
4. Continue from current task — don't restart completed work
5. Update this file when done or blocked

---

## Key Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-14 | Python as primary language | Best ecosystem for data science, crypto APIs, TA libraries |
| 2026-04-14 | Start with CoinGecko free tier | Most accessible, good coverage, no cost to start |
| 2026-04-14 | Paper trade $10K minimum 50 trades | Roadmap requirement — no live trading until proven |
| 2026-04-14 | Mode 1 (manual approval) to start | Safety first — earn trust through performance |