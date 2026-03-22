"""Risk manager — enforces daily loss limits, circuit breakers, trade limits."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional


@dataclass
class RiskState:
    trade_date: date = field(default_factory=date.today)
    daily_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    trading_halted: bool = False
    halt_reason: str = ""

    def reset_for_new_day(self) -> None:
        today = date.today()
        if self.trade_date != today:
            self.trade_date = today
            self.daily_pnl = 0.0
            self.trades_today = 0
            self.trading_halted = False
            self.halt_reason = ""
            # Note: consecutive_losses carry over by design


class RiskManager:
    def __init__(
        self,
        capital: float,
        max_daily_loss_pct: float = 0.03,
        max_trades_per_day: int = 3,
        max_consecutive_losses: int = 3,
        max_daily_loss_hard: float = 3_000.0,
    ):
        self.capital = capital
        self.max_daily_loss = capital * max_daily_loss_pct
        self.max_daily_loss_hard = max_daily_loss_hard
        self.max_trades_per_day = max_trades_per_day
        self.max_consecutive_losses = max_consecutive_losses
        self.state = RiskState()

    def can_trade(self) -> tuple[bool, str]:
        """
        Returns (allowed, reason).
        Call this before placing any new entry order.
        """
        self.state.reset_for_new_day()

        if self.state.trading_halted:
            return False, f"Trading halted: {self.state.halt_reason}"

        if self.state.trades_today >= self.max_trades_per_day:
            return False, f"Max trades reached: {self.state.trades_today}/{self.max_trades_per_day}"

        if self.state.daily_pnl <= -self.max_daily_loss:
            self._halt(f"Daily loss limit: ₹{self.state.daily_pnl:.0f} <= -₹{self.max_daily_loss:.0f}")
            return False, self.state.halt_reason

        if self.state.daily_pnl <= -self.max_daily_loss_hard:
            self._halt(f"Hard daily loss limit: ₹{self.state.daily_pnl:.0f}")
            return False, self.state.halt_reason

        if self.state.consecutive_losses >= self.max_consecutive_losses:
            self._halt(f"Max consecutive losses: {self.state.consecutive_losses}")
            return False, self.state.halt_reason

        return True, "OK"

    def record_trade(self, net_pnl: float) -> None:
        self.state.reset_for_new_day()
        self.state.daily_pnl += net_pnl
        self.state.trades_today += 1
        if net_pnl > 0:
            self.state.consecutive_losses = 0
        else:
            self.state.consecutive_losses += 1

        # Check limits after recording
        if self.state.daily_pnl <= -self.max_daily_loss:
            self._halt(f"Daily loss limit hit after trade: ₹{self.state.daily_pnl:.0f}")

    def emergency_stop(self) -> None:
        self._halt("EMERGENCY STOP — manual trigger")

    def reset_halt(self) -> None:
        self.state.trading_halted = False
        self.state.halt_reason = ""

    def _halt(self, reason: str) -> None:
        self.state.trading_halted = True
        self.state.halt_reason = reason

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
        }
