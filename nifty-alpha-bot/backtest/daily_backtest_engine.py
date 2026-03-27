"""
Daily-timeframe backtest engine — "Adaptive Alpha" Strategy Suite.

6-Regime Market Classifier:
  STRONG_TREND_UP   — ADX high + EMA stacked bullish + VIX calm
  STRONG_TREND_DOWN — ADX high + EMA stacked bearish + VIX calm
  MILD_TREND        — Moderate directional movement, EMA aligned
  MEAN_REVERT       — Low ADX + tight range + RSI mid-zone
  BREAKOUT          — Compression then expansion (ATR spike after squeeze)
  VOLATILE          — High VIX or ATR explosion — defensive mode

7 Strategies (regime-gated):
  1. TREND_CONTINUATION  — pullback to EMA in trend, bounce with VWAP confirm
  2. BREAKOUT_MOMENTUM   — range breakout with volume + EMA alignment
  3. REVERSAL_SNAP       — RSI extreme exhaustion + reversal candle
  4. GAP_FADE            — fade opening gaps that fill statistically
  5. RANGE_BOUNCE        — bounce off prior-day support/resistance in ranging market
  6. INSIDE_BAR_BREAK    — inside bar compression breakout (low-risk entry)
  7. VWAP_CROSS          — VWAP cross with prior deviation (institutional flow)

Risk management:
  - Regime-adaptive SL/target (tight in vol, wider in trend)
  - First calendar month of backtest: size as ₹25k risk only (no full-capital compounding)
  - Peak-equity drawdown guard: scale down / pause to keep portfolio DD near target
  - VIX-based lot reduction
  - Max consecutive losses → cooldown
  - Up to 4 distinct strategies/day; legs 2–4 use reduced size vs leg 1; VIX caps multi-leg risk
"""
from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass
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
    lot_size: int = 75
    lots: int = 1

    # First month of backtest window: only risk this much for sizing (no scaling from full equity)
    first_month_risk_capital: float = 25_000.0
    first_month_max_lots: int = 1

    # Drawdown control vs peak equity (portfolio-level); no trading halt (need trades to recover)
    dd_soft_pct: float = 0.045
    dd_hard_pct: float = 0.085
    dd_force_one_lot_pct: float = 0.108

    # ── Indicators ──
    ema_fast: int = 8
    ema_slow: int = 21
    ema_trend: int = 50
    rsi_period: int = 14
    atr_period: int = 14
    vwap_lookback: int = 5
    bb_period: int = 20
    bb_std: float = 2.0

    # ── SL / Target by strategy ──
    sl_pct_tc: float = 0.22
    target_pct_tc: float = 0.60

    sl_pct_bm: float = 0.20
    target_pct_bm: float = 0.55

    sl_pct_rs: float = 0.20
    target_pct_rs: float = 0.55

    sl_pct_gf: float = 0.22
    target_pct_gf: float = 0.52

    sl_pct_rb: float = 0.18
    target_pct_rb: float = 0.48

    sl_pct_ib: float = 0.18
    target_pct_ib: float = 0.48

    sl_pct_vc: float = 0.20
    target_pct_vc: float = 0.55

    # ── Break-even / EOD ──
    break_even_trigger_pct: float = 0.08  # Matches live: 8% (was 10%)

    # ── Shared filters ──
    vix_max: float = 24.0
    slippage_pct: float = 0.005

    # ── A+ Quality Gate (applied to ALL entries) ──
    # Composite score 0-100: RSI zone + ADX strength + VIX favorability +
    # filter checks passed + strategy tier. Blocks low-quality setups.
    enable_quality_gate: bool = True
    min_quality_score: float = 40.0        # Normal entry minimum — calibrated to max PF + monthly consistency

    # ── Strong-trend relaxed quality gate (A- trades) ──
    # In strong trend regimes, market is forgiving — allow slightly weaker setups
    strong_trend_quality_discount: float = 12.0  # Lower quality threshold by 12 in strong trend

    # ── Skip-after-loss filter (mirrors live bot logic) ──
    # After a losing trade, same-direction re-entry requires HIGHER quality score
    enable_skip_after_loss: bool = True
    skip_after_loss_min_quality: float = 60.0  # Stricter threshold after same-dir loss

    # ── Re-entry on same valid setup after SL ──
    # If a trade hits SL but the same signal is still valid: allow one re-entry per day
    # Models markets that shake out then resume the real move
    enable_reentry_after_sl: bool = False  # Disabled: adds losses empirically
    reentry_quality_min: float = 55.0  # Higher quality required for re-entry

    # ── Conviction-based day cap (mirrors live bot logic) ──
    # On strong trend days (high ADX), allow up to strong_trend_max_trades
    enable_conviction_day_cap: bool = True
    strong_trend_adx_thresh: float = 0.42      # ADX threshold for "strong trend"
    strong_trend_max_trades: int = 3

    # ── VOLATILE + strong trend override ──
    # Mirrors live bot: even on high-VIX (VOLATILE) days, allow 1 extra trend trade
    # when ADX shows strong directional conviction (proxy for: conviction≥0.8,
    # price moved>0.8%, pullback entry, A+ score≥75 conditions in trader.py)
    enable_volatile_trend_override: bool = True
    volatile_override_adx_min: float = 0.42        # same as strong_trend_adx_thresh
    volatile_override_max_cap: int = 2             # allow up to 2 trades on these days (was hard 1)
    volatile_override_extra_strategies: tuple = ("TREND_CONTINUATION", "BREAKOUT_MOMENTUM")
    volatile_override_quality_min: float = 55.0   # stricter quality gate (proxy for A+ score≥75)
    volatile_override_sl_mult: float = 0.85        # tighter SL (proxy for pullback entry condition)

    # ── Risk ──
    max_trades_per_day: int = 4
    max_consecutive_losses: int = 8
    max_daily_loss_pct: float = 0.03
    strike_step: int = 50
    lot_scaling_step: float = 100_000.0
    max_lots_cap: int = 2
    second_trade_lot_fraction: float = 0.45
    third_trade_lot_fraction: float = 0.35
    fourth_trade_lot_fraction: float = 0.30

    # ── Regime thresholds ──
    adx_strong_trend: float = 0.34
    adx_mild_trend: float = 0.175
    atr_volatile_mult: float = 1.7
    atr_squeeze_mult: float = 0.65
    vix_volatile: float = 22.5
    min_option_premium: float = 4.5

    # ── SL / Target: EMA_FRESH_CROSS ──
    sl_pct_efc: float = 0.20    # 20% SL — standard momentum entry
    target_pct_efc: float = 0.55  # 2.75× RR (cross days have strong follow-through)

    # ── Strategy enable flags ──
    enable_trend_continuation: bool = True
    enable_breakout_momentum: bool = True
    enable_reversal_snap: bool = True
    enable_gap_fade: bool = True
    enable_range_bounce: bool = True
    enable_inside_bar_break: bool = True
    enable_vwap_cross: bool = True
    enable_ema_fresh_cross: bool = False  # Disabled: WR=11%, avg=-₹1,054 — structurally losing

    # ── Fallback signal: fires when no primary strategy matches ──
    # NOTE: Backtested as harmful for intraday (WR=10%). Kept as option, disabled by default.
    enable_fallback_ema_cross: bool = False
    sl_pct_fb: float = 0.15      # 15% SL — tighter than primary (18-22%)
    target_pct_fb: float = 0.375  # 2.5x RR
    fallback_vix_max: float = 22.0  # Skip fallback on very high VIX days


# ═══════════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════════

def _ema(series: list, period: int) -> list:
    if not series:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [series[0]]
    for v in series[1:]:
        out.append(v * alpha + out[-1] * (1 - alpha))
    return out


def _sma(series: list, period: int) -> list:
    out = []
    for i in range(len(series)):
        window = series[max(0, i - period + 1):i + 1]
        out.append(sum(window) / len(window))
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


def _bollinger_bandwidth(closes: list, period: int = 20, std_mult: float = 2.0) -> list:
    """Bollinger Band width as % of SMA — measures compression/expansion."""
    out = [0.0] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        sma = sum(window) / period
        if sma == 0:
            continue
        variance = sum((x - sma) ** 2 for x in window) / period
        std = math.sqrt(variance)
        out[i] = (std_mult * 2 * std) / sma
    return out


# ═══════════════════════════════════════════════════════════════════
# 6-REGIME MARKET CLASSIFIER
# ═══════════════════════════════════════════════════════════════════

REGIME_NAMES = [
    "STRONG_TREND_UP", "STRONG_TREND_DOWN",
    "MILD_TREND", "MEAN_REVERT", "BREAKOUT", "VOLATILE",
]

def _classify_regime(
    i: int,
    closes: list, highs: list, lows: list,
    ema_fast_vals: list, ema_slow_vals: list, ema_trend_vals: list,
    adx_proxy_vals: list, atr_vals: list, atr_sma: list,
    bb_width: list, rsi_vals: list,
    vix: float, cfg: DailyBacktestConfig,
) -> str:
    """Multi-factor regime classifier with 6 states."""
    adx = adx_proxy_vals[i]
    atr_v = atr_vals[i]
    atr_a = atr_sma[i] if atr_sma[i] > 0 else 1.0
    atr_ratio = atr_v / atr_a
    rsi = rsi_vals[i]
    ema_f = ema_fast_vals[i]
    ema_s = ema_slow_vals[i]
    ema_t = ema_trend_vals[i]
    bbw = bb_width[i]

    # 1) VOLATILE — high VIX or extreme ATR expansion
    if vix > cfg.vix_volatile or atr_ratio > cfg.atr_volatile_mult:
        return "VOLATILE"

    # 2) BREAKOUT — Bollinger squeeze then expansion
    #    Prior 3 bars had narrow bandwidth, current bar expands
    if i >= 3 and bbw > 0:
        prior_avg_bbw = sum(bb_width[i - 3:i]) / 3
        if prior_avg_bbw > 0 and bbw / prior_avg_bbw > 1.48 and atr_ratio > 1.12:
            return "BREAKOUT"

    # 3) STRONG_TREND_UP — high ADX + bullish EMA stack
    if adx >= cfg.adx_strong_trend and ema_f > ema_s > ema_t:
        return "STRONG_TREND_UP"

    # 4) STRONG_TREND_DOWN — high ADX + bearish EMA stack
    if adx >= cfg.adx_strong_trend and ema_f < ema_s < ema_t:
        return "STRONG_TREND_DOWN"

    # 5) MILD_TREND — moderate ADX + some EMA alignment
    if adx >= cfg.adx_mild_trend and (ema_f > ema_s or ema_f < ema_s):
        return "MILD_TREND"

    # 6) MEAN_REVERT — everything else: low directional movement
    return "MEAN_REVERT"


# ═══════════════════════════════════════════════════════════════════
# ADAPTIVE STRATEGY PRIORITY PER REGIME
# ═══════════════════════════════════════════════════════════════════

STRATEGY_PRIORITY = {
    "STRONG_TREND_UP":   ["BREAKOUT_MOMENTUM", "TREND_CONTINUATION", "EMA_FRESH_CROSS"],
    "STRONG_TREND_DOWN": ["BREAKOUT_MOMENTUM", "TREND_CONTINUATION", "EMA_FRESH_CROSS"],
    "MILD_TREND":        ["EMA_FRESH_CROSS", "TREND_CONTINUATION", "BREAKOUT_MOMENTUM", "VWAP_CROSS", "GAP_FADE", "INSIDE_BAR_BREAK"],
    "MEAN_REVERT":       ["RANGE_BOUNCE", "GAP_FADE", "REVERSAL_SNAP", "VWAP_CROSS", "INSIDE_BAR_BREAK"],
    "BREAKOUT":          ["BREAKOUT_MOMENTUM", "EMA_FRESH_CROSS", "INSIDE_BAR_BREAK", "TREND_CONTINUATION", "GAP_FADE"],
    "VOLATILE":          ["GAP_FADE", "REVERSAL_SNAP"],  # EMA_FRESH_CROSS excluded — VIX too high
}

# Regime-adaptive SL/target multipliers: (sl_mult, tgt_mult)
REGIME_SL_TARGET_ADJUST = {
    "STRONG_TREND_UP":   (1.0, 1.20),
    "STRONG_TREND_DOWN": (1.0, 1.20),
    "MILD_TREND":        (1.0, 1.05),
    "MEAN_REVERT":       (0.90, 0.95),
    "BREAKOUT":          (0.85, 1.15),
    "VOLATILE":          (0.75, 0.75),
}

SL_TARGET_MAP = {
    "TREND_CONTINUATION": ("sl_pct_tc", "target_pct_tc"),
    "BREAKOUT_MOMENTUM":  ("sl_pct_bm", "target_pct_bm"),
    "REVERSAL_SNAP":      ("sl_pct_rs", "target_pct_rs"),
    "GAP_FADE":           ("sl_pct_gf", "target_pct_gf"),
    "RANGE_BOUNCE":       ("sl_pct_rb", "target_pct_rb"),
    "INSIDE_BAR_BREAK":   ("sl_pct_ib", "target_pct_ib"),
    "VWAP_CROSS":         ("sl_pct_vc", "target_pct_vc"),
    "EMA_FRESH_CROSS":    ("sl_pct_efc", "target_pct_efc"),
    "FALLBACK_EMA_CROSS": ("sl_pct_fb", "target_pct_fb"),
}

ALL_STRATEGIES = set(SL_TARGET_MAP.keys())

STRATEGY_FILTER_MAP = {
    "TREND":    {"TREND_CONTINUATION", "BREAKOUT_MOMENTUM"},
    "REVERSAL": {"REVERSAL_SNAP", "RANGE_BOUNCE"},
    "GAP":      {"GAP_FADE"},
    "VWAP":     {"VWAP_CROSS"},
    "BOTH":     ALL_STRATEGIES,
}


def _strategies_scan_order(regime: str, allowed: set) -> List[str]:
    """Regime priority first, then remaining allowed strategies (for volume + 2nd slot)."""
    pri = STRATEGY_PRIORITY.get(regime, STRATEGY_PRIORITY["MEAN_REVERT"])
    seen: set = set()
    out: List[str] = []
    for s in pri:
        if s in allowed and s not in seen:
            out.append(s)
            seen.add(s)
    for s in sorted(allowed):
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


# ═══════════════════════════════════════════════════════════════════
# STRATEGY SIGNALS
# ═══════════════════════════════════════════════════════════════════

def _check_trend_continuation(
    i: int, highs: list, lows: list, closes: list, opens: list,
    ema_fast_vals: list, ema_slow_vals: list, ema_trend_vals: list,
    rsi: float, vwap_vals: list, cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """Pullback to fast EMA in established trend, then bounce with body confirmation."""
    if i < 3:
        return None

    today_close, today_open = closes[i], opens[i]
    today_low, today_high = lows[i], highs[i]
    today_range = today_high - today_low
    body_ratio = abs(today_close - today_open) / today_range if today_range > 0 else 0
    ema_f, ema_s, ema_t = ema_fast_vals[i], ema_slow_vals[i], ema_trend_vals[i]
    vwap = vwap_vals[i]
    tolerance = ema_f * 0.0055

    bull_trend = all(ema_fast_vals[j] > ema_slow_vals[j] for j in range(i - 2, i + 1))
    bear_trend = all(ema_fast_vals[j] < ema_slow_vals[j] for j in range(i - 2, i + 1))

    if (bull_trend and today_low <= ema_f + tolerance
        and today_close > ema_f and today_close > today_open
        and body_ratio >= 0.36 and today_close > vwap * 0.999 and ema_f > ema_t
        and 38.0 <= rsi <= 76.0):
        return ("CALL", "TREND_CONTINUATION", {
            "trend": {"passed": True, "detail": f"Bull EMA stack, pullback to EMA8"},
            "bounce": {"passed": True, "detail": f"Green body {body_ratio:.0%} above EMA"},
            "vwap": {"passed": True, "detail": f"Close > VWAP"},
        })

    if (bear_trend and today_high >= ema_f - tolerance
        and today_close < ema_f and today_close < today_open
        and body_ratio >= 0.36 and today_close < vwap and ema_f < ema_t
        and 24.0 <= rsi <= 62.0):
        return ("PUT", "TREND_CONTINUATION", {
            "trend": {"passed": True, "detail": f"Bear EMA stack, pullback to EMA8"},
            "rejection": {"passed": True, "detail": f"Red body {body_ratio:.0%} below EMA"},
            "vwap": {"passed": True, "detail": f"Close < VWAP"},
        })

    return None


def _check_breakout_momentum(
    i: int, highs: list, lows: list, closes: list, opens: list,
    ema_fast_vals: list, ema_slow_vals: list, rsi: float,
    atr_vals: list, atr_sma: list, volumes: list,
    cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """Breakout above/below prior N-day range with volume + ATR expansion."""
    if i < 10:
        return None

    today_close, today_open = closes[i], opens[i]
    today_high, today_low = highs[i], lows[i]
    today_range = today_high - today_low
    body_ratio = abs(today_close - today_open) / today_range if today_range > 0 else 0

    lookback = 5
    prior_high = max(highs[i - lookback:i])
    prior_low = min(lows[i - lookback:i])
    ema_f, ema_s = ema_fast_vals[i], ema_slow_vals[i]

    atr_ratio = atr_vals[i] / atr_sma[i] if atr_sma[i] > 0 else 1.0
    vol_avg = sum(volumes[max(0, i - 10):i]) / min(10, i) if i > 0 else 1
    vol_ratio = volumes[i] / vol_avg if vol_avg > 0 else 1.0

    # Bullish breakout above prior range
    if (today_close > prior_high and today_close > today_open
        and body_ratio >= 0.42 and atr_ratio >= 1.03
        and vol_ratio >= 0.88 and ema_f > ema_s
        and 47.0 <= rsi <= 80.0):
        return ("CALL", "BREAKOUT_MOMENTUM", {
            "breakout": {"passed": True, "detail": f"Close {today_close:.0f} > {lookback}d high {prior_high:.0f}"},
            "momentum": {"passed": True, "detail": f"ATR ratio {atr_ratio:.1f}, vol ratio {vol_ratio:.1f}"},
            "body": {"passed": True, "detail": f"Green body {body_ratio:.0%}"},
        })

    # Bearish breakdown below prior range
    if (today_close < prior_low and today_close < today_open
        and body_ratio >= 0.42 and atr_ratio >= 1.03
        and vol_ratio >= 0.88 and ema_f < ema_s
        and 20.0 <= rsi <= 53.0):
        return ("PUT", "BREAKOUT_MOMENTUM", {
            "breakdown": {"passed": True, "detail": f"Close {today_close:.0f} < {lookback}d low {prior_low:.0f}"},
            "momentum": {"passed": True, "detail": f"ATR ratio {atr_ratio:.1f}, vol ratio {vol_ratio:.1f}"},
            "body": {"passed": True, "detail": f"Red body {body_ratio:.0%}"},
        })

    return None


def _check_reversal_snap(
    i: int, highs: list, lows: list, closes: list, opens: list,
    rsi: float, rsi_vals: list, vwap_vals: list,
    cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """Exhaustion reversal at RSI extremes after a significant directional move."""
    if i < 4:
        return None

    today_close, today_open = closes[i], opens[i]
    today_high, today_low = highs[i], lows[i]
    today_range = today_high - today_low
    body_ratio = abs(today_close - today_open) / today_range if today_range > 0 else 0
    vwap = vwap_vals[i]

    prior_move = (closes[i - 1] - closes[i - 3]) / closes[i - 3] if closes[i - 3] > 0 else 0
    rsi_prev = rsi_vals[i - 1]

    # Bullish snap: prior drop + RSI oversold + green reversal + close > VWAP
    if (prior_move <= -0.006
        and rsi_prev <= 36.0 and rsi > rsi_prev
        and today_close > today_open and body_ratio >= 0.44
        and today_close > vwap):
        return ("CALL", "REVERSAL_SNAP", {
            "exhaustion": {"passed": True, "detail": f"Prior drop {prior_move*100:.1f}%, RSI {rsi_prev:.0f}→{rsi:.0f}"},
            "reversal": {"passed": True, "detail": f"Green body {body_ratio:.0%}, close > VWAP"},
        })

    # Bearish snap: prior rise + RSI overbought + red reversal + close < VWAP
    if (prior_move >= 0.006
        and rsi_prev >= 64.0 and rsi < rsi_prev
        and today_close < today_open and body_ratio >= 0.44
        and today_close < vwap):
        return ("PUT", "REVERSAL_SNAP", {
            "exhaustion": {"passed": True, "detail": f"Prior rise {prior_move*100:.1f}%, RSI {rsi_prev:.0f}→{rsi:.0f}"},
            "reversal": {"passed": True, "detail": f"Red body {body_ratio:.0%}, close < VWAP"},
        })

    return None


def _check_gap_fade(
    i: int, highs: list, lows: list, closes: list, opens: list,
    rsi: float, cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """Fade opening gaps > 0.4% that show fill behavior during the day."""
    if i < 2:
        return None

    prev_close = closes[i - 1]
    today_open, today_close = opens[i], closes[i]
    today_high, today_low = highs[i], lows[i]
    today_range = today_high - today_low
    body_ratio = abs(today_close - today_open) / today_range if today_range > 0 else 0
    gap_pct = (today_open - prev_close) / prev_close if prev_close > 0 else 0

    # Gap up → fade (PUT)
    if (0.0018 <= gap_pct <= 0.022
        and today_close < today_open
        and today_close < today_open - (today_open - prev_close) * 0.22
        and body_ratio >= 0.36 and rsi >= 42.0):
        return ("PUT", "GAP_FADE", {
            "gap": {"passed": True, "detail": f"Gap up {gap_pct*100:.2f}%, filling"},
            "candle": {"passed": True, "detail": f"Red body {body_ratio:.0%}"},
        })

    # Gap down → fade (CALL)
    if (-0.022 <= gap_pct <= -0.0018
        and today_close > today_open
        and today_close > today_open + (prev_close - today_open) * 0.22
        and body_ratio >= 0.36 and rsi <= 58.0):
        return ("CALL", "GAP_FADE", {
            "gap": {"passed": True, "detail": f"Gap down {gap_pct*100:.2f}%, filling"},
            "candle": {"passed": True, "detail": f"Green body {body_ratio:.0%}"},
        })

    return None


def _check_range_bounce(
    i: int, highs: list, lows: list, closes: list, opens: list,
    rsi: float, vwap_vals: list, cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """Bounce off prior multi-day support/resistance in ranging market."""
    if i < 5:
        return None

    today_close, today_open = closes[i], opens[i]
    today_high, today_low = highs[i], lows[i]
    today_range = today_high - today_low
    body_ratio = abs(today_close - today_open) / today_range if today_range > 0 else 0
    vwap = vwap_vals[i]

    lookback = 4
    support = min(lows[i - lookback:i])
    resistance = max(highs[i - lookback:i])
    proximity = (resistance - support) * 0.045 if resistance > support else 10

    # Bullish bounce off support
    if (today_low <= support + proximity
        and today_close > today_open and today_close > support
        and body_ratio >= 0.38 and today_close >= vwap * 0.998
        and 28.0 <= rsi <= 54.0):
        return ("CALL", "RANGE_BOUNCE", {
            "support": {"passed": True, "detail": f"Low {today_low:.0f} near {lookback}d support {support:.0f}"},
            "bounce": {"passed": True, "detail": f"Green body {body_ratio:.0%}, RSI {rsi:.0f}"},
        })

    # Bearish rejection at resistance
    if (today_high >= resistance - proximity
        and today_close < today_open and today_close < resistance
        and body_ratio >= 0.38 and today_close <= vwap * 1.002
        and 46.0 <= rsi <= 72.0):
        return ("PUT", "RANGE_BOUNCE", {
            "resistance": {"passed": True, "detail": f"High {today_high:.0f} near {lookback}d resistance {resistance:.0f}"},
            "rejection": {"passed": True, "detail": f"Red body {body_ratio:.0%}, RSI {rsi:.0f}"},
        })

    return None


def _check_inside_bar_break(
    i: int, highs: list, lows: list, closes: list, opens: list,
    ema_fast_vals: list, ema_slow_vals: list, rsi: float,
    cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """Inside bar (today's range inside yesterday's) breakout — low-risk compression play."""
    if i < 2:
        return None

    prev_high, prev_low = highs[i - 1], lows[i - 1]
    today_high, today_low = highs[i], lows[i]
    today_close, today_open = closes[i], opens[i]
    today_range = today_high - today_low
    body_ratio = abs(today_close - today_open) / today_range if today_range > 0 else 0
    ema_f, ema_s = ema_fast_vals[i], ema_slow_vals[i]

    # Check if prior bar was an inside bar relative to 2 days ago
    if i < 3:
        return None
    pp_high, pp_low = highs[i - 2], lows[i - 2]
    is_inside = prev_high <= pp_high and prev_low >= pp_low

    if not is_inside:
        return None

    # Bullish breakout: clear close above the inside bar range + strong body
    margin = (prev_high - prev_low) * 0.06
    if (today_close > prev_high + margin and today_close > today_open
        and body_ratio >= 0.44 and ema_f > ema_s
        and 46.0 <= rsi <= 70.0):
        return ("CALL", "INSIDE_BAR_BREAK", {
            "pattern": {"passed": True, "detail": f"Inside bar break UP, close {today_close:.0f} > prev high {prev_high:.0f}"},
            "ema_bias": {"passed": True, "detail": f"EMA8 > EMA21, body {body_ratio:.0%}"},
        })

    # Bearish breakdown: clear close below the inside bar range + strong body
    if (today_close < prev_low - margin and today_close < today_open
        and body_ratio >= 0.44 and ema_f < ema_s
        and 30.0 <= rsi <= 54.0):
        return ("PUT", "INSIDE_BAR_BREAK", {
            "pattern": {"passed": True, "detail": f"Inside bar break DOWN, close {today_close:.0f} < prev low {prev_low:.0f}"},
            "ema_bias": {"passed": True, "detail": f"EMA8 < EMA21, body {body_ratio:.0%}"},
        })

    return None


def _check_vwap_cross(
    i: int, closes: list, opens: list, highs: list, lows: list,
    vwap_vals: list, rsi: float,
    ema_fast_vals: list, ema_slow_vals: list,
    cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """VWAP cross-over with prior deviation — institutional flow signal."""
    if i < 3:
        return None

    today_close, today_open = closes[i], opens[i]
    today_range = highs[i] - lows[i]
    body_ratio = abs(today_close - today_open) / today_range if today_range > 0 else 0
    vwap = vwap_vals[i]
    prev_close, prev_vwap = closes[i - 1], vwap_vals[i - 1]

    # Bullish: crossed above VWAP after being below it for 2+ bars
    prev2_close = closes[i - 2] if i >= 2 else prev_close
    prev2_vwap = vwap_vals[i - 2] if i >= 2 else prev_vwap
    if (prev_close < prev_vwap and prev2_close < prev2_vwap and today_close > vwap):
        dev = abs(prev_close - prev_vwap) / prev_vwap if prev_vwap > 0 else 0
        if (dev >= 0.0025
            and today_close > today_open and body_ratio >= 0.38
            and 40.0 <= rsi <= 68.0
            and ema_fast_vals[i] > ema_slow_vals[i]):
            return ("CALL", "VWAP_CROSS", {
                "cross": {"passed": True, "detail": f"Crossed above VWAP, prior deviation {dev*100:.2f}%"},
                "confirm": {"passed": True, "detail": f"Green body {body_ratio:.0%}, EMA aligned"},
            })

    # Bearish: crossed below VWAP after being above it for 2+ bars
    if (prev_close > prev_vwap and prev2_close > prev2_vwap and today_close < vwap):
        dev = abs(prev_close - prev_vwap) / prev_vwap if prev_vwap > 0 else 0
        if (dev >= 0.0025
            and today_close < today_open and body_ratio >= 0.38
            and 32.0 <= rsi <= 62.0
            and ema_fast_vals[i] < ema_slow_vals[i]):
            return ("PUT", "VWAP_CROSS", {
                "cross": {"passed": True, "detail": f"Crossed below VWAP, prior deviation {dev*100:.2f}%"},
                "confirm": {"passed": True, "detail": f"Red body {body_ratio:.0%}, EMA aligned"},
            })

    return None


def _check_ema_fresh_cross(
    i: int, highs: list, lows: list, closes: list, opens: list,
    ema_fast_vals: list, ema_slow_vals: list, ema_trend_vals: list,
    rsi: float, vwap_vals: list, cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """EMA_FRESH_CROSS: A+ setup — enter on the exact day EMA8 crosses EMA21.

    Why this is the best new A+ setup:
      - TREND_CONTINUATION requires 3+ days of aligned EMAs (trend already established)
      - This fires on the actual CROSS DAY — the earliest valid momentum entry
      - A cross of EMA8/EMA21 on daily bars is high-conviction institutional signal
      - EMA50 must confirm direction (no counter-trend setups)
      - RSI must be in the 'has-room-to-run' zone (not overextended)
      - Today's candle body must confirm the direction (not just a wick cross)
      - Close must be above/below VWAP (institutional anchoring)

    This does NOT overlap with TREND_CONTINUATION (which requires trend already established
    for 3 days). The cross day is specifically missed by all 7 existing strategies.
    """
    if i < 6:
        return None

    ema_f, ema_s, ema_t = ema_fast_vals[i], ema_slow_vals[i], ema_trend_vals[i]
    today_close, today_open = closes[i], opens[i]
    today_range = highs[i] - lows[i]
    body_ratio = abs(today_close - today_open) / today_range if today_range > 0 else 0
    vwap = vwap_vals[i]

    # Detect whether EMA8 crossed EMA21 within the last 3 bars
    # Cross day = most conviction; bars 1-2 after cross = continuation confirmation
    cross_bar = None
    for lookback in range(1, 4):
        j = i - lookback
        if j < 1:
            break
        prev_f, prev_s = ema_fast_vals[j - 1], ema_slow_vals[j - 1]
        cur_f, cur_s = ema_fast_vals[j], ema_slow_vals[j]
        if prev_f <= prev_s and cur_f > cur_s:    # bullish cross at bar j
            cross_bar = ("bull", lookback)
            break
        if prev_f >= prev_s and cur_f < cur_s:    # bearish cross at bar j
            cross_bar = ("bear", lookback)
            break

    if cross_bar is None:
        return None

    cross_dir, bars_ago = cross_bar
    # Reduce RSI tolerance as we move further from cross day (tighter confirmation needed)
    rsi_bull_max = 72.0 - bars_ago * 4   # day0=72, day1=68, day2=64
    rsi_bear_min = 28.0 + bars_ago * 4   # day0=28, day1=32, day2=36

    if (cross_dir == "bull"
        and ema_f > ema_s and ema_f > ema_t   # EMA50 confirms up
        and today_close > today_open           # Green candle
        and body_ratio >= 0.38
        and today_close > vwap                 # VWAP support
        and 46.0 <= rsi <= rsi_bull_max):
        return ("CALL", "EMA_FRESH_CROSS", {
            "cross": {"passed": True, "detail": f"EMA8 crossed above EMA21 {bars_ago}d ago"},
            "trend": {"passed": True, "detail": f"EMA21 {ema_s:.0f} > EMA50 {ema_t:.0f}"},
            "candle": {"passed": True, "detail": f"Green body {body_ratio:.0%} above VWAP"},
            "rsi": {"passed": True, "detail": f"RSI {rsi:.1f}, max allowed {rsi_bull_max:.0f}"},
        })

    if (cross_dir == "bear"
        and ema_f < ema_s and ema_f < ema_t   # EMA50 confirms down
        and today_close < today_open           # Red candle
        and body_ratio >= 0.38
        and today_close < vwap                 # Below VWAP
        and rsi_bear_min <= rsi <= 54.0):
        return ("PUT", "EMA_FRESH_CROSS", {
            "cross": {"passed": True, "detail": f"EMA8 crossed below EMA21 {bars_ago}d ago"},
            "trend": {"passed": True, "detail": f"EMA21 {ema_s:.0f} < EMA50 {ema_t:.0f}"},
            "candle": {"passed": True, "detail": f"Red body {body_ratio:.0%} below VWAP"},
            "rsi": {"passed": True, "detail": f"RSI {rsi:.1f}, min allowed {rsi_bear_min:.0f}"},
        })

    return None


# ═══════════════════════════════════════════════════════════════════
# A+ QUALITY SCORING
# ═══════════════════════════════════════════════════════════════════

# Strategy tiers based on actual backtested win rates + avg PnL per trade:
#   TREND_CONTINUATION: WR=53%, avg=₹2,994 → Tier 1
#   REVERSAL_SNAP:      WR=60%, avg=₹2,410 → Tier 1
#   BREAKOUT_MOMENTUM:  WR=48%, avg=₹2,334 → Tier 2
#   VWAP_CROSS:         WR=40%, avg=₹1,785 → Tier 2
#   GAP_FADE:           WR=46%, avg=₹1,390 → Tier 2
#   INSIDE_BAR_BREAK:   WR=43%, avg=₹675   → Tier 3
#   RANGE_BOUNCE:       WR=38%, avg=₹745   → Tier 3
#   EMA_FRESH_CROSS:    WR=11%, avg=-₹1,054 → Structurally LOSING — disable by default
_STRATEGY_TIER: Dict[str, int] = {
    "TREND_CONTINUATION":  20,
    "REVERSAL_SNAP":       18,
    "BREAKOUT_MOMENTUM":   14,
    "VWAP_CROSS":          12,
    "GAP_FADE":            11,
    "INSIDE_BAR_BREAK":     6,
    "RANGE_BOUNCE":         5,
    "EMA_FRESH_CROSS":      0,   # Structurally losing — blocked by quality gate
    "FALLBACK_EMA_CROSS":   2,
}

# Regime edge scores based on actual backtested WR:
#   VOLATILE:           WR=75%  (rare, very high edge)
#   MILD_TREND:         WR=54%  (reliable)
#   MEAN_REVERT:        WR=44%  (below average)
#   STRONG_TREND_UP:    WR=8%   (trap — CALL trades fail badly in strong up-trends)
_REGIME_QUALITY: Dict[str, int] = {
    "VOLATILE":           25,
    "MILD_TREND":         20,
    "MEAN_REVERT":        10,
    "STRONG_TREND_DOWN":  18,
    "STRONG_TREND_UP":    -25,  # Very heavy penalty — WR=8% empirically for CALL signals
    "BREAKOUT":           15,
}


def _compute_backtest_quality_score(
    signal: str,
    strategy_name: str,
    filter_log: dict,
    rsi: float,
    adx: float,
    vix: float,
    regime: str = "",
) -> float:
    """
    Data-driven quality score 0-100 for a daily backtest signal.
    Weights are calibrated from actual backtested win rates and avg PnL.

      1. Strategy tier    0-20  — based on historical WR and avg PnL
      2. Regime edge      0-25  — regime-specific performance (STRONG_TREND_UP penalised)
      3. Filter checks    0-20  — what fraction of the strategy's own checks passed cleanly
      4. ADX confirmation 0-20  — moderate trend is ideal; extreme ADX penalised
      5. RSI confirmation 0-15  — RSI aligned with direction and not overextended

    Thresholds:
      Normal entry:           score >= min_quality_score  (default 45)
      After same-dir loss:    score >= skip_after_loss_min_quality  (default 65)
    """
    score = 0.0

    # ── 1. Strategy tier (0-20) ───────────────────────────────────────
    score += _STRATEGY_TIER.get(strategy_name, 5)

    # ── 2. Regime edge (−15 to +25) ──────────────────────────────────
    score += _REGIME_QUALITY.get(regime, 10)

    # ── 3. Filter checks passed ratio (0-20) ─────────────────────────
    checks = [v for v in filter_log.values() if isinstance(v, dict) and "passed" in v]
    if checks:
        passed = sum(1 for c in checks if c.get("passed"))
        score += (passed / len(checks)) * 20

    # ── 4. ADX confirmation (0-20) ────────────────────────────────────
    # Moderate trend (0.18-0.35) = ideal. Too low = choppy. Too high = chasing.
    if 0.18 <= adx <= 0.35:
        score += 20
    elif 0.35 < adx <= 0.42:
        score += 14
    elif 0.14 <= adx < 0.18:
        score += 8
    elif adx > 0.42:
        score += 5   # Very high ADX often means overextended move

    # ── 5. RSI confirmation (0-15) ────────────────────────────────────
    # Reward RSI in the "has room to run" zone; penalise extremes
    if signal == "CALL":
        if 48.0 <= rsi <= 65.0:
            score += 15
        elif 42.0 <= rsi < 48.0 or 65.0 < rsi <= 72.0:
            score += 7
        # RSI < 42 (bearish) or > 72 (overbought) = 0
    else:  # PUT
        if 35.0 <= rsi <= 52.0:
            score += 15
        elif 28.0 <= rsi < 35.0 or 52.0 < rsi <= 58.0:
            score += 7

    return round(score, 1)


# ═══════════════════════════════════════════════════════════════════
# OPTION SIMULATION
# ═══════════════════════════════════════════════════════════════════

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
    lots_override: int = 0,
) -> Optional[Dict[str, Any]]:
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
    if raw_entry < cfg.min_option_premium:
        return None

    entry_slip = realistic_slippage(cfg.slippage_pct, vix, dte, raw_entry)
    entry_price = raw_entry * (1 + entry_slip)
    sl_price = entry_price * (1 - sl_pct)
    target_price = entry_price * (1 + target_pct)

    sigma_exit = max(0.05, sigma + iv_crush)
    T_exit = max(0.0001, (dte * 0.71 + 0.1) / 252.0)

    spot_best = day_high if direction == "CALL" else day_low
    spot_worst = day_low if direction == "CALL" else day_high

    opt_best = price_option(spot_best, strike, T_exit, RISK_FREE_RATE, sigma_exit, opt_type)["price"]
    opt_worst = price_option(spot_worst, strike, T_exit, RISK_FREE_RATE, sigma_exit, opt_type)["price"]
    opt_close = price_option(day_close, strike, T_exit, RISK_FREE_RATE, sigma_exit, opt_type)["price"]

    # Order: SL first (conservative), then check if both SL and target are
    # possible — if range is large enough for both, use 50/50 assumption,
    # otherwise pure target. Finally check EOD close.
    if opt_worst <= sl_price and opt_best < target_price:
        exit_price_raw = sl_price
        exit_reason = "SL_HIT"
    elif opt_worst <= sl_price and opt_best >= target_price:
        # Both possible in same bar — probabilistic: 26% target, 74% SL
        # Conservative assumption: adverse move more likely to hit first
        random.seed(int(spot_entry * 100 + dte * 10))
        if random.random() < 0.26:
            exit_price_raw = target_price
            exit_reason = "TARGET_HIT"
        else:
            exit_price_raw = sl_price
            exit_reason = "SL_HIT"
    elif opt_best >= target_price:
        exit_price_raw = target_price
        exit_reason = "TARGET_HIT"
    elif opt_close >= entry_price * (1 + cfg.break_even_trigger_pct):
        exit_price_raw = opt_close
        exit_reason = "EOD_PROFIT"
    else:
        exit_price_raw = opt_close
        exit_reason = "EOD_EXIT"

    exit_slip = realistic_slippage(cfg.slippage_pct, vix, dte, exit_price_raw)
    exit_price = exit_price_raw * (1 - exit_slip)

    effective_lots = lots_override if lots_override > 0 else cfg.lots
    qty = effective_lots * cfg.lot_size
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
        "lots": effective_lots,
        "spot_at_entry": round(spot_entry, 2),
        "delta_at_entry": round(entry_opt.get("delta", 0.5), 4),
        "iv_at_entry": round(sigma, 4),
        "vix": vix,
        "trade_date": trade_date.isoformat(),
        "entry_slippage_pct": round(entry_slip * 100, 2),
    }


# ═══════════════════════════════════════════════════════════════════
# MAIN ENGINE
# ═══════════════════════════════════════════════════════════════════

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

    allowed = STRATEGY_FILTER_MAP.get(strategy_filter, STRATEGY_FILTER_MAP["BOTH"])

    df = nifty_daily.copy()
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values("ts").reset_index(drop=True)

    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    opens = df["open"].tolist()
    volumes = df["volume"].tolist()
    dates = df["ts"].dt.date.tolist()

    ema_fast_vals = _ema(closes, cfg.ema_fast)
    ema_slow_vals = _ema(closes, cfg.ema_slow)
    ema_trend_vals = _ema(closes, cfg.ema_trend)
    rsi_vals = _rsi(closes, cfg.rsi_period)
    atr_vals = _atr(highs, lows, closes, cfg.atr_period)
    adx_vals = _directional_movement(highs, lows, closes, cfg.atr_period)
    bb_width = _bollinger_bandwidth(closes, cfg.bb_period, cfg.bb_std)

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

    warmup = max(cfg.ema_trend + 1, cfg.rsi_period + 1, atr_sma_period + 1, cfg.bb_period + 1, 5)
    if start_date:
        start_idx = next((j for j, d in enumerate(dates) if d >= start_date), 0)
        start_idx = max(start_idx, warmup)
    else:
        start_idx = warmup

    end_idx = next((j for j, d in enumerate(dates) if d > end_date), len(dates)) if end_date else len(dates)

    all_trades: List[Dict[str, Any]] = []
    capital = cfg.capital
    peak_equity = float(cfg.capital)
    consecutive_losses = 0
    regime_counts: Dict[str, int] = {r: 0 for r in REGIME_NAMES}
    strategy_counts: Dict[str, int] = {}
    skip_reasons: Dict[str, int] = {}
    start_ym = (dates[start_idx].year, dates[start_idx].month)

    # Skip-after-loss state (mirrors live bot _last_trade_was_loss / _last_exit_direction)
    last_trade_was_loss: bool = False
    last_exit_direction: Optional[str] = None

    if verbose:
        print(f"\n{'='*72}")
        print(f" ADAPTIVE ALPHA DAILY BACKTEST — {end_idx - start_idx} trading days")
        print(f" Range: {dates[start_idx]} → {dates[min(end_idx-1, len(dates)-1)]}")
        print(f" Capital: ₹{cfg.capital:,.0f} | Lots: {cfg.lots} (cap {cfg.max_lots_cap}) | Lot size: {cfg.lot_size}")
        print(f" Month-1 sizing: ≤₹{cfg.first_month_risk_capital:,.0f} risk → max {cfg.first_month_max_lots} lot(s)")
        print(f" Strategies: {', '.join(sorted(allowed))}")
        print(f" 6-Regime classifier + adaptive SL/target")
        print(f"{'='*72}\n")

    for i in range(start_idx, end_idx):
        trade_date = dates[i]
        vix = get_vix_for_date(vix_df, trade_date)

        peak_equity = max(peak_equity, capital)
        dd_pct = (peak_equity - capital) / peak_equity if peak_equity > 0 else 0.0

        if consecutive_losses >= cfg.max_consecutive_losses:
            consecutive_losses = max(0, consecutive_losses - 1)
            skip_reasons["consec_loss"] = skip_reasons.get("consec_loss", 0) + 1
            continue

        regime = _classify_regime(
            i, closes, highs, lows,
            ema_fast_vals, ema_slow_vals, ema_trend_vals,
            adx_vals, atr_vals, atr_sma, bb_width, rsi_vals,
            vix, cfg,
        )
        regime_counts[regime] = regime_counts.get(regime, 0) + 1

        rsi = rsi_vals[i]
        scan_order = _strategies_scan_order(regime, allowed)
        matches: List[Tuple[str, str, dict]] = []
        seen_strat: set = set()
        day_trade_cap = cfg.max_trades_per_day
        if vix > 21.0:
            day_trade_cap = min(day_trade_cap, 1)
        elif vix > 19.0:
            day_trade_cap = min(day_trade_cap, 2)
        elif vix > 17.0:
            day_trade_cap = min(day_trade_cap, 3)

        # Conviction-based day cap: strong trend (ADX proxy) → allow 3 trades
        if cfg.enable_conviction_day_cap and adx_vals[i] >= cfg.strong_trend_adx_thresh:
            day_trade_cap = max(day_trade_cap, min(cfg.strong_trend_max_trades, cfg.max_trades_per_day))

        # Extended window proxy: MILD_TREND and STRONG_TREND_DOWN allow one extra match slot
        # STRONG_TREND_UP excluded (WR=8% empirically — more slots = more losses)
        if regime in ("MILD_TREND", "STRONG_TREND_DOWN"):
            day_trade_cap = max(day_trade_cap, min(day_trade_cap + 1, cfg.max_trades_per_day))

        # VOLATILE + strong trend override: mirror live bot late window VIX exception
        # High VIX but strong ADX → volatile market with clear direction (crash/recovery day)
        # Allow 1 extra trend-following trade with stricter quality + tighter SL
        volatile_override_active = (
            regime == "VOLATILE"
            and cfg.enable_volatile_trend_override
            and adx_vals[i] >= cfg.volatile_override_adx_min
        )
        if volatile_override_active:
            extra = [s for s in cfg.volatile_override_extra_strategies
                     if s in allowed and s not in set(scan_order)]
            scan_order = scan_order + list(extra)
            day_trade_cap = max(day_trade_cap, min(cfg.volatile_override_max_cap, cfg.max_trades_per_day))

        for strat_name in scan_order:
            enabled_attr = f"enable_{strat_name.lower()}"
            if hasattr(cfg, enabled_attr) and not getattr(cfg, enabled_attr):
                continue

            signal_result = None
            if strat_name == "TREND_CONTINUATION":
                signal_result = _check_trend_continuation(
                    i, highs, lows, closes, opens,
                    ema_fast_vals, ema_slow_vals, ema_trend_vals,
                    rsi, vwap_vals, cfg)
            elif strat_name == "BREAKOUT_MOMENTUM":
                signal_result = _check_breakout_momentum(
                    i, highs, lows, closes, opens,
                    ema_fast_vals, ema_slow_vals, rsi,
                    atr_vals, atr_sma, volumes, cfg)
            elif strat_name == "REVERSAL_SNAP":
                signal_result = _check_reversal_snap(
                    i, highs, lows, closes, opens,
                    rsi, rsi_vals, vwap_vals, cfg)
            elif strat_name == "GAP_FADE":
                signal_result = _check_gap_fade(
                    i, highs, lows, closes, opens, rsi, cfg)
            elif strat_name == "RANGE_BOUNCE":
                signal_result = _check_range_bounce(
                    i, highs, lows, closes, opens, rsi, vwap_vals, cfg)
            elif strat_name == "INSIDE_BAR_BREAK":
                signal_result = _check_inside_bar_break(
                    i, highs, lows, closes, opens,
                    ema_fast_vals, ema_slow_vals, rsi, cfg)
            elif strat_name == "VWAP_CROSS":
                signal_result = _check_vwap_cross(
                    i, closes, opens, highs, lows,
                    vwap_vals, rsi, ema_fast_vals, ema_slow_vals, cfg)
            elif strat_name == "EMA_FRESH_CROSS":
                if vix <= 21.0:
                    signal_result = _check_ema_fresh_cross(
                        i, highs, lows, closes, opens,
                        ema_fast_vals, ema_slow_vals, ema_trend_vals,
                        rsi, vwap_vals, cfg)

            if signal_result is not None and strat_name not in seen_strat:
                sig, sn, fl = signal_result
                seen_strat.add(strat_name)
                matches.append((sig, sn, dict(fl)))
                if len(matches) >= day_trade_cap:
                    break

        # Fallback: EMA cross direction when no primary strategy fires
        if not matches and cfg.enable_fallback_ema_cross and vix <= cfg.fallback_vix_max:
            ema_f = ema_fast_vals[i]
            ema_s = ema_slow_vals[i]
            rsi_fb = rsi_vals[i]
            if ema_f > ema_s and rsi_fb >= 50:
                matches.append(("CALL", "FALLBACK_EMA_CROSS", {"ema_cross": "bullish", "rsi": round(rsi_fb, 1)}))
            elif ema_f < ema_s and rsi_fb <= 50:
                matches.append(("PUT", "FALLBACK_EMA_CROSS", {"ema_cross": "bearish", "rsi": round(rsi_fb, 1)}))

        if not matches:
            skip_reasons["no_signal"] = skip_reasons.get("no_signal", 0) + 1
            continue

        in_first_month = (trade_date.year, trade_date.month) == start_ym

        for leg_idx, (signal, strategy_name, filter_log) in enumerate(matches):
            filter_log = dict(filter_log)
            filter_log["regime"] = {"value": regime}
            filter_log["daily_leg"] = leg_idx + 1

            if regime == "STRONG_TREND_UP" and signal == "PUT":
                skip_reasons["regime_dir_mismatch"] = skip_reasons.get("regime_dir_mismatch", 0) + 1
                continue
            if regime == "STRONG_TREND_DOWN" and signal == "CALL":
                skip_reasons["regime_dir_mismatch"] = skip_reasons.get("regime_dir_mismatch", 0) + 1
                continue

            # Compute composite quality score for this signal
            quality = _compute_backtest_quality_score(
                signal, strategy_name, filter_log,
                rsi, adx_vals[i], vix, regime,
            )
            filter_log["quality_score"] = quality

            # A+ Quality Gate: block all low-quality setups
            # STRONG_TREND_DOWN only gets A- discount (WR=100% empirically, market forgiving)
            # STRONG_TREND_UP keeps normal threshold (WR=8%, do NOT relax)
            # MILD_TREND also gets a small discount (WR=54%, reliable regime)
            is_strong_bear = regime == "STRONG_TREND_DOWN"
            is_strong_trend = regime in ("STRONG_TREND_UP", "STRONG_TREND_DOWN")
            if is_strong_bear:
                effective_min_quality = cfg.min_quality_score - cfg.strong_trend_quality_discount
            elif regime == "MILD_TREND":
                effective_min_quality = cfg.min_quality_score - 5.0
            else:
                effective_min_quality = cfg.min_quality_score
            if cfg.enable_quality_gate and quality < effective_min_quality:
                skip_reasons["low_quality"] = skip_reasons.get("low_quality", 0) + 1
                continue

            # Stricter gate for volatile override trades (proxy for A+ score ≥ 75 condition)
            if volatile_override_active and strategy_name in cfg.volatile_override_extra_strategies:
                if quality < cfg.volatile_override_quality_min:
                    skip_reasons["volatile_override_quality"] = skip_reasons.get("volatile_override_quality", 0) + 1
                    continue

            # Skip-after-loss filter:
            # STRONG_TREND_DOWN: fake first move → real second move — allow re-entry
            # All other regimes: require higher quality score for same-direction re-entry
            if cfg.enable_skip_after_loss and last_trade_was_loss and last_exit_direction == signal:
                if not is_strong_bear and quality < cfg.skip_after_loss_min_quality:
                    skip_reasons["skip_after_loss"] = skip_reasons.get("skip_after_loss", 0) + 1
                    continue

            peak_equity = max(peak_equity, capital)
            dd_pct = (peak_equity - capital) / peak_equity if peak_equity > 0 else 0.0

            # ── Lot scaling (refresh DD / capital each leg) ──
            effective_lots = cfg.lots
            if in_first_month:
                effective_lots = min(cfg.lots, cfg.first_month_max_lots)
            elif capital > cfg.capital and cfg.lot_scaling_step > 0:
                extra = int((capital - cfg.capital) / cfg.lot_scaling_step)
                effective_lots = min(cfg.lots + extra, cfg.max_lots_cap)

            if dd_pct >= cfg.dd_force_one_lot_pct:
                effective_lots = 1
            elif dd_pct >= cfg.dd_hard_pct:
                effective_lots = min(effective_lots, 1)
            elif dd_pct >= cfg.dd_soft_pct:
                effective_lots = max(1, effective_lots - 1)

            if vix > 17:
                effective_lots = max(1, effective_lots - 1)
            if vix > cfg.vix_max - 2:
                effective_lots = 1
            if consecutive_losses >= 2:
                effective_lots = max(1, effective_lots - 1)

            full_day_lots = max(1, min(effective_lots, cfg.max_lots_cap))
            if leg_idx == 0:
                effective_lots = full_day_lots
            elif leg_idx == 1:
                effective_lots = max(1, int(round(full_day_lots * cfg.second_trade_lot_fraction)))
            elif leg_idx == 2:
                effective_lots = max(1, int(round(full_day_lots * cfg.third_trade_lot_fraction)))
            else:
                effective_lots = max(1, int(round(full_day_lots * cfg.fourth_trade_lot_fraction)))

            sl_key, tgt_key = SL_TARGET_MAP.get(strategy_name, ("sl_pct_tc", "target_pct_tc"))
            sl = getattr(cfg, sl_key)
            tgt = getattr(cfg, tgt_key)
            sl_mult, tgt_mult = REGIME_SL_TARGET_ADJUST.get(regime, (1.0, 1.0))
            # Volatile override extra trades: tighter SL (proxy for pullback entry condition)
            if volatile_override_active and strategy_name in cfg.volatile_override_extra_strategies:
                sl_mult = min(sl_mult, cfg.volatile_override_sl_mult)
            sl = sl * sl_mult
            tgt = tgt * tgt_mult

            trade = _simulate_option_trade(
                spot_entry=opens[i], direction=signal,
                trade_date=trade_date, vix=vix,
                day_high=highs[i], day_low=lows[i], day_close=closes[i],
                sl_pct=sl, target_pct=tgt, cfg=cfg,
                lots_override=effective_lots,
            )

            if trade is None or trade["status"] != "COMPLETED":
                skip_reasons["sim_failed"] = skip_reasons.get("sim_failed", 0) + 1
                continue

            trade["strategy"] = strategy_name
            trade["regime"] = regime
            trade["filter_log"] = filter_log
            trade["first_month_sizing"] = in_first_month
            trade["peak_dd_pct_at_entry"] = round(dd_pct * 100, 2)
            trade["daily_leg"] = leg_idx + 1
            all_trades.append(trade)
            strategy_counts[strategy_name] = strategy_counts.get(strategy_name, 0) + 1

            net = trade["net_pnl"]
            capital += net
            if net > 0:
                consecutive_losses = 0
                last_trade_was_loss = False
            else:
                consecutive_losses += 1
                last_trade_was_loss = True
            last_exit_direction = signal

            # ── Re-entry after SL: same setup still valid → allow one more leg ──
            # Only in STRONG_TREND_DOWN (WR=100%) — shakeout then real move
            # STRONG_TREND_UP excluded (WR=8% — re-entry makes losses worse)
            if (cfg.enable_reentry_after_sl
                    and trade["exit_reason"] == "SL_HIT"
                    and is_strong_bear
                    and leg_idx == 0  # only re-enter after the first leg's SL
                    and len(matches) < cfg.max_trades_per_day):
                # Re-add the same signal as a re-entry leg (with same filter_log, different tag)
                reentry_fl = dict(filter_log)
                reentry_fl["reentry"] = True
                matches.append((signal, strategy_name, reentry_fl))

            if verbose:
                sign = "+" if net >= 0 else ""
                leg_tag = f"[{leg_idx + 1}/{len(matches)}]"
                print(
                    f"  [{trade_date}] {leg_tag} {regime:15s} {strategy_name:20s} {signal:4s} | "
                    f"E={trade['entry_price']:.0f} X={trade['exit_price']:.0f} | "
                    f"{sign}₹{net:>7,.0f} | {trade['exit_reason']:10s} | L={effective_lots} V={vix:.0f} | ₹{capital:>10,.0f}"
                )

            sys.stdout.flush()

    metrics = compute_metrics(all_trades, cfg.capital)

    if verbose:
        total_days = end_idx - start_idx
        print(f"\n{'='*72}")
        print(f" SUMMARY — {total_days} days, {len(all_trades)} trades ({len(all_trades)/max(1,total_days)*100:.0f}%)")
        print(f" Capital: ₹{cfg.capital:,.0f} → ₹{capital:,.0f}  ({(capital-cfg.capital)/cfg.capital*100:+.1f}%)")
        print(f" Regimes: {regime_counts}")
        print(f" Strategies: {strategy_counts}")
        print(f" Skipped: {skip_reasons}")
        print(f"{'='*72}\n")

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


def build_daily_indicator_series(
    nifty_daily: pd.DataFrame,
    cfg: DailyBacktestConfig,
) -> Dict[str, Any]:
    """Build all indicator arrays (same math as run_daily_backtest)."""
    df = nifty_daily.copy()
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values("ts").reset_index(drop=True)

    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    opens = df["open"].tolist()
    volumes = df["volume"].tolist()
    dates = df["ts"].dt.date.tolist()

    ema_fast_vals = _ema(closes, cfg.ema_fast)
    ema_slow_vals = _ema(closes, cfg.ema_slow)
    ema_trend_vals = _ema(closes, cfg.ema_trend)
    rsi_vals = _rsi(closes, cfg.rsi_period)
    atr_vals = _atr(highs, lows, closes, cfg.atr_period)
    adx_vals = _directional_movement(highs, lows, closes, cfg.atr_period)
    bb_width = _bollinger_bandwidth(closes, cfg.bb_period, cfg.bb_std)

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

    warmup = max(cfg.ema_trend + 1, cfg.rsi_period + 1, atr_sma_period + 1, cfg.bb_period + 1, 5)
    return {
        "closes": closes, "highs": highs, "lows": lows, "opens": opens,
        "volumes": volumes, "dates": dates,
        "ema_fast_vals": ema_fast_vals, "ema_slow_vals": ema_slow_vals,
        "ema_trend_vals": ema_trend_vals, "rsi_vals": rsi_vals,
        "atr_vals": atr_vals, "adx_vals": adx_vals, "atr_sma": atr_sma,
        "bb_width": bb_width, "vwap_vals": vwap_vals, "warmup": warmup,
    }


def collect_strategy_matches_for_index(
    i: int,
    series: Dict[str, Any],
    vix: float,
    cfg: DailyBacktestConfig,
    allowed: set,
) -> Tuple[str, List[Tuple[str, str, dict]], int]:
    """Regime + ordered strategy matches + VIX-capped day trade limit (backtest parity)."""
    closes = series["closes"]
    highs, lows, opens = series["highs"], series["lows"], series["opens"]
    volumes = series["volumes"]
    ema_fast_vals = series["ema_fast_vals"]
    ema_slow_vals = series["ema_slow_vals"]
    ema_trend_vals = series["ema_trend_vals"]
    rsi_vals = series["rsi_vals"]
    atr_vals, atr_sma = series["atr_vals"], series["atr_sma"]
    bb_width, vwap_vals = series["bb_width"], series["vwap_vals"]

    regime = _classify_regime(
        i, closes, highs, lows,
        ema_fast_vals, ema_slow_vals, ema_trend_vals,
        series["adx_vals"], atr_vals, atr_sma, bb_width, rsi_vals,
        vix, cfg,
    )
    rsi = rsi_vals[i]
    adx_vals = series["adx_vals"]
    scan_order = _strategies_scan_order(regime, allowed)
    matches: List[Tuple[str, str, dict]] = []
    seen_strat: set = set()
    day_trade_cap = cfg.max_trades_per_day
    if vix > 21.0:
        day_trade_cap = min(day_trade_cap, 1)
    elif vix > 19.0:
        day_trade_cap = min(day_trade_cap, 2)
    elif vix > 17.0:
        day_trade_cap = min(day_trade_cap, 3)

    # VOLATILE + strong trend override (same as run_daily_backtest)
    if (regime == "VOLATILE"
            and cfg.enable_volatile_trend_override
            and adx_vals[i] >= cfg.volatile_override_adx_min):
        extra = [s for s in cfg.volatile_override_extra_strategies
                 if s in allowed and s not in set(scan_order)]
        scan_order = scan_order + list(extra)
        day_trade_cap = max(day_trade_cap, min(cfg.volatile_override_max_cap, cfg.max_trades_per_day))

    for strat_name in scan_order:
        enabled_attr = f"enable_{strat_name.lower()}"
        if hasattr(cfg, enabled_attr) and not getattr(cfg, enabled_attr):
            continue
        signal_result = None
        if strat_name == "TREND_CONTINUATION":
            signal_result = _check_trend_continuation(
                i, highs, lows, closes, opens,
                ema_fast_vals, ema_slow_vals, ema_trend_vals,
                rsi, vwap_vals, cfg)
        elif strat_name == "BREAKOUT_MOMENTUM":
            signal_result = _check_breakout_momentum(
                i, highs, lows, closes, opens,
                ema_fast_vals, ema_slow_vals, rsi,
                atr_vals, atr_sma, volumes, cfg)
        elif strat_name == "REVERSAL_SNAP":
            signal_result = _check_reversal_snap(
                i, highs, lows, closes, opens,
                rsi, rsi_vals, vwap_vals, cfg)
        elif strat_name == "GAP_FADE":
            signal_result = _check_gap_fade(i, highs, lows, closes, opens, rsi, cfg)
        elif strat_name == "RANGE_BOUNCE":
            signal_result = _check_range_bounce(
                i, highs, lows, closes, opens, rsi, vwap_vals, cfg)
        elif strat_name == "INSIDE_BAR_BREAK":
            signal_result = _check_inside_bar_break(
                i, highs, lows, closes, opens,
                ema_fast_vals, ema_slow_vals, rsi, cfg)
        elif strat_name == "VWAP_CROSS":
            signal_result = _check_vwap_cross(
                i, closes, opens, highs, lows,
                vwap_vals, rsi, ema_fast_vals, ema_slow_vals, cfg)
        elif strat_name == "EMA_FRESH_CROSS":
            if vix <= 21.0:
                signal_result = _check_ema_fresh_cross(
                    i, highs, lows, closes, opens,
                    ema_fast_vals, ema_slow_vals, ema_trend_vals,
                    rsi, vwap_vals, cfg)

        if signal_result is not None and strat_name not in seen_strat:
            sig, sn, fl = signal_result
            seen_strat.add(strat_name)
            matches.append((sig, sn, dict(fl)))
            if len(matches) >= day_trade_cap:
                break

    # Fallback: EMA cross direction when no primary strategy fires
    if not matches and cfg.enable_fallback_ema_cross and vix <= cfg.fallback_vix_max:
        ema_f = series["ema_fast_vals"][i]
        ema_s = series["ema_slow_vals"][i]
        rsi_fb = series["rsi_vals"][i]
        if ema_f > ema_s and rsi_fb >= 50:
            matches.append(("CALL", "FALLBACK_EMA_CROSS", {"ema_cross": "bullish", "rsi": round(rsi_fb, 1)}))
        elif ema_f < ema_s and rsi_fb <= 50:
            matches.append(("PUT", "FALLBACK_EMA_CROSS", {"ema_cross": "bearish", "rsi": round(rsi_fb, 1)}))

    return regime, matches, day_trade_cap


def sl_target_for_strategy_regime(
    strategy_name: str, regime: str, cfg: DailyBacktestConfig,
) -> Tuple[float, float]:
    sl_key, tgt_key = SL_TARGET_MAP.get(strategy_name, ("sl_pct_tc", "target_pct_tc"))
    sl = getattr(cfg, sl_key)
    tgt = getattr(cfg, tgt_key)
    sl_mult, tgt_mult = REGIME_SL_TARGET_ADJUST.get(regime, (1.0, 1.0))
    return sl * sl_mult, tgt * tgt_mult


def compute_live_lots_for_leg(
    cfg: DailyBacktestConfig,
    capital: float,
    peak_equity: float,
    vix: float,
    consecutive_losses: int,
    trade_date: date,
    anchor_ym: Tuple[int, int],
    leg_idx: int,
) -> int:
    """Mirror backtest lot logic for one leg (live)."""
    in_first_month = (trade_date.year, trade_date.month) == anchor_ym
    dd_pct = (peak_equity - capital) / peak_equity if peak_equity > 0 else 0.0

    effective_lots = cfg.lots
    if in_first_month:
        effective_lots = min(cfg.lots, cfg.first_month_max_lots)
    elif capital > cfg.capital and cfg.lot_scaling_step > 0:
        extra = int((capital - cfg.capital) / cfg.lot_scaling_step)
        effective_lots = min(cfg.lots + extra, cfg.max_lots_cap)

    if dd_pct >= cfg.dd_force_one_lot_pct:
        effective_lots = 1
    elif dd_pct >= cfg.dd_hard_pct:
        effective_lots = min(effective_lots, 1)
    elif dd_pct >= cfg.dd_soft_pct:
        effective_lots = max(1, effective_lots - 1)

    if vix > 17:
        effective_lots = max(1, effective_lots - 1)
    if vix > cfg.vix_max - 2:
        effective_lots = 1
    if consecutive_losses >= 2:
        effective_lots = max(1, effective_lots - 1)

    full_day_lots = max(1, min(effective_lots, cfg.max_lots_cap))
    if leg_idx == 0:
        return full_day_lots
    if leg_idx == 1:
        return max(1, int(round(full_day_lots * cfg.second_trade_lot_fraction)))
    if leg_idx == 2:
        return max(1, int(round(full_day_lots * cfg.third_trade_lot_fraction)))
    return max(1, int(round(full_day_lots * cfg.fourth_trade_lot_fraction)))


def evaluate_live_daily_adaptive(
    nifty_daily: pd.DataFrame,
    vix: float,
    cfg: Optional[DailyBacktestConfig] = None,
    strategy_filter: str = "BOTH",
    drop_incomplete_today: bool = True,
    anchor_ym: Optional[Tuple[int, int]] = None,
    capital: float = 0.0,
    peak_equity: float = 0.0,
    consecutive_losses: int = 0,
) -> Dict[str, Any]:
    """
    Evaluate the same rules as the daily backtest on the last **completed** daily bar.
    Use live VIX; optionally drop today's row so signals are causal for today's open.
    """
    if cfg is None:
        cfg = DailyBacktestConfig()
    allowed = STRATEGY_FILTER_MAP.get(strategy_filter, STRATEGY_FILTER_MAP["BOTH"])

    df = nifty_daily.copy()
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values("ts").reset_index(drop=True)
    if drop_incomplete_today:
        today = date.today()
        df = df[df["ts"].dt.date < today].reset_index(drop=True)

    if len(df) < 60:
        return {"ok": False, "error": "insufficient_daily_bars", "matches": [], "regime": None}

    series = build_daily_indicator_series(df, cfg)
    i = len(series["closes"]) - 1
    warmup = series["warmup"]
    if i < warmup:
        return {"ok": False, "error": "warmup_not_met", "warmup": warmup, "i": i, "matches": []}

    regime, matches, day_cap = collect_strategy_matches_for_index(i, series, vix, cfg, allowed)
    signal_date = series["dates"][i]

    if anchor_ym is None:
        anchor_ym = (signal_date.year, signal_date.month)
    trade_date = date.today()
    cap_use = capital if capital > 0 else cfg.capital
    peak_use = peak_equity if peak_equity > 0 else cap_use

    legs_out: List[Dict[str, Any]] = []
    for leg_idx, (signal, strategy_name, filter_log) in enumerate(matches):
        if regime == "STRONG_TREND_UP" and signal == "PUT":
            continue
        if regime == "STRONG_TREND_DOWN" and signal == "CALL":
            continue
        sl, tgt = sl_target_for_strategy_regime(strategy_name, regime, cfg)
        lots = compute_live_lots_for_leg(
            cfg, cap_use, peak_use, vix, consecutive_losses,
            trade_date, anchor_ym, leg_idx,
        )
        legs_out.append({
            "leg": leg_idx + 1,
            "direction": signal,
            "strategy": strategy_name,
            "sl_pct": round(sl, 4),
            "target_pct": round(tgt, 4),
            "lots": lots,
            "filter_log": {**filter_log, "regime": {"value": regime}, "daily_leg": leg_idx + 1},
        })

    breakout_watch = {
        "prior_5d_high": max(series["highs"][i - 5:i]) if i >= 5 else None,
        "prior_5d_low": min(series["lows"][i - 5:i]) if i >= 5 else None,
        "last_close": series["closes"][i],
        "ema8": series["ema_fast_vals"][i],
        "ema21": series["ema_slow_vals"][i],
        "rsi14": round(series["rsi_vals"][i], 1),
        "vwap5": round(series["vwap_vals"][i], 2),
    }

    return {
        "ok": True,
        "signal_bar_date": signal_date.isoformat(),
        "trade_session_date": trade_date.isoformat(),
        "regime": regime,
        "vix": round(vix, 2),
        "day_trade_cap": day_cap,
        "raw_matches": len(matches),
        "executable_legs": legs_out,
        "strategy_filter": strategy_filter,
        "breakout_watch": breakout_watch,
        "scan_order_sample": _strategies_scan_order(regime, allowed)[:8],
    }
