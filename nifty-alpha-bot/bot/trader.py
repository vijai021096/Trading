"""
Main live trading loop — Zerodha Kite edition.
Replaces groww.py's ORBLiveTrader.

Architecture: synchronous poll loop (same as groww.py pattern)
with state machine for position management.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import date, datetime, time as dtime
from pathlib import Path
from typing import Any, Dict, List, Optional

from kite_broker.client import KiteClient
from kite_broker.token_manager import get_valid_token, schedule_daily_refresh
from bot.risk_manager import RiskManager
from bot.state_machine import PositionStateMachine, PositionState
from shared.config import settings
from shared.orb_engine import evaluate_orb_signal, compute_sl_target
from shared.vwap_reclaim_engine import evaluate_vwap_reclaim_signal
from shared.black_scholes import charges_estimate

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


EVENTS_LOG = Path("/tmp/kite_bot_events.jsonl")
NIFTY_TOKEN_FILE = Path("/tmp/nifty_instrument_token.txt")


def _log_event(event_type: str, payload: dict) -> None:
    entry = {
        "ts": datetime.now().isoformat(),
        "event": event_type,
        **payload,
    }
    with open(EVENTS_LOG, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


class KiteORBTrader:
    """
    Live Nifty options trader using ORB + VWAP Reclaim strategies.
    Migrated from groww.py to Zerodha Kite.
    """

    def __init__(self, client: KiteClient) -> None:
        self.client = client
        self.cfg = settings
        self.risk = RiskManager(
            capital=self.cfg.capital,
            max_daily_loss_pct=self.cfg.max_daily_loss_pct,
            max_trades_per_day=self.cfg.max_trades_per_day,
            max_consecutive_losses=self.cfg.max_consecutive_losses,
            max_daily_loss_hard=self.cfg.max_daily_loss_hard,
        )
        self.sm = PositionStateMachine()
        self._candle_cache: List[Dict] = []
        self._last_candle_date: Optional[date] = None
        self._nifty_token: Optional[int] = None
        self._current_expiry: Optional[date] = None
        self._orb_signal_used = False
        self._reclaim_signal_used = False
        self._heartbeat_count = 0

    # ── Time helpers ─────────────────────────────────────────────

    def _now(self) -> datetime:
        return datetime.now()

    def _t(self, time_str: str) -> dtime:
        h, m = map(int, time_str.split(":"))
        return dtime(h, m)

    def _in_window(self, t: dtime, start_str: str, end_str: str) -> bool:
        return self._t(start_str) <= t <= self._t(end_str)

    def _market_active(self, now: datetime) -> bool:
        t = now.time()
        return self._t("09:15") <= t <= self._t(self.cfg.force_exit_time)

    # ── Candle management ─────────────────────────────────────────

    def _refresh_candles(self, now: datetime) -> List[Dict]:
        """Fetch today's 5m candles from Kite."""
        if self._nifty_token is None:
            self._nifty_token = self.client.get_nifty_token()
            if self._nifty_token is None:
                logger.warning("Could not get NIFTY instrument token")
                return self._candle_cache

        today = now.date()
        from_dt = datetime(today.year, today.month, today.day, 9, 0, 0)
        to_dt = now

        try:
            self._candle_cache = self.client.get_candles(
                self._nifty_token, from_dt, to_dt, "5minute"
            )
            if today != self._last_candle_date:
                self._last_candle_date = today
                logger.info(f"New trading day: {today}")
        except Exception as e:
            logger.warning(f"Candle fetch failed: {e}")

        return self._candle_cache

    # ── Daily reset ───────────────────────────────────────────────

    def _roll_day(self, now: datetime) -> None:
        today = now.date()
        if self._last_candle_date != today:
            self._orb_signal_used = False
            self._reclaim_signal_used = False
            self._current_expiry = self.client.get_nearest_expiry("NIFTY")
            logger.info(f"Day rolled: {today} | Expiry: {self._current_expiry}")

    # ── VIX fetching ─────────────────────────────────────────────

    def _get_vix(self) -> Optional[float]:
        try:
            # Kite provides India VIX as NSE:INDIA VIX
            vix = self.client.get_quote("INDIA VIX", "NSE")
            return vix if vix > 0 else None
        except Exception:
            return None

    # ── Position management ───────────────────────────────────────

    def _manage_active_position(self, now: datetime, candles: List[Dict]) -> None:
        """Check SL/target/trail for open position."""
        pos = self.sm.position
        if pos.state != PositionState.ACTIVE:
            return

        # Get current option price
        current_price = self.client.get_quote(pos.symbol, "NFO")
        if current_price <= 0:
            logger.warning(f"Could not get quote for {pos.symbol}")
            return

        # Update trailing stop
        trail_event = self.sm.update_trailing_stop(
            current_price,
            trail_trigger_pct=self.cfg.trail_trigger_pct,
            trail_lock_step_pct=self.cfg.trail_lock_step_pct,
            break_even_trigger_pct=self.cfg.break_even_trigger_pct,
        )
        if trail_event:
            logger.info(f"Trail event: {trail_event} | SL={self.sm.position.current_sl:.2f}")

        # Check exit conditions
        is_force_exit = now.time() >= self._t(self.cfg.force_exit_time)
        exit_reason = None

        if is_force_exit:
            exit_reason = "FORCE_EXIT"
        elif current_price <= pos.current_sl:
            exit_reason = "SL_HIT"
        elif current_price >= pos.target_price:
            exit_reason = "TARGET_HIT"

        if exit_reason:
            self._execute_exit(pos, exit_reason, current_price)

    def _execute_exit(
        self,
        pos,
        exit_reason: str,
        approx_price: float,
    ) -> None:
        """Place exit order and record trade."""
        logger.info(f"EXITING position: {pos.symbol} | Reason: {exit_reason} | Price≈{approx_price:.2f}")

        if self.cfg.paper_mode:
            # Paper mode: simulate fill at approximate price
            fill_price = approx_price
            order_id = "PAPER"
        else:
            resp = self.client.place_order(
                symbol=pos.symbol,
                qty=pos.qty,
                side="SELL",
                exchange="NFO",
                product="MIS",
            )
            order_id = resp.get("order_id", "")
            # Wait for fill
            filled = self.client.confirm_fill(order_id, timeout_seconds=15)
            if not filled:
                logger.warning(f"Exit order {order_id} not confirmed filled!")
            status = self.client.get_order_status(order_id)
            fill_price = float(status.get("average_price", approx_price) or approx_price)

        self.sm.transition_to_exit_pending(order_id, exit_reason)
        charges = charges_estimate(pos.entry_price, fill_price, pos.qty)
        trade_record = self.sm.confirm_exit(fill_price, charges)

        net = trade_record["net_pnl"]
        self.risk.record_trade(net)
        _log_event("TRADE_CLOSED", trade_record)

        sign = "+" if net >= 0 else ""
        logger.info(
            f"TRADE CLOSED | {pos.direction} {pos.symbol} | "
            f"Entry={pos.entry_price:.2f} Exit={fill_price:.2f} | "
            f"P&L: {sign}₹{net:.2f} | {exit_reason}"
        )

        # Telegram notification
        self._notify(
            f"{'✅' if net > 0 else '❌'} TRADE CLOSED\n"
            f"{pos.direction} {pos.symbol}\n"
            f"Entry: ₹{pos.entry_price:.0f} → Exit: ₹{fill_price:.0f}\n"
            f"P&L: {sign}₹{net:.0f} ({exit_reason})"
        )

    # ── Entry logic ───────────────────────────────────────────────

    def _scan_entry(self, now: datetime, candles: List[Dict], vix: Optional[float]) -> None:
        """Evaluate entry signals and place entry orders."""
        can_trade, reason = self.risk.can_trade()
        if not can_trade:
            return

        if not self.sm.is_idle:
            return

        current_time = now.time()
        orb_start = self._t(self.cfg.orb_start)
        orb_end = self._t(self.cfg.orb_end)
        entry_close = self._t(self.cfg.entry_window_close)
        reclaim_start = self._t(self.cfg.reclaim_window_start)
        reclaim_end = self._t(self.cfg.reclaim_window_end)

        if not candles:
            return

        last_candle = candles[-1]

        # ── ORB signal ────────────────────────────────────────────
        if (
            not self._orb_signal_used
            and orb_end <= current_time <= entry_close
        ):
            result = evaluate_orb_signal(
                candles, last_candle, vix,
                orb_start=orb_start, orb_end=orb_end,
                min_orb_range_points=self.cfg.min_orb_range_points,
                max_orb_range_points=self.cfg.max_orb_range_points,
                breakout_buffer_pct=self.cfg.breakout_buffer_pct,
                min_breakout_body_ratio=self.cfg.min_breakout_body_ratio,
                min_volume_surge_ratio=self.cfg.min_volume_surge_ratio,
                ema_fast=self.cfg.ema_fast, ema_slow=self.cfg.ema_slow,
                rsi_period=self.cfg.rsi_period, atr_period=self.cfg.atr_period,
                require_vwap_confirmation=self.cfg.require_vwap_confirmation,
                vwap_buffer_points=self.cfg.vwap_buffer_points,
                rsi_bull_min=self.cfg.rsi_bull_min, rsi_bear_max=self.cfg.rsi_bear_max,
                rsi_overbought_skip=self.cfg.rsi_overbought_skip,
                rsi_oversold_skip=self.cfg.rsi_oversold_skip,
                vix_max=self.cfg.vix_max,
            )
            _log_event("ORB_SCAN", {
                "signal": result.get("signal"),
                "all_passed": result["all_passed"],
                "filters": {k: v.get("passed") for k, v in result["filters"].items()},
            })

            if result["all_passed"] and result["signal"]:
                self._enter_trade(
                    signal=result["signal"],
                    strategy="ORB",
                    candle=last_candle,
                    atr=result["atr"],
                    filter_log=result["filters"],
                    vix=vix or 14.0,
                )
                self._orb_signal_used = True

        # ── VWAP Reclaim signal ────────────────────────────────────
        elif (
            not self._reclaim_signal_used
            and reclaim_start <= current_time <= reclaim_end
        ):
            idx = len(candles) - 1
            reclaim = evaluate_vwap_reclaim_signal(
                candles, idx, vix,
                reclaim_min_rejection_points=self.cfg.reclaim_min_rejection_points,
                rsi_period=self.cfg.rsi_period, atr_period=self.cfg.atr_period,
                vix_max=self.cfg.vix_max,
            )
            _log_event("RECLAIM_SCAN", {
                "signal": reclaim.get("signal"),
                "all_passed": reclaim["all_passed"],
            })

            if reclaim["all_passed"] and reclaim["signal"]:
                self._enter_trade(
                    signal=reclaim["signal"],
                    strategy="VWAP_RECLAIM",
                    candle=last_candle,
                    atr=reclaim["atr"],
                    filter_log=reclaim["filters"],
                    vix=vix or 14.0,
                )
                self._reclaim_signal_used = True

    def _enter_trade(
        self,
        signal: str,
        strategy: str,
        candle: Dict,
        atr: Optional[float],
        filter_log: dict,
        vix: float,
    ) -> None:
        """Select option, place entry order, transition state machine."""
        spot = float(candle["close"])
        is_thursday = datetime.now().date().weekday() == 3
        lots = self.cfg.thursday_max_lots if is_thursday else self.cfg.live_max_lots
        qty = lots * self.cfg.lot_size

        # Find ATM option
        opt_info = self.client.select_atm_option(
            spot=spot,
            direction=signal,
            strike_step=self.cfg.strike_step,
            expiry=self._current_expiry,
        )
        if not opt_info:
            logger.warning(f"No option found for {signal} signal at spot={spot}")
            return

        symbol = opt_info["symbol"]
        strike = opt_info["strike"]
        expiry = opt_info["expiry"]

        # Validate option quality
        quote = self.client.get_quote_details(symbol, "NFO")
        opt_price = quote.get("ltp") or quote.get("mid") or 0
        spread_pct = quote.get("spread_pct") or 0

        if opt_price < self.cfg.min_option_price:
            logger.warning(f"Option price too low: {opt_price:.2f} < {self.cfg.min_option_price}")
            return
        if opt_price > self.cfg.max_option_price:
            logger.warning(f"Option price too high: {opt_price:.2f} > {self.cfg.max_option_price}")
            return
        if spread_pct and spread_pct > self.cfg.max_spread_pct:
            logger.warning(f"Spread too wide: {spread_pct:.3f} > {self.cfg.max_spread_pct}")
            return

        # Compute SL/target
        sl_target = compute_sl_target(
            opt_price, signal, atr,
            atr_sl_multiplier=self.cfg.atr_sl_multiplier,
            atr_sl_min_pct=self.cfg.atr_sl_min_pct,
            atr_sl_max_pct=self.cfg.atr_sl_max_pct,
            rr_min=self.cfg.rr_min,
            is_thursday=is_thursday,
            thursday_max_loss_pct=self.cfg.thursday_max_loss_pct,
        )

        logger.info(
            f"SIGNAL: {strategy} {signal} | {symbol} | "
            f"LTP={opt_price:.2f} SL={sl_target['sl_price']:.2f} TGT={sl_target['target_price']:.2f}"
        )

        # Place entry order
        if self.cfg.paper_mode:
            order_id = "PAPER"
            fill_price = opt_price
        else:
            resp = self.client.place_order(
                symbol=symbol,
                qty=qty,
                side="BUY",
                exchange="NFO",
                product="MIS",
            )
            order_id = resp.get("order_id", "")
            filled = self.client.confirm_fill(order_id, timeout_seconds=15)
            if not filled:
                logger.error(f"Entry order {order_id} not confirmed — cancelling")
                self.client.cancel_order(order_id)
                return
            status = self.client.get_order_status(order_id)
            fill_price = float(status.get("average_price", opt_price) or opt_price)

        # Transition state machine
        self.sm.transition_to_entry_pending(
            symbol=symbol,
            direction=signal,
            option_type=opt_info["option_type"],
            strike=strike,
            expiry=str(expiry),
            qty=qty,
            lots=lots,
            sl_price=sl_target["sl_price"],
            target_price=sl_target["target_price"],
            spot_at_entry=spot,
            vix_at_entry=vix,
            strategy=strategy,
            filter_log=filter_log,
            entry_order_id=order_id,
        )
        self.sm.confirm_entry(fill_price)

        _log_event("ENTRY", {
            "strategy": strategy,
            "signal": signal,
            "symbol": symbol,
            "fill_price": fill_price,
            "sl": sl_target["sl_price"],
            "target": sl_target["target_price"],
            "spot": spot,
            "vix": vix,
        })

        self._notify(
            f"🚀 ENTRY: {strategy} {signal}\n"
            f"{symbol}\n"
            f"Entry: ₹{fill_price:.0f}\n"
            f"SL: ₹{sl_target['sl_price']:.0f} ({self.cfg.atr_sl_max_pct*100:.0f}% max)\n"
            f"Target: ₹{sl_target['target_price']:.0f} (RR {self.cfg.rr_min}x)"
        )

    # ── Notifications ─────────────────────────────────────────────

    def _notify(self, message: str) -> None:
        if not self.cfg.telegram_bot_token or not self.cfg.telegram_chat_id:
            return
        try:
            import httpx
            httpx.post(
                f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/sendMessage",
                json={"chat_id": self.cfg.telegram_chat_id, "text": message},
                timeout=5,
            )
        except Exception:
            pass

    # ── Main loop ──────────────────────────────────────────────────

    def run(self) -> None:
        mode = "PAPER" if self.cfg.paper_mode else "LIVE"
        logger.info(f"{'='*55}")
        logger.info(f" KITE ORB TRADER STARTING [{mode}]")
        logger.info(f" Capital: ₹{self.cfg.capital:,.0f} | Lot size: {self.cfg.lot_size}")
        logger.info(f" ORB: {self.cfg.orb_start}-{self.cfg.orb_end}")
        logger.info(f" SL: {self.cfg.atr_sl_min_pct*100:.0f}%-{self.cfg.atr_sl_max_pct*100:.0f}% ATR | RR: {self.cfg.rr_min}x")
        logger.info(f" VIX max: {self.cfg.vix_max} | Max trades: {self.cfg.max_trades_per_day}/day")
        logger.info(f"{'='*55}")

        self._notify(f"🤖 Bot started [{mode}] | Capital: ₹{self.cfg.capital:,.0f}")

        api_failures = 0

        while True:
            try:
                now = self._now()

                # Skip weekends
                if now.weekday() >= 5:
                    time.sleep(60)
                    continue

                if not self._market_active(now):
                    time.sleep(self.cfg.poll_seconds)
                    continue

                self._roll_day(now)

                # Refresh candles
                candles = self._refresh_candles(now)
                vix = self._get_vix()

                # Heartbeat every 60 polls
                self._heartbeat_count += 1
                if self._heartbeat_count % (60 // self.cfg.poll_seconds) == 0:
                    rs = self.risk.status()
                    logger.info(
                        f"HEARTBEAT [{mode}] "
                        f"trades={rs['trades_today']}/{self.cfg.max_trades_per_day} "
                        f"pnl=₹{rs['daily_pnl']:+.0f} "
                        f"vix={vix or '?'} "
                        f"state={self.sm.position.state.value}"
                    )

                # Manage open position
                if self.sm.is_active:
                    self._manage_active_position(now, candles)
                # Scan for new entries
                elif self.sm.is_idle:
                    self._scan_entry(now, candles, vix)

                api_failures = 0

            except KeyboardInterrupt:
                logger.info("Bot stopped by user.")
                break
            except Exception as e:
                api_failures += 1
                logger.error(f"LOOP ERROR ({api_failures}): {e}")
                traceback.print_exc()
                _log_event("LOOP_ERROR", {"error": str(e), "failures": api_failures})

                if api_failures >= self.cfg.api_circuit_breaker_failures:
                    cooldown = self.cfg.api_circuit_breaker_cooldown_seconds
                    logger.warning(f"CIRCUIT BREAKER: {api_failures} failures. Cooling down {cooldown}s")
                    time.sleep(cooldown)
                    api_failures = 0

            sys.stdout.flush()
            time.sleep(self.cfg.poll_seconds)
