"""
Kraken CLI Integration — Phase 5.1b
Wraps the krakenfx/kraken-cli binary as a drop-in replacement for our CCXT exchange client.
Supports BOTH paper trading (no API key needed) and live trading (API key required).

Usage:
  python -m skills.execution_engine.kraken_cli          # CLI test
  from skills.execution_engine.kraken_cli import KrakenCLI
  client = KrakenCLI(mode="paper")  # paper (default)
  client = KrakenCLI(mode="live")   # live — needs KRAKEN_API_KEY + KRAKEN_API_SECRET
"""

import json
import os
import subprocess
from typing import Optional


KRAKEN_CLI = os.path.expanduser("~/.cargo/bin/kraken")


def _run(args: list, timeout: int = 15) -> dict:
    """Run kraken CLI with JSON output, return parsed dict."""
    env = os.environ.copy()
    env["PATH"] = os.path.expanduser("~/.cargo/bin") + ":" + env.get("PATH", "")

    try:
        result = subprocess.run(
            [KRAKEN_CLI, "--output", "json"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip() or result.stdout.strip()}
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"raw": result.stdout}
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out"}
    except FileNotFoundError:
        return {"error": f"kraken CLI not found at {KRAKEN_CLI}"}


class KrakenCLI:
    """
    Unified interface to krakenfx/kraken-cli binary.
    mode: "paper" (default) or "live"
    """

    def __init__(self, mode: str = "paper"):
        self.mode  = mode.lower()
        self.label = "🟡 PAPER" if self.mode == "paper" else "🔴 LIVE"

        check = _run(["status"])
        if "error" in check:
            raise RuntimeError(f"kraken CLI check failed: {check['error']}")

        if self.mode == "paper":
            _run(["paper", "init"])

    # ─── Market Data ─────────────────────────────────────────────────────────

    def get_ticker(self, symbol: str) -> dict:
        """
        Get ticker for symbol. Symbol format: "BTCUSD" or "BTC/USD".
        Returns {ask, bid, last, high, low, base_volume, quote_volume}.
        """
        pair = self._normalize_pair(symbol)
        out  = _run(["ticker", pair])

        # Kraken returns {"XXBTZUSD": {"a": [...], "b": [...], ...}}
        raw = out.get(pair) or out.get("data", {})
        if not isinstance(raw, dict):
            return {}

        def _f(v, idx=0):
            try:
                val = v[idx] if isinstance(v, (list, tuple)) else v
                return float(val) if val not in (None, "") else 0.0
            except Exception:
                return 0.0

        return {
            "ask":          _f(raw.get("a", [[0]]), 0),
            "bid":          _f(raw.get("b", [[0]]), 0),
            "last":         _f(raw.get("c", [0, ""]), 0),
            "high":         _f(raw.get("h", [0, ""]), 1),
            "low":          _f(raw.get("l", [0, ""]), 1),
            "base_volume":  _f(raw.get("v", [0, 0]), 0),
            "quote_volume": _f(raw.get("v", [0, 0]), 1),
            "raw":          raw,
        }

    def get_order_book(self, symbol: str, depth: int = 10) -> dict:
        """Get order book bids/asks."""
        pair = self._normalize_pair(symbol)
        out  = _run(["orderbook", pair, "--depth", str(depth)])
        data = out.get("data", {})
        bids = [[float(b["price"]), float(b["volume"])] for b in data.get("bids", [])]
        asks = [[float(a["price"]), float(a["volume"])] for a in data.get("asks", [])]
        return {"bids": bids, "asks": asks}

    def get_ohlc(self, symbol: str, interval: int = 60) -> list:
        """
        Get OHLC data.
        interval: 1=1m, 5=5m, 15=15m, 60=1h (default), 240=4h, 1440=1d
        Returns: list of [timestamp_ms, open, high, low, close, volume]
        """
        pair     = self._normalize_pair(symbol)
        ival     = {"1": "1", "5": "5", "15": "15", "60": "60", "240": "240", "1440": "1440"}.get(str(interval), "60")
        out      = _run(["ohlc", pair, "--interval", ival])
        raw_list = out.get("data", [])
        if isinstance(raw_list, dict):
            raw_list = [raw_list]
        return [
            [int(float(c["time"]) * 1000) if "time" in c else 0,
             float(c["open"]), float(c["high"]),
             float(c["low"]), float(c["close"]), float(c["volume"])]
            for c in raw_list
        ]

    # ─── Account ─────────────────────────────────────────────────────────────

    def get_balance(self, asset: str = "USD") -> dict:
        """Get balance for asset. Returns {free, used}."""
        out  = _run(["balance"])
        data = out.get("data", [])
        if isinstance(data, dict):
            val = data.get(asset.upper(), data.get(self._normalize_asset(asset), "0"))
            return {"free": str(val), "used": "0"}
        for row in data:
            asset_key = row.get("Asset") or row.get("asset") or ""
            if asset.upper() in asset_key or self._normalize_asset(asset) in asset_key:
                return {"free": str(row.get("Balance", row.get("available", "0"))), "used": "0"}
        return {"free": "0", "used": "0"}

    def get_balances(self) -> dict:
        """Get all balances as {asset: balance_str}."""
        out  = _run(["balance"])
        data = out.get("data", [])
        if isinstance(data, dict):
            return {k: str(v) for k, v in data.items()}
        return {row.get("Asset", row.get("asset", "")): str(row.get("Balance", "0"))
                for row in data if isinstance(row, dict)}

    def is_authenticated(self) -> bool:
        """Live mode needs API key in env vars."""
        if self.mode == "paper":
            return True
        return bool(os.environ.get("KRAKEN_API_KEY") and os.environ.get("KRAKEN_API_SECRET"))

    # ─── Trading ─────────────────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> dict:
        """
        Place a paper or live order.
        Returns: {order_id, status, filled_amount, avg_price, cost, fee}
        """
        pair = self._normalize_pair(symbol)
        vol  = str(amount)

        cmd = (["paper"] if self.mode == "paper" else []) + [side.lower(), pair, vol]
        if order_type == "limit" and price:
            cmd += ["--price", str(price)]

        out = _run(cmd + ["--yes"])

        # Parse the JSON response
        raw = out.get("data", out) if isinstance(out, dict) else out
        if isinstance(raw, dict) and not raw.get("error"):
            return {
                "order_id":       raw.get("order_id", f"KRAKEN-{pair}"),
                "trade_id":       raw.get("trade_id", ""),
                "status":         "FILLED" if raw.get("action") == "market_order_filled" else raw.get("action", ""),
                "side":           raw.get("side", side.lower()),
                "filled_amount":  float(raw.get("volume", 0) or 0),
                "avg_price":      float(raw.get("price", 0) or 0),
                "cost":           float(raw.get("cost", 0) or 0),
                "fee":            float(raw.get("fee", 0) or 0),
            }
        return {"status": "error", "reason": str(raw)}

    def cancel_order(self, order_id: str, symbol: str = None) -> dict:
        """Cancel an open order."""
        cmd = (["paper", "cancel", order_id] if self.mode == "paper"
               else ["order", "cancel", order_id])
        out = _run(cmd)
        return {"ok": "error" not in out}

    def get_open_orders(self, symbol: str = None) -> list:
        """Get open orders."""
        cmd = ["paper", "orders"] if self.mode == "paper" else ["open-orders"]
        out = _run(cmd)
        data = out.get("data", [])
        return data if isinstance(data, list) else []

    # ─── Paper Trading ───────────────────────────────────────────────────────

    def paper_status(self) -> dict:
        """Paper account status."""
        out = _run(["paper", "status"])
        d   = out.get("data", out)
        if isinstance(d, dict):
            return {
                "starting_balance": d.get("starting_balance", 10000),
                "current_value":    d.get("current_value", 10000),
                "unrealized_pnl":   d.get("unrealized_pnl", 0),
                "unrealized_pnl_pct": d.get("unrealized_pnl_pct", 0),
                "total_trades":     d.get("total_trades", 0),
                "open_orders":      d.get("open_orders", 0),
                "fee_rate":         d.get("fee_rate", 0.0026),
            }
        return d

    def paper_history(self, limit: int = 50) -> list:
        """Paper trade history (limit param accepted but Kraken CLI doesn't support it)."""
        out  = _run(["paper", "history"])
        data = out.get("trades", [])
        if isinstance(data, list) and limit < len(data):
            data = data[:limit]
        return data if isinstance(data, list) else []

    def paper_reset(self, balance: float = 10_000) -> dict:
        """Reset paper account to given balance (default $10k)."""
        out = _run(["paper", "reset", "--balance", str(balance)])
        return {"ok": "error" not in out, "data": out.get("data", out)}

    # ─── Fee Estimation ─────────────────────────────────────────────────────

    def get_fee_estimate(self, symbol: str, side: str, amount: float, price: float) -> dict:
        """Estimate fees for a trade. Kraken standard taker fee 0.26%."""
        cost     = amount * price
        fee_rate = 0.0026
        return {
            "estimated_fee": round(cost * fee_rate, 4),
            "fee_rate":      fee_rate,
            "cost":          round(cost, 4),
        }

    # ─── Helpers ───────────────────────────────────────────────────────────

    def _normalize_pair(self, symbol: str) -> str:
        """BTC/USD → XXBTZUSD, BTCUSD → XXBTZUSD"""
        s = symbol.replace("/", "").upper()
        mapping = {
            "BTCUSD": "XXBTZUSD", "ETHUSD": "XETHZUSD", "SOLUSD": "SOLUSD",
            "XRPUSD": "XRPUSD", "DOGEUSD": "XDGUSD", "ADAUSD": "ADAUSD",
            "DOTUSD": "DOTUSD", "AVAXUSD": "AVAXUSD", "LINKUSD": "LINKUSD",
        }
        return mapping.get(s, s)

    def _normalize_asset(self, asset: str) -> str:
        mapping = {"BTC": "XXBT", "ETH": "XETH", "USD": "ZUSD",
                  "USDT": "USDT", "SOL": "SOL", "DOGE": "XDG"}
        return mapping.get(asset.upper(), asset.upper())

    def status(self) -> dict:
        s = _run(["status"])
        return {
            "mode":          self.mode.upper(),
            "authenticated": self.is_authenticated(),
            "kraken_status": s.get("data", s),
        }

    def __repr__(self):
        return f"<KrakenCLI mode={self.mode}>"


if __name__ == "__main__":
    import sys
    mode = "live" if "--live" in sys.argv else "paper"
    print(f"=== Kraken CLI [{mode.upper()}] ===\n")

    client = KrakenCLI(mode=mode)
    print(f"Mode:          {client.mode.upper()}")
    print(f"Authenticated: {client.is_authenticated()}")

    ticker = client.get_ticker("BTCUSD")
    if ticker:
        print(f"\nBTC/USD: last=${ticker['last']:,.1f}  bid=${ticker['bid']:,.1f}  ask=${ticker['ask']:,.1f}")
        print(f"24h high=${ticker['high']:,.1f}  low=${ticker['low']:,.1f}  vol={ticker['base_volume']:,.2f} BTC")

    if mode == "paper":
        ps = client.paper_status()
        print(f"\nPaper Account:")
        print(f"  Balance:    ${ps.get('current_value', 0):,.2f}")
        print(f"  P&L:        ${ps.get('unrealized_pnl', 0):,.2f} ({ps.get('unrealized_pnl_pct', 0)*100:+.2f}%)")
        print(f"  Total Trades: {ps.get('total_trades', 0)}")
    else:
        bal = client.get_balance("USD")
        print(f"\nLive USD balance: {bal.get('free', 'N/A')}")

    print(f"\n✅ KrakenCLI [{mode}] ready")