#!/usr/bin/env python3
"""
Lightweight scanner-to-correlation pipeline.
Writes partial results after every 5 coins to survive SIGKILL.
"""
import json, sys, os, time, importlib.util as _il

WORK_DIR = "/home/vinny2times/.openclaw/workspace/crypto-quant"
os.chdir(WORK_DIR)
sys.path.insert(0, WORK_DIR)

RESULTS_FILE = "/tmp/crypto-quant-pipeline-results.json"
CACHE_FILE   = "/tmp/crypto-quant-candidates.json"
BATCH_SIZE   = 5

# ── Load modules once ──
print("Loading modules...")
_ta  = _il.spec_from_file_location("ta",  "skills/ta_engine/analyze.py")
TA   = _il.module_from_spec(_ta);  TA.__name__ = "ta";  _ta.loader.exec_module(TA)

_soc = _il.spec_from_file_location("soc", "skills/sentiment_engine/social_alpha.py")
SOC  = _il.module_from_spec(_soc);  SOC.__name__ = "soc";  _soc.loader.exec_module(SOC)

_wl  = _il.spec_from_file_location("wl",  "skills/wallet_engine/smart_money.py")
WL   = _il.module_from_spec(_wl);  WL.__name__ = "wl";  _wl.loader.exec_module(WL)

# ── Global signals once ──
print("Global sentiment...")
social = SOC.get_global_sentiment()
social_score = float(social.get("combined_score", 50.0))

print("Smart money...")
sm = WL.get_smart_money_signal()
smart_score = float(sm.get("score", 50.0))

print(f"  social={social_score} smart={smart_score}")

# ── Load cache ──
with open(CACHE_FILE) as f:
    scan = json.load(f)
candidates = scan["candidates"]
print(f"Candidates: {len(candidates)}")

# ── Load partial if exists ──
def load_partial():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            d = json.load(f)
        return d.get("results", []), d.get("done", 0)
    return [], 0

results, done = load_partial()
print(f"Resuming from index {done}/{len(candidates)}")

# ── Process in batches ──
def calc_composite(ta_score, raw_score, mcap, volume_24h, price_1h, price_24h, rank):
    onchain  = min(100, 30 + (volume_24h/mcap*5 if mcap else 0))
    defi     = min(100, 20 + max(0,(500-rank)/10) + max(0, min(40, price_24h)))
    social_adj = min(100, max(0, social_score + (price_1h*2 if price_1h and price_1h>3 else 0)))
    boost   = min(raw_score * 1.2, 18)
    comp    = (ta_score*0.35 + onchain*0.20 + smart_score*0.20 +
               defi*0.15 + social_adj*0.10 + boost)
    return round(min(100, max(0, comp)), 1), round(boost, 1)

def sig(c): return "🟢 STRONG BUY" if c>=70 else ("🟡 MODERATE" if c>=50 else "⚪ NEUTRAL")

for i in range(done, len(candidates)):
    c = candidates[i]
    sym, cid = c["symbol"], c.get("coin_id", c["symbol"].lower())
    raw = c.get("raw_score", 2.0)
    mcap = c.get("mcap", 1) or 1
    vol  = c.get("volume_24h", 0)
    p1h  = c.get("price_1h", 0)
    p24  = c.get("price_24h", 0)
    rank = c.get("rank", 500)

    try:
        ta_r = TA.analyze(symbol=sym, coin_id=cid, days=30)
        ta_s = float(ta_r.get("conviction_score", 50)) if "error" not in ta_r else 50.0
        rsi  = ta_r.get("indicators", {}).get("rsi_14") or c.get("rsi")
    except Exception as e:
        ta_s, rsi = 50.0, None

    comp, boost = calc_composite(ta_s, raw, mcap, vol, p1h, p24, rank)
    results.append({
        "symbol": sym, "coin_id": cid,
        "price_1h": p1h, "price_24h": p24,
        "rsi": rsi,
        "ta_score": round(ta_s,1),
        "scanner_boost": boost,
        "composite": comp,
        "signal": sig(comp),
        "triggers": c.get("triggers", []),
    })
    print(f"  [{i+1}/{len(candidates)}] {sym} TA={ta_s:.0f} RSI={rsi} comp={comp} {sig(comp)}")

    # Write partial after every BATCH_SIZE
    if (i+1) % BATCH_SIZE == 0:
        with open(RESULTS_FILE, "w") as f:
            json.dump({"results": results, "done": i+1,
                       "social_score": social_score, "smart_score": smart_score,
                       "candidates_count": len(candidates)}, f, indent=2)
        print(f"  💾 Checkpoint saved ({i+1} coins)")

    if i < len(candidates)-1:
        time.sleep(1.2)

# ── Final save ──
with open(RESULTS_FILE, "w") as f:
    json.dump({"results": results, "done": len(candidates),
               "candidates_count": len(candidates),
               "social_score": social_score, "smart_score": smart_score,
               "run_timestamp": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ")}, f, indent=2)

# ── Print summary ──
results.sort(key=lambda x: x["composite"], reverse=True)
print(f"\n{'='*65}")
print(f"{'COIN':<9}| {'1H%':>7} | {'RSI':>5} | {'TA':>5} | {'Boost':>5} | {'COMPOSITE':>9} | SIGNAL")
print(f"{'-'*65}")
for r in results:
    p1h = r["price_1h"]
    rsi_s = f"{r['rsi']:.0f}" if r.get("rsi") else "-"
    print(f"{r['symbol']:<9}| {f'{p1h:+.1f}%':>7} | {rsi_s:>5} | {r['ta_score']:>5.0f} | {r['scanner_boost']:>+5.1f} | {r['composite']:>9.1f}/100 | {r['signal']}")
print(f"{'='*65}")
sb = [r['symbol'] for r in results if r['composite']>=70]
mo = [r['symbol'] for r in results if 50<=r['composite']<70]
ne = [r['symbol'] for r in results if r['composite']<50]
print(f"🟢 STRONG BUY (≥70):   {len(sb)} — {', '.join(sb[:20])}")
print(f"🟡 MODERATE (50-69): {len(mo)} — {', '.join(mo[:20])}")
print(f"⚪ NEUTRAL (<50):     {len(ne)} — {', '.join(ne[:20])}")
print(f"\n✅ Done — {len(results)}/{len(candidates)} processed")
