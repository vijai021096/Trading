"""
Live NIFTY Options Trader V2 — Regime-aware, direction-dynamic, risk-sized.

Architecture:
  RegimeV2       → 5-state classifier (SKIP/DIRECTIONAL/RANGE_BREAK/PULLBACK/UNCERTAIN)
                   Direction = BIAS, live candles confirm. Gap reversals handled naturally.
  StrategyEngine → build_entry_signal() → EntrySignal with all computed params
  Execution      → Aggressive limit entry + SL limit order (no SL-M)
  PositionSM     → IDLE → ENTRY_PENDING → ACTIVE → EXIT_PENDING → CLOSED
  RiskManager    → drawdown halt, daily loss limit, trade count gate

Bot runs on a 5-second poll loop:
  1. Refresh candles (Kite API)
  2. On new day: classify regime, reset state
  3. If IDLE + in window: try to build entry signal
  4. If ENTRY_PENDING: confirm fill or cancel
  5. If ACTIVE: check SL, target, trail; broker sync every 60s
  6. Write narrative event every cycle (storyteller)
"""
from __future__ import annotations

import json
import os as _os
import time
import traceback
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from kite_broker.client import KiteClient
from bot.risk_manager import RiskManager
from bot.state_machine import PositionStateMachine, PositionState, save_position, reset_position
from bot.strategy_engine import build_entry_signal, EntrySignal
from shared.config import settings
from shared.regime_v2 import RegimeV2, classify_regime_v2_live
from shared.black_scholes import charges_estimate


# ── File paths ────────────────────────────────────────────────────────────────

_STATE_DIR = Path(_os.environ.get("STATE_DIR", "/tmp"))
EVENTS_LOG      = _STATE_DIR / "kite_bot_events.jsonl"
HALT_FLAG       = _STATE_DIR / "kite_bot_halt.flag"
OVERRIDE_FILE   = _STATE_DIR / "kite_bot_runtime_override.json"
NARRATIVE_FILE  = _STATE_DIR / "kite_bot_narrative.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_event(event_type: str, payload: dict) -> None:
    entry = {"ts": datetime.now().isoformat(), "event": event_type, **payload}
    with open(EVENTS_LOG, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _write_narrative(data: dict) -> None:
    """Write bot's current thinking to a JSON file for the UI storyteller."""
    try:
        NARRATIVE_FILE.write_text(json.dumps({"ts": datetime.now().isoformat(), **data}, default=str))
    except Exception:
        pass


def _read_override() -> dict:
    try:
        if OVERRIDE_FILE.exists():
            return json.loads(OVERRIDE_FILE.read_text()) or {}
    except Exception:
        pass
    return {}


def _t(time_str: str) -> dtime:
    h, m = map(int, time_str.split(":"))
    return dtime(h, m)


# ── Trader ────────────────────────────────────────────────────────────────────

class KiteORBTrader:
    """
    Main trader class. Call run() to start the poll loop.
    """

    def __init__(self, client: KiteClient) -> None:
        self.client    = client
        self.cfg       = settings
        self.risk      = RiskManager(
            capital                = self.cfg.capital,
            max_daily_loss_pct     = self.cfg.max_daily_loss_pct,
            max_trades_per_day     = self.cfg.max_trades_per_day,
            max_consecutive_losses = self.cfg.max_consecutive_losses,
            max_daily_loss_hard    = self.cfg.max_daily_loss_hard,
            risk_per_trade_pct     = self.cfg.risk_per_trade_pct,
            lot_size               = self.cfg.lot_size,
            max_lots               = self.cfg.live_max_lots,
            max_drawdown_pct       = self.cfg.max_drawdown_pct,
        )
        self.sm = PositionStateMachine()

        # ── Daily state ──────────────────────────────────────────────
        self._candle_cache:       List[Dict]        = []
        self._nifty_token:        Optional[int]     = None
        self._last_candle_date:   Optional[date]    = None
        self._regime:             Optional[RegimeV2] = None
        self._regime_classified:  bool              = False
        self._is_expiry_day:      bool              = False
        self._vix:                Optional[float]   = None
        self._first_scan_done:    bool              = False   # Skip first scan after restart
        self._trades_today:       int               = 0
        self._direction_lost_today: Optional[str]  = None    # Block re-entry in same direction
        self._pending_order_id:   Optional[str]    = None
        self._pending_signal:     Optional[EntrySignal] = None
        self._last_broker_sync:   float             = 0.0
        self._sl_order_id:        Optional[str]    = None    # Active SL limit order
        self._heartbeat_count:    int               = 0

        # ── Narrative state ──────────────────────────────────────────
        self._narrative_status:   str = "STARTING"
        self._narrative_detail:   str = "Initializing bot..."

        logger.info("KiteORBTrader V2 initialized — regime=V2, engine=StrategyEngine")

    # ── Main loop ────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Main poll loop. Runs until KeyboardInterrupt."""
        logger.info("Bot started — entering poll loop (5s)")
        _log_event("BOT_START", {"version": "v2", "capital": self.cfg.capital})

        while True:
            try:
                now = datetime.now()
                if self._market_active(now):
                    self._tick(now)
                else:
                    self._off_market_narrative(now)
                time.sleep(self.cfg.poll_seconds)
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"TICK_ERROR: {e}\n{traceback.format_exc()}")
                time.sleep(10)

    def _tick(self, now: datetime) -> None:
        self._heartbeat_count += 1

        # ── 1. Refresh candles & roll day ──────────────────────────
        candles = self._refresh_candles(now)
        if not candles:
            self._set_narrative("WAITING", "No candle data yet — waiting for market open")
            return

        self._roll_day(now)

        spot = self._get_spot()
        if spot <= 0:
            self._set_narrative("WAITING", "Cannot get NIFTY spot price")
            return

        # ── 2. Refresh VIX ─────────────────────────────────────────
        if self._heartbeat_count % 12 == 0:  # every ~60s
            self._vix = self._get_vix()

        # ── 3. Dispatch by position state ──────────────────────────
        state = self.sm.position.state

        if state == PositionState.IDLE:
            self._handle_idle(now, candles, spot)
        elif state == PositionState.ENTRY_PENDING:
            self._handle_entry_pending(now, spot)
        elif state == PositionState.ACTIVE:
            self._handle_active(now, spot)
        elif state == PositionState.EXIT_PENDING:
            self._handle_exit_pending(now, spot)
        # CLOSED is transient — resets to IDLE immediately

        # ── 4. Write narrative ─────────────────────────────────────
        self._flush_narrative(now, spot)

    # ── Day roll ─────────────────────────────────────────────────────────────

    def _roll_day(self, now: datetime) -> None:
        today = now.date()

        if self._last_candle_date != today:
            logger.info(f"DAY_ROLL: {self._last_candle_date} → {today}")
            self._last_candle_date      = today
            self._regime_classified     = False
            self._regime                = None
            self._first_scan_done       = False
            self._trades_today          = 0
            self._direction_lost_today  = None
            self._pending_order_id      = None
            self._pending_signal        = None
            self._sl_order_id           = None
            self._is_expiry_day         = self._check_expiry_day(today)
            self._classify_regime(today)

        elif not self._regime_classified:
            # Day already started but regime hasn't been classified yet
            # (happens if candle data was unavailable at roll time)
            self._classify_regime(today)

    def _classify_regime(self, today: date) -> None:
        """Classify daily regime using live candles from Kite."""
        try:
            regime = classify_regime_v2_live(self.client, today, self._vix)
            self._regime = regime
            self._regime_classified = True
            logger.info(
                f"REGIME: {regime.name} | bias={regime.direction_bias} "
                f"| trade={regime.should_trade} | window={regime.window_start}-{regime.window_end} "
                f"| {regime.detail}"
            )
            _log_event("REGIME_CLASSIFIED", {
                "regime": regime.name,
                "bias": regime.direction_bias,
                "should_trade": regime.should_trade,
                "detail": regime.detail,
                "scores": regime.scores,
            })
        except Exception as e:
            logger.warning(f"REGIME_CLASSIFY_ERROR: {e} — will retry next poll")

    # ── IDLE: look for entry ──────────────────────────────────────────────────

    def _handle_idle(self, now: datetime, candles: List[Dict], spot: float) -> None:
        regime = self._regime

        # No regime yet
        if regime is None:
            self._set_narrative("WAITING", "Classifying market regime — checking gap, VIX, trend...")
            return

        # Regime says skip
        if not regime.should_trade:
            self._set_narrative("SKIP", f"Regime: {regime.name} — {regime.detail}")
            return

        # Halt flag
        if HALT_FLAG.exists():
            self._set_narrative("HALTED", "Emergency halt active — manual resume required")
            return

        # Risk gates
        can_trade, reason = self.risk.can_trade()
        if not can_trade:
            self._set_narrative("RISK_GATE", reason)
            return

        # Max trades per regime
        if self._trades_today >= regime.max_trades:
            self._set_narrative("DONE", f"Max trades for today reached ({regime.max_trades}) — regime: {regime.name}")
            return

        # Entry window
        t = now.time()
        if not (_t(regime.window_start) <= t <= _t(regime.window_end)):
            if t < _t(regime.window_start):
                self._set_narrative("WAITING", f"Entry window opens at {regime.window_start} — regime: {regime.name}")
            else:
                self._set_narrative("DONE", f"Entry window closed at {regime.window_end} — done for today")
            return

        # Startup guard — skip very first scan (opening candles are noisy)
        if not self._first_scan_done:
            self._first_scan_done = True
            self._set_narrative("WAITING", "First scan skipped — letting opening candles settle")
            logger.info("STARTUP_GUARD: skipping first scan cycle")
            return

        # Check override
        ov = _read_override()
        if ov.get("pause"):
            self._set_narrative("PAUSED", "Bot paused via dashboard")
            return

        # ── Build entry signal ──────────────────────────────────────
        self._set_narrative("SCANNING", f"Scanning for entry... regime={regime.name} bias={regime.direction_bias}")

        signal = build_entry_signal(
            now              = now,
            candles          = candles,
            spot             = spot,
            vix              = self._vix or 15.0,
            regime           = regime,
            capital          = self.risk.current_capital,
            lot_size         = self.cfg.lot_size,
            kite_client      = self.client,
            is_expiry_day    = self._is_expiry_day,
            direction_lost_today = self._direction_lost_today,
        )

        if signal is None:
            return  # narrative already set to SCANNING above

        # ── Enter trade ─────────────────────────────────────────────
        self._enter_trade(signal, spot)

    # ── Entry execution ───────────────────────────────────────────────────────

    def _enter_trade(self, signal: EntrySignal, spot: float) -> None:
        """Place entry limit order and transition to ENTRY_PENDING."""
        logger.info(
            f"ENTRY_SIGNAL: {signal.direction} {signal.symbol} "
            f"| LTP={signal.ltp:.0f} limit={signal.entry_limit:.0f} "
            f"| SL={signal.sl_price:.0f} ({signal.sl_pct*100:.0f}%) "
            f"| target={signal.target_price:.0f} "
            f"| lots={signal.lots} qty={signal.qty} "
            f"| strategy={signal.strategy} conviction={signal.conviction:.2f}"
        )

        try:
            result = self.client.place_order(
                symbol      = signal.symbol,
                qty         = signal.qty,
                side        = "BUY",
                exchange    = "NFO",
                product     = "MIS",
                limit_price = signal.entry_limit,
            )
            order_id = result.get("order_id", "") if isinstance(result, dict) else str(result)
        except Exception as e:
            logger.error(f"ENTRY_ORDER_FAILED: {e}")
            _log_event("ENTRY_ORDER_FAILED", {"symbol": signal.symbol, "error": str(e)})
            return

        self.sm.transition_to_entry_pending(
            symbol        = signal.symbol,
            direction     = signal.direction,
            option_type   = signal.option_type,
            strike        = signal.strike,
            expiry        = str(signal.expiry),
            qty           = signal.qty,
            lots          = signal.lots,
            sl_price      = signal.sl_price,
            target_price  = signal.target_price,
            spot_at_entry = spot,
            vix_at_entry  = self._vix or 0.0,
            strategy      = signal.strategy,
            filter_log    = {
                "regime":     signal.regime,
                "rsi":        signal.rsi,
                "vwap":       signal.vwap,
                "conviction": signal.conviction,
                "candles":    signal.candle_confirm,
            },
            entry_order_id = order_id,
        )
        self._pending_order_id = order_id
        self._pending_signal   = signal

        _log_event("ENTRY_PLACED", {
            "order_id":    order_id,
            "symbol":      signal.symbol,
            "direction":   signal.direction,
            "strategy":    signal.strategy,
            "lots":        signal.lots,
            "qty":         signal.qty,
            "entry_limit": signal.entry_limit,
            "sl_price":    signal.sl_price,
            "target":      signal.target_price,
            "regime":      signal.regime,
            "conviction":  signal.conviction,
            "ltp_at_signal": signal.ltp,
        })
        self._set_narrative(
            "ENTRY_PENDING",
            f"Limit order placed: {signal.direction} {signal.symbol} @ {signal.entry_limit:.0f} | order_id={order_id}",
        )

    # ── Entry pending ─────────────────────────────────────────────────────────

    def _handle_entry_pending(self, now: datetime, spot: float) -> None:
        """Check if entry order has filled. Cancel if stale (>60s)."""
        order_id = self._pending_order_id
        signal   = self._pending_signal
        if not order_id or not signal:
            logger.warning("ENTRY_PENDING but no order_id — resetting")
            self.sm.cancel_entry()
            return

        try:
            order_info = self.client.get_order_status(order_id)
            status     = str(order_info.get("status", "")).upper()
            fill_price = float(order_info.get("average_price") or order_info.get("price") or 0)
        except Exception as e:
            logger.warning(f"ORDER_STATUS_ERROR: {e}")
            return

        if status == "COMPLETE":
            fill = fill_price or signal.entry_limit
            self.sm.confirm_entry(fill)
            self._trades_today += 1
            logger.info(f"ENTRY_FILLED: {signal.symbol} @ {fill:.0f} | lots={signal.lots}")
            _log_event("ENTRY_FILLED", {
                "order_id":   order_id,
                "symbol":     signal.symbol,
                "fill_price": fill,
                "lots":       signal.lots,
                "strategy":   signal.strategy,
            })

            # Place SL limit order immediately
            self._place_sl_order(signal, fill)
            self._set_narrative("ACTIVE", f"IN TRADE: {signal.direction} {signal.symbol} | entry={fill:.0f}")

        elif status in ("REJECTED", "CANCELLED"):
            logger.warning(f"ENTRY_ORDER_{status}: {order_id} — cancelling")
            self.sm.cancel_entry()
            self._pending_order_id = None
            self._pending_signal   = None
            _log_event("ENTRY_CANCELLED", {"order_id": order_id, "status": status})

        else:
            # Still pending — check timeout (60s)
            entry_time_str = self.sm.position.entry_time
            if entry_time_str:
                entry_time = datetime.fromisoformat(entry_time_str)
                if (now - entry_time).total_seconds() > 60:
                    logger.warning(f"ENTRY_TIMEOUT: {order_id} — cancelling stale order")
                    try:
                        self.client.cancel_order(order_id)
                    except Exception:
                        pass
                    self.sm.cancel_entry()
                    self._pending_order_id = None
                    self._pending_signal   = None
                    _log_event("ENTRY_TIMEOUT", {"order_id": order_id})

    def _place_sl_order(self, signal: EntrySignal, fill_price: float) -> None:
        """Place SL as an SL-limit sell order at signal's SL price."""
        # Use actual fill price to compute SL (may differ from signal LTP)
        sl_price = round(fill_price * (1 - signal.sl_pct), 1)

        try:
            result = self.client.place_slm_order(
                symbol        = signal.symbol,
                qty           = signal.qty,
                trigger_price = sl_price,
                exchange      = "NFO",
                product       = "MIS",
            )
            sl_order_id = result.get("order_id", "") if isinstance(result, dict) else str(result)
            self._sl_order_id = sl_order_id
            self.sm.position.sl_price   = sl_price
            self.sm.position.current_sl = sl_price
            save_position(self.sm.position)
            logger.info(f"SL_ORDER_PLACED: trigger={sl_price:.0f} order_id={sl_order_id}")
            _log_event("SL_ORDER_PLACED", {"order_id": sl_order_id, "sl_price": sl_price})
        except Exception as e:
            logger.error(f"SL_ORDER_FAILED: {e} — will monitor price manually")
            _log_event("SL_ORDER_FAILED", {"error": str(e)})

    # ── Active: monitor position ───────────────────────────────────────────────

    def _handle_active(self, now: datetime, spot: float) -> None:
        pos = self.sm.position
        symbol = pos.symbol

        # ── Broker sync every 60s ───────────────────────────────────
        if time.time() - self._last_broker_sync > 60:
            self._broker_sync(symbol)
            self._last_broker_sync = time.time()
            if self.sm.is_idle:
                return  # Position was externally closed

        # ── Get current option price ────────────────────────────────
        ltp = self.client.get_quote(symbol, "NFO")
        if ltp <= 0:
            logger.warning(f"ACTIVE: cannot get LTP for {symbol}")
            return

        # ── Update narrative ────────────────────────────────────────
        entry    = pos.entry_price
        pnl_pct  = (ltp - entry) / entry * 100 if entry > 0 else 0
        pnl_rs   = (ltp - entry) * pos.qty
        self._set_narrative(
            "ACTIVE",
            f"{pos.direction} {symbol} | LTP={ltp:.0f} entry={entry:.0f} "
            f"P&L={pnl_rs:+.0f} ({pnl_pct:+.1f}%) | SL={pos.current_sl:.0f} target={pos.target_price:.0f}",
        )

        # ── Target hit ─────────────────────────────────────────────
        if ltp >= pos.target_price:
            logger.info(f"TARGET_HIT: {symbol} LTP={ltp:.0f} >= target={pos.target_price:.0f}")
            self._exit_position("TARGET", ltp)
            return

        # ── SL hit (price monitoring — exchange order may have already fired) ──
        if ltp <= pos.current_sl:
            logger.info(f"SL_HIT: {symbol} LTP={ltp:.0f} <= SL={pos.current_sl:.0f}")
            self._exit_position("SL_HIT", ltp)
            return

        # ── Force exit time ─────────────────────────────────────────
        if now.time() >= _t(self.cfg.force_exit_time):
            logger.info(f"FORCE_EXIT: {now.time()} >= {self.cfg.force_exit_time}")
            self._exit_position("FORCE_EXIT_TIME", ltp)
            return

        # ── Trail stop ──────────────────────────────────────────────
        trail_event = self.sm.update_trailing_stop(
            current_price         = ltp,
            trail_trigger_pct     = self.cfg.trail_trigger_pct,
            trail_lock_step_pct   = self.cfg.trail_lock_step_pct,
            break_even_trigger_pct = self.cfg.break_even_trigger_pct,
        )
        if trail_event:
            logger.info(f"TRAIL: {trail_event} | new_sl={pos.current_sl:.0f}")
            self._update_sl_order(pos.current_sl, pos.qty, symbol)
            _log_event(trail_event, {"new_sl": pos.current_sl, "ltp": ltp})

    def _update_sl_order(self, new_sl: float, qty: int, symbol: str) -> None:
        """Modify existing SL order to new trigger price."""
        if not self._sl_order_id:
            return
        try:
            self.client.modify_slm_order(self._sl_order_id, new_sl)
            logger.info(f"SL_ORDER_MODIFIED: trigger={new_sl:.0f}")
        except Exception as e:
            logger.warning(f"SL_MODIFY_FAILED: {e} — will rely on price monitoring")

    def _broker_sync(self, symbol: str) -> None:
        """Check actual position at broker. Close locally if externally squared off."""
        try:
            positions = self.client.get_positions()
            # get_positions() returns a flat list of position dicts
            if isinstance(positions, dict):
                positions = positions.get("net", []) or []
            net_qty = 0
            ltp     = 0.0
            for p in positions:
                if p.get("tradingsymbol") == symbol:
                    net_qty = abs(int(p.get("quantity", 0)))
                    ltp     = float(p.get("last_price", 0))
                    break
            discrepancy = self.sm.sync_with_broker(net_qty, ltp)
            if discrepancy:
                logger.warning(f"BROKER_SYNC: position externally closed for {symbol}")
                _log_event("BROKER_SYNC_CLOSE", {"symbol": symbol, "ltp": ltp})
                self._record_close("BROKER_SYNC", ltp)
        except Exception as e:
            logger.warning(f"BROKER_SYNC_ERROR: {e}")

    # ── Exit pending ──────────────────────────────────────────────────────────

    def _handle_exit_pending(self, now: datetime, spot: float) -> None:
        """Check if exit order has filled."""
        order_id = self.sm.position.exit_order_id
        if not order_id or order_id == "EXTERNAL":
            self._finalize_close()
            return

        try:
            order_info = self.client.get_order_status(order_id)
            status     = str(order_info.get("status", "")).upper()
            fill_price = float(order_info.get("average_price") or order_info.get("price") or 0)
        except Exception as e:
            logger.warning(f"EXIT_ORDER_STATUS_ERROR: {e}")
            return

        if status == "COMPLETE":
            self._finalize_close(fill_price)
        elif status in ("REJECTED", "CANCELLED"):
            logger.error(f"EXIT_ORDER_{status}: {order_id} — forcing market exit")
            self._force_market_exit()

    def _finalize_close(self, fill_price: float = 0.0) -> None:
        pos = self.sm.position
        if fill_price <= 0:
            fill_price = pos.exit_price or pos.entry_price
        reason = pos.exit_reason
        charges = charges_estimate(pos.entry_price, fill_price, pos.qty)
        trade = self.sm.confirm_exit(fill_price, charges)

        net_pnl = trade.get("net_pnl", 0.0)
        self.risk.record_trade(net_pnl)

        # Track losing direction for direction_lost_today
        if net_pnl < 0 and pos.direction:
            self._direction_lost_today = pos.direction
            logger.info(f"DIRECTION_LOST: {pos.direction} — blocking re-entry in this direction today")

        logger.info(
            f"TRADE_CLOSED: {pos.direction} {pos.symbol} | "
            f"entry={pos.entry_price:.0f} exit={fill_price:.0f} "
            f"net_pnl={net_pnl:+.0f} reason={reason}"
        )
        _log_event("TRADE_CLOSED", {
            "symbol":      pos.symbol,
            "direction":   pos.direction,
            "strategy":    pos.strategy,
            "entry_price": pos.entry_price,
            "exit_price":  fill_price,
            "qty":         pos.qty,
            "lots":        pos.lots,
            "net_pnl":     net_pnl,
            "charges":     charges,
            "exit_reason": reason,
        })

        self._pending_order_id = None
        self._pending_signal   = None
        self._sl_order_id      = None

        result = "WIN" if net_pnl > 0 else "LOSS"
        self._set_narrative("CLOSED", f"Trade {result}: {net_pnl:+.0f} | reason={reason}")

    def _record_close(self, reason: str, ltp: float) -> None:
        """Called when broker sync detects external close."""
        pos = self.sm.position
        charges = charges_estimate(pos.entry_price, ltp, pos.qty)
        self.sm.position.exit_reason = reason
        self.sm.position.exit_price  = ltp
        trade = self.sm.confirm_exit(ltp, charges)
        net_pnl = trade.get("net_pnl", 0.0)
        self.risk.record_trade(net_pnl)
        if net_pnl < 0 and pos.direction:
            self._direction_lost_today = pos.direction
        self._sl_order_id = None
        _log_event("TRADE_CLOSED_EXTERNAL", {
            "reason":    reason,
            "exit_price": ltp,
            "net_pnl":   net_pnl,
        })

    # ── Exit helpers ──────────────────────────────────────────────────────────

    def _exit_position(self, reason: str, ltp: float) -> None:
        """Place market sell to close the position."""
        pos = self.sm.position
        if pos.state != PositionState.ACTIVE:
            return

        # Cancel existing SL order first
        if self._sl_order_id:
            try:
                self.client.cancel_order(self._sl_order_id)
                logger.info(f"SL_ORDER_CANCELLED: {self._sl_order_id}")
            except Exception as e:
                logger.warning(f"SL_CANCEL_FAILED: {e}")
            self._sl_order_id = None

        try:
            result = self.client.place_order(
                symbol  = pos.symbol,
                qty     = pos.qty,
                side    = "SELL",
                exchange= "NFO",
                product = "MIS",
                ltp     = ltp,   # aggressive limit (1% below LTP = market-like)
            )
            exit_order_id = result.get("order_id", "") if isinstance(result, dict) else str(result)
        except Exception as e:
            logger.error(f"EXIT_ORDER_FAILED: {e}")
            _log_event("EXIT_ORDER_FAILED", {"reason": reason, "error": str(e)})
            return

        self.sm.transition_to_exit_pending(exit_order_id, reason)
        _log_event("EXIT_PLACED", {"order_id": exit_order_id, "reason": reason, "ltp": ltp})

    def _force_market_exit(self) -> None:
        """Emergency exit when exit order was rejected."""
        pos = self.sm.position
        ltp = self.client.get_quote(pos.symbol, "NFO")
        try:
            result = self.client.place_order(
                symbol  = pos.symbol,
                qty     = pos.qty,
                side    = "SELL",
                exchange= "NFO",
                product = "MIS",
                ltp     = ltp,
            )
            order_id = result.get("order_id", "") if isinstance(result, dict) else str(result)
            self.sm.transition_to_exit_pending(order_id, "FORCE_MARKET_EXIT")
        except Exception as e:
            logger.critical(f"FORCE_EXIT_FAILED: {e} — MANUAL INTERVENTION REQUIRED")

    # ── Candles & market data ─────────────────────────────────────────────────

    def _refresh_candles(self, now: datetime) -> List[Dict]:
        """Fetch today's 5-min candles from Kite. Returns cached list."""
        if self._nifty_token is None:
            self._nifty_token = self.client.get_nifty_token()
            if self._nifty_token is None:
                return []

        today = now.date()
        from_dt = datetime(today.year, today.month, today.day, 9, 0)
        to_dt   = now

        try:
            candles = self.client.get_candles(self._nifty_token, from_dt, to_dt, "5minute")
            if candles:
                self._candle_cache = candles
                # Update last_candle_date from actual data
                dates = sorted(set(c["ts"].date() for c in candles if hasattr(c["ts"], "date")))
                if dates:
                    # Use today's date if today's candles exist, else latest
                    if today in dates:
                        self._last_candle_date = today
                    else:
                        self._last_candle_date = dates[-1]
        except Exception as e:
            logger.warning(f"CANDLE_FETCH_ERROR: {e}")

        return self._candle_cache

    def _get_spot(self) -> float:
        try:
            ltp = self.client.get_quote("NIFTY 50", "NSE")
            return float(ltp) if ltp and ltp > 0 else 0.0
        except Exception as e:
            logger.warning(f"SPOT_FETCH_ERROR: {e}")
            return 0.0

    def _get_vix(self) -> Optional[float]:
        try:
            ltp = self.client.get_quote("INDIA VIX", "NSE")
            return float(ltp) if ltp and ltp > 0 else None
        except Exception:
            return None

    # ── Market timing ─────────────────────────────────────────────────────────

    def _market_active(self, now: datetime) -> bool:
        t = now.time()
        return _t("09:00") <= t <= _t("15:30")

    def _check_expiry_day(self, today: date) -> bool:
        """Returns True if today is a Thursday (weekly expiry for NIFTY)."""
        return today.weekday() == 3  # Thursday

    # ── Narrative ─────────────────────────────────────────────────────────────

    def _set_narrative(self, status: str, detail: str) -> None:
        self._narrative_status = status
        self._narrative_detail = detail

    def _off_market_narrative(self, now: datetime) -> None:
        if now.time() < _t("09:00"):
            self._set_narrative("PRE_MARKET", f"Market opens at 09:15 — current time {now.strftime('%H:%M')}")
        else:
            self._set_narrative("CLOSED", f"Market closed — today's P&L: ₹{self.risk.state.daily_pnl:+.0f}")

    def _flush_narrative(self, now: datetime, spot: float) -> None:
        regime = self._regime
        _write_narrative({
            "status":        self._narrative_status,
            "detail":        self._narrative_detail,
            "regime":        regime.name if regime else "UNKNOWN",
            "regime_bias":   regime.direction_bias if regime else None,
            "regime_detail": regime.detail if regime else "",
            "window":        f"{regime.window_start}–{regime.window_end}" if regime else "",
            "spot":          spot,
            "vix":           self._vix,
            "trades_today":  self._trades_today,
            "daily_pnl":     self.risk.state.daily_pnl,
            "is_expiry_day": self._is_expiry_day,
            "position": self.sm.current_state_dict() if not self.sm.is_idle else None,
        })

    # ── Startup broker sync ───────────────────────────────────────────────────

    def startup_sync(self) -> None:
        """
        Called once on startup. Checks if there's an active position in local state
        that matches the broker — handles restarts during an open trade.
        """
        pos = self.sm.position
        if pos.state not in (PositionState.ACTIVE, PositionState.ENTRY_PENDING, PositionState.EXIT_PENDING):
            logger.info("STARTUP_SYNC: no open position in local state — clean start")
            return

        logger.info(f"STARTUP_SYNC: local state has position {pos.symbol} [{pos.state.value}] — verifying with broker")

        try:
            raw = self.client.get_positions()
            positions = raw if isinstance(raw, list) else (raw.get("net", []) if isinstance(raw, dict) else [])
            net_qty = 0
            ltp     = 0.0
            for p in positions:
                if p.get("tradingsymbol") == pos.symbol:
                    net_qty = abs(int(p.get("quantity", 0)))
                    ltp     = float(p.get("last_price", 0))
                    break

            if net_qty == 0 and pos.state == PositionState.ACTIVE:
                logger.warning(f"STARTUP_SYNC: broker has 0 qty for {pos.symbol} — position closed externally")
                self._record_close("STARTUP_SYNC_CLOSED", ltp or pos.entry_price)
            elif net_qty > 0:
                logger.info(f"STARTUP_SYNC: broker confirms {net_qty} qty for {pos.symbol} @ {ltp:.0f} — resuming")
                if pos.state == PositionState.ENTRY_PENDING and ltp > 0:
                    self.sm.confirm_entry(ltp)
                    self._trades_today += 1
            else:
                logger.info("STARTUP_SYNC: position state is PENDING/EXIT — will resolve in next tick")

        except Exception as e:
            logger.warning(f"STARTUP_SYNC_ERROR: {e} — proceeding with local state")
