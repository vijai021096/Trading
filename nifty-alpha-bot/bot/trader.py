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
from shared.impulse_detector import detect_impulse, ImpulseResult, ImpulseGrade
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
        self._current_impulse: Optional[ImpulseResult] = None
        self._daily_regime: Optional[DailyRegime] = None
        self._regime_logged_today = False
        self._trend_logged_today = False
        self._daily_regime_classified = False
        self._day_stopped_profit = False
        self._last_trade_was_loss: bool = False
        self._last_exit_direction: Optional[str] = None
        self._lost_directions_today: set = set()
        self._last_exit_reason: str = ""
        self._last_trade_pnl: float = 0.0
        self._last_trade_strategy: str = ""
        self._skip_reasons_today: list = []
        self._last_broker_sync: float = 0.0
        self._orb_signal_used = False
        self._momentum_signal_used = False
        self._ema_pullback_signal_used = False
        self._reclaim_signal_used = False
        self._daily_adaptive_plan: Optional[Dict[str, Any]] = None
        self._late_trend_rescanned: bool = False   # guard: only one late-trend re-scan per day
        self._last_entry_confidence: float = 0.0   # track confidence of last entry (for re-entry gate)
        self._reentries_today: int = 0             # Change 3: max 1 re-entry per day
        self._fallback_entry_triggered: bool = False  # Change 2: anti-miss fallback (once per day)

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

    def _confirm_intraday_momentum(self, direction: str, candles: List[Dict]) -> tuple[bool, str]:
        """Check last 3 completed 5m candles confirm the signal direction before entry.
        Prevents entering stale signals on restart or when price has reversed.
        Returns (ok, reason_string).
        """
        completed = [c for c in candles if c.get("ts") is not None][-4:-1]  # last 3 completed
        if len(completed) < 2:
            return True, "insufficient candles — skipping momentum check"

        # Count bullish vs bearish candles
        bull = sum(1 for c in completed if c["close"] >= c["open"])
        bear = len(completed) - bull

        # VWAP as simple average of recent candle closes (proxy)
        avg_close = sum(c["close"] for c in completed) / len(completed)
        current_close = completed[-1]["close"]

        if direction == "PUT":
            # Need majority bearish candles + current price below recent average
            momentum_ok = bear >= 2 and current_close <= avg_close
            reason = (
                f"PUT momentum: {bear}/{len(completed)} bear candles, "
                f"price {current_close:.0f} vs avg {avg_close:.0f}"
            )
        else:
            # CALL: majority bullish + price above average
            momentum_ok = bull >= 2 and current_close >= avg_close
            reason = (
                f"CALL momentum: {bull}/{len(completed)} bull candles, "
                f"price {current_close:.0f} vs avg {avg_close:.0f}"
            )

        return momentum_ok, reason

    def _is_overextended(self, direction: str, candles: List[Dict]) -> tuple[bool, str]:
        """Skip late entries if Nifty has already moved too far in signal direction."""
        if len(candles) < 2:
            return False, "insufficient candles"
        open_price = candles[0]["open"]
        current = candles[-1]["close"]
        if not open_price:
            return False, "no open price"
        intraday_move = (current - open_price) / open_price
        threshold = self.cfg.overextended_move_pct
        if direction == "PUT" and intraday_move < -threshold:
            return True, f"overextended DOWN: Nifty already {intraday_move*100:.1f}% from open (limit -{threshold*100:.1f}%)"
        if direction == "CALL" and intraday_move > threshold:
            return True, f"overextended UP: Nifty already +{intraday_move*100:.1f}% from open (limit +{threshold*100:.1f}%)"
        return False, f"not overextended: intraday_move={intraday_move*100:.2f}%"

    def _compute_composite_score(self, confidence: float, filter_log: dict) -> float:
        """Composite entry score = confidence * 0.5 + quality * 0.5 + conviction * 20.
        Returns 0-120 range. Used to rank multiple signal candidates."""
        quality = float((filter_log or {}).get("quality_score", 0.0))
        conviction = self._current_trend.conviction if self._current_trend else 0.0
        return confidence * 0.5 + quality * 0.5 + conviction * 20

    def _resolve_leg_direction(self, leg: dict, candles: list, spot: float) -> Optional[str]:
        """Resolve direction for NEUTRAL legs using live intraday data.
        Returns 'CALL', 'PUT', or None (skip — no clear direction).
        """
        setup_type = leg.get("setup_type", "BREAKOUT")
        fl = leg.get("filter_log") or {}
        bias = leg.get("bias", "NEUTRAL")
        strength = leg.get("bias_strength", 0.7)

        # Already has a direction (non-NEUTRAL, non-None)
        direction = leg.get("direction")
        if direction not in (None, "NEUTRAL"):
            # Bias rejection for weak-biased directional legs
            if (self._current_trend and strength < 0.75):
                trend_dir = self._current_trend.direction
                conviction = self._current_trend.conviction
                if (direction == "CALL" and trend_dir == "BEAR" and conviction >= 0.75):
                    return None  # weak bullish bias vs confirmed bear trend → skip
                if (direction == "PUT" and trend_dir == "BULL" and conviction >= 0.75):
                    return None  # weak bearish bias vs confirmed bull trend → skip
            return direction

        # NEUTRAL: resolve from intraday data
        if not candles or len(candles) < 2:
            return None

        prev_close = float(fl.get("prev_close", 0) or 0)
        if not prev_close:
            prev_close = float((self._daily_adaptive_plan or {}).get("breakout_watch", {}).get("last_close", 0) or 0)

        open_px = float(candles[0].get("open", spot))
        gap_pct = (open_px - prev_close) / prev_close if prev_close > 0 else 0

        # Current intraday momentum
        trend_dir = self._current_trend.direction if self._current_trend else "NEUTRAL"
        trend_conviction = self._current_trend.conviction if self._current_trend else 0.0

        if setup_type == "BREAKOUT":
            if abs(gap_pct) >= 0.002:
                return "CALL" if gap_pct > 0 else "PUT"
            if trend_conviction >= 0.5:
                return "CALL" if trend_dir in ("BULL", "STRONG_BULL") else "PUT"
            return None

        elif setup_type == "GAP_FADE":
            if gap_pct >= 0.004:
                return "PUT"   # gap up → fade = PUT
            if gap_pct <= -0.004:
                return "CALL"  # gap down → fade = CALL
            return None

        elif setup_type == "COMPRESSION":  # INSIDE_BAR_BREAK
            prev_high = float(fl.get("prev_high", 0) or 0)
            prev_low = float(fl.get("prev_low", 0) or 0)
            margin = float(fl.get("margin", 0) or 0)
            if prev_high and prev_low:
                if open_px > prev_high + margin:
                    return "CALL"
                if open_px < prev_low - margin:
                    return "PUT"
            if trend_conviction >= 0.5:
                return "CALL" if trend_dir in ("BULL", "STRONG_BULL") else "PUT"
            return None

        # Default: use trend direction
        if trend_conviction >= 0.6:
            return "CALL" if trend_dir in ("BULL", "STRONG_BULL") else "PUT"
        return None

    def _in_daily_adaptive_window(self, now: datetime) -> bool:
        t = now.time()
        start = self._t(self.cfg.daily_adaptive_window_start)
        # Use extended window end for trending regimes
        extended_regimes = [r.strip() for r in self.cfg.trending_regimes_for_extended_window.split(",")]
        regime_name = (self._daily_regime.name if self._daily_regime else "")
        if regime_name in extended_regimes:
            end = self._t(self.cfg.trending_regime_window_end)
        else:
            end = self._t(self.cfg.daily_adaptive_window_end)
        return start <= t <= end

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
            self._current_impulse = None
            self._daily_regime = None
            self._active_slm_order_id = None
            self._daily_adaptive_plan = None
            self._late_trend_rescanned = False
            self._last_entry_confidence = 0.0
            self._orb_signal_used = False
            self._momentum_signal_used = False
            self._ema_pullback_signal_used = False
            self._reclaim_signal_used = False
            self._skip_reasons_today = []
            self._lost_directions_today = set()
            self._last_exit_reason = ""
            self._last_trade_pnl = 0.0
            self._last_trade_strategy = ""
            self._reentries_today = 0
            self._fallback_entry_triggered = False
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
        # ── Impulse detection (runs once per session after 4th candle) ──
        # Cached so we don't re-evaluate on every loop tick.
        if self._current_impulse is None and len(candles) >= 4:
            self._current_impulse = detect_impulse(candles)
            if self._current_impulse.grade != ImpulseGrade.NONE:
                logger.info(
                    f"IMPULSE: {self._current_impulse.grade} [{self._current_impulse.direction}] "
                    f"bonus=+{self._current_impulse.bonus_votes} | {self._current_impulse.detail}"
                )
                _log_event("IMPULSE_DETECTED", {
                    "grade": self._current_impulse.grade,
                    "direction": self._current_impulse.direction,
                    "bonus_votes": self._current_impulse.bonus_votes,
                    "rules": self._current_impulse.rules,
                    "detail": self._current_impulse.detail,
                })

        # Compute live move from session open for hard trend override
        _move_from_open = 0.0
        if candles and len(candles) >= 2:
            _open = float(candles[0].get("open", 0) or 0)
            if _open > 0:
                _move_from_open = (float(candles[-1]["close"]) - _open) / _open * 100

        trend = detect_trend(candles, vix, impulse=self._current_impulse, move_from_open_pct=_move_from_open)

        if not self._trend_logged_today:
            self._trend_logged_today = True
            logger.info(
                f"TREND: {trend.state.value} [{trend.direction}] | "
                f"conviction={trend.conviction:.2f} risk_mult={trend.risk_multiplier:.2f} "
                f"impulse={trend.impulse_grade} | {trend.detail}"
            )
            _log_event("TREND_DETECTED", {
                "state": trend.state.value,
                "direction": trend.direction,
                "conviction": trend.conviction,
                "risk_multiplier": trend.risk_multiplier,
                "strategy_priority": trend.strategy_priority,
                "scores": trend.scores,
                "impulse_grade": trend.impulse_grade,
            })
        elif (self._current_trend is not None and
              self._current_trend.state != trend.state):
            # Log state change intraday
            logger.info(
                f"TREND SHIFT: {self._current_trend.state.value} → {trend.state.value} "
                f"| conviction={trend.conviction:.2f} impulse={trend.impulse_grade} | {trend.detail}"
            )
            _log_event("TREND_SHIFTED", {
                "from": self._current_trend.state.value,
                "to": trend.state.value,
                "conviction": trend.conviction,
                "risk_multiplier": trend.risk_multiplier,
                "scores": trend.scores,
                "impulse_grade": trend.impulse_grade,
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

        # ── Time-based SL tightening (live bot) ──────────────────────
        # After 45 mins with no meaningful momentum, tighten SL to -15%.
        # Prevents theta decay from slowly bleeding the trade to full SL.
        if not exit_reason and pos.entry_time is not None:
            trade_age_min = (now - pos.entry_time).total_seconds() / 60
            gain_now = (current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0
            time_sl_threshold = pos.entry_price * (1 - 0.15)   # -15% time SL
            if (trade_age_min >= 45
                    and gain_now < 0.06          # no meaningful upward momentum
                    and current_price < time_sl_threshold
                    and pos.current_sl < time_sl_threshold):
                # Tighten SL-M to -15% if it hasn't been tightened already
                if self._active_slm_order_id and self.cfg.use_slm_exit:
                    ok = self.client.modify_slm_order(self._active_slm_order_id, time_sl_threshold)
                    if ok:
                        pos.current_sl = time_sl_threshold
                        logger.info(
                            f"TIME_SL: trade_age={trade_age_min:.0f}min, no momentum (gain={gain_now*100:.1f}%) "
                            f"→ SL tightened to ₹{time_sl_threshold:.2f} (-15%)"
                        )
                        _log_event("TIME_SL_TIGHTENED", {
                            "trade_age_min": round(trade_age_min, 1),
                            "gain_pct": round(gain_now * 100, 2),
                            "new_sl": round(time_sl_threshold, 2),
                        })
                elif not self.cfg.use_slm_exit:
                    exit_reason = "TIME_SL"    # software SL mode — exit immediately

        # Structure-based exit: exit early on trend reversal candles if already in profit
        if not exit_reason and len(candles) >= 2:
            gain_pct = (current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0
            if gain_pct >= self.cfg.structure_exit_min_profit_pct:
                last_c = candles[-1]
                prev_c = candles[-2]
                # For PUT position: Nifty making higher lows = bounce = PUT reversing
                if pos.direction == "PUT":
                    if (last_c["low"] > prev_c["low"] and last_c["close"] > prev_c["close"]):
                        exit_reason = "STRUCTURE_BREAK"
                        logger.info(
                            f"STRUCTURE_BREAK (PUT): Nifty higher low {prev_c['low']:.0f}→{last_c['low']:.0f}, "
                            f"close {prev_c['close']:.0f}→{last_c['close']:.0f} | gain={gain_pct*100:.1f}%"
                        )
                # For CALL position: Nifty making lower highs = reversal = CALL reversing
                elif pos.direction == "CALL":
                    if (last_c["high"] < prev_c["high"] and last_c["close"] < prev_c["close"]):
                        exit_reason = "STRUCTURE_BREAK"
                        logger.info(
                            f"STRUCTURE_BREAK (CALL): Nifty lower high {prev_c['high']:.0f}→{last_c['high']:.0f}, "
                            f"close {prev_c['close']:.0f}→{last_c['close']:.0f} | gain={gain_pct*100:.1f}%"
                        )

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
                        # Retry fetching average_price up to 3 times — Kite may not
                        # populate it immediately even after status = COMPLETE
                        for _price_attempt in range(3):
                            status = self.client.get_order_status(order_id)
                            avg = float(status.get("average_price", 0) or 0)
                            if avg > 0:
                                fill_price = avg
                                break
                            time.sleep(0.5)
                        else:
                            fill_price = approx_price
                            logger.warning(
                                f"Exit {order_id}: average_price not populated after retries — "
                                f"using approx ₹{approx_price:.2f}. Check Kite for actual fill."
                            )
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
        # Track last trade outcome for skip-after-loss and direction correlation logic
        self._last_trade_was_loss = net < 0
        self._last_exit_direction = pos.direction
        if net < 0:
            self._lost_directions_today.add(pos.direction)  # hard-block this direction for today
        self._last_exit_reason = exit_reason
        self._last_trade_pnl = net
        self._last_trade_strategy = pos.strategy or ""
        _log_event("TRADE_CLOSED", trade_record)

        # ── Re-entry after SL (Change 3 — tightened) ────────────────────────────
        # Rules: max 1 re-entry per day | regime must be STRONG_TREND_DOWN only |
        #        conviction >= 0.70 | trend must be STRONG_BEAR | price made new low
        if (exit_reason == "SL_HIT"
                and self._daily_adaptive_plan is not None
                and self._last_entry_confidence >= 62.0
                and self._reentries_today < 1          # hard cap: 1 re-entry max
                and net < 0):
            plan_regime = self._daily_adaptive_plan.get("regime", "")
            # Only STRONG_TREND_DOWN: WR=100% on re-entry (MILD_TREND removed — too loose)
            reentry_regime_ok = plan_regime == "STRONG_TREND_DOWN"
            # Conviction gate: trend must still be STRONG_BEAR with high conviction
            _trend_ok = (
                self._current_trend is not None
                and self._current_trend.state == TrendState.STRONG_BEAR
                and self._current_trend.conviction >= 0.70
            )
            # Price confirmation: current price should be at or below SL exit (new low confirms)
            _candles = self._candle_cache or []
            _price_new_low = (
                len(_candles) >= 1
                and float(_candles[-1]["close"]) <= pos.current_sl * 1.005  # within 0.5% of SL
            ) if pos.direction == "PUT" else (
                len(_candles) >= 1
                and float(_candles[-1]["close"]) >= pos.current_sl * 0.995
            )
            legs: list = list(self._daily_adaptive_plan.get("executable_legs") or [])
            day_cap = int(self._daily_adaptive_plan.get("day_trade_cap") or self.cfg.max_trades_per_day)
            trades_so_far = int(self.risk.status().get("trades_today", 0))
            if (reentry_regime_ok and _trend_ok and _price_new_low
                    and trades_so_far < day_cap and trades_so_far >= len(legs)):
                reentry_leg: Dict[str, Any] = {
                    "strategy": pos.strategy or "",
                    "direction": pos.direction,
                    "lots": 1,
                    "sl_pct": 0.0,
                    "target_pct": 0.0,
                    "filter_log": {"reentry": True, "after_sl": True, "regime": plan_regime},
                }
                self._daily_adaptive_plan["executable_legs"] = legs + [reentry_leg]
                self._lost_directions_today.discard(pos.direction)
                self._reentries_today += 1
                logger.info(
                    f"REENTRY_INJECTED: {pos.strategy} {pos.direction} after SL "
                    f"(regime={plan_regime}, conviction={self._current_trend.conviction:.2f}, "
                    f"conf={self._last_entry_confidence:.0f}) — direction block lifted"
                )
            elif exit_reason == "SL_HIT" and net < 0 and not reentry_regime_ok:
                logger.info(
                    f"REENTRY_BLOCKED: regime={plan_regime} not STRONG_TREND_DOWN "
                    f"or trend_ok={_trend_ok} or new_low={_price_new_low} — no re-entry"
                )

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

        # ── Late trend entry: if morning scan found no signal but strong trend emerges 10-12am ──
        # Reset plan to allow one fresh scan (only done once per day via _late_trend_rescanned guard)
        curr_mins = now.hour * 60 + now.minute
        if (self._daily_adaptive_plan is not None
                and not self._late_trend_rescanned
                and not (self._daily_adaptive_plan.get("executable_legs"))
                and 10 * 60 <= curr_mins <= 12 * 60
                and self._current_trend is not None
                and self._current_trend.state.value in ("STRONG_BULL", "STRONG_BEAR")
                and (self._current_trend.conviction or 0) >= 0.72):
            logger.info(
                f"LATE_TREND_ENTRY: morning had no signal, but strong trend "
                f"state={self._current_trend.state.value} conviction={self._current_trend.conviction:.2f} "
                f"detected at {now.strftime('%H:%M')} — resetting plan for late scan"
            )
            self._daily_adaptive_plan = None
            self._late_trend_rescanned = True  # prevent infinite re-scan loops

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

        # Conviction-based max trades: allow more entries on genuinely strong trend days
        if (self._current_trend is not None
                and self._current_trend.conviction >= self.cfg.strong_trend_conviction_min
                and self._current_trend.state.value in ("STRONG_BULL", "STRONG_BEAR")):
            day_cap = min(self.cfg.strong_trend_max_trades, self.cfg.max_trades_per_day)
            logger.info(
                f"STRONG_TREND: conviction={self._current_trend.conviction:.2f} → "
                f"day_cap expanded to {day_cap}"
            )

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

        # ── Best signal selection: score all remaining legs, pick highest ──
        remaining_legs = legs[idx:]
        scored = []
        for l in remaining_legs:
            from shared.trend_detector import compute_signal_confidence
            stub_trend = self._current_trend or TrendResult(
                state=TrendState.NEUTRAL, direction="NEUTRAL", conviction=0,
                risk_multiplier=0.6, strategy_priority=[]
            )
            # NEUTRAL legs have direction=None; use "CALL" as placeholder for scoring
            score_direction = l.get("direction") or "CALL"
            conf = compute_signal_confidence(
                l["strategy"], score_direction, stub_regime.regime, stub_trend,
                dict(l.get("filter_log") or {}), effective_vix,
            )
            composite = self._compute_composite_score(conf, dict(l.get("filter_log") or {}))
            scored.append((l, conf, composite))

        if not scored:
            return

        # Pick best by composite score
        best_leg, best_conf, best_composite = max(scored, key=lambda x: x[2])
        self._last_entry_confidence = best_conf  # store for re-entry quality gate

        # A+ filter: confidence >= threshold
        # In strong trend, allow A- (confidence >= 65) — market is forgiving
        is_strong_trend = (
            self._current_trend is not None and
            self._current_trend.state.value in ("STRONG_BULL", "STRONG_BEAR")
        )
        min_conf = 65.0 if is_strong_trend else self.cfg.min_confidence_score

        if best_conf < min_conf:
            # ── Change 2: Fallback anti-miss entry ───────────────────────────────
            # Strong trend confirmed + no trade taken yet + approaching 11am → lower bar once
            _curr_mins = now.hour * 60 + now.minute
            _trades_today = int(self.risk.status().get("trades_today", 0))
            _fallback_ok = (
                not self._fallback_entry_triggered
                and _trades_today == 0
                and _curr_mins >= 10 * 60 + 30  # 10:30am — gave morning enough time
                and _curr_mins < 11 * 60         # before 11am deadline
                and is_strong_trend
                and best_conf >= 55.0            # absolute floor — no junk trades
            )
            if _fallback_ok:
                self._fallback_entry_triggered = True
                logger.info(
                    f"FALLBACK_ENTRY: no trade by {now.strftime('%H:%M')}, "
                    f"strong trend ({self._current_trend.state.value} "    # type: ignore[union-attr]
                    f"conviction={self._current_trend.conviction:.2f}), "  # type: ignore[union-attr]
                    f"conf={best_conf:.0f} ≥ 55 → lowering threshold for one entry"
                )
                _log_event("FALLBACK_ENTRY", {
                    "time": now.strftime("%H:%M"),
                    "trend": self._current_trend.state.value,  # type: ignore[union-attr]
                    "conviction": self._current_trend.conviction,  # type: ignore[union-attr]
                    "best_conf": round(best_conf, 1),
                    "strategy": best_leg["strategy"],
                })
                # Allow through with relaxed threshold (conf >= 55 already checked above)
            else:
                if self._heartbeat_count % max(1, (60 // max(1, self.cfg.poll_seconds))) == 0:
                    logger.info(
                        f"A+_FILTER SKIP: best confidence {best_conf:.0f} < {min_conf:.0f} "
                        f"(composite={best_composite:.1f})"
                    )
                self._skip_reasons_today.append({
                    "strategy": best_leg["strategy"], "direction": best_leg.get("direction", ""),
                    "reason": f"Confidence {best_conf:.0f} < {min_conf:.0f} threshold",
                    "conf": round(best_conf, 1),
                })
                return

        logger.info(
            f"BEST_SIGNAL: {best_leg['strategy']} {best_leg.get('direction', 'NEUTRAL')} "
            f"confidence={best_conf:.0f} composite={best_composite:.1f}"
        )

        leg = best_leg

        # ── Resolve direction for NEUTRAL/biased legs ─────────────────
        candles = self._candle_cache or self._refresh_candles(now)
        resolved_dir = self._resolve_leg_direction(leg, candles or [], spot)
        if resolved_dir is None:
            logger.info(
                f"NEUTRAL_SKIP: {leg['strategy']} — no clear intraday direction "
                f"(setup_type={leg.get('setup_type')}, bias={leg.get('bias')})"
            )
            self._skip_reasons_today.append({
                "strategy": leg["strategy"], "direction": leg.get("direction", "NEUTRAL"),
                "reason": f"NEUTRAL/weak-bias — no clear intraday direction (setup_type={leg.get('setup_type')})",
                "conf": round(best_conf, 1),
            })
            return
        # Override leg direction with resolved direction
        if resolved_dir != leg.get("direction"):
            leg = dict(leg)
            leg["direction"] = resolved_dir
            logger.info(f"DIRECTION_RESOLVED: {leg['strategy']} → {resolved_dir} (was {best_leg.get('direction', 'NEUTRAL')})")

        # ── Intraday momentum confirmation ────────────────────────────
        # Validate that recent 5m candles still confirm the signal direction.
        momentum_ok, momentum_reason = self._confirm_intraday_momentum(leg["direction"], candles)
        if not momentum_ok:
            if self._heartbeat_count % max(1, (60 // max(1, self.cfg.poll_seconds))) == 0:
                logger.info(f"MOMENTUM SKIP: {leg['direction']} not confirmed — {momentum_reason}")
            return

        logger.info(f"MOMENTUM OK: {momentum_reason}")

        # ── Direction correlation block (hard block after any loss in same direction) ──
        if leg["direction"] in self._lost_directions_today:
            logger.info(
                f"DIRECTION_BLOCKED: {leg['direction']} already lost today — "
                f"skipping {leg['strategy']} to prevent overexposure"
            )
            self._skip_reasons_today.append({
                "strategy": leg["strategy"], "direction": leg["direction"],
                "reason": "Direction correlation block — this direction already lost today",
            })
            return

        # ── Skip after same-direction loss (prevents chasing failed setups) ──
        # Exception: strong trend days often shake out then resume — allow re-entry
        last_exit = getattr(self, '_last_exit_direction', None)
        last_was_loss = getattr(self, '_last_trade_was_loss', False)
        if last_was_loss and last_exit == leg["direction"] and not is_strong_trend:
            if best_conf < 75:
                logger.info(
                    f"SKIP_AFTER_LOSS: last {last_exit} trade was a loss, "
                    f"confidence {best_conf:.0f} < 75 — skipping same direction"
                )
                self._skip_reasons_today.append({
                    "strategy": leg["strategy"], "direction": leg["direction"],
                    "reason": "Skip after loss — same direction, confidence < 75",
                    "conf": round(best_conf, 1),
                })
                return

        # ── Late window A+ filter (after 10:30) ──────────────────────
        is_late = now.time() >= self._t(self.cfg.late_window_start)
        if is_late:
            # VIX must be calm — exception: very strong trend day with A+ score ≥ 75
            if effective_vix > self.cfg.late_window_vix_max:
                conviction = self._current_trend.conviction if self._current_trend else 0.0
                # Directional move check: price must have moved ≥ 0.8% from open in leg direction
                intraday_move_ok = False
                if candles and len(candles) >= 2:
                    open_px = candles[0].get("open", 0)
                    curr_px = candles[-1].get("close", 0)
                    if open_px and open_px > 0:
                        raw_move = (curr_px - open_px) / open_px
                        dir_move = raw_move if leg["direction"] == "CALL" else -raw_move
                        intraday_move_ok = dir_move >= 0.008
                if (is_strong_trend and conviction >= 0.8
                        and best_conf >= 75 and intraday_move_ok):
                    logger.info(
                        f"LATE_VIX_OVERRIDE: VIX {effective_vix:.1f} > {self.cfg.late_window_vix_max} "
                        f"BUT strong trend conviction={conviction:.2f}, conf={best_conf:.0f}≥75, "
                        f"directional move≥0.8% — allowing entry"
                    )
                    _log_event("LATE_VIX_OVERRIDE", {
                        "vix": round(effective_vix, 1), "conviction": round(conviction, 2),
                        "confidence": round(best_conf, 1), "strategy": leg["strategy"],
                        "direction": leg["direction"],
                    })
                else:
                    logger.info(
                        f"LATE_WINDOW SKIP: VIX {effective_vix:.1f} > {self.cfg.late_window_vix_max} "
                        f"(conviction={conviction:.2f}, conf={best_conf:.0f}, move_ok={intraday_move_ok})"
                    )
                    self._skip_reasons_today.append({
                        "strategy": leg["strategy"], "direction": leg.get("direction", ""),
                        "reason": f"Late window — VIX {effective_vix:.1f} > {self.cfg.late_window_vix_max}",
                        "conf": round(best_conf, 1),
                    })
                    return
            # Strategy must be A+ tier
            allowed = [s.strip() for s in self.cfg.late_window_strategies.split(",")]
            if leg["strategy"] not in allowed:
                logger.info(
                    f"LATE_WINDOW SKIP: strategy {leg['strategy']} not in A+ list {allowed}"
                )
                self._skip_reasons_today.append({
                    "strategy": leg["strategy"], "direction": leg.get("direction", ""),
                    "reason": f"Late window — {leg['strategy']} not in A+ tier",
                    "conf": round(best_conf, 1),
                })
                return
            # Overextension check — only in late window
            # Exception: very high conviction (>= 0.8) strong trend days can move 2-3%
            overextended, oe_reason = self._is_overextended(leg["direction"], candles)
            if overextended:
                conviction = self._current_trend.conviction if self._current_trend else 0.0
                if conviction >= 0.8 and is_strong_trend:
                    logger.info(
                        f"OVEREXTENDED ALLOWED (strong conviction={conviction:.2f}): {oe_reason}"
                    )
                else:
                    logger.info(f"OVEREXTENDED SKIP (late window): {oe_reason}")
                    self._skip_reasons_today.append({
                        "strategy": leg["strategy"], "direction": leg.get("direction", ""),
                        "reason": f"Overextended — {oe_reason}",
                        "conf": round(best_conf, 1),
                    })
                    return
            sl_pct = self.cfg.late_window_sl_pct
            target_pct = self.cfg.late_window_target_pct
            logger.info(
                f"LATE_WINDOW ENTRY: {leg['strategy']} {leg['direction']} | "
                f"VIX={effective_vix:.1f} ok | SL={sl_pct*100:.0f}% TGT={target_pct*100:.0f}%"
            )
        else:
            sl_pct = float(leg["sl_pct"])
            target_pct = float(leg["target_pct"])

        self._enter_trade(
            signal=leg["direction"],
            strategy=leg["strategy"],
            candle=candle,
            atr=None,
            filter_log=dict(leg.get("filter_log") or {}),
            vix=effective_vix,
            regime=stub_regime,
            sl_pct_override=sl_pct,
            target_pct_override=target_pct,
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

        # ── FIX 3: Early session detection (9:15–10:00 = aggressive mode) ──
        is_early_session = current_time < self._t("10:00")

        # ── FIX 5: Missed move detection — skip if Nifty moved >150pts in 30min ──
        if len(candles) >= 7:
            price_30min_ago = float(candles[-7]["close"])
            price_now = float(candles[-1]["close"])
            move_pts = abs(price_now - price_30min_ago)
            if move_pts >= 150.0:
                logger.info(
                    f"MISSED_MOVE: {move_pts:.0f}pts in 30min exceeds 150pt threshold "
                    f"— skipping new entries (prevent late chasing)"
                )
                _log_event("MISSED_MOVE", {
                    "move_pts": round(move_pts, 1),
                    "price_30min_ago": round(price_30min_ago, 1),
                    "price_now": round(price_now, 1),
                    "threshold_pts": 150.0,
                    "regime": regime.regime,
                    "trend": trend.state.value,
                })
                return

        # Strategy list: start from TREND priority, intersect with daily regime whitelist
        strategy_list = trend.strategy_priority
        risk_multiplier = trend.risk_multiplier

        if self._daily_regime:
            regime_strategies = set(self._daily_regime.allowed_strategies)
            strategy_list = [s for s in strategy_list if s in regime_strategies]
            regime_direction = self._daily_regime.allowed_direction
        else:
            regime_direction = None

        # ── FIX 1: Intraday regime overrides ──
        if regime.regime == "VOLATILE":
            if regime.strong_trend_override:
                # Strong trend day detected inside VOLATILE — allow trend strategies
                logger.info(
                    "STRONG_TREND_OVERRIDE: VOLATILE regime + strong trend detected "
                    "(EMA stack + above VWAP + no pullback) — allowing EMA_PULLBACK & MOMENTUM_BREAKOUT"
                )
                _log_event("STRONG_TREND_OVERRIDE", {
                    "regime": regime.regime,
                    "detail": regime.detail,
                    "strategy_override": ["EMA_PULLBACK", "MOMENTUM_BREAKOUT", "ORB", "VWAP_RECLAIM"],
                })
                # Moderate risk reduction (high ATR = bigger moves, but direction is clear)
                risk_multiplier = min(risk_multiplier, 0.80)
            else:
                strategy_list = [s for s in strategy_list if s != "MOMENTUM_BREAKOUT"]
                risk_multiplier = min(risk_multiplier, 0.60)

        if trend.state == TrendState.NEUTRAL:
            strategy_list = [s for s in strategy_list if s not in ("ORB", "MOMENTUM_BREAKOUT")]

        # 10:30 trend-conflict check (skip in early session — price hasn't set direction yet)
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

        # FIX 3/4: Early session FAST MODE — relaxed filter params
        if is_early_session:
            _orb_body = max(0.28, self.cfg.min_breakout_body_ratio - 0.15)
            _orb_vol = max(0.90, self.cfg.min_volume_surge_ratio - 0.30)
            _rsi_bull_min = max(35.0, self.cfg.rsi_bull_min - 10.0)
            _rsi_bear_max = min(65.0, self.cfg.rsi_bear_max + 10.0)
            _pb_prox = self.cfg.ema_pullback_proximity_pct * 1.5
            _pb_body = max(0.28, 0.38 - 0.10)
            logger.debug(
                f"EARLY_SESSION_MODE: relaxed filters active "
                f"(body≥{_orb_body:.0%}, vol≥{_orb_vol:.1f}x, RSI {_rsi_bull_min:.0f}-{_rsi_bear_max:.0f})"
            )
        else:
            _orb_body = self.cfg.min_breakout_body_ratio
            _orb_vol = self.cfg.min_volume_surge_ratio
            _rsi_bull_min = self.cfg.rsi_bull_min
            _rsi_bear_max = self.cfg.rsi_bear_max
            _pb_prox = self.cfg.ema_pullback_proximity_pct
            _pb_body = 0.38

        def _fmt_filters(filters):
            return {
                k: {"passed": v.get("passed"), "value": v.get("value"), "detail": v.get("detail", "")}
                for k, v in filters.items()
            } if filters else {}

        def _eval_strategy(name, result, event_type):
            filters = result.get("filters", {})
            failed_filters = [k for k, v in filters.items() if not (v.get("passed") if isinstance(v, dict) else v)]
            waiting_for = failed_filters[:3] if failed_filters else []
            _log_event(event_type, {
                "strategy": name, "regime": regime.regime,
                "trend": trend.state.value, "conviction": trend.conviction,
                "signal": result.get("signal"), "all_passed": result["all_passed"],
                "filters": _fmt_filters(filters),
                "waiting_for": waiting_for,
                "early_session": is_early_session,
                "strong_trend_override": regime.strong_trend_override,
            })
            confidence = compute_signal_confidence(
                name, result.get("signal", ""), regime.regime, trend, filters, effective_vix
            )
            scan_results.append({
                "strategy": name, "signal": result.get("signal"),
                "passed": result["all_passed"], "confidence": confidence,
                "waiting_for": waiting_for,
            })
            if result["all_passed"] and result["signal"]:
                sl_pct, target_pct = SL_TARGET_BY_STRATEGY.get(name, (0.28, 0.60))
                candidates.append({
                    "strategy": name, "signal": result["signal"],
                    "confidence": confidence, "sl_pct": sl_pct, "target_pct": target_pct,
                    "atr": result.get("atr", 0), "filters": filters,
                })
            else:
                failed = [f"{k}={v.get('value','') if isinstance(v, dict) else ''}" for k, v in filters.items() if not (v.get("passed") if isinstance(v, dict) else v)]
                logger.info(
                    f"{name} SKIP: {'waiting for ' + ', '.join(f[:4]) if failed else 'no signal'} "
                    f"(conf={confidence:.0f}, early={is_early_session})"
                )

        orb_enabled = strat_state.get("orb_enabled", True)

        # ── ORB ──
        if "ORB" in strategy_list and orb_enabled and not self._orb_signal_used and orb_end <= current_time <= entry_close:
            result = evaluate_orb_signal(
                candles, last_candle, vix,
                orb_start=orb_start, orb_end=orb_end,
                min_orb_range_points=self.cfg.min_orb_range_points,
                max_orb_range_points=self.cfg.max_orb_range_points,
                breakout_buffer_pct=self.cfg.breakout_buffer_pct,
                min_breakout_body_ratio=_orb_body,
                min_volume_surge_ratio=_orb_vol,
                ema_fast=self.cfg.ema_fast, ema_slow=self.cfg.ema_slow,
                rsi_period=self.cfg.rsi_period, atr_period=self.cfg.atr_period,
                require_vwap_confirmation=self.cfg.require_vwap_confirmation,
                vwap_buffer_points=self.cfg.vwap_buffer_points,
                rsi_bull_min=_rsi_bull_min, rsi_bear_max=_rsi_bear_max,
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
                min_breakout_body_ratio=max(0.28, _orb_body - 0.05),
                min_volume_surge_ratio=max(0.80, _orb_vol - 0.10),
                ema_fast=self.cfg.ema_fast, ema_slow=self.cfg.ema_slow,
                rsi_period=self.cfg.rsi_period, atr_period=self.cfg.atr_period,
                require_vwap_confirmation=self.cfg.require_vwap_confirmation,
                vwap_buffer_points=self.cfg.vwap_buffer_points,
                rsi_bull_min=_rsi_bull_min, rsi_bear_max=_rsi_bear_max,
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
                pullback_proximity_pct=_pb_prox,
                min_body_ratio=_pb_body,
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
            "strong_trend_override": regime.strong_trend_override,
            "trend": trend.state.value,
            "trend_direction": trend.direction,
            "conviction": trend.conviction,
            "risk_multiplier": risk_multiplier,
            "vix": effective_vix,
            "early_session": is_early_session,
            "strategies_evaluated": len(scan_results),
            "signals_detected": len(candidates),
            "scans": scan_results,  # includes waiting_for per strategy
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

        # ── Conviction-based OTM selection ──────────────────────────
        # A+ = EXTREME impulse + STRONG_BEAR/BULL → deep OTM (2 steps = 100pts)
        # STRONG trend (not A+) → 1-OTM (50pts for better premium/R:R)
        # Normal → ATM; regime otm_offset provides a fallback floor.
        impulse_grade_now = (
            self._current_impulse.grade
            if self._current_impulse is not None else ImpulseGrade.NONE
        )
        trend_state_now = (
            self._current_trend.state if self._current_trend is not None else None
        )
        _strong_states = (TrendState.STRONG_BEAR, TrendState.STRONG_BULL)
        _is_aplus = (
            impulse_grade_now == ImpulseGrade.EXTREME
            and trend_state_now in _strong_states
        )
        _is_strong = (
            trend_state_now in _strong_states
            and not _is_aplus
        )
        if _is_aplus:
            otm_offset = self.cfg.aplus_otm_steps
        elif _is_strong:
            otm_offset = self.cfg.strong_otm_steps
        else:
            regime_otm = self._daily_regime.otm_offset if self._daily_regime else 0
            otm_offset = max(regime_otm, self.cfg.normal_otm_steps)

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

        # ── Contextual SL (live bot) ─────────────────────────────────
        # A+ setup: full wide SL (passed in as sl_pct_override, typically 0.30)
        # STRONG trend: medium SL (~25%)
        # Normal: tight SL (~20-22%) — don't give marginal setups extra room
        if _is_aplus:
            sl_pct = sl_pct_override              # full 30%
        elif _is_strong:
            sl_pct = sl_pct_override * 0.83       # ~25%
        else:
            sl_pct = sl_pct_override * 0.73       # ~22%
        if is_thursday:
            sl_pct = min(sl_pct, self.cfg.thursday_max_loss_pct)
        logger.info(f"CONTEXTUAL_SL: setup={setup_tag} sl={sl_pct*100:.1f}% (base={sl_pct_override*100:.0f}%)")

        # ── Conviction-based risk scaling ────────────────────────────
        # A+ (EXTREME impulse + STRONG trend) → 5% risk (3-4 lots at ₹1L)
        # STRONG trend (non-A+)               → 3% risk (2 lots)
        # Normal                              → regime/config default (1-2 lots)
        base_risk_pct = self._daily_regime.execution.risk_pct if self._daily_regime else self.cfg.risk_per_trade_pct
        if _is_aplus:
            effective_risk_pct = self.cfg.aplus_risk_pct * risk_multiplier
            logger.info(
                f"CONVICTION_SIZING: A+ setup (EXTREME impulse + {trend_state_now}) "
                f"→ risk={effective_risk_pct*100:.1f}% OTM={otm_offset} steps"
            )
        elif _is_strong:
            effective_risk_pct = max(base_risk_pct * 1.50, 0.03) * risk_multiplier
            logger.info(
                f"CONVICTION_SIZING: STRONG trend ({trend_state_now}) "
                f"→ risk={effective_risk_pct*100:.1f}% OTM={otm_offset} steps"
            )
        else:
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
        setup_tag = "A+" if _is_aplus else ("STRONG" if _is_strong else "STD")
        otm_tag   = f"OTM+{otm_offset}" if otm_offset > 0 else "ATM"
        logger.info(
            f"SIGNAL: {strategy} {signal} [{setup_tag}/{otm_tag}] | "
            f"trend={trend_info} impulse={impulse_grade_now} regime={regime.regime} | "
            f"confidence={conf_score:.0f} | "
            f"{symbol} strike={strike} | LTP={opt_price:.2f} SL={sl_price:.2f} ({sl_pct*100:.0f}%) "
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
            "setup_tag": setup_tag, "otm_offset": otm_offset,
            "impulse_grade": impulse_grade_now,
        })

        daily_regime_name = self._daily_regime.name if self._daily_regime else "?"
        _otm_label = f"OTM+{otm_offset}" if otm_offset > 0 else "ATM"
        _setup_label = "A+" if _is_aplus else ("STRONG" if _is_strong else "STD")
        self._notify(
            f"🚀 ENTRY: {strategy} {signal} [{daily_regime_name}] [{_setup_label}/{_otm_label}]\n"
            f"{symbol}\n"
            f"Fill: ₹{fill_price:.0f} (slip {((fill_price - opt_price) / opt_price * 100):+.1f}%)\n"
            f"SL: ₹{sl_price:.0f} ({sl_pct*100:.0f}%) | TGT: ₹{target_price:.0f}\n"
            f"Risk: ₹{size_info['actual_risk']:.0f} | Lots: {lots} | SL-M: {'YES' if self._active_slm_order_id else 'NO'}"
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
                        "last_exit_reason": self._last_exit_reason,
                        "last_trade_pnl": self._last_trade_pnl,
                        "last_trade_strategy": self._last_trade_strategy,
                        "skip_reasons": self._skip_reasons_today[-5:],
                        "move_from_open_pct": (
                            round((float(candles[-1]["close"]) - float(candles[0]["open"]))
                                  / float(candles[0]["open"]) * 100, 3)
                            if candles and len(candles) >= 2
                            and float(candles[0].get("open", 0)) > 0
                            else 0.0
                        ),
                        "nifty_open_price": float(candles[0]["open"]) if candles else 0.0,
                        "trend_state_live": self._current_trend.state.value if self._current_trend else "NEUTRAL",
                        "trend_conviction_live": round(self._current_trend.conviction, 3) if self._current_trend else 0.0,
                        "impulse_grade_live": (self._current_impulse.grade if self._current_impulse else "NONE"),
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
