"""
Exchange Client — Phase 5, Task 5.1
Unified exchange interface using CCXT.
Supports: Binance, Coinbase, Kraken, OKX, and 100+ exchanges.

Modes:
  - sandbox=True  → testnet/sandbox (default)
  - sandbox=False → live trading

Usage:
  from skills.execution_engine.exchange_client import ExchangeClient
  client = ExchangeClient("binance", sandbox=True)
  client.get_balance()
  client.place_order("BTC/USDT", "BUY", 0.01, "limit", 75000)
"""

import os
import time
import ccxt
from typing import Optional
from datetime import datetime, timezone


# ─── .env Loader ──────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    v = os.environ.get(key, os.environ.get(key.replace(".", "_").upper(), default))
    # Also check .env file in project root
    if not v:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            for line in open(env_path):
                k, _, val = line.strip().partition("=")
                if k == key:
                    v = val.strip().strip('"').strip("'")
    return v or default


# ─── Exchange Configuration ────────────────────────────────────────────────────

EXCHANGE_CONFIGS = {
    "binance": {
        "class": ccxt.binance,
        "keys": ["BINANCE_API_KEY", "BINANCE_SECRET_KEY"],
        "sandbox_param": "testnet",
        "futures": True,
        "ccxt_id": "binance",
    },
    "coinbase": {
        "class": ccxt.coinbase,
        "keys": ["COINBASE_API_KEY", "COINBASE_SECRET_KEY"],
        "sandbox_param": "sandbox",
        "futures": False,
        "ccxt_id": "coinbase",
    },
    "kraken": {
        "class": ccxt.kraken,
        "keys": ["KRAKEN_API_KEY", "KRAKEN_SECRET_KEY"],
        "sandbox_param": None,  # Kraken uses separate testnet host
        "futures": False,
        "ccxt_id": "kraken",
    },
    "okx": {
        "class": ccxt.okx,
        "keys": ["OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE"],
        "sandbox_param": "testnet",
        "futures": True,
        "ccxt_id": "okx",
    },
}


# ─── Core Client ───────────────────────────────────────────────────────────────

class ExchangeClient:
    """
    Unified interface for exchange operations via CCXT.
    Handles: authentication, sandbox/live mode, rate limiting, order management.
    """

    def __init__(
        self,
        exchange_id: str = "binance",
        sandbox: bool = True,
        api_key: str = None,
        api_secret: str = None,
        passphrase: str = None,
    ):
        if exchange_id not in EXCHANGE_CONFIGS:
            raise ValueError(
                f"Unknown exchange: {exchange_id}. "
                f"Supported: {list(EXCHANGE_CONFIGS.keys())}"
            )

        cfg = EXCHANGE_CONFIGS[exchange_id]

        # Load credentials from .env if not provided
        if api_key is None:
            api_key = _env(cfg["keys"][0])
        if api_secret is None:
            api_secret = _env(cfg["keys"][1])
        if passphrase is None and len(cfg["keys"]) > 2:
            passphrase = _env(cfg["keys"][2])

        self.exchange_id = exchange_id
        self.sandbox     = sandbox
        self.cfg         = cfg
        self._api_key    = api_key
        self._api_secret = api_secret
        self._passphrase = passphrase

        # Build CCXT exchange instance
        exchange_class = cfg["class"]
        params = {"enableRateLimit": True}

        if sandbox and cfg.get("sandbox_param"):
            params[cfg["sandbox_param"]] = True

        if api_key and api_secret:
            self.exchange = exchange_class({
                "apiKey": api_key,
                "secret": api_secret,
                **(({"password": passphrase} if passphrase else {})),
                **params,
            })
            self._authenticated = True
        else:
            self.exchange = exchange_class(params)
            self._authenticated = False

        # Sandboxing overrides
        if sandbox and exchange_id == "binance":
            self.exchange.set_sandbox_mode(True)

        # Rate limit state
        self._rate_limit_calls  = 0
        self._rate_limit_start  = time.time()
        self.RATE_LIMIT_WINDOW   = 60    # seconds
        self.RATE_LIMIT_MAX     = 120   # calls per window

    # ─── Auth Check ─────────────────────────────────────────────────────────

    def is_authenticated(self) -> bool:
        return self._authenticated

    def require_auth(self):
        if not self._authenticated:
            raise PermissionError(
                f"{self.exchange_id}: No API credentials loaded. "
                f"Set {self.cfg['keys'][0]} and {self.cfg['keys'][1]} in .env"
            )

    # ─── Rate Limiting ─────────────────────────────────────────────────────

    def _check_rate_limit(self):
        """Exponential backoff if rate limited."""
        now = time.time()
        if now - self._rate_limit_start > self.RATE_LIMIT_WINDOW:
            self._rate_limit_calls = 0
            self._rate_limit_start = now

        self._rate_limit_calls += 1
        if self._rate_limit_calls > self.RATE_LIMIT_MAX:
            sleep_time = self.RATE_LIMIT_WINDOW - (now - self._rate_limit_start)
            if sleep_time > 0:
                time.sleep(sleep_time)
            self._rate_limit_calls = 0
            self._rate_limit_start = now

    def _call(self, method, *args, max_retries=3, **kwargs):
        """Call a CCXT method with rate limiting and exponential backoff."""
        for attempt in range(max_retries):
            try:
                self._check_rate_limit()
                return method(*args, **kwargs)
            except ccxt.RateLimitExceeded as e:
                wait = 2 ** attempt
                time.sleep(wait)
                continue
            except ccxt.NetworkError as e:
                wait = 2 ** attempt
                time.sleep(wait)
                continue
            except Exception:
                raise
        raise RuntimeError(f"{method.__name__} failed after {max_retries} retries")

    # ─── Market Data ────────────────────────────────────────────────────────

    def get_ticker(self, symbol: str) -> dict:
        """Get current ticker for a symbol. No auth required."""
        ticker = self._call(self.exchange.fetch_ticker, symbol)
        return {
            "symbol":       symbol,
            "bid":          ticker.get("bid"),
            "ask":          ticker.get("ask"),
            "last":         ticker.get("last"),
            "volume":       ticker.get("baseVolume"),
            "quote_volume": ticker.get("quoteVolume"),
            "change_pct":   ticker.get("change"),
            "timestamp":    ticker.get("timestamp"),
        }

    def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        """Get order book. No auth required."""
        ob = self._call(self.exchange.fetch_order_book, symbol, limit)
        return {
            "symbol": symbol,
            "bids":   ob.get("bids", []),
            "asks":   ob.get("asks", []),
            "timestamp": ob.get("timestamp"),
        }

    def get_fees(self, symbol: str = None) -> dict:
        """Get trading fees. No auth required."""
        markets = self.exchange.markets if symbol is None else {symbol: self.exchange.market(symbol)}
        fees = {}
        for sym, m in markets.items():
            fees[sym] = {
                "maker": m.get("maker", 0),
                "taker": m.get("taker", 0),
            }
        return fees

    # ─── Account Data ───────────────────────────────────────────────────────

    def get_balance(self, asset: str = None) -> dict:
        """Get account balance. Requires auth."""
        self.require_auth()
        bal = self._call(self.exchange.fetch_balance)
        if asset:
            return {
                "free":  bal["free"].get(asset, 0),
                "used":  bal["used"].get(asset, 0),
                "total": bal["total"].get(asset, 0),
            }
        return {
            "free":  {k: v for k, v in bal.get("free", {}).items() if v},
            "used":  {k: v for k, v in bal.get("used", {}).items() if v},
            "total": {k: v for k, v in bal.get("total", {}).items() if v},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_positions(self, symbol: str = None) -> list:
        """Get open positions (for margin/futures). Requires auth."""
        self.require_auth()
        try:
            positions = self._call(self.exchange.fetch_positions, symbol)
            return [
                {
                    "symbol":      p.get("symbol"),
                    "side":        p.get("side"),
                    "size":        p.get("contracts") or p.get("size", 0),
                    "entry_price": p.get("entryPrice"),
                    "pnl":         p.get("unrealizedPnl"),
                    "leverage":    p.get("leverage"),
                }
                for p in positions
                if p.get("contracts", 0) or p.get("size", 0)
            ]
        except Exception:
            return []

    # ─── Order Management ───────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,        # "BUY" or "SELL"
        amount: float,
        order_type: str = "market",  # "market", "limit"
        price: float = None,
        params: dict = None,
    ) -> dict:
        """
        Place an order. Returns order result from CCXT.

        For market orders: executes immediately at best available price.
        For limit orders: executes when price reaches the specified level.
        """
        self.require_auth()

        if order_type == "market":
            order = self._call(
                self.exchange.create_order,
                symbol, "market", side.lower(),
                amount, None, params or {}
            )
        elif order_type == "limit":
            if price is None:
                raise ValueError(f"Limit order requires a price for {symbol}")
            order = self._call(
                self.exchange.create_order,
                symbol, "limit", side.lower(),
                amount, price, params or {}
            )
        else:
            raise ValueError(f"Unsupported order type: {order_type}")

        return self._format_order(order)

    def cancel_order(self, order_id: str, symbol: str) -> dict:
        """Cancel an open order. Requires auth."""
        self.require_auth()
        try:
            result = self._call(self.exchange.cancel_order, order_id, symbol)
            return {"success": True, "order_id": order_id, "result": result}
        except Exception as e:
            return {"success": False, "order_id": order_id, "error": str(e)}

    def get_order_status(self, order_id: str, symbol: str) -> dict:
        """Get the current status of an order. Requires auth."""
        self.require_auth()
        try:
            order = self._call(self.exchange.fetch_order, order_id, symbol)
            return self._format_order(order)
        except Exception as e:
            return {"order_id": order_id, "error": str(e), "status": "UNKNOWN"}

    def get_open_orders(self, symbol: str = None) -> list:
        """Get all open orders. Requires auth."""
        self.require_auth()
        orders = self._call(self.exchange.fetch_open_orders, symbol)
        return [self._format_order(o) for o in orders]

    # ─── Order Formatting ───────────────────────────────────────────────────

    def _format_order(self, order: dict) -> dict:
        """Normalize CCXT order response."""
        return {
            "order_id":      order.get("id"),
            "symbol":        order.get("symbol"),
            "type":          order.get("type"),
            "side":          order.get("side"),
            "amount":        order.get("amount"),
            "filled":        order.get("filled", 0),
            "remaining":     order.get("remaining", 0),
            "price":         order.get("price"),
            "average":       order.get("average"),
            "cost":          order.get("cost"),
            "status":        order.get("status"),
            "fee":           order.get("fee"),
            "timestamp":     order.get("timestamp"),
            "datetime":      order.get("datetime"),
            "last_trade":    order.get("lastTradeTimestamp"),
        }

    # ─── Helpers ────────────────────────────────────────────────────────────

    def market_buy(self, symbol: str, amount: float, params: dict = None) -> dict:
        """Convenience: market buy."""
        return self.place_order(symbol, "BUY", amount, "market", params=params)

    def market_sell(self, symbol: str, amount: float, params: dict = None) -> dict:
        """Convenience: market sell."""
        return self.place_order(symbol, "SELL", amount, "market", params=params)

    def limit_buy(self, symbol: str, amount: float, price: float, params: dict = None) -> dict:
        """Convenience: limit buy."""
        return self.place_order(symbol, "BUY", amount, "limit", price, params=params)

    def limit_sell(self, symbol: str, amount: float, price: float, params: dict = None) -> dict:
        """Convenience: limit sell."""
        return self.place_order(symbol, "SELL", amount, "limit", price, params=params)

    def get_fee_estimate(self, symbol: str, side: str, amount: float, price: float = None) -> dict:
        """Estimate fees for a potential trade."""
        fee_rate = self.exchange.markets.get(symbol, {}).get("taker", 0.001)
        notional = amount * (price or self.get_ticker(symbol)["last"])
        fee = notional * fee_rate
        return {
            "symbol":      symbol,
            "side":        side,
            "amount":      amount,
            "price_used":  price,
            "notional":    notional,
            "fee_rate":    fee_rate,
            "estimated_fee": round(fee, 4),
        }

    # ─── Mode Info ──────────────────────────────────────────────────────────

    def mode_label(self) -> str:
        return "🔴 LIVE" if not self.sandbox else "🟡 SANDBOX"

    def __repr__(self):
        return f"ExchangeClient({self.exchange_id}, {self.mode_label()})"


# ─── Factory ─────────────────────────────────────────────────────────────────

def create_client(exchange: str = "binance", sandbox: bool = True) -> ExchangeClient:
    """Factory to create an exchange client."""
    return ExchangeClient(exchange, sandbox=sandbox)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, json

    exchange_id = sys.argv[1] if len(sys.argv) > 1 else "binance"
    sandbox     = "--live" not in sys.argv

    print(f"=== Exchange Client: {exchange_id.upper()} | "
          f"{'🔴 LIVE' if not sandbox else '🟡 SANDBOX'} ===\n")

    client = ExchangeClient(exchange_id, sandbox=sandbox)

    if client.is_authenticated():
        print(f"✅ Authenticated — {client.cfg['keys'][0]}")
    else:
        print(f"⚠️  Not authenticated — set API keys in .env to enable trading\n")

    # Show available symbols (public)
    try:
        markets = list(client.exchange.markets.keys())[:10]
        print(f"Markets (sample): {markets[:5]}")
    except Exception as e:
        print(f"Markets error: {e}")

    if client.is_authenticated():
        try:
            bal = client.get_balance()
            print(f"\nBalance (top assets):")
            for asset, v in list(bal["free"].items())[:5]:
                print(f"  {asset}: {v}")
        except Exception as e:
            print(f"Balance error: {e}")

    print(f"\n✅ ExchangeClient({exchange_id}, sandbox={sandbox}) initialized")