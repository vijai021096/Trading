"""
Risk manager — drawdown-based halt, daily 2R loss limit, per-trade sizing.

Key design for low-win-rate / high-RR systems:
  - Daily loss limit = 2R (allows 2 losing trades before halt, not 1)
  - Primary halt = drawdown from peak > 20% (adaptive, not fixed streak)
  - Consecutive loss counter is informational, not a hard stop
  - Position sizing: fixed % of current capital risked per trade
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple


STATE_DIR = Path(os.environ.get("STATE_DIR", "/tmp"))
HALT_FLAG = STATE_DIR / "kite_bot_halt.flag"
STRATEGY_STATE_FILE = STATE_DIR / "kite_bot_strategy_state.json"
RISK_STATE_FILE = STATE_DIR / "kite_bot_risk_state.json"


@dataclass
class RiskState:
    trade_date: date = field(default_factory=date.today)
    daily_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    trading_halted: bool = False
    halt_reason: str = ""
    peak_capital: float = 0.0

    def reset_for_new_day(self) -> None:
        today = date.today()
        if self.trade_date != today:
            self.trade_date = today
            self.daily_pnl = 0.0
            self.trades_today = 0
            self.trading_halted = False
            self.halt_reason = ""


class RiskManager:
    def __init__(
        self,
        capital: float,
        max_daily_loss_pct: float = 0.08,
        max_trades_per_day: int = 3,
        max_consecutive_losses: int = 8,
        max_daily_loss_hard: float = 2_500.0,
        risk_per_trade_pct: float = 0.02,
        lot_size: int = 65,
        max_lots: int = 1,
        max_drawdown_pct: float = 20.0,
    ):
        self.capital = capital
        self.current_capital = capital
        self.max_daily_loss = capital * max_daily_loss_pct
        self.max_daily_loss_hard = max_daily_loss_hard
        self.max_trades_per_day = max_trades_per_day
        self.max_consecutive_losses = max_consecutive_losses
        self.risk_per_trade_pct = risk_per_trade_pct
        self.lot_size = lot_size
        self.max_lots = max_lots
        self.max_drawdown_pct = max_drawdown_pct
        self.state = RiskState(peak_capital=capital)

        self._load_persisted_state()

    def _load_persisted_state(self) -> None:
        """Load risk state from disk (survives bot restarts)."""
        if RISK_STATE_FILE.exists():
            try:
                data = json.loads(RISK_STATE_FILE.read_text())
                self.current_capital = data.get("current_capital", self.capital)
                self.state.peak_capital = data.get("peak_capital", self.capital)
                self.state.consecutive_losses = data.get("consecutive_losses", 0)
                # Restore intraday counters only if saved date matches today
                saved_date = data.get("trade_date", "")
                today = date.today().isoformat()
                if saved_date == today:
                    self.state.trades_today = data.get("trades_today", 0)
                    self.state.daily_pnl = data.get("daily_pnl", 0.0)
                    self.state.trade_date = date.today()
            except Exception:
                pass

    def _persist_state(self) -> None:
        """Save risk state to disk."""
        try:
            data = {
                "current_capital": round(self.current_capital, 2),
                "peak_capital": round(self.state.peak_capital, 2),
                "consecutive_losses": self.state.consecutive_losses,
                "trade_date": self.state.trade_date.isoformat(),
                "trades_today": self.state.trades_today,
                "daily_pnl": round(self.state.daily_pnl, 2),
                "updated_at": datetime.now().isoformat(),
            }
            RISK_STATE_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def can_trade(self) -> Tuple[bool, str]:
        """Check all risk gates before placing a new entry."""
        self.state.reset_for_new_day()

        if HALT_FLAG.exists():
            return False, "EMERGENCY_STOP: Dashboard halt flag active"

        if self.state.trading_halted:
            return False, f"Trading halted: {self.state.halt_reason}"

        if self.state.trades_today >= self.max_trades_per_day:
            return False, f"Max trades reached: {self.state.trades_today}/{self.max_trades_per_day}"

        # Daily loss check (allows 2 SL hits before stopping)
        if self.state.daily_pnl <= -self.max_daily_loss:
            self._halt(f"Daily loss limit: ₹{self.state.daily_pnl:.0f} (limit ₹{self.max_daily_loss:.0f})")
            return False, self.state.halt_reason

        if self.state.daily_pnl <= -self.max_daily_loss_hard:
            self._halt(f"Hard daily loss: ₹{self.state.daily_pnl:.0f}")
            return False, self.state.halt_reason

        # Drawdown-based halt (primary circuit breaker)
        dd = self.drawdown_pct()
        if dd >= self.max_drawdown_pct:
            self._halt(
                f"DRAWDOWN HALT: {dd:.1f}% from peak "
                f"(₹{self.state.peak_capital:,.0f} → ₹{self.current_capital:,.0f})"
            )
            return False, self.state.halt_reason

        return True, "OK"

    def compute_position_size(
        self,
        entry_price: float,
        sl_pct: float,
        risk_pct_override: float = 0.0,
    ) -> dict:
        """
        Compute position size based on fixed % risk of current capital.
        If risk_pct_override > 0, use that instead of default risk_per_trade_pct
        (allows regime/trend-based risk scaling from the trader).
        """
        effective_pct = risk_pct_override if risk_pct_override > 0 else self.risk_per_trade_pct
        risk_amount = self.current_capital * effective_pct
        risk_per_unit = entry_price * sl_pct
        if risk_per_unit <= 0:
            return {"lots": 1, "qty": self.lot_size, "risk_amount": risk_amount,
                    "risk_per_lot": 0, "actual_risk": 0}

        max_qty = risk_amount / risk_per_unit
        lots = max(1, min(self.max_lots, int(max_qty / self.lot_size)))
        qty = lots * self.lot_size
        actual_risk = risk_per_unit * qty

        return {
            "lots": lots,
            "qty": qty,
            "risk_amount": round(risk_amount, 2),
            "risk_per_lot": round(risk_per_unit * self.lot_size, 2),
            "actual_risk": round(actual_risk, 2),
        }

    def record_trade(self, net_pnl: float) -> None:
        self.state.reset_for_new_day()
        self.state.daily_pnl += net_pnl
        self.state.trades_today += 1
        self.current_capital += net_pnl

        if self.current_capital > self.state.peak_capital:
            self.state.peak_capital = self.current_capital

        if net_pnl > 0:
            self.state.consecutive_losses = 0
        else:
            self.state.consecutive_losses += 1

        self._persist_state()

        # Check daily limit after recording
        if self.state.daily_pnl <= -self.max_daily_loss:
            self._halt(f"Daily loss limit hit: ₹{self.state.daily_pnl:.0f}")

    def get_strategy_state(self) -> dict:
        default = {"orb_enabled": True, "vwap_enabled": True}
        try:
            if STRATEGY_STATE_FILE.exists():
                return json.loads(STRATEGY_STATE_FILE.read_text())
        except Exception:
            pass
        return default

    def emergency_stop(self) -> None:
        self._halt("EMERGENCY STOP — manual trigger")

    def reset_halt(self) -> None:
        self.state.trading_halted = False
        self.state.halt_reason = ""

    def _halt(self, reason: str) -> None:
        self.state.trading_halted = True
        self.state.halt_reason = reason

    def drawdown_pct(self) -> float:
        if self.state.peak_capital <= 0:
            return 0.0
        return ((self.state.peak_capital - self.current_capital) / self.state.peak_capital) * 100

    def status(self) -> dict:
        self.state.reset_for_new_day()
        return {
            "trade_date": self.state.trade_date.isoformat(),
            "daily_pnl": round(self.state.daily_pnl, 2),
            "trades_today": self.state.trades_today,
            "consecutive_losses": self.state.consecutive_losses,
            "trading_halted": self.state.trading_halted,
            "halt_reason": self.state.halt_reason,
            "remaining_trades": max(0, self.max_trades_per_day - self.state.trades_today),
            "remaining_daily_loss": round(self.max_daily_loss + self.state.daily_pnl, 2),
            "current_capital": round(self.current_capital, 2),
            "drawdown_pct": round(self.drawdown_pct(), 2),
            "max_drawdown_pct": self.max_drawdown_pct,
            "risk_per_trade_pct": self.risk_per_trade_pct * 100,
            "emergency_stop_active": HALT_FLAG.exists(),
            "peak_capital": round(self.state.peak_capital, 2),
        }
