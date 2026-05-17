"""
Paper Trader — simulated position management.
- Reads/writes portfolio.json
- Opens/closes positions based on signals
- Applies stop-loss and take-profit rules
- Tracks P&L, win rate, drawdown
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from datetime import datetime, timezone
from enum import Enum

PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "../../data/portfolio.json")

class PositionStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"

@dataclass
class Position:
    symbol: str
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    size: float     # position value in USD
    quantity: float # coin amount
    stop_loss: float
    take_profit: float
    opened_at: str
    status: str = "open"
    exit_price: Optional[float] = None
    closed_at: Optional[str] = None
    close_reason: Optional[str] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

class PaperTrader:
    def __init__(self, portfolio_path: str = PORTFOLIO_PATH):
        self.portfolio_path = portfolio_path
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.portfolio_path):
            with open(self.portfolio_path) as f:
                return json.load(f)
        return {
            "cash": 10000.0,
            "value": 10000.0,
            "positions": [],
            "history": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

    def _save(self):
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        # Recalculate total value
        total = self.data["cash"]
        for pos in self.data.get("positions", []):
            if pos.get("status") == "open":
                # We don't know current price here; will be updated in check_cycle
                total += pos.get("size", 0)  # approximate
        self.data["value"] = round(total, 2)
        with open(self.portfolio_path, "w") as f:
            json.dump(self.data, f, indent=2)

    def open_position(self, symbol: str, direction: str, price: float, size_pct: float = 0.33,
                      sl_pct: float = 0.02, tp_pct: float = 0.04) -> Optional[Position]:
        """Open a new position. Returns None if insufficient funds or max positions reached."""
        max_positions = 3
        open_pos = [p for p in self.data.get("positions", []) if p.get("status") == "open"]
        if len(open_pos) >= max_positions:
            return None

        # SHORT positions also require cash margin (no leverage yet)
        cash = self.data.get("cash", 0)
        size = cash * size_pct
        if size < 10:  # minimum $10 trade
            return None

        quantity = size / price
        sl = price * (1 - sl_pct) if direction == "LONG" else price * (1 + sl_pct)
        tp = price * (1 + tp_pct) if direction == "LONG" else price * (1 - tp_pct)

        now = datetime.now(timezone.utc).isoformat()
        pos = Position(
            symbol=symbol,
            direction=direction,
            entry_price=price,
            size=round(size, 2),
            quantity=round(quantity, 6),
            stop_loss=round(sl, 2),
            take_profit=round(tp, 2),
            opened_at=now
        )

        self.data["cash"] = round(cash - size, 2)
        self.data["positions"].append(pos.to_dict())
        self._save()
        return pos

    def check_cycle(self, prices: Dict[str, float]) -> Dict:
        """Run one trading cycle: check SL/TP, update unrealized P&L."""
        closed = []
        open_positions = []
        total_value = self.data.get("cash", 0)

        for pos in self.data.get("positions", []):
            if pos.get("status") != "open":
                continue

            symbol = pos.get("symbol", "").lower()
            current = prices.get(symbol)
            if current is None:
                open_positions.append(pos)
                continue

            entry = pos.get("entry_price", 0)
            size = pos.get("size", 0)
            direction = pos.get("direction", "LONG")
            sl = pos.get("stop_loss", 0)
            tp = pos.get("take_profit", 0)

            # Check stop loss / take profit
            reason = None
            if direction == "LONG":
                if current <= sl:
                    reason = "STOP_LOSS"
                elif current >= tp:
                    reason = "TAKE_PROFIT"
            elif direction == "SHORT":
                if current >= sl:
                    reason = "STOP_LOSS"
                elif current <= tp:
                    reason = "TAKE_PROFIT"

            if reason:
                # LONG: (current - entry) * qty
                # SHORT: (entry - current) * qty (profit when price drops)
                if direction == "LONG":
                    pnl = (current - entry) * pos.get("quantity", 0)
                else:  # SHORT
                    pnl = (entry - current) * pos.get("quantity", 0)
                pnl_pct = ((current / entry) - 1) * 100 if entry else 0
                if direction == "SHORT":
                    pnl_pct = -pnl_pct  # Invert for SHORT
                pos["status"] = "closed"
                pos["exit_price"] = round(current, 2)
                pos["closed_at"] = datetime.now(timezone.utc).isoformat()
                pos["close_reason"] = reason
                pos["pnl"] = round(pnl, 2)
                pos["pnl_pct"] = round(pnl_pct, 2)
                # For SHORT: cash = cash + size + pnl (same as LONG since PnL already signed correctly)
                self.data["cash"] = round(self.data.get("cash", 0) + size + pnl, 2)
                self.data["history"].append(pos)
                closed.append(pos)
            else:
                unrealized = (current - entry) * pos.get("quantity", 0)
                total_value += size + unrealized
                open_positions.append(pos)

        # Update only open positions list
        all_positions = [p for p in self.data.get("positions", []) if p.get("status") != "open"] + open_positions
        self.data["positions"] = all_positions
        self.data["value"] = round(total_value, 2)
        self._save()
        return {"closed": closed, "open_count": len(open_positions)}

    def get_stats(self) -> dict:
        """Return portfolio statistics."""
        history = self.data.get("history", [])
        total_pnl = sum(h.get("pnl", 0) for h in history)
        wins = sum(1 for h in history if h.get("pnl", 0) > 0)
        losses = sum(1 for h in history if h.get("pnl", 0) <= 0)
        total_trades = len(history)

        values = [self.data.get("value", 10000.0)]
        for h in history:
            values.append(values[-1] + h.get("pnl", 0))

        peak = max(values) if values else 10000.0
        trough = min(values) if values else 10000.0
        max_dd = ((trough - peak) / peak) * 100 if peak else 0

        return {
            "cash": self.data.get("cash", 0),
            "value": self.data.get("value", 0),
            "open_positions": len([p for p in self.data.get("positions", []) if p.get("status") == "open"]),
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / total_trades * 100) if total_trades else 0,
            "total_pnl": round(total_pnl, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "profit_factor": abs(sum(h.get("pnl", 0) for h in history if h.get("pnl", 0) > 0) /
                              sum(abs(h.get("pnl", 0)) for h in history if h.get("pnl", 0) < 0)) if losses else 0
        }
