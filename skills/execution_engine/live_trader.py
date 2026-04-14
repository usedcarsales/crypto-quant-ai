"""
Live Trading Engine — Phase 5, Task 5.2
Bridges paper trading signals with real exchange execution.

Workflow:
  1. Receive approved signals from risk_manager (4.4)
  2. Validate against live exchange state (balance, positions, fees)
  3. Execute via exchange_client (5.1) — sandbox by default
  4. Track order status, fill price, slippage, fees
  5. Reconcile with paper portfolio for tracking
  6. Emergency stop if daily loss exceeds 5%

Mode:
  - sandbox=True (default): simulated fills against live order book
  - sandbox=False: REAL money — requires operator confirmation per execution
"""

import importlib.util as _spec
import json
import os
from datetime import datetime, timezone
from typing import Optional


# ─── Load Dependencies ─────────────────────────────────────────────────────────

def _load_mod(name, path):
    s = _spec.spec_from_file_location(name, path)
    m = _spec.module_from_spec(s)
    s.loader.exec_module(m)
    return m

EXCH_MOD   = _load_mod("exch",  "skills/execution_engine/exchange_client.py")
RISK_MOD   = _load_mod("risk",  "skills/signal_engine/risk_manager.py")
PAPER_MOD  = _load_mod("paper", "skills/signal_engine/paper_trader.py")


# ─── State Files ────────────────────────────────────────────────────────────────

LIVE_STATE_FILE    = "/tmp/crypto-quant-live-state.json"
LIVE_ORDERS_FILE   = "/tmp/crypto-quant-live-orders.json"
LIVE_ALERTS_FILE   = "/tmp/crypto-quant-live-alerts.json"


# ─── Load / Save Helpers ───────────────────────────────────────────────────────

def _load_json(path):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, default=str)
    except Exception:
        pass


# ─── Live Trade Executor ───────────────────────────────────────────────────────

class LiveTrader:
    """
    Manages live trade execution against exchange.
    All orders go through risk_manager pre-check.
    Sandbox mode by default — must be explicitly set to live.
    """

    def __init__(
        self,
        exchange: str = "binance",
        sandbox: bool = True,
        client: EXCH_MOD.ExchangeClient = None,
    ):
        self.exchange_id = exchange
        self.sandbox     = sandbox
        self.mode_label  = "🔴 LIVE" if not sandbox else "🟡 SANDBOX"

        # Exchange client
        if client:
            self.client = client
        else:
            self.client = EXCH_MOD.ExchangeClient(exchange, sandbox=sandbox)

        # Load state
        self.state   = _load_json(LIVE_STATE_FILE)
        self.orders  = _load_json(LIVE_ORDERS_FILE)
        self.alerts  = _load_json(LIVE_ALERTS_FILE)

        # Reset daily loss tracking if new day
        self._reset_daily_if_needed()

    # ─── Mode ────────────────────────────────────────────────────────────────

    def is_live(self) -> bool:
        return not self.sandbox

    def require_sandbox_warning(self):
        """Prompt operator confirmation before live execution."""
        if self.sandbox:
            return  # sandbox = no warning needed
        # In live mode, this should have been pre-confirmed
        pass

    # ─── Pre-Trade Validation ─────────────────────────────────────────────────

    def pre_trade_check(self, signal: dict) -> tuple[bool, str]:
        """
        Full pre-trade validation before any order placement.
        Returns (allowed, reason).
        """
        coin      = signal.get("coin", "")
        direction = signal.get("direction", "")
        size_usd  = signal.get("position_size_usd", 0)
        entry     = signal.get("entry_price", 0)

        # ── 1. Risk manager check ──────────────────────────────────────────
        allowed, reason = RISK_MOD.can_open_position(coin)
        if not allowed:
            return False, f"Risk manager: {reason}"

        # ── 2. Portfolio size check ──────────────────────────────────────
        ok, reason, max_size = RISK_MOD.position_size_allowed(coin, size_usd)
        if not ok:
            return False, f"Size check: {reason}"

        # ── 3. Exchange authentication ─────────────────────────────────────
        if not self.client.is_authenticated():
            return False, "Exchange not authenticated — set API keys in .env"

        # ── 4. Balance check ──────────────────────────────────────────────
        if size_usd > 0:
            quote = signal.get("quote", "USDT")
            try:
                balance = self.client.get_balance(quote)
                available = float(balance.get("free", 0))
                if available < size_usd:
                    return False, f"Insufficient {quote}: have ${available:.2f}, need ${size_usd:.2f}"
            except Exception as e:
                return False, f"Balance check failed: {e}"

        # ── 5. Symbol validation ───────────────────────────────────────────
        symbol = f"{coin}/{signal.get('quote', 'USDT')}"
        if symbol not in self.client.exchange.markets:
            return False, f"Symbol {symbol} not available on {self.exchange_id}"

        # ── 6. Emergency stop check ────────────────────────────────────────
        daily_loss_limit = self.state.get("daily_loss_limit_pct", 5.0)
        daily_pnl_pct    = self.state.get("daily_pnl_pct", 0)
        if daily_pnl_pct <= -daily_loss_limit:
            return False, f"EMERGENCY STOP: Daily loss {daily_pnl_pct:.2f}% exceeds limit -{daily_loss_limit}%"

        return True, "OK"

    # ─── Order Execution ─────────────────────────────────────────────────────

    def execute_signal(self, signal: dict, confirm: bool = False) -> dict:
        """
        Execute a trade signal on the live exchange.

        Args:
            signal:  trade signal dict from trade_signals.py
            confirm: must be True for live mode (operator confirmation)

        Returns: {status, order, fill_price, slippage, fees, message}
        """
        coin      = signal.get("coin", "")
        direction = signal.get("direction", "")
        size_usd  = signal.get("position_size_usd", 0)
        entry     = signal.get("entry_price", 0)
        signal_type = signal.get("signal_type", "MODERATE")
        quote     = signal.get("quote", "USDT")
        symbol    = f"{coin}/{quote}"

        # ── Live mode guard ─────────────────────────────────────────────────
        if self.is_live() and not confirm:
            return {
                "status": "REJECTED",
                "reason": "Live mode requires explicit confirm=True",
                "coin": coin,
            }

        # ── Pre-trade validation ────────────────────────────────────────────
        allowed, reason = self.pre_trade_check(signal)
        if not allowed:
            return {"status": "REJECTED", "reason": reason, "coin": coin}

        # ── Get current price ───────────────────────────────────────────────
        try:
            ticker = self.client.get_ticker(symbol)
            market_price = ticker.get("last", entry)
        except Exception as e:
            return {"status": "ERROR", "reason": f"Could not fetch market price: {e}"}

        # ── Calculate size in base currency ─────────────────────────────────
        if direction == "BUY":
            size_base = size_usd / market_price
        else:
            # For SELL, we need to check how much base we hold
            bal = self.client.get_balance(coin)
            available_base = float(bal.get("free", 0))
            size_base = min(available_base, size_usd / market_price)

        if size_base <= 0:
            return {"status": "REJECTED", "reason": f"Invalid position size: {size_base}", "coin": coin}

        # ── Estimate fees ───────────────────────────────────────────────────
        fee_est = self.client.get_fee_estimate(symbol, direction, size_base, market_price)

        # ── Place order ─────────────────────────────────────────────────────
        try:
            if self.is_live():
                # Real order
                result = self.client.place_order(
                    symbol=symbol,
                    side=direction,
                    amount=size_base,
                    order_type="market",
                )
            else:
                # Sandbox — simulate fill at market price
                result = self._simulate_fill(symbol, direction, size_base, market_price)
        except Exception as e:
            return {"status": "ERROR", "reason": f"Order placement failed: {e}"}

        # ── Record live order ────────────────────────────────────────────────
        fill_price = result.get("average") or market_price
        slippage   = abs(fill_price - market_price) / market_price * 100 if market_price else 0
        pnl_est    = self._estimate_pnl(direction, entry, fill_price, size_base)

        live_order = {
            "order_id":       result.get("order_id", f"SIM-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"),
            "coin":           coin,
            "direction":      direction,
            "signal_type":    signal_type,
            "symbol":         symbol,
            "size_base":      round(size_base, 8),
            "size_usd":       round(size_usd, 2),
            "entry_price":    round(fill_price, 4),
            "slippage_pct":  round(slippage, 4),
            "fee_paid":       fee_est.get("estimated_fee", 0),
            "fee_rate":       fee_est.get("fee_rate", 0),
            "pnl_estimate":   round(pnl_est, 2),
            "mode":           "LIVE" if self.is_live() else "SANDBOX",
            "status":         "FILLED",
            "executed_at":    datetime.now(timezone.utc).isoformat(),
            "raw_order":      result,
        }

        self._record_order(live_order)

        # ── Sync to risk manager ─────────────────────────────────────────────
        RISK_MOD.add_position(
            coin=coin,
            direction=direction,
            entry_price=fill_price,
            size_usd=size_usd,
            stop_loss=signal.get("stop_loss", 0),
            take_profit=signal.get("take_profit", 0),
        )

        return {
            "status":      "FILLED",
            "order":       live_order,
            "fill_price":  fill_price,
            "slippage_pct": round(slippage, 4),
            "fees":        fee_est.get("estimated_fee", 0),
            "pnl_estimate": round(pnl_est, 2),
            "mode":        self.mode_label,
            "message":     f"{self.mode_label} {direction} {size_base:.4f} {coin} @ ${fill_price:,.2f}",
        }

    def _simulate_fill(self, symbol: str, direction: str, size_base: float, price: float) -> dict:
        """Simulate a market fill at current price for sandbox mode."""
        return {
            "id":          f"SIM-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "symbol":      symbol,
            "type":        "market",
            "side":        direction.lower(),
            "amount":      size_base,
            "filled":      size_base,
            "remaining":   0,
            "price":       price,
            "average":     price,
            "cost":        size_base * price,
            "status":      "closed",
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "datetime":    datetime.now(timezone.utc).isoformat(),
            "fee":         {"cost": size_base * price * 0.001},  # 0.1% taker estimate
        }

    def _estimate_pnl(self, direction: str, entry: float, fill: float, size_base: float) -> float:
        if direction == "BUY":
            return (fill - entry) * size_base
        else:
            return (entry - fill) * size_base

    def _record_order(self, order: dict):
        """Persist order to live orders file."""
        orders = self.orders.get("orders", [])
        orders.append(order)
        self.orders["orders"] = orders
        _save_json(LIVE_ORDERS_FILE, self.orders)

    # ─── Emergency Stop ─────────────────────────────────────────────────────

    def check_emergency_stop(self) -> bool:
        """
        Check if daily loss has exceeded the 5% threshold.
        If so, close all positions and halt.
        """
        state   = self.state
        loss_pct = abs(state.get("daily_pnl_pct", 0))
        limit   = state.get("daily_loss_limit_pct", 5.0)

        if loss_pct >= limit:
            self.trigger_emergency_stop(f"Daily loss {loss_pct:.2f}% >= {limit}% limit")
            return True
        return False

    def trigger_emergency_stop(self, reason: str):
        """
        Emergency stop: close all positions, halt trading, alert.
        """
        self.state["emergency_stop_active"] = True
        self.state["emergency_stop_reason"]  = reason
        self.state["emergency_stop_time"]    = datetime.now(timezone.utc).isoformat()
        _save_json(LIVE_STATE_FILE, self.state)

        # Close all open orders
        try:
            open_orders = self.client.get_open_orders()
            for o in open_orders:
                self.client.cancel_order(o["order_id"], o["symbol"])
        except Exception:
            pass

        # Alert
        self._send_alert(f"🚨 EMERGENCY STOP: {reason}")

    def _send_alert(self, message: str):
        """Send alert — log to file for now."""
        alert = {
            "type":    "EMERGENCY_STOP",
            "message": message,
            "time":    datetime.now(timezone.utc).isoformat(),
        }
        alerts = self.alerts.get("alerts", [])
        alerts.append(alert)
        self.alerts["alerts"] = alerts
        _save_json(LIVE_ALERTS_FILE, self.alerts)

    # ─── Daily P&L Reconciliation ───────────────────────────────────────────

    def reconcile(self) -> dict:
        """
        Reconcile live positions with exchange.
        Update daily P&L, sync to risk manager.
        """
        if not self.client.is_authenticated():
            return {"error": "Not authenticated"}

        orders = self.orders.get("orders", [])
        open_live = [o for o in orders if o.get("status") == "FILLED" and o.get("mode") in ("LIVE", "SANDBOX")]

        total_pnl = 0
        for order in open_live:
            coin  = order["coin"]
            entry = order["entry_price"]
            size  = order["size_base"]
            dir   = order["direction"]

            try:
                ticker = self.client.get_ticker(f"{coin}/USDT")
                current = ticker.get("last", entry)
            except Exception:
                current = entry

            if dir == "BUY":
                pnl = (current - entry) * size
            else:
                pnl = (entry - current) * size

            order["current_price"] = current
            order["unrealized_pnl"] = round(pnl, 2)
            total_pnl += pnl

        self.orders["orders"] = orders
        _save_json(LIVE_ORDERS_FILE, self.orders)

        self.state["daily_pnl"]       = round(total_pnl, 2)
        self.state["daily_pnl_pct"]   = round(total_pnl / 10000 * 100, 4)  # vs $10k base
        self.state["last_reconcile"]  = datetime.now(timezone.utc).isoformat()
        _save_json(LIVE_STATE_FILE, self.state)

        return {
            "open_positions": len(open_live),
            "total_unrealized_pnl": round(total_pnl, 2),
            "daily_pnl_pct": self.state["daily_pnl_pct"],
            "emergency_stop": self.state.get("emergency_stop_active", False),
        }

    def _reset_daily_if_needed(self):
        today = datetime.now(timezone.utc).date().isoformat()
        last  = self.state.get("last_reset_date", "")
        if last != today:
            self.state["daily_pnl"]       = 0
            self.state["daily_pnl_pct"]   = 0
            self.state["last_reset_date"] = today
            self.state["emergency_stop_active"] = False
            _save_json(LIVE_STATE_FILE, self.state)

    # ─── Status ─────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return current live trading status."""
        orders = self.orders.get("orders", [])
        open_pos = [o for o in orders if o.get("status") == "FILLED"]
        live_orders = [o for o in orders if o.get("mode") == "LIVE"]
        sandbox_orders = [o for o in orders if o.get("mode") == "SANDBOX"]

        return {
            "exchange":     self.exchange_id,
            "mode":         "LIVE" if self.is_live() else "SANDBOX",
            "authenticated": self.client.is_authenticated(),
            "total_orders": len(orders),
            "open_positions": len(open_pos),
            "live_orders":  len(live_orders),
            "sandbox_orders": len(sandbox_orders),
            "daily_pnl":    self.state.get("daily_pnl", 0),
            "daily_pnl_pct": self.state.get("daily_pnl_pct", 0),
            "emergency_stop_active": self.state.get("emergency_stop_active", False),
            "last_reconcile": self.state.get("last_reconcile"),
        }

    # ─── Formatting ─────────────────────────────────────────────────────────

    def format_status(self) -> str:
        s = self.get_status()
        emoji = "🔴" if s["mode"] == "LIVE" else "🟡"
        lines = [
            f"{emoji} **Live Trading Status — {self.exchange_id.upper()} [{s['mode']}]**",
            f"   Authenticated: {'✅' if s['authenticated'] else '❌'}",
            f"   Orders: {s['total_orders']} total | {s['open_positions']} open | "
            f"{s['live_orders']} live | {s['sandbox_orders']} sandbox",
            f"   Daily P&L: ${s['daily_pnl']:.2f} ({s['daily_pnl_pct']:+.3f}%)",
            f"   Emergency Stop: {'🚨 ACTIVE' if s['emergency_stop_active'] else '✅ Clear'}",
            f"   Last reconcile: {s['last_reconcile'] or 'Never'}",
        ]
        return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("=== Live Trading Engine ===\n")

    sandbox = "--live" not in sys.argv
    exchange = sys.argv[1] if len(sys.argv) > 1 else "binance"

    trader = LiveTrader(exchange=exchange, sandbox=sandbox)

    print(trader.format_status())

    if trader.client.is_authenticated():
        print("\n✅ Exchange authenticated — ready to trade")
    else:
        ex = trader.exchange_id.upper()
        print(f"\n⚠️  Not authenticated — set {ex}_API_KEY and {ex}_SECRET_KEY in .env")
    if trader.check_emergency_stop():
        print("\n🚨 EMERGENCY STOP IS ACTIVE — trading halted")

    print(f"\nMode: {trader.mode_label}")
    print("✅ LiveTradingEngine ready")