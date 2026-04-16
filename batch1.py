#!/usr/bin/env python3
"""
Batch 1 of 3: Coins 0-16 (first half of 47 candidates)
"""
import json, sys, os, time, importlib.util as _il

WORK_DIR = "/home/vinny2times/.openclaw/workspace/crypto-quant"
os.chdir(WORK_DIR)
sys.path.insert(0, WORK_DIR)

with open("/tmp/crypto-quant-candidates.json", "r") as f:
    candidates = json.load(f)["candidates"]

# Load TA module
_ta_spec = _il.spec_from_file_location("ta_mod", "skills/ta_engine/analyze.py")
TA_MOD = _il.module_from_spec(_ta_spec)
TA_MOD.__name__ = "ta_mod"
_ta_spec.loader.exec_module(TA_MOD)

# Load social alpha
_soc_spec = _il.spec_from_file_location("soc_mod", "skills/sentiment_engine/social_alpha.py")
SOC_MOD = _il.module_from_spec(_soc_spec)
SOC_MOD.__name__ = "soc_mod"
_soc_spec.loader.exec_module(SOC_MOD)

# Load smart money
_wl_spec = _il.spec_from_file_location("wl_mod", "skills/wallet_engine/smart_money.py")
WL_MOD = _il.module_from_spec(_wl_spec)
WL_MOD.__name__ = "wl_mod"
_wl_spec.loader.exec_module(WL_MOD)

try:
    g = SOC_MOD.get_global_sentiment()
    social_score = g.get("combined_score", 50.0)
except:
    social_score = 50.0

try:
    sm = WL_MOD.get_smart_money_signal()
    smart_money_score = sm.get("score", 50.0)
except:
    smart_money_score = 50.0

batch = candidates[0:17]
results = []

for i, coin in enumerate(batch):
    sym = coin["symbol"]
    cid = coin["coin_id"]
    raw = coin.get("raw_score", 2.0)
    rsi = coin.get("rsi")
    p1h = coin.get("price_1h", 0)
    p24 = coin.get("price_24h", 0)
    rank = coin.get("rank", 500)
    vol = coin.get("volume_24h", 0)
    mcap = coin.get("mcap", 1)

    ta_score = 50.0
    ta_rsi = rsi
    ta_trend = "unknown"

    try:
        r = TA_MOD.analyze(symbol=sym, coin_id=cid, days=30)
        if "error" not in r:
            ta_score = r.get("conviction_score", 50)
            ta_rsi = r.get("indicators", {}).get("rsi_14", rsi)
            ta_trend = r.get("trend", "unknown")
        print(f"[{i+1}/17] {sym}: TA={ta_score} RSI={ta_rsi}", flush=True)
    except Exception as e:
        print(f"[{i+1}/17] {sym}: {str(e)[:50]}", flush=True)

    if ta_rsi is None:
        ta_rsi = rsi

    onchain = min(100, 30 + (vol/mcap*100) * 5) if mcap > 0 else 30
    defi = min(100, 20 + max(0,(500-rank)/10) + max(0, min(40, p24)))
    social_c = min(100, social_score + (p1h*2 if p1h > 3 else 0) - (abs(p1h)*2 if p1h < -3 else 0))
    boost = min(raw * 1.2, 18)

    composite = round(min(100, ta_score*0.35 + onchain*0.20 + smart_money_score*0.20 + defi*0.15 + social_c*0.10 + boost), 1)

    results.append({
        "symbol": sym, "coin_id": cid, "name": coin.get("name", sym),
        "price": coin.get("price", 0), "price_1h": p1h, "price_24h": p24,
        "price_7d": coin.get("price_7d", 0), "rsi": ta_rsi,
        "ta_score": round(ta_score, 1), "onchain_score": round(onchain, 1),
        "smart_money_score": round(smart_money_score, 1),
        "defi_score": round(defi, 1), "social_score": round(social_c, 1),
        "scanner_boost": round(boost, 1), "raw_score": raw,
        "composite": composite,
        "signal": "🟢 STRONG BUY" if composite >= 70 else "🟡 MODERATE" if composite >= 50 else "⚪ NEUTRAL",
        "trend": ta_trend, "rank": rank, "volume_24h": vol, "mcap": mcap,
    })

    if i < len(batch) - 1:
        time.sleep(1.2)

with open("/tmp/batch1.json", "w") as f:
    json.dump({"batch": 1, "results": results, "count": len(results)}, f)
print(f"Batch 1 done: {len(results)} coins processed")