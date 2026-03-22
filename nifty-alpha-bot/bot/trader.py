"""
Live Nifty options trader — Regime-aware, risk-sized, SL-M protected.

Execution model:
  Entry: Aggressive limit order (LTP + 0.5% buffer) for fast fill without market slippage
  SL:    SL-M order placed immediately after fill — exchange-level protection
  Exit:  Cancel SL-M → place market sell on target/force-exit
  Trail: Modify SL-M trigger price when trailing conditions met
"""
from __future__ import annotations

import json
import os as _os
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
from shared.regime_detector import detect_regime, RegimeResult, SL_TARGET_MAP, STRATEGY_PRIORITY
from shared.black_scholes import charges_estimate

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


_STATE_DIR = Path(_os.environ.get("STATE_DIR", "/tmp"))
EVENTS_LOG = _STATE_DIR / "kite_bot_events.jsonl"
NIFTY_TOKEN_FILE = _STATE_DIR / "nifty_instrument_token.txt"


def _log_event(event_type: str, payload: dict) -> None:
    entry = {
        "ts": datetime.now().isoformat(),
        "event": event_type,
        **payload,
    }
    with open(EVENTS_LOG, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


class KiteORBTrader:

    def __init__(self, client: KiteClient) -> None:
        self.client = client
        self.cfg = settings
        self.risk = RiskManager(
            capital=self.cfg.capital,
            max_daily_loss_pct=self.cfg.max_daily_loss_pct,
            max_trades_per_day=self.cfg.max_trades_per_day,
            max_consecutive_losses=self.cfg.max_consecutive_losses,
            max_daily_loss_hard=self.cfg.max_daily_loss_hard,
            risk_per_trade_pct=self.cfg.risk_per_trade_pct,
            lot_size=self.cfg.lot_size,
            max_lots=self.cfg.max_lots,
            max_drawdown_pct=self.cfg.max_drawdown_pct,
        )
        self.sm = PositionStateMachine()
        self._candle_cache: List[Dict] = []
        self._last_candle_date: Optional[date] = None
        self._nifty_token: Optional[int] = None
        self._current_expiry: Optional[date] = None
        self._orb_signal_used = False
        self._reclaim_signal_used = False
        self._heartbeat_count = 0
        self._current_regime: Optional[RegimeResult] = None
        self._regime_logged_today = False
        self._active_slm_order_id: Optional[str] = None

    # ── Time helpers ─────────────────────────────────────────────

    def _now(self) -> datetime:
        return datetime.now()

    def _t(self, time_str: str) -> dtime:
        h, m = map(int, time_str.split(":"))
        return dtime(h, m)

    def _market_active(self, now: datetime) -> bool:
        t = now.time()
        return self._t("09:15") <= t <= self._t(self.cfg.force_exit_time)

    # ── Candle management ─────────────────────────────────────────

    def _refresh_candles(self, now: datetime) -> List[Dict]:
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

    def _roll_day(self, now: datetime) -> None:
        today = now.date()
        if self._last_candle_date != today:
            self._orb_signal_used = False
            self._reclaim_signal_used = False
            self._regime_logged_today = False
            self._current_regime = None
            self._active_slm_order_id = None
            self._current_expiry = self.client.get_nearest_expiry("NIFTY")
            logger.info(f"Day rolled: {today} | Expiry: {self._current_expiry}")

    def _get_vix(self) -> Optional[float]:
        try:
            vix = self.client.get_quote("INDIA VIX", "NSE")
            return vix if vix > 0 else None
        except Exception:
            return None

    # ── Regime detection ─────────────────────────────────────────

    def _detect_regime(self, candles: List[Dict], vix: float) -> RegimeResult:
        regime = detect_regime(candles, vix)

        if not self._regime_logged_today:
            self._regime_logged_today = True
            logger.info(
                f"REGIME: {regime.regime} | {regime.detail} | "
                f"Priority: {', '.join(regime.strategy_priority)}"
            )
            _log_event("REGIME_DETECTED", {
                "regime": regime.regime,
                "adx_proxy": regime.adx_proxy,
                "atr_ratio": regime.atr_ratio,
                "vix": regime.vix,
                "rsi": regime.rsi,
                "strategy_priority": regime.strategy_priority,
            })

        return regime

    # ── Position management ───────────────────────────────────────

    def _manage_active_position(self, now: datetime, candles: List[Dict]) -> None:
        pos = self.sm.position
        if pos.state != PositionState.ACTIVE:
            return

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
        if trail_event and self._active_slm_order_id and self.cfg.use_slm_exit:
            ok = self.client.modify_slm_order(
                self._active_slm_order_id,
                self.sm.position.current_sl,
            )
            if ok:
                logger.info(f"SL-M modified: {trail_event} → trigger={self.sm.position.current_sl:.2f}")
            else:
                logger.warning(f"SL-M modify failed for trail event: {trail_event}")

        # Check exit conditions (target and force-exit handled here;
        # SL is handled by SL-M order at exchange level)
        is_force_exit = now.time() >= self._t(self.cfg.force_exit_time)
        exit_reason = None

        if is_force_exit:
            exit_reason = "FORCE_EXIT"
        elif current_price >= pos.target_price:
            exit_reason = "TARGET_HIT"
        elif not self.cfg.use_slm_exit and current_price <= pos.current_sl:
            exit_reason = "SL_HIT"

        # Check if SL-M order got executed (SL hit at exchange)
        if self._active_slm_order_id and self.cfg.use_slm_exit:
            slm_status = self.client.get_order_status(self._active_slm_order_id)
            if str(slm_status.get("status", "")).upper() == "COMPLETE":
                fill_price = float(slm_status.get("average_price", current_price) or current_price)
                trigger_price = pos.current_sl
                slm_slip = trigger_price - fill_price
                slm_slip_pct = (slm_slip / trigger_price * 100) if trigger_price > 0 else 0

                logger.info(
                    f"SL-M TRIGGERED | trigger={trigger_price:.2f} fill={fill_price:.2f} | "
                    f"SL slippage: ₹{slm_slip:.2f}/unit ({slm_slip_pct:+.2f}%) | "
                    f"Extra loss: ₹{slm_slip * pos.qty:.0f}"
                )
                if abs(slm_slip_pct) > 2.0:
                    logger.warning(
                        f"HIGH SL SLIPPAGE: {slm_slip_pct:+.2f}% — "
                        f"planned SL ₹{trigger_price:.2f}, got ₹{fill_price:.2f}"
                    )

                _log_event("SLM_EXECUTED", {
                    "symbol": pos.symbol,
                    "trigger_price": round(trigger_price, 2),
                    "fill_price": round(fill_price, 2),
                    "slm_slippage": round(slm_slip, 2),
                    "slm_slippage_pct": round(slm_slip_pct, 3),
                    "extra_loss_per_unit": round(slm_slip, 2),
                    "extra_loss_total": round(slm_slip * pos.qty, 2),
                    "qty": pos.qty,
                })

                self._active_slm_order_id = None
                self._record_exit(pos, "SL_HIT", fill_price)
                return

        if exit_reason:
            self._execute_exit(pos, exit_reason, current_price)

    def _execute_exit(self, pos, exit_reason: str, approx_price: float) -> None:
        """Exit by cancelling SL-M and placing a market sell."""
        logger.info(f"EXITING: {pos.symbol} | Reason: {exit_reason} | Price~{approx_price:.2f}")

        # Cancel pending SL-M order
        if self._active_slm_order_id:
            self.client.cancel_order(self._active_slm_order_id)
            self._active_slm_order_id = None

        if self.cfg.paper_mode:
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
            filled = self.client.confirm_fill(order_id, timeout_seconds=15)
            if not filled:
                logger.warning(f"Exit order {order_id} not confirmed filled!")
            status = self.client.get_order_status(order_id)
            fill_price = float(status.get("average_price", approx_price) or approx_price)

        self._record_exit(pos, exit_reason, fill_price)

    def _record_exit(self, pos, exit_reason: str, fill_price: float) -> None:
        planned_sl = pos.current_sl
        self.sm.transition_to_exit_pending("", exit_reason)
        charges = charges_estimate(pos.entry_price, fill_price, pos.qty)
        trade_record = self.sm.confirm_exit(fill_price, charges)

        # Compute SL slippage for SL exits
        sl_slip_info = ""
        if exit_reason == "SL_HIT" and planned_sl > 0:
            sl_slip = planned_sl - fill_price
            sl_slip_pct = (sl_slip / planned_sl * 100) if planned_sl > 0 else 0
            extra_loss = sl_slip * pos.qty
            trade_record["sl_trigger_price"] = round(planned_sl, 2)
            trade_record["sl_fill_price"] = round(fill_price, 2)
            trade_record["sl_slippage"] = round(sl_slip, 2)
            trade_record["sl_slippage_pct"] = round(sl_slip_pct, 3)
            trade_record["sl_extra_loss"] = round(extra_loss, 2)
            if abs(sl_slip) > 0.01:
                sl_slip_info = f"\nSL slip: ₹{sl_slip:.1f}/unit ({sl_slip_pct:+.1f}%), extra: ₹{extra_loss:.0f}"

        net = trade_record["net_pnl"]
        self.risk.record_trade(net)
        _log_event("TRADE_CLOSED", trade_record)

        sign = "+" if net >= 0 else ""
        logger.info(
            f"TRADE CLOSED | {pos.direction} {pos.symbol} | "
            f"Entry={pos.entry_price:.2f} Exit={fill_price:.2f} | "
            f"P&L: {sign}₹{net:.2f} | {exit_reason}"
        )

        self._notify(
            f"{'✅' if net > 0 else '❌'} TRADE CLOSED\n"
            f"{pos.direction} {pos.symbol}\n"
            f"Entry: ₹{pos.entry_price:.0f} → Exit: ₹{fill_price:.0f}\n"
            f"P&L: {sign}₹{net:.0f} ({exit_reason}){sl_slip_info}\n"
            f"Capital: ₹{self.risk.current_capital:,.0f} | DD: {self.risk.drawdown_pct():.1f}%"
        )

    # ── Entry logic ───────────────────────────────────────────────

    def _scan_entry(self, now: datetime, candles: List[Dict], vix: Optional[float]) -> None:
        can_trade, reason = self.risk.can_trade()
        if not can_trade:
            if self._heartbeat_count % (60 // self.cfg.poll_seconds) == 0:
                logger.info(f"RISK BLOCKED: {reason}")
                _log_event("RISK_BLOCKED", {"reason": reason, **self.risk.status()})
            return

        if not self.sm.is_idle:
            return

        strat_state = self.risk.get_strategy_state()
        orb_enabled = strat_state.get("orb_enabled", True)
        vwap_enabled = strat_state.get("vwap_enabled", True)

        current_time = now.time()
        orb_start = self._t(self.cfg.orb_start)
        orb_end = self._t(self.cfg.orb_end)
        entry_close = self._t(self.cfg.entry_window_close)
        reclaim_start = self._t(self.cfg.reclaim_window_start)
        reclaim_end = self._t(self.cfg.reclaim_window_end)

        if not candles:
            return

        last_candle = candles[-1]
        effective_vix = vix or 14.0
        regime = self._detect_regime(candles, effective_vix)
        self._current_regime = regime

        for strategy_name in regime.strategy_priority:
            if strategy_name in ("ORB", "RELAXED_ORB"):
                if not orb_enabled or self._orb_signal_used:
                    continue
                if not (orb_end <= current_time <= entry_close):
                    continue

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
                    "strategy": strategy_name, "regime": regime.regime,
                    "signal": result.get("signal"), "all_passed": result["all_passed"],
                    "filters": {
                        k: {"passed": v.get("passed"), "value": v.get("value"), "detail": v.get("detail", "")}
                        for k, v in result["filters"].items()
                    },
                })
                if not result["all_passed"]:
                    failed = [f"{k}={v.get('value','')}" for k, v in result["filters"].items() if not v.get("passed")]
                    logger.info(f"ORB SKIP [{strategy_name}]: {', '.join(failed[:5])}")

                if result["all_passed"] and result["signal"]:
                    sl_pct, target_pct = SL_TARGET_MAP.get(strategy_name, (0.30, 0.65))
                    self._enter_trade(
                        signal=result["signal"], strategy=strategy_name,
                        candle=last_candle, atr=result["atr"],
                        filter_log=result["filters"], vix=effective_vix,
                        regime=regime, sl_pct_override=sl_pct,
                        target_pct_override=target_pct,
                    )
                    self._orb_signal_used = True
                    return

            elif strategy_name == "VWAP_RECLAIM":
                if not vwap_enabled or self._reclaim_signal_used:
                    continue
                if not (reclaim_start <= current_time <= reclaim_end):
                    continue

                idx = len(candles) - 1
                reclaim = evaluate_vwap_reclaim_signal(
                    candles, idx, vix,
                    reclaim_min_rejection_points=self.cfg.reclaim_min_rejection_points,
                    rsi_period=self.cfg.rsi_period, atr_period=self.cfg.atr_period,
                    vix_max=self.cfg.vix_max,
                )
                reclaim_filters = reclaim.get("filters", {})
                _log_event("RECLAIM_SCAN", {
                    "strategy": "VWAP_RECLAIM", "regime": regime.regime,
                    "signal": reclaim.get("signal"), "all_passed": reclaim["all_passed"],
                    "filters": {
                        k: {"passed": v.get("passed"), "value": v.get("value"), "detail": v.get("detail", "")}
                        for k, v in reclaim_filters.items()
                    } if reclaim_filters else {},
                })
                if not reclaim["all_passed"]:
                    failed = [f"{k}={v.get('value','')}" for k, v in reclaim_filters.items() if not v.get("passed")]
                    logger.info(f"VWAP SKIP: {', '.join(failed[:5]) if failed else 'no signal'}")

                if reclaim["all_passed"] and reclaim["signal"]:
                    sl_pct, target_pct = SL_TARGET_MAP.get("VWAP_RECLAIM", (0.30, 0.65))
                    self._enter_trade(
                        signal=reclaim["signal"], strategy="VWAP_RECLAIM",
                        candle=last_candle, atr=reclaim["atr"],
                        filter_log=reclaim["filters"], vix=effective_vix,
                        regime=regime, sl_pct_override=sl_pct,
                        target_pct_override=target_pct,
                    )
                    self._reclaim_signal_used = True
                    return

    def _enter_trade(
        self,
        signal: str,
        strategy: str,
        candle: Dict,
        atr: Optional[float],
        filter_log: dict,
        vix: float,
        regime: RegimeResult,
        sl_pct_override: float = 0.30,
        target_pct_override: float = 0.65,
    ) -> None:
        signal_time = time.time()
        spot = float(candle["close"])
        is_thursday = datetime.now().date().weekday() == 3

        opt_info = self.client.select_atm_option(
            spot=spot, direction=signal,
            strike_step=self.cfg.strike_step, expiry=self._current_expiry,
        )
        if not opt_info:
            logger.warning(f"No option found for {signal} signal at spot={spot}")
            return

        symbol = opt_info["symbol"]
        strike = opt_info["strike"]
        expiry = opt_info["expiry"]

        quote = self.client.get_quote_details(symbol, "NFO")
        opt_price = quote.get("ltp") or quote.get("mid") or 0
        spread_pct = quote.get("spread_pct") or 0

        if opt_price < self.cfg.min_option_price:
            logger.warning(f"Option price too low: {opt_price:.2f}")
            return
        if opt_price > self.cfg.max_option_price:
            logger.warning(f"Option price too high: {opt_price:.2f}")
            return
        if spread_pct and spread_pct > self.cfg.max_spread_pct:
            logger.warning(f"Spread too wide: {spread_pct:.3f}")
            return

        sl_pct = sl_pct_override
        if is_thursday:
            sl_pct = min(sl_pct, self.cfg.thursday_max_loss_pct)

        effective_risk_pct = self.cfg.risk_per_trade_pct
        if regime.regime == "VOLATILE":
            effective_risk_pct *= 0.5
            logger.info(f"VOLATILE: halving risk to {effective_risk_pct*100:.1f}%")

        size_info = self.risk.compute_position_size(entry_price=opt_price, sl_pct=sl_pct)
        lots = size_info["lots"]
        qty = size_info["qty"]

        sl_price = round(opt_price * (1 - sl_pct), 1)
        target_price = round(opt_price * (1 + target_pct_override), 1)

        logger.info(
            f"SIGNAL: {strategy} {signal} [{regime.regime}] | {symbol} | "
            f"LTP={opt_price:.2f} SL={sl_price:.2f} ({sl_pct*100:.0f}%) "
            f"TGT={target_price:.2f} ({target_pct_override*100:.0f}%) | "
            f"Lots={lots} Qty={qty} Risk=₹{size_info['actual_risk']:.0f}"
        )

        # Place entry order
        if self.cfg.paper_mode:
            order_id = "PAPER"
            fill_price = opt_price
            entry_latency_ms = 0
        else:
            # Aggressive limit: LTP + buffer for fast fill
            if self.cfg.use_limit_orders:
                limit_px = opt_price * (1 + self.cfg.limit_price_buffer_pct)
                resp = self.client.place_order(
                    symbol=symbol, qty=qty, side="BUY",
                    exchange="NFO", product="MIS", limit_price=limit_px,
                )
            else:
                resp = self.client.place_order(
                    symbol=symbol, qty=qty, side="BUY",
                    exchange="NFO", product="MIS",
                )
            order_id = resp.get("order_id", "")
            filled = self.client.confirm_fill(order_id, timeout_seconds=15)
            if not filled:
                logger.error(f"Entry order {order_id} not filled — cancelling")
                self.client.cancel_order(order_id)
                return
            status = self.client.get_order_status(order_id)
            fill_price = float(status.get("average_price", opt_price) or opt_price)
            entry_latency_ms = int((time.time() - signal_time) * 1000)

        logger.info(
            f"FILLED: {fill_price:.2f} (signal LTP was {opt_price:.2f}, "
            f"slip={((fill_price - opt_price) / opt_price * 100):+.2f}%, "
            f"latency={entry_latency_ms}ms)"
        )

        # Recalculate SL/target based on actual fill price
        sl_price = round(fill_price * (1 - sl_pct), 1)
        target_price = round(fill_price * (1 + target_pct_override), 1)

        # Place SL-M order at exchange for protection
        if not self.cfg.paper_mode and self.cfg.use_slm_exit:
            try:
                slm_resp = self.client.place_slm_order(
                    symbol=symbol, qty=qty,
                    trigger_price=sl_price,
                )
                self._active_slm_order_id = slm_resp.get("order_id")
                logger.info(f"SL-M placed: trigger={sl_price:.2f} order_id={self._active_slm_order_id}")
            except Exception as e:
                logger.error(f"SL-M placement failed: {e} — will use software SL")
                self._active_slm_order_id = None

        filter_log["regime"] = {"passed": True, "value": regime.regime, "detail": regime.detail}

        self.sm.transition_to_entry_pending(
            symbol=symbol, direction=signal, option_type=opt_info["option_type"],
            strike=strike, expiry=str(expiry), qty=qty, lots=lots,
            sl_price=sl_price, target_price=target_price,
            spot_at_entry=spot, vix_at_entry=vix,
            strategy=strategy, filter_log=filter_log, entry_order_id=order_id,
        )
        self.sm.confirm_entry(fill_price)

        _log_event("ENTRY", {
            "strategy": strategy, "regime": regime.regime, "signal": signal,
            "symbol": symbol, "fill_price": fill_price,
            "signal_ltp": opt_price,
            "slippage_pct": round((fill_price - opt_price) / opt_price * 100, 3),
            "entry_latency_ms": entry_latency_ms,
            "sl": sl_price, "sl_pct": sl_pct,
            "target": target_price, "target_pct": target_pct_override,
            "spot": spot, "vix": vix,
            "lots": lots, "qty": qty, "risk_amount": size_info["actual_risk"],
            "slm_order_id": self._active_slm_order_id,
            "order_type": "LIMIT" if self.cfg.use_limit_orders else "MARKET",
        })

        self._notify(
            f"🚀 ENTRY: {strategy} {signal} [{regime.regime}]\n"
            f"{symbol}\n"
            f"Fill: ₹{fill_price:.0f} (slip {((fill_price - opt_price) / opt_price * 100):+.1f}%)\n"
            f"SL: ₹{sl_price:.0f} ({sl_pct*100:.0f}%) | TGT: ₹{target_price:.0f}\n"
            f"Risk: ₹{size_info['actual_risk']:.0f} | SL-M: {'YES' if self._active_slm_order_id else 'NO'}"
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
        logger.info(f"{'='*60}")
        logger.info(f" KITE REGIME-AWARE TRADER [{mode}]")
        logger.info(f" Capital: ₹{self.cfg.capital:,.0f} | Lot size: {self.cfg.lot_size}")
        logger.info(f" Risk/trade: {self.cfg.risk_per_trade_pct*100:.1f}% | Max lots: {self.cfg.max_lots}")
        logger.info(f" Daily loss limit: {self.cfg.max_daily_loss_pct*100:.0f}% (2R) | Hard: ₹{self.cfg.max_daily_loss_hard:,.0f}")
        logger.info(f" Drawdown halt: {self.cfg.max_drawdown_pct:.0f}%")
        logger.info(f" Entry: {'Aggressive LIMIT' if self.cfg.use_limit_orders else 'MARKET'} | SL: {'SL-M' if self.cfg.use_slm_exit else 'Software'}")
        logger.info(f" Max trades: {self.cfg.max_trades_per_day}/day | VIX max: {self.cfg.vix_max}")
        logger.info(f"{'='*60}")

        self._notify(
            f"🤖 Bot started [{mode}]\n"
            f"Capital: ₹{self.cfg.capital:,.0f}\n"
            f"Risk/trade: {self.cfg.risk_per_trade_pct*100:.1f}%\n"
            f"DD halt: {self.cfg.max_drawdown_pct:.0f}%\n"
            f"SL: {'SL-M' if self.cfg.use_slm_exit else 'Software'}"
        )

        api_failures = 0

        while True:
            try:
                now = self._now()

                if now.weekday() >= 5:
                    time.sleep(60)
                    continue

                if not self._market_active(now):
                    time.sleep(self.cfg.poll_seconds)
                    continue

                self._roll_day(now)
                candles = self._refresh_candles(now)
                vix = self._get_vix()

                self._heartbeat_count += 1
                hb_interval = max(1, 60 // self.cfg.poll_seconds)
                if self._heartbeat_count % hb_interval == 0:
                    rs = self.risk.status()
                    regime_str = self._current_regime.regime if self._current_regime else "?"
                    hb_data = {
                        "mode": mode,
                        "regime": regime_str,
                        "trades_today": rs["trades_today"],
                        "max_trades": self.cfg.max_trades_per_day,
                        "daily_pnl": rs["daily_pnl"],
                        "current_capital": rs["current_capital"],
                        "peak_capital": rs["peak_capital"],
                        "drawdown_pct": rs["drawdown_pct"],
                        "vix": vix or 0,
                        "state": self.sm.position.state.value,
                        "consecutive_losses": rs["consecutive_losses"],
                        "remaining_daily_loss": rs["remaining_daily_loss"],
                        "halted": rs["trading_halted"],
                        "halt_reason": rs.get("halt_reason", ""),
                    }
                    logger.info(
                        f"HEARTBEAT [{mode}] "
                        f"regime={regime_str} "
                        f"trades={rs['trades_today']}/{self.cfg.max_trades_per_day} "
                        f"pnl=₹{rs['daily_pnl']:+.0f} "
                        f"capital=₹{rs['current_capital']:,.0f} "
                        f"dd={rs['drawdown_pct']:.1f}% "
                        f"vix={vix or '?'} "
                        f"state={self.sm.position.state.value}"
                    )
                    _log_event("HEARTBEAT", hb_data)

                if self.sm.is_active:
                    self._manage_active_position(now, candles)
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
                    logger.warning(f"CIRCUIT BREAKER: {api_failures} failures. Cooling {cooldown}s")
                    time.sleep(cooldown)
                    api_failures = 0

            sys.stdout.flush()
            time.sleep(self.cfg.poll_seconds)
