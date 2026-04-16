#!/usr/bin/env python3
"""
Scanner → Correlation Pipeline
Loads all 47 cached candidates, runs TA analysis, loads global signals,
computes composite scores, outputs Discord table.
"""

import json
import sys
import os
import time
import importlib.util as _il

# ── Working directory ──
WORK_DIR = "/home/vinny2times/.openclaw/workspace/crypto-quant"
os.chdir(WORK_DIR)
sys.path.insert(0, WORK_DIR)

# ── Load modules ONCE at top ──
print("Loading TA engine module...")
_ta_spec = _il.spec_from_file_location("ta_mod", "skills/ta_engine/analyze.py")
TA_MOD = _il.module_from_spec(_ta_spec)
_ta_spec.loader.exec_module(TA_MOD)
print("✅ TA engine loaded")

print("Loading social alpha module...")
_soc_spec = _il.spec_from_file_location("soc_mod", "skills/sentiment_engine/social_alpha.py")
SOC_MOD = _il.module_from_spec(_soc_spec)
_soc_spec.loader.exec_module(SOC_MOD)
print("✅ Social alpha loaded")

print("Loading smart money module...")
_wl_spec = _il.spec_from_file_location("wl_mod", "skills/wallet_engine/smart_money.py")
WL_MOD = _il.module_from_spec(_wl_spec)
_wl_spec.loader.exec_module(WL_MOD)
print("✅ Smart money loaded")

# ── Load cached candidates ──
print("Loading cached candidates...")
with open("/tmp/crypto-quant-candidates.json", "r") as f:
    scan_data = json.load(f)

candidates = scan_data["candidates"]
print(f"Loaded {len(candidates)} candidates")

# ── Load global signals ONCE ──
print("\nFetching global sentiment...")
try:
    global_sentiment = SOC_MOD.get_global_sentiment()
    social_score = global_sentiment.get("combined_score", 50.0)
    print(f"  Global sentiment: {global_sentiment.get('global_sentiment', 'unknown')} (score: {social_score})")
except Exception as e:
    print(f"  ⚠️ Global sentiment failed: {e}")
    social_score = 50.0

print("Fetching smart money signal...")
try:
    smart_money = WL_MOD.get_smart_money_signal()
    smart_money_score = smart_money.get("score", 50.0)
    smart_money_signal = smart_money.get("signal", "NEUTRAL")
    print(f"  Smart money: {smart_money_signal} (score: {smart_money_score})")
except Exception as e:
    print(f"  ⚠️ Smart money failed: {e}")
    smart_money_score = 50.0
    smart_money_signal = "NEUTRAL"

# ── Process each candidate ──
print(f"\nRunning TA analysis on {len(candidates)} coins...")
results = []
errors = 0

for i, coin in enumerate(candidates):
    symbol = coin["symbol"]
    coin_id = coin["coin_id"]
    raw_score = coin.get("raw_score", 2.0)
    rsi = coin.get("rsi")
    price_1h = coin.get("price_1h", 0)
    price_24h = coin.get("price_24h", 0)

    print(f"  [{i+1}/{len(candidates)}] {symbol} ({coin_id})...", end=" ", flush=True)

    # Run TA analysis
    ta_score = 50.0  # default
    ta_conviction = 50
    ta_rsi = rsi
    ta_trend = "unknown"
    ta_rec = "NEUTRAL"
    
    try:
        ta_result = TA_MOD.analyze(symbol=symbol, coin_id=coin_id, days=30)
        if "error" in ta_result:
            print(f"⚠️ TA error: {ta_result['error']}")
            errors += 1
        else:
            ta_conviction = ta_result.get("conviction_score", 50)
            ta_score = ta_conviction  # 0-100 scale
            ta_rsi = ta_result.get("indicators", {}).get("rsi_14", rsi)
            ta_trend = ta_result.get("trend", "unknown")
            ta_rec = ta_result.get("recommendation", "NEUTRAL")
            print(f"✅ TA={ta_conviction} RSI={ta_rsi} trend={ta_trend}")
    except Exception as e:
        err_str = str(e)
        if "429" in err_str:
            print(f"⚠️ Rate limited, skipping")
            errors += 1
        else:
            print(f"⚠️ TA failed: {err_str[:60]}")
            errors += 1

    # Use scanner RSI if TA didn't return one
    if ta_rsi is None:
        ta_rsi = rsi

    # ── Compute Composite Score ──
    # TA(35%) + OnChain(20%) + SmartMoney(20%) + DeFi(15%) + Social(10%) + Scanner Boost
    # OnChain: proxy from volume/mcap ratio and 24h change
    vol_24h = coin.get("volume_24h", 0)
    mcap = coin.get("mcap", 1)
    vol_mcap_ratio = (vol_24h / mcap * 100) if mcap > 0 else 0
    # OnChain score: higher vol/mcap ratio = more activity = higher score (capped)
    onchain_score = min(100, 30 + vol_mcap_ratio * 5)  # base 30, bonus from volume
    
    # DeFi: proxy from price momentum and rank
    rank = coin.get("rank", 500)
    rank_factor = max(0, min(40, (500 - rank) / 10))  # better rank = higher score
    momentum_factor = max(0, min(40, price_24h))  # 24h% as positive momentum signal
    defi_score = 20 + rank_factor + momentum_factor  # base 20 + rank + momentum
    defi_score = min(100, defi_score)

    # Social: use global sentiment as baseline, adjusted per coin
    social_coin_score = social_score  # global baseline
    # Coins with higher 1h moves get social attention boost
    if price_1h and price_1h > 3:
        social_coin_score = min(100, social_score + price_1h * 2)
    elif price_1h and price_1h < -3:
        social_coin_score = max(0, social_score + price_1h * 2)

    # Scanner boost = min(raw_score * 1.2, 18)
    scanner_boost = min(raw_score * 1.2, 18)

    # Weighted composite
    composite = (
        ta_score * 0.35 +
        onchain_score * 0.20 +
        smart_money_score * 0.20 +
        defi_score * 0.15 +
        social_coin_score * 0.10 +
        scanner_boost
    )
    composite = round(min(100, max(0, composite)), 1)

    # Signal classification
    if composite >= 70:
        signal = "🟢 STRONG BUY"
    elif composite >= 50:
        signal = "🟡 MODERATE"
    else:
        signal = "⚪ NEUTRAL"

    results.append({
        "symbol": symbol,
        "coin_id": coin_id,
        "name": coin.get("name", symbol),
        "price": coin.get("price", 0),
        "price_1h": price_1h,
        "price_24h": price_24h,
        "price_7d": coin.get("price_7d", 0),
        "rsi": ta_rsi,
        "ta_score": round(ta_score, 1),
        "onchain_score": round(onchain_score, 1),
        "smart_money_score": round(smart_money_score, 1),
        "defi_score": round(defi_score, 1),
        "social_score": round(social_coin_score, 1),
        "scanner_boost": round(scanner_boost, 1),
        "raw_score": raw_score,
        "composite": composite,
        "signal": signal,
        "trend": ta_trend,
        "recommendation": ta_rec,
        "rank": rank,
        "volume_24h": vol_24h,
        "mcap": mcap,
    })

    # Rate limit: 1.2s between TA calls (CoinGecko)
    if i < len(candidates) - 1:
        time.sleep(1.2)

# ── Sort by composite score descending ──
results.sort(key=lambda x: x["composite"], reverse=True)

# ── Save results ──
output_path = "/tmp/crypto-quant-pipeline-results.json"
with open(output_path, "w") as f:
    json.dump({
        "run_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "candidates_count": len(candidates),
        "results_count": len(results),
        "errors": errors,
        "global_sentiment": global_sentiment if isinstance(global_sentiment, dict) else {"score": social_score},
        "smart_money": smart_money if isinstance(smart_money, dict) else {"score": smart_money_score, "signal": smart_money_signal},
        "results": results,
    }, f, indent=2)
print(f"\n💾 Results saved to {output_path}")

# ── Format Discord table ──
lines = []
lines.append("📊 **Scanner → Correlation Pipeline Results**")
lines.append("")
lines.append("```")
lines.append(f"{'COIN':<9}| {'1H%':>7} | {'RSI':>5} | {'TA Sc':>5} | {'Boost':>5} | {'COMPOSITE':>9} | SIGNAL")
lines.append("-" * 68)

strong_buy = []
moderate = []
neutral = []

for r in results:
    sym = r["symbol"][:8]
    p1h = r["price_1h"]
    p1h_str = f"{p1h:+.1f}%" if p1h is not None else "N/A"
    rsi_val = r["rsi"]
    rsi_str = f"{rsi_val:.0f}" if rsi_val is not None else "-"
    ta_str = f"{r['ta_score']:.1f}"
    boost_str = f"+{r['scanner_boost']:.1f}"
    comp_str = f"{r['composite']:.1f}/100"
    sig = r["signal"]
    
    lines.append(f"{sym:<9}| {p1h_str:>7} | {rsi_str:>5} | {ta_str:>5} | {boost_str:>5} | {comp_str:>9} | {sig}")
    
    if r["composite"] >= 70:
        strong_buy.append(r["symbol"])
    elif r["composite"] >= 50:
        moderate.append(r["symbol"])
    else:
        neutral.append(r["symbol"])

lines.append("```")
lines.append("")
lines.append("**TOTALS:**")
lines.append(f"🟢 STRONG BUY (≥70): {len(strong_buy)} coins — {', '.join(strong_buy[:15])}")
if len(strong_buy) > 15:
    lines.append(f"   ...and {len(strong_buy) - 15} more")
lines.append(f"🟡 MODERATE (50-69): {len(moderate)} coins — {', '.join(moderate[:15])}")
if len(moderate) > 15:
    lines.append(f"   ...and {len(moderate) - 15} more")
lines.append(f"⚪ NEUTRAL (<50): {len(neutral)} coins — {', '.join(neutral[:10])}")
if len(neutral) > 10:
    lines.append(f"   ...and {len(neutral) - 10} more")
lines.append("")
lines.append(f"_Processed {len(results)}/{len(candidates)} candidates | {errors} errors_")

table = "\n".join(lines)
print("\n" + table)

# Save the formatted table for the message tool
with open("/tmp/crypto-quant-pipeline-table.txt", "w") as f:
    f.write(table)
print("\n📋 Table saved to /tmp/crypto-quant-pipeline-table.txt")