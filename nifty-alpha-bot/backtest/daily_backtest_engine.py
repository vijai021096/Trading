"""
Daily-timeframe backtest engine for 2+ year backtesting.

Multi-strategy, regime-aware engine that selects the optimal strategy
per day based on market conditions:

  1. ORB (Opening Range Breakout) — trending days with clear breakout
  2. VWAP Reclaim — mean-reversion from VWAP deviation
  3. Mean-Reversion — range-bound days, RSI pullback + bounce
  4. Momentum/Gap Continuation — strong trend days, gap + follow-through
  5. Relaxed ORB — breakout without strict EMA alignment (weaker edge)

Regime detection classifies each day as TRENDING, RANGING, or VOLATILE
based on prior-day ADX proxy, ATR-to-range ratio, and VIX.

Realistic option pricing with IV smile, IV crush, dynamic slippage,
intraday high/low SL/target simulation.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backtest.data_downloader import get_vix_for_date
from backtest.metrics import compute_metrics
from shared.black_scholes import (
    price_option, implied_vol_from_vix, atm_strike,
    charges_estimate, realistic_slippage,
)

RISK_FREE_RATE = 0.065


@dataclass
class DailyBacktestConfig:
    capital: float = 100_000.0
    lot_size: int = 65
    lots: int = 1

    # ── ORB ──
    breakout_buffer_pct: float = 0.0005
    min_range_pct: float = 0.004
    max_range_pct: float = 0.022

    # ── VWAP ──
    vwap_lookback: int = 5
    vwap_deviation_pct: float = 0.003

    # ── Mean-Reversion ──
    mr_rsi_oversold: float = 35.0
    mr_rsi_overbought: float = 65.0
    mr_body_ratio_min: float = 0.45
    mr_prev_candle_body_ratio_min: float = 0.35

    # ── Momentum / Gap continuation ──
    gap_min_pct: float = 0.002
    gap_max_pct: float = 0.025
    gap_followthrough_pct: float = 0.0008

    # ── Relaxed ORB (no EMA requirement) ──
    relaxed_orb_body_ratio: float = 0.45
    relaxed_orb_rsi_min: float = 38.0
    relaxed_orb_rsi_max: float = 62.0

    # ── Range-Day Fade (bounce off prior day extremes) ──
    fade_proximity_pct: float = 0.003
    fade_body_ratio_min: float = 0.45
    fade_rsi_bull_zone: float = 38.0
    fade_rsi_bear_zone: float = 62.0

    # ── EMA-Pullback (trend continuation after pullback to EMA) ──
    ema_pb_min_trend_days: int = 3
    ema_pb_touch_tolerance_pct: float = 0.003
    ema_pb_body_ratio_min: float = 0.40

    # ── Shared filters ──
    ema_fast: int = 5
    ema_slow: int = 13
    rsi_period: int = 14
    rsi_bull_min: float = 40.0
    rsi_bear_max: float = 60.0
    rsi_overbought_skip: float = 80.0
    rsi_oversold_skip: float = 20.0
    vix_max: float = 28.0

    # ── Regime thresholds ──
    adx_trending_threshold: float = 0.30
    atr_volatile_multiplier: float = 1.8

    # ── SL / Target (optimized Mar 2026) ──
    sl_pct: float = 0.28
    target_pct: float = 0.65
    sl_pct_mr: float = 0.18
    target_pct_mr: float = 0.45
    sl_pct_gap: float = 0.28
    target_pct_gap: float = 0.55
    sl_pct_relaxed: float = 0.28
    target_pct_relaxed: float = 0.58
    sl_pct_fade: float = 0.22
    target_pct_fade: float = 0.50
    sl_pct_ema_pb: float = 0.30
    target_pct_ema_pb: float = 0.65
    slippage_pct: float = 0.005

    # ── Risk ──
    max_trades_per_day: int = 1
    max_consecutive_losses: int = 6
    max_daily_loss_pct: float = 0.04
    strike_step: int = 50

    # ── Strategy enable flags ──
    enable_orb: bool = True
    enable_vwap: bool = True
    enable_mean_reversion: bool = True
    enable_gap_momentum: bool = False
    enable_relaxed_orb: bool = True
    enable_fade: bool = True
    enable_ema_pullback: bool = True


# ── Indicators ────────────────────────────────────────────────────

def _ema(series: list, period: int) -> list:
    if not series:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [series[0]]
    for v in series[1:]:
        out.append(v * alpha + out[-1] * (1 - alpha))
    return out


def _rsi(closes: list, period: int = 14) -> list:
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    result = [50.0] * period
    gains, losses_v = 0.0, 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d > 0:
            gains += d
        else:
            losses_v += abs(d)
    avg_gain = gains / period
    avg_loss = losses_v / period
    rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
    result.append(100.0 - 100.0 / (1.0 + rs))
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(0, d)) / period
        avg_loss = (avg_loss * (period - 1) + max(0, -d)) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
        result.append(100.0 - 100.0 / (1.0 + rs))
    return result


def _atr(highs: list, lows: list, closes: list, period: int = 14) -> list:
    """Wilder's ATR."""
    if len(closes) < 2:
        return [0.0] * len(closes)
    trs = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if len(trs) < period:
        return trs
    atr_val = sum(trs[:period]) / period
    out = [0.0] * (period - 1) + [atr_val]
    for i in range(period, len(trs)):
        atr_val = (atr_val * (period - 1) + trs[i]) / period
        out.append(atr_val)
    return out


def _directional_movement(highs: list, lows: list, closes: list, period: int = 14) -> list:
    """ADX proxy: ratio of absolute directional movement to total range over a window.
    Returns 0-1 where >0.55 suggests trending."""
    if len(closes) < period + 1:
        return [0.5] * len(closes)

    result = [0.5] * period
    for i in range(period, len(closes)):
        window_close = closes[i - period:i + 1]
        net_move = abs(window_close[-1] - window_close[0])
        total_range = sum(highs[j] - lows[j] for j in range(i - period + 1, i + 1))
        ratio = net_move / total_range if total_range > 0 else 0.5
        result.append(min(1.0, ratio))
    return result


# ── Regime Detection ──────────────────────────────────────────────

def _detect_regime(
    adx_proxy: float, atr_val: float, atr_avg: float,
    vix: float, cfg: DailyBacktestConfig,
) -> str:
    """Classify the day into TRENDING, RANGING, or VOLATILE."""
    atr_ratio = atr_val / atr_avg if atr_avg > 0 else 1.0

    if vix > cfg.vix_max or atr_ratio > cfg.atr_volatile_multiplier:
        return "VOLATILE"
    if adx_proxy >= cfg.adx_trending_threshold:
        return "TRENDING"
    return "RANGING"


# ── Strategy Signals ──────────────────────────────────────────────

def _check_orb(
    i: int, highs: list, lows: list, closes: list, opens: list,
    ema_f: float, ema_s: float, rsi: float,
    cfg: DailyBacktestConfig, strict_ema: bool = True,
) -> Optional[Tuple[str, str, dict]]:
    """ORB breakout of previous day's high/low."""
    prev_high = highs[i - 1]
    prev_low = lows[i - 1]
    prev_range = prev_high - prev_low
    prev_range_pct = prev_range / closes[i - 1] if closes[i - 1] > 0 else 0
    today_open = opens[i]
    today_close = closes[i]
    today_high = highs[i]
    today_low = lows[i]
    today_range = today_high - today_low
    today_body = abs(today_close - today_open)
    body_ratio = today_body / today_range if today_range > 0 else 0

    if not (cfg.min_range_pct <= prev_range_pct <= cfg.max_range_pct):
        return None

    call_th = prev_high * (1 + cfg.breakout_buffer_pct)
    put_th = prev_low * (1 - cfg.breakout_buffer_pct)

    if today_close > call_th:
        ema_ok = (ema_f > ema_s) if strict_ema else True
        rsi_lo = cfg.rsi_bull_min if strict_ema else cfg.relaxed_orb_rsi_min
        rsi_hi = cfg.rsi_overbought_skip if strict_ema else cfg.relaxed_orb_rsi_max
        # For relaxed ORB, require the candle to be green (close > open)
        candle_ok = True if strict_ema else (today_close > today_open and body_ratio >= cfg.relaxed_orb_body_ratio)
        if ema_ok and candle_ok and rsi_lo <= rsi <= rsi_hi:
            tag = "ORB" if strict_ema else "RELAXED_ORB"
            flog = {
                "breakout": {"passed": True, "detail": f"Close {today_close:.0f} > prev_high {prev_high:.0f}"},
                "ema_trend": {"passed": ema_f > ema_s, "detail": f"EMA{cfg.ema_fast}={ema_f:.0f} vs EMA{cfg.ema_slow}={ema_s:.0f}"},
                "rsi": {"passed": True, "value": round(rsi, 1)},
            }
            return ("CALL", tag, flog)

    elif today_close < put_th:
        ema_ok = (ema_f < ema_s) if strict_ema else True
        rsi_lo = cfg.rsi_oversold_skip if strict_ema else (100 - cfg.relaxed_orb_rsi_max)
        rsi_hi = cfg.rsi_bear_max if strict_ema else (100 - cfg.relaxed_orb_rsi_min)
        # For relaxed ORB, require the candle to be red (close < open)
        candle_ok = True if strict_ema else (today_close < today_open and body_ratio >= cfg.relaxed_orb_body_ratio)
        if ema_ok and candle_ok and rsi_lo <= rsi <= rsi_hi:
            tag = "ORB" if strict_ema else "RELAXED_ORB"
            flog = {
                "breakout": {"passed": True, "detail": f"Close {today_close:.0f} < prev_low {prev_low:.0f}"},
                "ema_trend": {"passed": ema_f < ema_s, "detail": f"EMA{cfg.ema_fast}={ema_f:.0f} vs EMA{cfg.ema_slow}={ema_s:.0f}"},
                "rsi": {"passed": True, "value": round(rsi, 1)},
            }
            return ("PUT", tag, flog)

    return None


def _check_vwap_reclaim(
    i: int, closes: list, vwap_vals: list, rsi: float,
    cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """VWAP cross with sufficient prior deviation."""
    if i < 2:
        return None
    prev_close = closes[i - 1]
    prev_vwap = vwap_vals[i - 1]
    today_close = closes[i]
    vwap = vwap_vals[i]

    if prev_close < prev_vwap and today_close > vwap:
        dev = abs(prev_close - prev_vwap) / prev_vwap
        if dev >= cfg.vwap_deviation_pct and cfg.rsi_bull_min <= rsi <= cfg.rsi_overbought_skip:
            return ("CALL", "VWAP_RECLAIM", {
                "vwap_cross": {"passed": True, "detail": f"Cross above VWAP {vwap:.0f}"},
                "deviation": {"passed": True, "value": round(dev * 100, 2)},
            })
    elif prev_close > prev_vwap and today_close < vwap:
        dev = abs(prev_close - prev_vwap) / prev_vwap
        if dev >= cfg.vwap_deviation_pct and cfg.rsi_oversold_skip <= rsi <= cfg.rsi_bear_max:
            return ("PUT", "VWAP_RECLAIM", {
                "vwap_cross": {"passed": True, "detail": f"Cross below VWAP {vwap:.0f}"},
                "deviation": {"passed": True, "value": round(dev * 100, 2)},
            })
    return None


def _check_mean_reversion(
    i: int, highs: list, lows: list, closes: list, opens: list,
    rsi: float, vwap_vals: list, ema_f: float, ema_s: float,
    cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """Range-bound mean-reversion: RSI extreme + reversal candle + bounce toward midpoint."""
    if i < 3:
        return None
    today_open = opens[i]
    today_close = closes[i]
    today_high = highs[i]
    today_low = lows[i]
    today_body = abs(today_close - today_open)
    today_range = today_high - today_low
    body_ratio = today_body / today_range if today_range > 0 else 0

    prev_body = abs(closes[i - 1] - opens[i - 1])
    prev_range = highs[i - 1] - lows[i - 1]
    prev_body_ratio = prev_body / prev_range if prev_range > 0 else 0

    prev2_close = closes[i - 2]
    prev_close = closes[i - 1]
    vwap = vwap_vals[i]

    # Bullish reversal: prior day(s) dropped, RSI low, today bounces up
    # VWAP confirmation: close must be above VWAP (support held)
    prior_drop = prev_close < prev2_close and closes[i - 1] < closes[max(0, i - 3)]
    prev_momentum = prev_body_ratio >= cfg.mr_prev_candle_body_ratio_min
    if (rsi <= cfg.mr_rsi_oversold
        and prior_drop
        and prev_momentum
        and today_close > today_open
        and today_close > vwap
        and body_ratio >= cfg.mr_body_ratio_min):
        return ("CALL", "MEAN_REVERSION", {
            "rsi_extreme": {"passed": True, "value": round(rsi, 1), "detail": f"RSI {rsi:.1f} <= {cfg.mr_rsi_oversold}"},
            "reversal_candle": {"passed": True, "detail": f"Green body {body_ratio:.0%}, after drop"},
            "vwap_support": {"passed": True, "detail": f"Close {today_close:.0f} > VWAP {vwap:.0f}"},
            "prior_move": {"passed": True, "detail": f"Prior drop + body {prev_body_ratio:.0%}"},
        })

    # Bearish reversal: prior day(s) rose, RSI high, today drops
    # VWAP confirmation: close must be below VWAP (resistance held)
    prior_rise = prev_close > prev2_close and closes[i - 1] > closes[max(0, i - 3)]
    if (rsi >= cfg.mr_rsi_overbought
        and prior_rise
        and prev_momentum
        and today_close < today_open
        and today_close < vwap
        and body_ratio >= cfg.mr_body_ratio_min):
        return ("PUT", "MEAN_REVERSION", {
            "rsi_extreme": {"passed": True, "value": round(rsi, 1), "detail": f"RSI {rsi:.1f} >= {cfg.mr_rsi_overbought}"},
            "reversal_candle": {"passed": True, "detail": f"Red body {body_ratio:.0%}, after rise"},
            "vwap_resistance": {"passed": True, "detail": f"Close {today_close:.0f} < VWAP {vwap:.0f}"},
            "prior_move": {"passed": True, "detail": f"Prior rise + body {prev_body_ratio:.0%}"},
        })

    return None


def _check_gap_momentum(
    i: int, highs: list, lows: list, closes: list, opens: list,
    ema_f: float, ema_s: float, rsi: float,
    cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """Gap-and-go / momentum continuation: gap open + follow-through in gap direction."""
    if i < 2:
        return None
    prev_close = closes[i - 1]
    today_open = opens[i]
    today_close = closes[i]
    gap_pct = (today_open - prev_close) / prev_close if prev_close > 0 else 0

    # Gap up + bullish follow-through
    if (cfg.gap_min_pct <= gap_pct <= cfg.gap_max_pct
        and today_close > today_open * (1 + cfg.gap_followthrough_pct)
        and ema_f > ema_s
        and cfg.rsi_bull_min <= rsi <= cfg.rsi_overbought_skip):
        return ("CALL", "GAP_MOMENTUM", {
            "gap": {"passed": True, "detail": f"Gap up {gap_pct*100:.2f}%"},
            "followthrough": {"passed": True, "detail": f"Close {today_close:.0f} > Open {today_open:.0f}"},
            "ema_trend": {"passed": True, "detail": f"EMA{cfg.ema_fast} > EMA{cfg.ema_slow}"},
        })

    # Gap down + bearish follow-through
    if (-cfg.gap_max_pct <= gap_pct <= -cfg.gap_min_pct
        and today_close < today_open * (1 - cfg.gap_followthrough_pct)
        and ema_f < ema_s
        and cfg.rsi_oversold_skip <= rsi <= cfg.rsi_bear_max):
        return ("PUT", "GAP_MOMENTUM", {
            "gap": {"passed": True, "detail": f"Gap down {gap_pct*100:.2f}%"},
            "followthrough": {"passed": True, "detail": f"Close {today_close:.0f} < Open {today_open:.0f}"},
            "ema_trend": {"passed": True, "detail": f"EMA{cfg.ema_fast} < EMA{cfg.ema_slow}"},
        })

    return None


def _check_range_fade(
    i: int, highs: list, lows: list, closes: list, opens: list,
    rsi: float, cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """Fade moves near prior-day extremes on range-bound days.
    If price approaches prior-day high but reverses down, take PUT.
    If price approaches prior-day low but bounces up, take CALL."""
    if i < 2:
        return None
    prev_high = highs[i - 1]
    prev_low = lows[i - 1]
    today_open = opens[i]
    today_close = closes[i]
    today_high = highs[i]
    today_low = lows[i]
    today_body = abs(today_close - today_open)
    today_range = today_high - today_low
    body_ratio = today_body / today_range if today_range > 0 else 0

    proximity = prev_high * cfg.fade_proximity_pct

    # Touched near prior high but closed lower (bearish rejection)
    if (today_high >= prev_high - proximity
        and today_close < today_open
        and today_close < prev_high
        and body_ratio >= cfg.fade_body_ratio_min
        and rsi >= cfg.fade_rsi_bear_zone):
        return ("PUT", "RANGE_FADE", {
            "fade_level": {"passed": True, "detail": f"High {today_high:.0f} near prev_high {prev_high:.0f}"},
            "rejection": {"passed": True, "detail": f"Closed below open, body ratio {body_ratio:.0%}"},
            "rsi": {"passed": True, "value": round(rsi, 1)},
        })

    # Touched near prior low but closed higher (bullish bounce)
    if (today_low <= prev_low + proximity
        and today_close > today_open
        and today_close > prev_low
        and body_ratio >= cfg.fade_body_ratio_min
        and rsi <= cfg.fade_rsi_bull_zone):
        return ("CALL", "RANGE_FADE", {
            "fade_level": {"passed": True, "detail": f"Low {today_low:.0f} near prev_low {prev_low:.0f}"},
            "bounce": {"passed": True, "detail": f"Closed above open, body ratio {body_ratio:.0%}"},
            "rsi": {"passed": True, "value": round(rsi, 1)},
        })

    return None


def _check_ema_pullback(
    i: int, highs: list, lows: list, closes: list, opens: list,
    ema_f: float, ema_s: float, ema_fast_vals: list, ema_slow_vals: list,
    rsi: float, cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """Trend continuation: price pulls back to fast EMA and bounces in trend direction.
    Requires established trend (EMA fast > slow for N days)."""
    if i < cfg.ema_pb_min_trend_days + 1:
        return None

    today_close = closes[i]
    today_open = opens[i]
    today_low = lows[i]
    today_high = highs[i]
    today_body = abs(today_close - today_open)
    today_range = today_high - today_low
    body_ratio = today_body / today_range if today_range > 0 else 0

    # Check if trend has been consistent for min_trend_days
    bullish_trend = all(
        ema_fast_vals[j] > ema_slow_vals[j]
        for j in range(i - cfg.ema_pb_min_trend_days, i + 1)
    )
    bearish_trend = all(
        ema_fast_vals[j] < ema_slow_vals[j]
        for j in range(i - cfg.ema_pb_min_trend_days, i + 1)
    )

    tolerance = ema_f * cfg.ema_pb_touch_tolerance_pct

    # Bullish: price dipped to EMA fast and closed above it
    if (bullish_trend
        and today_low <= ema_f + tolerance
        and today_close > ema_f
        and today_close > today_open
        and body_ratio >= cfg.ema_pb_body_ratio_min
        and 45.0 <= rsi <= cfg.rsi_overbought_skip):
        return ("CALL", "EMA_PULLBACK", {
            "trend": {"passed": True, "detail": f"Bullish trend {cfg.ema_pb_min_trend_days}+ days"},
            "pullback": {"passed": True, "detail": f"Low {today_low:.0f} touched EMA{cfg.ema_fast} {ema_f:.0f}"},
            "bounce": {"passed": True, "detail": f"Closed {today_close:.0f} above EMA, body {body_ratio:.0%}"},
        })

    # Bearish: price popped to EMA fast and closed below it
    if (bearish_trend
        and today_high >= ema_f - tolerance
        and today_close < ema_f
        and today_close < today_open
        and body_ratio >= cfg.ema_pb_body_ratio_min
        and cfg.rsi_oversold_skip <= rsi <= 55.0):
        return ("PUT", "EMA_PULLBACK", {
            "trend": {"passed": True, "detail": f"Bearish trend {cfg.ema_pb_min_trend_days}+ days"},
            "pullback": {"passed": True, "detail": f"High {today_high:.0f} touched EMA{cfg.ema_fast} {ema_f:.0f}"},
            "rejection": {"passed": True, "detail": f"Closed {today_close:.0f} below EMA, body {body_ratio:.0%}"},
        })

    return None


# ── Option Simulation ─────────────────────────────────────────────

def _get_weekly_expiry(trade_date: date) -> date:
    days_until_thursday = (3 - trade_date.weekday()) % 7
    return trade_date + timedelta(days=days_until_thursday)


def _simulate_option_trade(
    spot_entry: float,
    direction: str,
    trade_date: date,
    vix: float,
    day_high: float,
    day_low: float,
    day_close: float,
    sl_pct: float,
    target_pct: float,
    cfg: DailyBacktestConfig,
) -> Optional[Dict[str, Any]]:
    """Simulate option trade using daily OHLC with intraday SL/target via high/low."""
    expiry = _get_weekly_expiry(trade_date)
    strike = atm_strike(spot_entry, cfg.strike_step)
    opt_type = "CE" if direction == "CALL" else "PE"
    dte = (expiry - trade_date).days
    moneyness = spot_entry / strike
    sigma = implied_vol_from_vix(vix, moneyness)
    iv_crush = -0.005 * (vix / 15.0)

    T_entry = max(0.0001, (dte * 0.71 + 0.5) / 252.0)

    entry_opt = price_option(spot_entry, strike, T_entry, RISK_FREE_RATE, sigma, opt_type)
    raw_entry = entry_opt["price"]
    if raw_entry < 5:
        return None

    entry_slip = realistic_slippage(cfg.slippage_pct, vix, dte, raw_entry)
    entry_price = raw_entry * (1 + entry_slip)

    sl_price = entry_price * (1 - sl_pct)
    target_price = entry_price * (1 + target_pct)

    sigma_exit = max(0.05, sigma + iv_crush)
    T_exit = max(0.0001, (dte * 0.71 + 0.1) / 252.0)

    if direction == "CALL":
        spot_best = day_high
        spot_worst = day_low
    else:
        spot_best = day_low
        spot_worst = day_high

    opt_best = price_option(spot_best, strike, T_exit, RISK_FREE_RATE, sigma_exit, opt_type)["price"]
    opt_worst = price_option(spot_worst, strike, T_exit, RISK_FREE_RATE, sigma_exit, opt_type)["price"]
    opt_close = price_option(day_close, strike, T_exit, RISK_FREE_RATE, sigma_exit, opt_type)["price"]

    if opt_worst <= sl_price:
        exit_price_raw = sl_price
        exit_reason = "SL_HIT"
    elif opt_best >= target_price:
        exit_price_raw = target_price
        exit_reason = "TARGET_HIT"
    else:
        exit_price_raw = opt_close
        exit_reason = "FORCE_EXIT"

    exit_slip = realistic_slippage(cfg.slippage_pct, vix, dte, exit_price_raw)
    exit_price = exit_price_raw * (1 - exit_slip)

    qty = cfg.lots * cfg.lot_size
    gross_pnl = (exit_price - entry_price) * qty
    charges = charges_estimate(entry_price, exit_price, qty)
    net_pnl = gross_pnl - charges

    return {
        "status": "COMPLETED",
        "direction": direction,
        "option_type": opt_type,
        "strike": strike,
        "expiry": expiry.isoformat(),
        "entry_ts": f"{trade_date}T09:30:00",
        "exit_ts": f"{trade_date}T15:15:00",
        "entry_price": round(entry_price, 2),
        "exit_price": round(exit_price, 2),
        "sl_price": round(sl_price, 2),
        "target_price": round(target_price, 2),
        "exit_reason": exit_reason,
        "gross_pnl": round(gross_pnl, 2),
        "charges": round(charges, 2),
        "net_pnl": round(net_pnl, 2),
        "qty": qty,
        "lots": cfg.lots,
        "spot_at_entry": round(spot_entry, 2),
        "delta_at_entry": round(entry_opt.get("delta", 0.5), 4),
        "iv_at_entry": round(sigma, 4),
        "vix": vix,
        "trade_date": trade_date.isoformat(),
        "entry_slippage_pct": round(entry_slip * 100, 2),
    }


# ── Strategy Priority by Regime ──────────────────────────────────

STRATEGY_PRIORITY = {
    "TRENDING": ["ORB", "GAP_MOMENTUM", "EMA_PULLBACK", "VWAP_RECLAIM", "RELAXED_ORB"],
    "RANGING":  ["VWAP_RECLAIM", "EMA_PULLBACK", "MEAN_REVERSION", "RANGE_FADE", "RELAXED_ORB", "GAP_MOMENTUM"],
    "VOLATILE": ["VWAP_RECLAIM", "MEAN_REVERSION", "RANGE_FADE"],
}

SL_TARGET_MAP = {
    "ORB":             ("sl_pct", "target_pct"),
    "VWAP_RECLAIM":    ("sl_pct", "target_pct"),
    "MEAN_REVERSION":  ("sl_pct_mr", "target_pct_mr"),
    "GAP_MOMENTUM":    ("sl_pct_gap", "target_pct_gap"),
    "RELAXED_ORB":     ("sl_pct_relaxed", "target_pct_relaxed"),
    "RANGE_FADE":      ("sl_pct_fade", "target_pct_fade"),
    "EMA_PULLBACK":    ("sl_pct_ema_pb", "target_pct_ema_pb"),
}

ALL_STRATEGIES = {"ORB", "VWAP_RECLAIM", "MEAN_REVERSION", "GAP_MOMENTUM", "RELAXED_ORB", "RANGE_FADE", "EMA_PULLBACK"}

STRATEGY_FILTER_MAP = {
    "ORB":     {"ORB", "RELAXED_ORB"},
    "VWAP":    {"VWAP_RECLAIM"},
    "MR":      {"MEAN_REVERSION", "RANGE_FADE"},
    "GAP":     {"GAP_MOMENTUM"},
    "BOTH":    ALL_STRATEGIES,
}


# ── Main Engine ───────────────────────────────────────────────────

def run_daily_backtest(
    nifty_daily: pd.DataFrame,
    vix_df: pd.DataFrame,
    cfg: Optional[DailyBacktestConfig] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    verbose: bool = True,
    strategy_filter: str = "BOTH",
) -> Dict[str, Any]:
    if cfg is None:
        cfg = DailyBacktestConfig()

    allowed_strategies = STRATEGY_FILTER_MAP.get(strategy_filter, STRATEGY_FILTER_MAP["BOTH"])

    df = nifty_daily.copy()
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values("ts").reset_index(drop=True)

    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    opens = df["open"].tolist()
    dates = df["ts"].dt.date.tolist()

    ema_fast_vals = _ema(closes, cfg.ema_fast)
    ema_slow_vals = _ema(closes, cfg.ema_slow)
    rsi_vals = _rsi(closes, cfg.rsi_period)
    atr_vals = _atr(highs, lows, closes, 14)
    adx_proxy_vals = _directional_movement(highs, lows, closes, 14)

    atr_sma_period = 50
    atr_sma = [0.0] * len(atr_vals)
    for idx in range(len(atr_vals)):
        window = atr_vals[max(0, idx - atr_sma_period + 1):idx + 1]
        atr_sma[idx] = sum(window) / len(window) if window else 1.0

    df["tp"] = (df["high"] + df["low"] + df["close"]) / 3
    df["tp_vol"] = df["tp"] * df["volume"].clip(lower=1)
    df["vol_sum"] = df["volume"].clip(lower=1).rolling(cfg.vwap_lookback, min_periods=1).sum()
    df["vwap"] = df["tp_vol"].rolling(cfg.vwap_lookback, min_periods=1).sum() / df["vol_sum"]
    vwap_vals = df["vwap"].tolist()

    warmup = max(cfg.ema_slow + 1, cfg.rsi_period + 1, atr_sma_period + 1, 3)
    if start_date:
        start_idx = next((j for j, d in enumerate(dates) if d >= start_date), 0)
        start_idx = max(start_idx, warmup)
    else:
        start_idx = warmup

    if end_date:
        end_idx = next((j for j, d in enumerate(dates) if d > end_date), len(dates))
    else:
        end_idx = len(dates)

    all_trades: List[Dict[str, Any]] = []
    capital = cfg.capital
    consecutive_losses = 0
    regime_counts = {"TRENDING": 0, "RANGING": 0, "VOLATILE": 0}
    strategy_counts: Dict[str, int] = {}
    skip_reasons: Dict[str, int] = {}

    if verbose:
        print(f"\n{'='*70}")
        print(f" MULTI-STRATEGY DAILY BACKTEST: {end_idx - start_idx} trading days")
        print(f" Range: {dates[start_idx]} to {dates[min(end_idx-1, len(dates)-1)]}")
        print(f" Capital: ₹{cfg.capital:,.0f} | Lots: {cfg.lots} | Lot size: {cfg.lot_size}")
        print(f" Strategies: {', '.join(sorted(allowed_strategies))}")
        print(f" VIX cap: {cfg.vix_max} | Consec loss limit: {cfg.max_consecutive_losses}")
        print(f"{'='*70}\n")

    for i in range(start_idx, end_idx):
        trade_date = dates[i]
        vix = get_vix_for_date(vix_df, trade_date)

        if consecutive_losses >= cfg.max_consecutive_losses:
            consecutive_losses = max(0, consecutive_losses - 1)
            skip_reasons["consec_loss"] = skip_reasons.get("consec_loss", 0) + 1
            continue

        # Detect regime
        adx_p = adx_proxy_vals[i] if i < len(adx_proxy_vals) else 0.5
        atr_v = atr_vals[i] if i < len(atr_vals) else 0
        atr_a = atr_sma[i] if i < len(atr_sma) else 1
        regime = _detect_regime(adx_p, atr_v, atr_a, vix, cfg)
        regime_counts[regime] += 1

        ema_f = ema_fast_vals[i]
        ema_s = ema_slow_vals[i]
        rsi = rsi_vals[i]

        # Try strategies in regime-priority order
        priority = STRATEGY_PRIORITY.get(regime, STRATEGY_PRIORITY["RANGING"])
        signal_result = None

        for strat_name in priority:
            if strat_name not in allowed_strategies:
                continue

            if strat_name == "ORB" and cfg.enable_orb:
                signal_result = _check_orb(i, highs, lows, closes, opens, ema_f, ema_s, rsi, cfg, strict_ema=True)
            elif strat_name == "RELAXED_ORB" and cfg.enable_relaxed_orb:
                signal_result = _check_orb(i, highs, lows, closes, opens, ema_f, ema_s, rsi, cfg, strict_ema=False)
            elif strat_name == "VWAP_RECLAIM" and cfg.enable_vwap:
                signal_result = _check_vwap_reclaim(i, closes, vwap_vals, rsi, cfg)
            elif strat_name == "MEAN_REVERSION" and cfg.enable_mean_reversion:
                signal_result = _check_mean_reversion(i, highs, lows, closes, opens, rsi, vwap_vals, ema_f, ema_s, cfg)
            elif strat_name == "GAP_MOMENTUM" and cfg.enable_gap_momentum:
                signal_result = _check_gap_momentum(i, highs, lows, closes, opens, ema_f, ema_s, rsi, cfg)
            elif strat_name == "RANGE_FADE" and cfg.enable_fade:
                signal_result = _check_range_fade(i, highs, lows, closes, opens, rsi, cfg)
            elif strat_name == "EMA_PULLBACK" and cfg.enable_ema_pullback:
                signal_result = _check_ema_pullback(i, highs, lows, closes, opens, ema_f, ema_s, ema_fast_vals, ema_slow_vals, rsi, cfg)

            if signal_result is not None:
                break

        if signal_result is None:
            skip_reasons["no_signal"] = skip_reasons.get("no_signal", 0) + 1
            continue

        signal, strategy_name, filter_log = signal_result
        filter_log["regime"] = {"value": regime}

        sl_key, tgt_key = SL_TARGET_MAP.get(strategy_name, ("sl_pct", "target_pct"))
        sl = getattr(cfg, sl_key)
        tgt = getattr(cfg, tgt_key)

        trade = _simulate_option_trade(
            spot_entry=opens[i],
            direction=signal,
            trade_date=trade_date,
            vix=vix,
            day_high=highs[i],
            day_low=lows[i],
            day_close=closes[i],
            sl_pct=sl,
            target_pct=tgt,
            cfg=cfg,
        )

        if trade is None or trade["status"] != "COMPLETED":
            skip_reasons["sim_failed"] = skip_reasons.get("sim_failed", 0) + 1
            continue

        trade["strategy"] = strategy_name
        trade["regime"] = regime
        trade["filter_log"] = filter_log
        all_trades.append(trade)
        strategy_counts[strategy_name] = strategy_counts.get(strategy_name, 0) + 1

        net = trade["net_pnl"]
        capital += net
        if net > 0:
            consecutive_losses = 0
        else:
            consecutive_losses += 1

        if verbose:
            sign = "+" if net >= 0 else ""
            print(
                f"  [{trade_date}] {regime:8s} {strategy_name:15s} {signal:4s} | "
                f"Entry={trade['entry_price']:.0f} Exit={trade['exit_price']:.0f} | "
                f"P&L: {sign}₹{net:.0f} | {trade['exit_reason']} | VIX={vix:.1f}"
            )

        sys.stdout.flush()

    metrics = compute_metrics(all_trades, cfg.capital)

    if verbose:
        total_days = end_idx - start_idx
        print(f"\n{'='*70}")
        print(f" SUMMARY")
        print(f"  Days: {total_days} | Traded: {len(all_trades)} ({len(all_trades)/total_days*100:.0f}%)")
        print(f"  Regimes: {regime_counts}")
        print(f"  Strategy breakdown: {strategy_counts}")
        print(f"  Skip reasons: {skip_reasons}")
        print(f"  Final capital: ₹{capital:,.0f} | Return: {((capital - cfg.capital) / cfg.capital) * 100:.1f}%")
        print(f"{'='*70}\n")

    return {
        "trades": all_trades,
        "metrics": metrics,
        "config": cfg.__dict__,
        "start_date": dates[start_idx].isoformat() if start_idx < len(dates) else None,
        "end_date": dates[min(end_idx - 1, len(dates) - 1)].isoformat() if end_idx > 0 else None,
        "timeframe": "daily",
        "regime_counts": regime_counts,
        "strategy_counts": strategy_counts,
        "skip_reasons": skip_reasons,
    }
