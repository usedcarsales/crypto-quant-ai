"""
Technical Analysis Engine
Phase 2, Tasks 2.1–2.5 — Core TA, Multi-Timeframe, Patterns, Levels, Score
Powered by: ta library + CoinGecko live data
"""

import importlib.util as _il

# ── Direct module load (avoids package import issues) ─────────────────────
_spec = _il.spec_from_file_location("cg_mod", "skills/price_engine/coingecko.py")
_cg = _il.module_from_spec(_spec)
_spec.loader.exec_module(_cg)
get_ohlc = _cg.get_ohlc
get_market_chart = _cg.get_market_chart

import pandas as pd
import numpy as np
from datetime import datetime, timezone


# ─── Indicator Library ────────────────────────────────────────────────────────

def calc_sma(closes: list, period: int) -> float:
    if len(closes) < period:
        return None
    return round(float(np.mean(closes[-period:])), 4)


def calc_ema(closes: list, period: int) -> float:
    if len(closes) < period:
        return None
    return round(float(pd.Series(closes).ewm(span=period, adjust=False).mean().iloc[-1]), 4)


def calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return None
    delta = pd.Series(closes).diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


def calc_macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    if len(closes) < slow + signal:
        return {"macd": None, "signal": None, "histogram": None}
    s = pd.Series(closes)
    ema_f = s.ewm(span=fast, adjust=False).mean()
    ema_s = s.ewm(span=slow, adjust=False).mean()
    macd_line = ema_f - ema_s
    sig_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - sig_line
    return {
        "macd": round(float(macd_line.iloc[-1]), 4),
        "signal": round(float(sig_line.iloc[-1]), 4),
        "histogram": round(float(hist.iloc[-1]), 4),
        "histogram_prev": round(float(hist.iloc[-2]), 4) if len(hist) > 1 else None,
    }


def calc_bollinger(closes: list, period: int = 20, std_mult: float = 2.0) -> dict:
    if len(closes) < period:
        return {}
    s = pd.Series(closes)
    mid = s.rolling(window=period).mean()
    std = s.rolling(window=period).std()
    upper = mid + std * std_mult
    lower = mid - std * std_mult
    bw = float((upper.iloc[-1] - lower.iloc[-1]) / mid.iloc[-1]) if mid.iloc[-1] else None
    pos = float((closes[-1] - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1])) \
          if upper.iloc[-1] != lower.iloc[-1] else 0.5
    return {
        "upper":   round(float(upper.iloc[-1]), 4),
        "middle":  round(float(mid.iloc[-1]), 4),
        "lower":   round(float(lower.iloc[-1]), 4),
        "bandwidth": round(bw, 4) if bw else None,
        "position":  round(pos, 4),
    }


def calc_atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    if len(highs) < period + 1:
        return None
    tr1 = pd.Series(highs) - pd.Series(lows)
    tr2 = (pd.Series(highs) - pd.Series(closes).shift(1)).abs()
    tr3 = (pd.Series(lows) - pd.Series(closes).shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean().iloc[-1]
    return round(float(atr), 4)


def calc_stochastic(highs: list, lows: list, closes: list, period: int = 14) -> dict:
    if len(closes) < period:
        return {}
    lo = pd.Series(lows).rolling(window=period).min()
    hi = pd.Series(highs).rolling(window=period).max()
    k = 100 * (pd.Series(closes) - lo) / (hi - lo)
    d = k.rolling(window=3).mean()
    return {"k": round(float(k.iloc[-1]), 2), "d": round(float(d.iloc[-1]), 2)}


def calc_adx(highs: list, lows: list, closes: list, period: int = 14) -> dict:
    if len(closes) < period + 1:
        return {}
    dh = pd.Series(highs).diff()
    dl = -pd.Series(lows).diff()
    plus_dm  = dh.where(dh > dl, 0).where(dh > 0, 0)
    minus_dm = dl.where(dl > dh, 0).where(dl > 0, 0)
    tr1 = pd.Series(highs) - pd.Series(lows)
    tr2 = (pd.Series(highs) - pd.Series(closes).shift(1)).abs()
    tr3 = (pd.Series(lows) - pd.Series(closes).shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_s = tr.rolling(window=period).mean()
    pdi = 100 * plus_dm.rolling(window=period).mean() / atr_s
    mdi = 100 * minus_dm.rolling(window=period).mean() / atr_s
    dx  = 100 * (pdi - mdi).abs() / (pdi + mdi)
    adx_val = dx.rolling(window=period).mean().iloc[-1]
    return {
        "adx":     round(float(adx_val), 2),
        "plus_di": round(float(pdi.iloc[-1]), 2),
        "minus_di": round(float(mdi.iloc[-1]), 2),
    }


def calc_obv(closes: list, volumes: list) -> float:
    if len(closes) < 2 or len(closes) != len(volumes):
        return None
    obv = 0.0
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:
            obv += volumes[i]
        elif closes[i] < closes[i-1]:
            obv -= volumes[i]
    return round(obv, 2)


def calc_vwap(volumes: list, highs: list, lows: list, closes: list) -> float:
    if len(volumes) < 2 or len(volumes) != len(closes):
        return None
    tp = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    return round(sum(v * t for v, t in zip(volumes, tp)) / sum(volumes), 4)


# ─── Trend Detection ──────────────────────────────────────────────────────────

def detect_trend(closes: list, ema_20: float, ema_50: float, ema_200: float = None) -> str:
    if None in (ema_20, ema_50):
        return "unknown"
    if ema_200:
        if ema_20 > ema_50 > ema_200:  return "strong_uptrend"
        if ema_20 < ema_50 < ema_200:  return "strong_downtrend"
        if ema_20 > ema_50:             return "weak_uptrend"
        return "weak_downtrend"
    return "uptrend" if ema_20 > ema_50 else "downtrend"


def detect_ema_crossover(closes: list) -> str:
    if len(closes) < 27:
        return "none"
    ef_prev = calc_ema(closes[:-1], 12)
    es_prev = calc_ema(closes[:-1], 26)
    ef_curr = calc_ema(closes, 12)
    es_curr = calc_ema(closes, 26)
    if ef_prev is None or es_prev is None:
        return "none"
    if ef_prev <= es_prev and ef_curr > es_curr:
        return "bullish"
    if ef_prev >= es_prev and ef_curr < es_curr:
        return "bearish"
    return "none"


# ─── Support & Resistance ─────────────────────────────────────────────────────

def find_support_resistance(closes: list, volumes: list = None, lookback: int = 50) -> dict:
    data = closes[-lookback:]
    current = data[-1]
    highs, lows = [], []
    for i in range(2, len(data) - 2):
        if data[i] > data[i-1] and data[i] > data[i-2] and data[i] > data[i+1] and data[i] > data[i+2]:
            highs.append(float(data[i]))
        elif data[i] < data[i-1] and data[i] < data[i-2] and data[i] < data[i+1] and data[i] < data[i+2]:
            lows.append(float(data[i]))
    # Pivot-based levels — ensure they bound the current price
    resistance = float(min(highs[-3:])) if highs else current * 1.05
    support    = float(max(lows[-3:]))  if lows  else current * 0.95
    # If pivots are inside current price, use % bands instead
    if resistance <= current:
        resistance = current * 1.03  # 3% above as nearest resistance
    if support >= current:
        support = current * 0.97    # 3% below as nearest support
    return {
        "current_price": round(current, 4),
        "resistance":    round(resistance, 4),
        "support":       round(support, 4),
        "range_width":   round(resistance - support, 4),
        "near_rsr_pct":  round((resistance - current) / current * 100, 2) if current else None,
        "near_sup_pct":  round((current - support) / current * 100, 2) if current else None,
        "pivot_highs":   [round(h, 4) for h in highs[-5:]],
        "pivot_lows":    [round(l, 4) for l in lows[-5:]],
    }


# ─── Full TA Analysis ─────────────────────────────────────────────────────────

def analyze(symbol: str, coin_id: str = None, days: int = 30) -> dict:
    if coin_id is None:
        coin_id = symbol.lower()

    ohlcv = get_ohlc(coin_id, days=days)
    if not ohlcv or len(ohlcv) < 20:
        return {"symbol": symbol, "error": f"insufficient data ({len(ohlcv) if ohlcv else 0} points)"}

    closes  = [float(c["close"])  for c in ohlcv]
    highs   = [float(c["high"])   for c in ohlcv]
    lows    = [float(c["low"])    for c in ohlcv]
    vols    = []  # ohlcv has no volume; get_market_chart called separately if needed

    # Indicators
    ema20  = calc_ema(closes, 20)
    ema50  = calc_ema(closes, 50)
    ema200 = calc_ema(closes, 200) if len(closes) >= 200 else None
    rsi    = calc_rsi(closes, 14)
    macd   = calc_macd(closes)
    bb     = calc_bollinger(closes)
    atr    = calc_atr(highs, lows, closes)
    stoch  = calc_stochastic(highs, lows, closes)
    adx    = calc_adx(highs, lows, closes)
    obv    = calc_obv(closes, vols)
    vwap   = calc_vwap(vols, highs, lows, closes)
    sr     = find_support_resistance(closes, vols)
    trend  = detect_trend(closes, ema20, ema50, ema200)
    cross  = detect_ema_crossover(closes)

    # Signal scoring
    bull, bear = 0, 0
    if rsi and rsi < 35:   bull += 1
    if rsi and rsi > 65:   bear += 1
    if macd["histogram"] and macd["histogram"] > 0:  bull += 1
    if macd["histogram"] and macd["histogram"] < 0:  bear += 1
    if bb.get("position") and bb["position"] < 0.2:  bull += 1
    if bb.get("position") and bb["position"] > 0.8:  bear += 1
    if "uptrend" in trend:   bull += 1
    if "downtrend" in trend: bear += 1
    if cross == "bullish":   bull += 2
    if cross == "bearish":   bear += 2
    if adx.get("adx") and adx["adx"] > 25:
        if adx.get("plus_di", 0) > adx.get("minus_di", 0): bull += 1
        else: bear += 1

    total = bull + bear
    conviction = 50 if total == 0 else max(0, min(100, int(50 + (bull - bear) / total * 50)))

    risk_pct = 0.01
    if conviction >= 85: risk_pct = 0.02
    elif conviction >= 75: risk_pct = 0.015

    stop_pct = round(atr / closes[-1] * 100, 2) if atr and closes[-1] else None

    return {
        "symbol":            symbol.upper(),
        "coin_id":           coin_id,
        "current_price":     round(closes[-1], 4),
        "trend":             trend,
        "indicators": {
            "ema_20":   ema20,  "ema_50":  ema50,  "ema_200": ema200,
            "rsi_14":   rsi,
            "macd":     macd,
            "bollinger": bb,
            "atr_14":   atr,
            "stochastic": stoch,
            "adx":       adx,
            "obv":       obv,   "vwap": vwap,
            "support_resistance": sr,
        },
        "signals": {
            "ema_crossover": cross,
            "bullish_count": bull,
            "bearish_count": bear,
        },
        "conviction_score": conviction,
        "risk_pct":        risk_pct,
        "stop_loss_pct":   stop_pct,
        "recommendation":   _recommend(conviction, bull, bear, rsi, macd),
        "data_points":      len(ohlcv),
        "timestamp":        datetime.now(timezone.utc).isoformat(),
    }


def _recommend(conv: int, bull: int, bear: int, rsi: float, macd: dict) -> str:
    if conv >= 80 and bull > bear:    return "STRONG BUY"
    if conv >= 65 and bull > bear:     return "BUY"
    if conv <= 20 and bear > bull:    return "STRONG SELL"
    if conv <= 35 and bear > bull:    return "SELL"
    if rsi and rsi > 75:              return "TAKE PROFIT — OVERBOUGHT"
    if rsi and rsi < 30:              return "BUY — OVERSOLD"
    if macd.get("histogram") and abs(macd["histogram"]) < 0.001: return "HOLD — MACD FLAT"
    return "NEUTRAL"


# ─── Multi-Timeframe ─────────────────────────────────────────────────────────

def analyze_all_timeframes(symbol: str, coin_id: str = None) -> dict:
    tfs = {
        "4h": analyze(symbol, coin_id, days=7),
        "1d": analyze(symbol, coin_id, days=30),
        "1w": analyze(symbol, coin_id, days=90),
    }
    convs = [v["conviction_score"] for v in tfs.values() if "error" not in v]
    avg_conv = round(sum(convs) / len(convs), 1) if convs else 50
    recs = [v["recommendation"] for v in tfs.values() if "error" not in v]
    buy  = sum(1 for r in recs if "BUY"  in r)
    sell = sum(1 for r in recs if "SELL" in r or "OVERBOUGHT" in r)
    return {
        "symbol": symbol.upper(),
        "timeframes": tfs,
        "avg_conviction": avg_conv,
        "alignment": {"bullish": buy, "bearish": sell, "neutral": len(tfs) - buy - sell},
        "synthesis": "BULLISH" if buy >= 2 else "BEARISH" if sell >= 2 else "NEUTRAL",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== BTC Technical Analysis ===")
    btc = analyze("BTC", "bitcoin", days=30)
    if "error" in btc:
        print(f"Error: {btc['error']}")
    else:
        i = btc["indicators"]
        print(f"\nPrice:     ${btc['current_price']:,.2f}")
        print(f"Trend:     {btc['trend']}")
        print(f"RSI(14):   {i['rsi_14']}")
        print(f"MACD:      {i['macd']}")
        print(f"BB Upper:  {i['bollinger']['upper']} | Lower: {i['bollinger']['lower']}")
        print(f"ATR(14):   {i['atr_14']}")
        print(f"Stochastic: {i['stochastic']}")
        print(f"ADX:        {i['adx']}")
        print(f"Support:   ${i['support_resistance']['support']:,.2f}")
        print(f"Resistance:${i['support_resistance']['resistance']:,.2f}")
        print(f"\nSignals:   {btc['signals']}")
        print(f"Conviction:{btc['conviction_score']}/100")
        print(f"Stop Loss: {btc['stop_loss_pct']}%")
        print(f"Rec:       {btc['recommendation']}")

    print("\n=== ETH Technical Analysis ===")
    eth = analyze("ETH", "ethereum", days=30)
    if "error" not in eth:
        i = eth["indicators"]
        print(f"Price:     ${eth['current_price']:,.2f}")
        print(f"Trend:     {eth['trend']}")
        print(f"RSI(14):   {i['rsi_14']}")
        print(f"MACD hist: {i['macd']['histogram']}")
        print(f"Conviction:{eth['conviction_score']}/100")
        print(f"Rec:       {eth['recommendation']}")

    print("\n✅ TA Engine working")
