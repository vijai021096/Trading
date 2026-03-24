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

import pandas as pd

from kite_broker.client import KiteClient
from kite_broker.token_manager import get_valid_token, schedule_daily_refresh
from bot.risk_manager import RiskManager
from bot.state_machine import PositionStateMachine, PositionState
from shared.config import settings
from shared.orb_engine import evaluate_orb_signal, compute_sl_target
from shared.vwap_reclaim_engine import evaluate_vwap_reclaim_signal
from shared.ema_pullback_engine import evaluate_ema_pullback_signal
from shared.momentum_breakout_engine import evaluate_momentum_breakout_signal
from shared.regime_detector import detect_regime, RegimeResult, SL_TARGET_MAP, STRATEGY_PRIORITY
from shared.trend_detector import (
    detect_trend, TrendResult, TrendState, STRATEGY_PRIORITY_BY_TREND,
    SL_TARGET_BY_STRATEGY, TIER_PARAMS, assign_tier, compute_signal_confidence,
)
from shared.quality_filter import compute_trade_quality
from shared.black_scholes import charges_estimate
from shared.regime_classifier import (
    classify_regime_live, DailyRegime, RegimeClassifierConfig, regime_conflicts_with_trend,
)
from backtest.daily_backtest_engine import evaluate_live_daily_adaptive
from bot.daily_adaptive_support import (
    daily_backtest_config_from_settings,
    load_anchor_ym,
    save_anchor_ym,
)

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
        self._trades_today = 0
        self._strategies_used: Dict[str, int] = {}
        self._heartbeat_count = 0
        self._current_regime: Optional[RegimeResult] = None
        self._current_trend: Optional[TrendResult] = None
        self._daily_regime: Optional[DailyRegime] = None
        self._regime_logged_today = False
        self._trend_logged_today = False
        self._daily_regime_classified = False
        self._day_stopped_profit = False
        self._last_broker_sync: float = 0.0
        self._orb_signal_used = False
        self._momentum_signal_used = False
        self._ema_pullback_signal_used = False
        self._reclaim_signal_used = False
        self._daily_adaptive_plan: Optional[Dict[str, Any]] = None

        # Restore SL-M order ID from persisted state (survives restarts)
        self._active_slm_order_id: Optional[str] = self.sm.position.slm_order_id or None
        if self._active_slm_order_id:
            logger.info(f"Restored SL-M order ID from state: {self._active_slm_order_id}")

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

    def _refresh_daily_nifty_df(self) -> Optional[pd.DataFrame]:
        if self._nifty_token is None:
            self._nifty_token = self.client.get_nifty_token()
            if self._nifty_token is None:
                logger.warning("Could not get NIFTY token for daily bars")
                return None
        from datetime import timedelta

        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=520)
        try:
            candles = self.client.get_candles(self._nifty_token, from_dt, to_dt, "day")
            if not candles:
                return None
            return pd.DataFrame(candles)
        except Exception as e:
            logger.warning(f"Daily NIFTY fetch failed: {e}")
            return None

    def _in_daily_adaptive_window(self, now: datetime) -> bool:
        t = now.time()
        return self._t(self.cfg.daily_adaptive_window_start) <= t <= self._t(
            self.cfg.daily_adaptive_window_end
        )

    def _roll_day(self, now: datetime) -> None:
        today = now.date()
        if self._last_candle_date != today:
            self._trades_today = 0
            self._strategies_used = {}
            self._regime_logged_today = False
            self._trend_logged_today = False
            self._daily_regime_classified = False
            self._day_stopped_profit = False
            self._current_trend = None
            self._current_regime = None
            self._daily_regime = None
            self._active_slm_order_id = None
            self._daily_adaptive_plan = None
            self._orb_signal_used = False
            self._momentum_signal_used = False
            self._ema_pullback_signal_used = False
            self._reclaim_signal_used = False
            self._current_expiry = self.client.get_nearest_expiry("NIFTY")
            logger.info(f"Day rolled: {today} | Expiry: {self._current_expiry}")

            # Classify daily regime once per day
            vix = self._get_vix()
            self._daily_regime = classify_regime_live(self.client, today, vix)
            self._daily_regime_classified = True

            if self.cfg.trading_engine.strip().lower() == "daily_adaptive" and load_anchor_ym() is None:
                save_anchor_ym(today.year, today.month)

            regime_msg = (
                f"DAILY REGIME: {self._daily_regime.name}\n"
                f"Direction: {self._daily_regime.allowed_direction or 'ANY'}\n"
                f"Strategies: {', '.join(self._daily_regime.allowed_strategies)}\n"
                f"OTM: {self._daily_regime.otm_offset} | Max trades: {self._daily_regime.execution.max_trades}\n"
                f"Window: {self._daily_regime.execution.window_start}-{self._daily_regime.execution.window_end}\n"
                f"Risk: {self._daily_regime.execution.risk_pct*100:.0f}%\n"
                f"Detail: {self._daily_regime.detail}"
            )
            logger.info(regime_msg)
            _log_event("DAILY_REGIME", {
                "regime": self._daily_regime.name,
                "direction": self._daily_regime.allowed_direction,
                "strategies": self._daily_regime.allowed_strategies,
                "otm_offset": self._daily_regime.otm_offset,
                "should_trade": self._daily_regime.should_trade,
                "max_trades": self._daily_regime.execution.max_trades,
                "risk_pct": self._daily_regime.execution.risk_pct,
                "scores": self._daily_regime.scores,
                "detail": self._daily_regime.detail,
            })
            self._notify(f"📊 {regime_msg}")

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

    def _detect_trend(self, candles: List[Dict], vix: float) -> TrendResult:
        trend = detect_trend(candles, vix)

        if not self._trend_logged_today:
            self._trend_logged_today = True
            logger.info(
                f"TREND: {trend.state.value} [{trend.direction}] | "
                f"conviction={trend.conviction:.2f} risk_mult={trend.risk_multiplier:.2f} | "
                f"{trend.detail}"
            )
            _log_event("TREND_DETECTED", {
                "state": trend.state.value,
                "direction": trend.direction,
                "conviction": trend.conviction,
                "risk_multiplier": trend.risk_multiplier,
                "strategy_priority": trend.strategy_priority,
                "scores": trend.scores,
            })
        elif (self._current_trend is not None and
              self._current_trend.state != trend.state):
            # Log state change intraday
            logger.info(
                f"TREND SHIFT: {self._current_trend.state.value} → {trend.state.value} "
                f"| conviction={trend.conviction:.2f} | {trend.detail}"
            )
            _log_event("TREND_SHIFTED", {
                "from": self._current_trend.state.value,
                "to": trend.state.value,
                "conviction": trend.conviction,
                "risk_multiplier": trend.risk_multiplier,
                "scores": trend.scores,
            })

        self._current_trend = trend
        return trend

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
            if pos.state != PositionState.ACTIVE:
                return
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
                self.sm.position.slm_order_id = ""
                from bot.state_machine import save_position
                save_position(self.sm.position)
                self._record_exit(pos, "SL_HIT", fill_price)
                return

        if exit_reason:
            self._execute_exit(pos, exit_reason, current_price)

    def _execute_exit(self, pos, exit_reason: str, approx_price: float) -> None:
        """Exit by cancelling SL-M and placing a market sell."""
        logger.info(f"EXITING: {pos.symbol} | Reason: {exit_reason} | Price~{approx_price:.2f}")

        # Cancel pending SL-M order
        if self._active_slm_order_id:
            try:
                self.client.cancel_order(self._active_slm_order_id)
            except Exception as e:
                logger.warning(f"SL-M cancel failed (may already be done): {e}")
            self._active_slm_order_id = None
            self.sm.position.slm_order_id = ""
            from bot.state_machine import save_position
            save_position(self.sm.position)

        if self.cfg.paper_mode:
            fill_price = approx_price
            order_id = "PAPER"
        else:
            # For force-exit, retry up to 3 times to guarantee exit before market close
            max_attempts = 3 if exit_reason == "FORCE_EXIT" else 1
            fill_price = approx_price
            order_id = ""

            for attempt in range(1, max_attempts + 1):
                try:
                    resp = self.client.place_order(
                        symbol=pos.symbol,
                        qty=pos.qty,
                        side="SELL",
                        exchange="NFO",
                        product="MIS",
                    )
                    order_id = resp.get("order_id", "")
                    filled = self.client.confirm_fill(order_id, timeout_seconds=15)

                    if filled:
                        status = self.client.get_order_status(order_id)
                        fill_price = float(status.get("average_price", approx_price) or approx_price)
                        logger.info(f"Exit confirmed: order={order_id} price={fill_price:.2f} (attempt {attempt})")
                        break
                    else:
                        logger.warning(f"Exit order {order_id} not filled (attempt {attempt}/{max_attempts}) — cancelling and retrying")
                        try:
                            self.client.cancel_order(order_id)
                        except Exception:
                            pass
                        if attempt < max_attempts:
                            time.sleep(2)
                except Exception as e:
                    logger.error(f"Exit order failed (attempt {attempt}/{max_attempts}): {e}")
                    if attempt < max_attempts:
                        time.sleep(2)
            else:
                logger.error(f"EXIT FAILED after {max_attempts} attempts — position may still be open. Check Kite manually!")
                _log_event("EXIT_FAILED", {
                    "symbol": pos.symbol, "reason": exit_reason,
                    "attempts": max_attempts, "approx_price": approx_price,
                })

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

        # Stop trading for the day if profit >= 2R
        if net > 0 and pos.entry_price > 0:
            # Use original SL pct (distance from entry to initial sl), clamped positive
            # current_sl may be above entry when trailing — use cfg fallback in that case
            raw_sl_pct = (pos.entry_price - pos.current_sl) / pos.entry_price if pos.current_sl > 0 else 0
            sl_pct_used = raw_sl_pct if raw_sl_pct > 0 else self.cfg.risk_per_trade_pct
            one_r = pos.entry_price * sl_pct_used * pos.qty
            daily_pnl = self.risk.status().get("daily_pnl", 0)
            if daily_pnl >= one_r * 2:
                self._day_stopped_profit = True
                logger.info(f"DAY STOPPED: Profit ₹{daily_pnl:.0f} >= 2R (₹{one_r*2:.0f})")
                self._notify(f"🎯 DAY STOPPED — Profit ₹{daily_pnl:.0f} >= 2R")

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

    def _scan_entry_daily_adaptive(self, now: datetime, vix: Optional[float]) -> None:
        """Same rules as daily backtest: last completed daily bar + live VIX, multi-leg day plan."""
        can_trade, reason = self.risk.can_trade()
        if not can_trade:
            if self._heartbeat_count % max(1, (60 // max(1, self.cfg.poll_seconds))) == 0:
                logger.info(f"RISK BLOCKED (daily_adaptive): {reason}")
                _log_event(
                    "RISK_BLOCKED",
                    {"reason": reason, "engine": "daily_adaptive", **self.risk.status()},
                )
            return

        if not self.sm.is_idle:
            return

        if self._day_stopped_profit:
            return

        if not self._in_daily_adaptive_window(now):
            return

        # Intraday "SKIP" day classifier does not block daily_adaptive (different model).
        effective_vix = float(vix if vix is not None else self._get_vix() or 14.0)

        if self._daily_adaptive_plan is None:
            df = self._refresh_daily_nifty_df()
            if df is None or df.empty:
                logger.warning("DAILY_ADAPTIVE: could not load daily NIFTY dataframe")
                return
            dcfg = daily_backtest_config_from_settings(self.cfg)
            anchor = load_anchor_ym()
            st = self.risk.status()
            ev = evaluate_live_daily_adaptive(
                df,
                effective_vix,
                dcfg,
                strategy_filter=self.cfg.daily_strategy_filter,
                drop_incomplete_today=True,
                anchor_ym=anchor,
                capital=float(st.get("current_capital", self.cfg.capital)),
                peak_equity=float(st.get("peak_capital", self.cfg.capital)),
                consecutive_losses=int(st.get("consecutive_losses", 0)),
            )
            if not ev.get("ok"):
                if self._heartbeat_count % max(1, (60 // max(1, self.cfg.poll_seconds))) == 0:
                    logger.warning(
                        f"DAILY_ADAPTIVE eval not ready: {ev.get('error')} "
                        f"(will retry next poll)"
                    )
                return

            self._daily_adaptive_plan = ev
            _log_event(
                "DAILY_ADAPTIVE_SCAN",
                {**ev, "anchor_ym": list(anchor) if anchor else None},
            )
            logger.info(
                f"DAILY_ADAPTIVE_SCAN ok={ev.get('ok')} regime={ev.get('regime')} "
                f"legs={len(ev.get('executable_legs') or [])} cap={ev.get('day_trade_cap')} "
                f"vix={effective_vix:.2f}"
            )

        plan = self._daily_adaptive_plan or {}
        if not plan.get("ok"):
            return

        legs: List[Dict[str, Any]] = plan.get("executable_legs") or []
        day_cap = int(plan.get("day_trade_cap") or self.cfg.max_trades_per_day)
        day_cap = min(day_cap, self.cfg.max_trades_per_day)
        idx = int(self.risk.status().get("trades_today", 0))
        if idx >= len(legs) or idx >= day_cap:
            return

        bw = plan.get("breakout_watch") or {}
        stub_regime = RegimeResult(
            regime="DAILY_ADAPTIVE",
            adx_proxy=0.0,
            atr_current=1.0,
            atr_avg=1.0,
            atr_ratio=1.0,
            vix=effective_vix,
            rsi=float(bw.get("rsi14") or 50),
            ema_fast=float(bw.get("ema8") or 0),
            ema_slow=float(bw.get("ema21") or 0),
            strategy_priority=[],
            sl_target={},
            detail=f"{plan.get('regime')} | signal_bar={plan.get('signal_bar_date')}",
        )

        spot = self.client.get_quote("NIFTY 50", "NSE")
        if spot <= 0:
            logger.warning("DAILY_ADAPTIVE: NIFTY spot unavailable")
            return
        candle = {"close": spot, "open": spot, "high": spot, "low": spot, "ts": now}

        leg = legs[idx]
        self._enter_trade(
            signal=leg["direction"],
            strategy=leg["strategy"],
            candle=candle,
            atr=None,
            filter_log=dict(leg.get("filter_log") or {}),
            vix=effective_vix,
            regime=stub_regime,
            sl_pct_override=float(leg["sl_pct"]),
            target_pct_override=float(leg["target_pct"]),
            risk_multiplier=1.0,
            fixed_option_lots=int(leg["lots"]),
        )

    def _scan_entry(self, now: datetime, candles: List[Dict], vix: Optional[float]) -> None:
        can_trade, reason = self.risk.can_trade()
        if not can_trade:
            if self._heartbeat_count % (60 // self.cfg.poll_seconds) == 0:
                logger.info(f"RISK BLOCKED: {reason}")
                _log_event("RISK_BLOCKED", {"reason": reason, **self.risk.status()})
            return

        if not self.sm.is_idle:
            return

        # Daily regime gate — SKIP days mean zero trades
        if self._daily_regime and not self._daily_regime.should_trade:
            return

        if self._day_stopped_profit:
            return

        strat_state = self.risk.get_strategy_state()
        vwap_enabled = strat_state.get("vwap_enabled", True)

        current_time = now.time()
        orb_start = self._t(self.cfg.orb_start)
        orb_end = self._t(self.cfg.orb_end)
        entry_close = self._t(self.cfg.entry_window_close)
        reclaim_start = self._t(self.cfg.reclaim_window_start)
        reclaim_end = self._t(self.cfg.reclaim_window_end)

        # Regime-driven time window
        if self._daily_regime:
            regime_window_start = self._t(self._daily_regime.execution.window_start)
            regime_window_end = self._t(self._daily_regime.execution.window_end)
            if current_time < regime_window_start or current_time > regime_window_end:
                return

        if not candles:
            return

        last_candle = candles[-1]
        effective_vix = vix or 14.0
        regime = self._detect_regime(candles, effective_vix)
        self._current_regime = regime
        trend = self._detect_trend(candles, effective_vix)

        # Strategy list: start from TREND priority, intersect with daily regime whitelist
        strategy_list = trend.strategy_priority
        risk_multiplier = trend.risk_multiplier

        if self._daily_regime:
            regime_strategies = set(self._daily_regime.allowed_strategies)
            strategy_list = [s for s in strategy_list if s in regime_strategies]
            regime_direction = self._daily_regime.allowed_direction
        else:
            regime_direction = None

        # Intraday regime overrides (existing logic)
        if regime.regime == "VOLATILE":
            strategy_list = [s for s in strategy_list if s != "MOMENTUM_BREAKOUT"]
            risk_multiplier = min(risk_multiplier, 0.60)

        if trend.state == TrendState.NEUTRAL:
            strategy_list = [s for s in strategy_list if s not in ("ORB", "MOMENTUM_BREAKOUT")]

        # 10:30 trend-conflict check
        conflict_time = self._t("10:30")
        if (self._daily_regime
                and current_time >= conflict_time
                and regime_conflicts_with_trend(self._daily_regime, trend.direction)):
            logger.info(
                f"TREND CONFLICT: regime={self._daily_regime.name} ({self._daily_regime.allowed_direction}) "
                f"vs trend={trend.direction} — reducing confidence"
            )
            risk_multiplier *= 0.5

        pb_window_start = self._t(self.cfg.ema_pullback_window_start)
        pb_window_end = self._t(self.cfg.ema_pullback_window_end)
        mb_window_start = self._t(self.cfg.momentum_breakout_window_start)
        mb_window_end = self._t(self.cfg.momentum_breakout_window_end)

        # ── Evaluate ALL strategies, collect candidates, pick strongest ──
        candidates: list = []
        scan_results: list = []
        idx = len(candles) - 1

        def _fmt_filters(filters):
            return {
                k: {"passed": v.get("passed"), "value": v.get("value"), "detail": v.get("detail", "")}
                for k, v in filters.items()
            } if filters else {}

        def _eval_strategy(name, result, event_type):
            filters = result.get("filters", {})
            _log_event(event_type, {
                "strategy": name, "regime": regime.regime,
                "trend": trend.state.value, "conviction": trend.conviction,
                "signal": result.get("signal"), "all_passed": result["all_passed"],
                "filters": _fmt_filters(filters),
            })
            confidence = compute_signal_confidence(
                name, result.get("signal", ""), regime.regime, trend, filters, effective_vix
            )
            scan_results.append({
                "strategy": name, "signal": result.get("signal"),
                "passed": result["all_passed"], "confidence": confidence,
            })
            if result["all_passed"] and result["signal"]:
                sl_pct, target_pct = SL_TARGET_BY_STRATEGY.get(name, (0.28, 0.60))
                candidates.append({
                    "strategy": name, "signal": result["signal"],
                    "confidence": confidence, "sl_pct": sl_pct, "target_pct": target_pct,
                    "atr": result.get("atr", 0), "filters": filters,
                })
            else:
                failed = [f"{k}={v.get('value','')}" for k, v in filters.items() if not v.get("passed")]
                logger.info(f"{name} SKIP: {', '.join(failed[:5]) if failed else 'no signal'} (conf={confidence:.0f})")

        # ── ORB ──
        if "ORB" in strategy_list and orb_enabled and not self._orb_signal_used and orb_end <= current_time <= entry_close:
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
            _eval_strategy("ORB", result, "ORB_SCAN")

        # ── RELAXED_ORB ──
        if "RELAXED_ORB" in strategy_list and orb_enabled and not self._orb_signal_used and orb_end <= current_time <= entry_close:
            result = evaluate_orb_signal(
                candles, last_candle, vix,
                orb_start=orb_start, orb_end=orb_end,
                min_orb_range_points=self.cfg.min_orb_range_points,
                max_orb_range_points=self.cfg.relaxed_orb_max_range_points,
                breakout_buffer_pct=self.cfg.breakout_buffer_pct,
                min_breakout_body_ratio=max(0.35, self.cfg.min_breakout_body_ratio - 0.10),
                min_volume_surge_ratio=max(1.0, self.cfg.min_volume_surge_ratio - 0.2),
                ema_fast=self.cfg.ema_fast, ema_slow=self.cfg.ema_slow,
                rsi_period=self.cfg.rsi_period, atr_period=self.cfg.atr_period,
                require_vwap_confirmation=self.cfg.require_vwap_confirmation,
                vwap_buffer_points=self.cfg.vwap_buffer_points,
                rsi_bull_min=self.cfg.rsi_bull_min, rsi_bear_max=self.cfg.rsi_bear_max,
                rsi_overbought_skip=self.cfg.rsi_overbought_skip,
                rsi_oversold_skip=self.cfg.rsi_oversold_skip,
                vix_max=self.cfg.vix_max,
            )
            _eval_strategy("RELAXED_ORB", result, "ORB_SCAN")

        # ── MOMENTUM_BREAKOUT ──
        if "MOMENTUM_BREAKOUT" in strategy_list and not self._momentum_signal_used and mb_window_start <= current_time <= mb_window_end:
            mb_result = evaluate_momentum_breakout_signal(
                candles, idx, vix,
                breakout_lookback=self.cfg.momentum_breakout_lookback,
                min_body_ratio=self.cfg.momentum_breakout_min_body_ratio,
                rsi_period=self.cfg.rsi_period, atr_period=self.cfg.atr_period,
                rsi_bull_min=self.cfg.momentum_breakout_rsi_bull_min,
                rsi_bull_max=self.cfg.momentum_breakout_rsi_bull_max,
                rsi_bear_min=self.cfg.momentum_breakout_rsi_bear_min,
                rsi_bear_max=self.cfg.momentum_breakout_rsi_bear_max,
                vix_max=self.cfg.vix_max,
                min_volume_surge_ratio=self.cfg.momentum_breakout_min_volume_surge,
                ema_fast=self.cfg.ema_fast, ema_slow=self.cfg.ema_slow,
            )
            _eval_strategy("MOMENTUM_BREAKOUT", mb_result, "MOMENTUM_SCAN")

        # ── EMA_PULLBACK ──
        ema_dead_start = self._t("11:00")
        ema_dead_end = self._t("12:00")
        if "EMA_PULLBACK" in strategy_list and not self._ema_pullback_signal_used and pb_window_start <= current_time <= pb_window_end and not (ema_dead_start <= current_time < ema_dead_end):
            pb_result = evaluate_ema_pullback_signal(
                candles, idx, vix,
                ema_fast=self.cfg.ema_fast, ema_slow=self.cfg.ema_slow,
                pullback_proximity_pct=self.cfg.ema_pullback_proximity_pct,
                min_body_ratio=self.cfg.ema_pullback_min_body_ratio,
                rsi_period=self.cfg.rsi_period, atr_period=self.cfg.atr_period,
                vix_max=self.cfg.vix_max,
                lookback_candles=self.cfg.ema_pullback_lookback_candles,
            )
            _eval_strategy("EMA_PULLBACK", pb_result, "EMA_PULLBACK_SCAN")

        # ── VWAP_RECLAIM ──
        if "VWAP_RECLAIM" in strategy_list and vwap_enabled and not self._reclaim_signal_used and reclaim_start <= current_time <= reclaim_end:
            reclaim = evaluate_vwap_reclaim_signal(
                candles, idx, vix,
                reclaim_min_rejection_points=self.cfg.reclaim_min_rejection_points,
                rsi_period=self.cfg.rsi_period, atr_period=self.cfg.atr_period,
                vix_max=self.cfg.vix_max,
            )
            _eval_strategy("VWAP_RECLAIM", reclaim, "RECLAIM_SCAN")

        # ── Log full scan cycle ──
        _log_event("SCAN_CYCLE", {
            "regime": regime.regime,
            "trend": trend.state.value,
            "trend_direction": trend.direction,
            "conviction": trend.conviction,
            "risk_multiplier": risk_multiplier,
            "vix": effective_vix,
            "strategies_evaluated": len(scan_results),
            "signals_detected": len(candidates),
            "scans": scan_results,
            "candidates": [
                {"strategy": c["strategy"], "signal": c["signal"], "confidence": c["confidence"]}
                for c in candidates
            ],
        })

        # ── Pick strongest candidate ──
        if not candidates:
            return

        # Filter by regime direction
        if regime_direction:
            candidates = [c for c in candidates if c["signal"] == regime_direction]
        if not candidates:
            return

        # Check regime max trades
        if self._daily_regime:
            trades_today = self.risk.status().get("trades_today", 0)
            if trades_today >= self._daily_regime.execution.max_trades:
                return

        candidates.sort(key=lambda c: c["confidence"], reverse=True)
        best = candidates[0]

        if len(candidates) > 1:
            runner_up = candidates[1]
            logger.info(
                f"MULTI-SIGNAL: {len(candidates)} signals detected. "
                f"BEST={best['strategy']} ({best['signal']}, conf={best['confidence']:.0f}) "
                f"vs {runner_up['strategy']} ({runner_up['signal']}, conf={runner_up['confidence']:.0f})"
            )
        else:
            logger.info(
                f"SIGNAL: {best['strategy']} {best['signal']} confidence={best['confidence']:.0f}"
            )

        self._enter_trade(
            signal=best["signal"], strategy=best["strategy"],
            candle=last_candle, atr=best["atr"],
            filter_log=best["filters"], vix=effective_vix,
            regime=regime, sl_pct_override=best["sl_pct"],
            target_pct_override=best["target_pct"], risk_multiplier=risk_multiplier,
        )
        # Mark used flags
        if best["strategy"] in ("ORB", "RELAXED_ORB"):
            self._orb_signal_used = True
        elif best["strategy"] == "MOMENTUM_BREAKOUT":
            self._momentum_signal_used = True
        elif best["strategy"] == "EMA_PULLBACK":
            self._ema_pullback_signal_used = True
        elif best["strategy"] == "VWAP_RECLAIM":
            self._reclaim_signal_used = True

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
        risk_multiplier: float = 1.0,
        fixed_option_lots: Optional[int] = None,
    ) -> None:
        signal_time = time.time()
        spot = float(candle["close"])
        is_thursday = datetime.now().date().weekday() == 3

        # OTM offset from daily regime (1-OTM on STRONG days for better R:R)
        otm_offset = self._daily_regime.otm_offset if self._daily_regime else 0
        target_strike_offset = otm_offset * self.cfg.strike_step
        if signal == "CALL":
            target_spot_for_strike = spot + target_strike_offset
        else:
            target_spot_for_strike = spot - target_strike_offset

        opt_info = self.client.select_atm_option(
            spot=target_spot_for_strike, direction=signal,
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

        # Regime-driven risk: STRONG=3%, normal=2%, RANGING=1% (intraday sizing only)
        base_risk_pct = self._daily_regime.execution.risk_pct if self._daily_regime else self.cfg.risk_per_trade_pct
        effective_risk_pct = base_risk_pct * risk_multiplier
        if regime.regime == "VOLATILE":
            effective_risk_pct = min(effective_risk_pct, base_risk_pct * 0.50)

        if fixed_option_lots is not None:
            lots = int(fixed_option_lots)
            lot_unit = self.cfg.nifty_option_lot_size
            qty = lots * lot_unit
            risk_per_unit = opt_price * sl_pct
            actual_risk = round(risk_per_unit * qty, 2)
            size_info = {
                "lots": lots,
                "qty": qty,
                "risk_amount": actual_risk,
                "actual_risk": actual_risk,
            }
            logger.info(
                f"DAILY_ADAPTIVE SIZING: lots={lots} × {lot_unit} = qty {qty} | "
                f"est_risk≈₹{actual_risk:,.0f} (sl {sl_pct*100:.1f}%)"
            )
        else:
            if effective_risk_pct != base_risk_pct:
                logger.info(
                    f"RISK SCALED: {base_risk_pct*100:.1f}% × {risk_multiplier:.2f} "
                    f"= {effective_risk_pct*100:.1f}% | regime={regime.regime} "
                    f"daily_regime={self._daily_regime.name if self._daily_regime else '?'}"
                )
            size_info = self.risk.compute_position_size(
                entry_price=opt_price, sl_pct=sl_pct, risk_pct_override=effective_risk_pct
            )
            lots = size_info["lots"]
            qty = size_info["qty"]

        sl_price = round(opt_price * (1 - sl_pct), 1)
        target_price = round(opt_price * (1 + target_pct_override), 1)

        trend_info = f"{self._current_trend.state.value}" if self._current_trend else "?"
        conf_score = compute_signal_confidence(
            strategy, signal, regime.regime, self._current_trend or TrendResult(
                state=TrendState.NEUTRAL, direction="NEUTRAL", conviction=0,
                risk_multiplier=0.6, strategy_priority=[]
            ),
            filter_log, vix,
        )
        logger.info(
            f"SIGNAL: {strategy} {signal} | trend={trend_info} regime={regime.regime} | "
            f"confidence={conf_score:.0f} | "
            f"{symbol} | LTP={opt_price:.2f} SL={sl_price:.2f} ({sl_pct*100:.0f}%) "
            f"TGT={target_price:.2f} ({target_pct_override*100:.0f}%) | "
            f"Lots={lots} Qty={qty} Risk=₹{size_info['actual_risk']:.0f} "
            f"(risk_mult={risk_multiplier:.2f})"
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
                logger.error(f"SL placement failed: {e} — exiting position immediately for safety")
                _log_event("SL_PLACEMENT_FAILED", {"symbol": symbol, "error": str(e), "action": "emergency_exit"})
                try:
                    exit_resp = self.client.place_order(
                        symbol=symbol, qty=qty, side="SELL",
                        exchange="NFO", product="MIS",
                    )
                    self.client.confirm_fill(exit_resp.get("order_id", ""), timeout_seconds=15)
                    logger.info("Emergency exit placed after SL placement failure")
                except Exception as exit_err:
                    logger.error(f"EMERGENCY EXIT FAILED: {exit_err} — CHECK KITE MANUALLY!")
                    _log_event("EMERGENCY_EXIT_FAILED", {"symbol": symbol, "error": str(exit_err)})
                    self._notify(f"🚨 EMERGENCY: SL failed AND exit failed for {symbol}. CHECK KITE NOW!")
                # Record trade so trades_today is incremented — prevents re-entry loop on next scan
                self.risk.record_trade(0.0)
                return

        filter_log["regime"] = {"passed": True, "value": regime.regime, "detail": regime.detail}
        if self._current_trend:
            filter_log["trend"] = {
                "passed": True,
                "value": self._current_trend.state.value,
                "detail": (
                    f"direction={self._current_trend.direction} "
                    f"conviction={self._current_trend.conviction:.2f} "
                    f"risk_mult={risk_multiplier:.2f}"
                ),
            }

        self.sm.transition_to_entry_pending(
            symbol=symbol, direction=signal, option_type=opt_info["option_type"],
            strike=strike, expiry=str(expiry), qty=qty, lots=lots,
            sl_price=sl_price, target_price=target_price,
            spot_at_entry=spot, vix_at_entry=vix,
            strategy=strategy, filter_log=filter_log, entry_order_id=order_id,
        )
        self.sm.confirm_entry(fill_price)
        # Persist SL-M order ID so it survives bot restarts
        if self._active_slm_order_id:
            self.sm.position.slm_order_id = self._active_slm_order_id
            from bot.state_machine import save_position
            save_position(self.sm.position)

        _log_event("ENTRY", {
            "engine": "daily_adaptive" if fixed_option_lots is not None else "intraday",
            "strategy": strategy, "regime": regime.regime, "signal": signal,
            "confidence": conf_score,
            "trend": trend_info, "conviction": self._current_trend.conviction if self._current_trend else 0,
            "risk_multiplier": risk_multiplier,
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

        daily_regime_name = self._daily_regime.name if self._daily_regime else "?"
        otm_tag = f" | OTM={otm_offset}" if otm_offset > 0 else ""
        self._notify(
            f"🚀 ENTRY: {strategy} {signal} [{daily_regime_name}]{otm_tag}\n"
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
        logger.info(
            f" Engine: {self.cfg.trading_engine} | "
            f"Capital: ₹{self.cfg.capital:,.0f} | "
            f"Opt lot unit: {self.cfg.nifty_option_lot_size} | "
            f"Intraday lot_size: {self.cfg.lot_size}"
        )
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

        # Startup broker sync — if bot restarted mid-trade, verify position is still open
        if not self.cfg.paper_mode and self.sm.is_active:
            try:
                broker_qty = self.client.get_open_qty(self.sm.position.symbol)
                current_price = self.client.get_quote(self.sm.position.symbol, "NFO")
                was_synced = self.sm.sync_with_broker(broker_qty, last_price=current_price)
                if was_synced:
                    logger.warning(
                        f"STARTUP SYNC: position for {self.sm.position.symbol} was closed externally "
                        f"(broker_qty={broker_qty}) — resetting to IDLE"
                    )
                    self._active_slm_order_id = None
                    self._notify(f"⚠️ Startup sync: position closed externally. Check Kite.")
                else:
                    logger.info(
                        f"STARTUP SYNC: broker position confirmed active "
                        f"qty={self.sm.position.qty} symbol={self.sm.position.symbol}"
                    )
            except Exception as e:
                logger.warning(f"Startup broker sync failed: {e}")

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

                # Broker reconciliation every 60s — detects manual exits and external closes
                if self.sm.is_active:
                    now_ts = time.time()
                    if now_ts - self._last_broker_sync >= 60:
                        self._last_broker_sync = now_ts
                        try:
                            broker_qty = self.client.get_open_qty(self.sm.position.symbol)
                            current_price = self.client.get_quote(self.sm.position.symbol, "NFO")
                            symbol_before_sync = self.sm.position.symbol
                            expected_qty = self.sm.position.qty
                            was_synced = self.sm.sync_with_broker(broker_qty, last_price=current_price)
                            if was_synced:
                                if broker_qty == 0:
                                    logger.warning(
                                        f"BROKER SYNC: {symbol_before_sync} fully closed externally "
                                        f"(expected qty={expected_qty}, broker=0)"
                                    )
                                    _log_event("BROKER_SYNC_CLOSED", {
                                        "symbol": symbol_before_sync,
                                        "expected_qty": expected_qty,
                                        "broker_qty": broker_qty,
                                        "last_price": current_price,
                                    })
                                    self._active_slm_order_id = None
                                    self._notify(
                                        "⚠️ BROKER SYNC: Position closed externally\n"
                                        f"Symbol: {symbol_before_sync}\n"
                                        "Check Kite for details."
                                    )
                                else:
                                    logger.warning(
                                        f"BROKER SYNC: {symbol_before_sync} partially closed externally "
                                        f"(expected qty={expected_qty}, broker={broker_qty}) — qty updated"
                                    )
                                    _log_event("BROKER_SYNC_PARTIAL", {
                                        "symbol": symbol_before_sync,
                                        "expected_qty": expected_qty,
                                        "broker_qty": broker_qty,
                                    })
                        except Exception as e:
                            logger.warning(f"Broker sync check failed: {e}")

                if self.sm.is_active:
                    self._manage_active_position(now, candles)
                elif self.sm.is_idle:
                    if self.cfg.trading_engine.strip().lower() == "daily_adaptive":
                        self._scan_entry_daily_adaptive(now, vix)
                    else:
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
