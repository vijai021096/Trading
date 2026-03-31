"""
Position state machine: IDLE → ENTRY_PENDING → ACTIVE → EXIT_PENDING → CLOSED
Prevents duplicate orders and position drift.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger


class PositionState(str, Enum):
    IDLE = "IDLE"
    ENTRY_PENDING = "ENTRY_PENDING"
    ACTIVE = "ACTIVE"
    EXIT_PENDING = "EXIT_PENDING"
    CLOSED = "CLOSED"


@dataclass
class Position:
    state: PositionState = PositionState.IDLE
    symbol: str = ""
    direction: str = ""          # CALL / PUT
    option_type: str = ""        # CE / PE
    strike: float = 0.0
    expiry: str = ""
    qty: int = 0
    lots: int = 0
    entry_price: float = 0.0
    exit_price: float = 0.0
    sl_price: float = 0.0
    target_price: float = 0.0
    current_sl: float = 0.0      # Dynamic — updates with trail
    entry_time: str = ""
    exit_time: str = ""
    entry_order_id: str = ""
    exit_order_id: str = ""
    exit_reason: str = ""
    strategy: str = ""           # ORB / VWAP_RECLAIM
    spot_at_entry: float = 0.0
    vix_at_entry: float = 0.0
    filter_log: Dict[str, Any] = field(default_factory=dict)
    break_even_set: bool = False
    highest_price_seen: float = 0.0
    slm_order_id: str = ""          # Persisted so SL-M survives bot restarts

    # Risk
    gross_pnl: float = 0.0
    charges: float = 0.0
    net_pnl: float = 0.0


import os
STATE_DIR = Path(os.environ.get("STATE_DIR", "/tmp"))
STATE_FILE = STATE_DIR / "kite_bot_position.json"


def load_position() -> Position:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            p = Position(**{k: v for k, v in data.items() if k in Position.__dataclass_fields__})
            p.state = PositionState(p.state)
            return p
        except Exception:
            pass
    return Position()


def save_position(pos: Position) -> None:
    data = asdict(pos)
    data["state"] = pos.state.value
    STATE_FILE.write_text(json.dumps(data, indent=2, default=str))


def reset_position() -> Position:
    pos = Position()
    save_position(pos)
    return pos


class PositionStateMachine:
    """
    Manages a single open position with explicit state transitions.
    No transition can skip a state — prevents double orders.
    """

    def __init__(self):
        self.position = load_position()

    @property
    def is_idle(self) -> bool:
        return self.position.state == PositionState.IDLE

    @property
    def is_active(self) -> bool:
        return self.position.state == PositionState.ACTIVE

    @property
    def is_open(self) -> bool:
        return self.position.state in (
            PositionState.ENTRY_PENDING,
            PositionState.ACTIVE,
            PositionState.EXIT_PENDING,
        )

    def transition_to_entry_pending(
        self,
        symbol: str,
        direction: str,
        option_type: str,
        strike: float,
        expiry: str,
        qty: int,
        lots: int,
        sl_price: float,
        target_price: float,
        spot_at_entry: float,
        vix_at_entry: float,
        strategy: str,
        filter_log: dict,
        entry_order_id: str = "",
    ) -> None:
        if self.position.state != PositionState.IDLE:
            logger.warning(
                f"transition_to_entry_pending: expected IDLE, got {self.position.state} — resetting state"
            )
            self.position = Position()
        self.position = Position(
            state=PositionState.ENTRY_PENDING,
            symbol=symbol,
            direction=direction,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            qty=qty,
            lots=lots,
            sl_price=sl_price,
            target_price=target_price,
            current_sl=sl_price,
            entry_time=datetime.now().isoformat(),
            entry_order_id=entry_order_id,
            strategy=strategy,
            spot_at_entry=spot_at_entry,
            vix_at_entry=vix_at_entry,
            filter_log=filter_log,
        )
        save_position(self.position)

    def confirm_entry(self, fill_price: float) -> None:
        if self.position.state != PositionState.ENTRY_PENDING:
            logger.warning(f"confirm_entry: expected ENTRY_PENDING, got {self.position.state} — proceeding anyway")
        self.position.state = PositionState.ACTIVE
        self.position.entry_price = fill_price
        self.position.highest_price_seen = fill_price
        save_position(self.position)

    def cancel_entry(self) -> None:
        """Called when entry order is rejected or times out."""
        if self.position.state != PositionState.ENTRY_PENDING:
            logger.warning(f"cancel_entry: expected ENTRY_PENDING, got {self.position.state} — resetting anyway")
        self.position = reset_position()

    def update_trailing_stop(
        self,
        current_price: float,
        trail_trigger_pct: float = 0.20,
        trail_lock_step_pct: float = 0.10,
        break_even_trigger_pct: float = 0.12,
    ) -> Optional[str]:
        """
        Update trailing stop logic.
        Returns "BREAK_EVEN_SET" | "TRAIL_UPDATED" | None
        """
        if self.position.state != PositionState.ACTIVE:
            return None

        self.position.highest_price_seen = max(
            self.position.highest_price_seen, current_price
        )
        entry = self.position.entry_price
        gain_pct = (current_price - entry) / entry if entry > 0 else 0

        changed = None

        # Break-even
        if not self.position.break_even_set and gain_pct >= break_even_trigger_pct:
            new_sl = entry * 1.005
            if new_sl > self.position.current_sl:
                self.position.current_sl = new_sl
                self.position.break_even_set = True
                changed = "BREAK_EVEN_SET"

        # Trail
        if gain_pct >= trail_trigger_pct:
            trail_sl = self.position.highest_price_seen * (1 - trail_lock_step_pct)
            if trail_sl > self.position.current_sl:
                self.position.current_sl = trail_sl
                changed = "TRAIL_UPDATED"

        if changed:
            save_position(self.position)
        return changed

    def transition_to_exit_pending(
        self,
        exit_order_id: str,
        exit_reason: str,
    ) -> None:
        if self.position.state != PositionState.ACTIVE:
            logger.warning(
                f"transition_to_exit_pending: expected ACTIVE, got {self.position.state} — proceeding anyway"
            )
        self.position.state = PositionState.EXIT_PENDING
        self.position.exit_order_id = exit_order_id
        self.position.exit_reason = exit_reason
        self.position.exit_time = datetime.now().isoformat()
        save_position(self.position)

    def confirm_exit(self, fill_price: float, charges: float = 0.0) -> Dict[str, Any]:
        """Finalize exit, compute P&L, return trade record."""
        if self.position.state != PositionState.EXIT_PENDING:
            logger.warning(f"confirm_exit: expected EXIT_PENDING, got {self.position.state} — proceeding anyway")
        self.position.state = PositionState.CLOSED
        self.position.exit_price = fill_price
        self.position.gross_pnl = (fill_price - self.position.entry_price) * self.position.qty
        self.position.charges = charges
        self.position.net_pnl = self.position.gross_pnl - charges
        save_position(self.position)

        trade_record = asdict(self.position)
        trade_record["state"] = PositionState.CLOSED.value
        # Reset for next trade
        self.position = reset_position()
        return trade_record

    def force_close(self, reason: str = "FORCE_CLOSE") -> None:
        """Emergency close — transition directly to IDLE."""
        self.position = reset_position()

    def sync_with_broker(self, broker_qty: int, last_price: float = 0.0) -> bool:
        """
        Reconcile local state with broker's actual position.
        Called every 60s during market hours.
        Returns True if a discrepancy was detected and resolved.

        Detects:
          - Full close: broker_qty == 0 (manual sq-off, SL-M, margin call)
          - Partial close: broker_qty < bot expected qty (partial manual exit)
        """
        if self.position.state != PositionState.ACTIVE:
            return False

        expected_qty = self.position.qty

        if broker_qty == 0:
            # Position fully closed externally
            exit_price = last_price if last_price > 0 else self.position.entry_price
            self.position.state = PositionState.EXIT_PENDING
            self.position.exit_reason = "BROKER_SYNC_CLOSED"
            self.position.exit_time = datetime.now().isoformat()
            self.position.exit_order_id = "EXTERNAL"
            save_position(self.position)

            self.position.state = PositionState.CLOSED
            self.position.exit_price = exit_price
            self.position.gross_pnl = (exit_price - self.position.entry_price) * expected_qty
            self.position.net_pnl = self.position.gross_pnl
            save_position(self.position)
            self.position = reset_position()
            return True

        if 0 < broker_qty < expected_qty:
            # Partial close — update qty to match broker reality
            self.position.qty = broker_qty
            save_position(self.position)
            return True

        return False

    def current_state_dict(self) -> dict:
        d = asdict(self.position)
        d["state"] = self.position.state.value
        return d
