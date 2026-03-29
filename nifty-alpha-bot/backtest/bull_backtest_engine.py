"""
Bull-market daily backtest engine — separate from the bear engine.

2 Regimes (CALL-only):
  STRONG_BULL  — EMA8>EMA21>EMA50 + ADX>0.28 + VIX<20 + close>EMA50
  MILD_BULL    — EMA8>EMA21 + close>EMA21 + RSI>50 + VIX<24

5 Strategies (all produce CALL signals — buying dips in uptrend):
  BULL_EMA_PULLBACK   — day's low tests EMA21 zone, close bounces above EMA8
  BULL_EMA8_TOUCH     — day's low dips to EMA8 zone, bounces above EMA8 (more frequent)
  BULL_VWAP_RECLAIM   — intraday dip below VWAP, close reclaims it (MILD_BULL only)
  BULL_REVERSAL_DIP   — opens flat/down in bull trend, recovers above EMA8 by close
  BULL_TREND_CONTINUATION — STRONG_BULL momentum continuation (RSI 50-78)
  BULL_HIGHER_LOW     — 4 consecutive higher lows + green candle + rising RSI

Why separate from bear engine:
  Bull trends are slower and smoother — they need different rules.
  The bear engine uses momentum/breakout strategies that fail badly on
  uptrends (WR=8%). This engine uses pullback/bounce strategies that
  have historically delivered 48-56% WR in trending bull markets.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backtest.data_downloader import get_vix_for_date
from backtest.metrics import compute_metrics
from shared.black_scholes import (
    atm_strike,
    charges_estimate,
    implied_vol_from_vix,
    price_option,
    realistic_slippage,
)

RISK_FREE_RATE = 0.065

BULL_REGIME_NAMES = ["STRONG_BULL", "MILD_BULL", "NO_EDGE"]


# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════

@dataclass
class BullBacktestConfig:
    capital: float = 100_000.0
    lot_size: int = 65
    lots: int = 1

    first_month_risk_capital: float = 25_000.0
    first_month_max_lots: int = 1

    dd_soft_pct: float = 0.045
    dd_hard_pct: float = 0.085
    dd_force_one_lot_pct: float = 0.108

    # ── Indicators (same periods as bear engine) ──
    ema_fast: int = 8
    ema_slow: int = 21
    ema_trend: int = 50
    rsi_period: int = 14
    atr_period: int = 14
    vwap_lookback: int = 5

    # ── SL / Target ──
    # Pullback strategies (EMA_PULLBACK, EMA8_TOUCH, REVERSAL_DIP): price dips then recovers —
    # SL is wider (25%) because we're buying at a support level with room to bounce 3x+.
    sl_pct_bep: float = 0.25   # BULL_EMA_PULLBACK / BULL_EMA8_TOUCH / BULL_TREND_CONTINUATION  2.4x RR
    target_pct_bep: float = 0.60

    sl_pct_brd: float = 0.22   # BULL_REVERSAL_DIP  2.7x RR (entry at open after recovery)
    target_pct_brd: float = 0.60

    sl_pct_bvr: float = 0.20   # BULL_VWAP_RECLAIM  2.75x RR
    target_pct_bvr: float = 0.55

    sl_pct_bhl: float = 0.25   # BULL_HIGHER_LOW  (disabled by default)
    target_pct_bhl: float = 0.70

    # ── Contextual SL tiers ──
    enable_contextual_sl: bool = True
    sl_mult_aplus: float = 1.00
    sl_mult_strong: float = 0.83
    sl_mult_normal: float = 0.78
    sl_aplus_quality_min: float = 68.0
    sl_strong_quality_min: float = 55.0

    # ── Time-based SL (dead-trade exit) ──
    enable_time_sl: bool = True
    time_sl_no_momentum_pct: float = 0.12   # wider: option needs 12% gain before applying
    time_sl_exit_pct: float = 0.18          # exit at -18% if dead trade

    # ── Break-even ──
    break_even_trigger_pct: float = 0.10

    # ── Quality gates ──
    enable_quality_gate: bool = True
    min_quality_score: float = 58.0       # matches bear engine; 58 balances quality vs frequency
    strong_bull_quality_discount: float = 8.0  # STRONG_BULL discount: 58-8=50 floor
    skip_after_loss_min_quality: float = 65.0  # after a loss: demand better setup

    # ── Re-entry: disabled for bull (direction persistence less reliable) ──
    enable_reentry_after_sl: bool = False

    # ── Regime thresholds ──
    adx_strong_bull: float = 0.28
    vix_strong_bull_max: float = 20.0
    vix_mild_bull_max: float = 22.0   # raised from 20 — early bull recovery after a bear period often has VIX 20-23 while EMA8 is already crossing EMA21
    rsi_mild_bull_min: float = 50.0

    # ── Risk ──
    max_trades_per_day: int = 2   # bull days: 1-2 entries max (trend is smooth)
    max_consecutive_losses: int = 5
    max_daily_loss_pct: float = 0.03
    enable_daily_loss_cap: bool = True
    enable_direction_correlation_block: bool = True
    enable_skip_after_loss: bool = True
    vix_max: float = 22.0
    strike_step: int = 50
    slippage_pct: float = 0.005
    min_option_premium: float = 4.5

    lot_scaling_step: float = 20_000.0
    max_lots_cap: int = 5
    second_trade_lot_fraction: float = 0.50

    # ── Strategy enable flags ──
    enable_bull_ema_pullback: bool = False      # Disabled: unreliable regardless of entry timing, blocks good strategies
    enable_bull_ema8_touch: bool = False        # Disabled: MILD_BULL = 21% WR (-₹27k), STRONG_BULL = 33% marginal — hurts overall P&L
    enable_bull_vwap_reclaim: bool = True       # MILD_BULL only — on STRONG_BULL, VWAP dip is a warning (0% WR tested)
    enable_bull_reversal_dip: bool = False      # Disabled: 25% WR across multiple test runs, consistently hurts P&L
    enable_bull_trend_continuation: bool = True # Both regimes — RSI 50-78, EMA21 rising
    enable_bull_higher_low: bool = False        # Disabled: WR=8-12% on daily data, hurts results
    enable_bull_fresh_crossover: bool = False   # Disabled: false crossovers during bear relief bounces give 20% WR, -₹7.6k
    enable_bull_momentum_breakout: bool = True  # Close breaks above prior 5-day high in established bull trend


# ═══════════════════════════════════════════════════════════════════
# INDICATORS (shared helpers — same as bear engine)
# ═══════════════════════════════════════════════════════════════════

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
    trs = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    alpha = 2.0 / (period + 1.0)
    out = [trs[0]]
    for v in trs[1:]:
        out.append(v * alpha + out[-1] * (1 - alpha))
    return out


def _directional_movement(highs: list, lows: list, closes: list, period: int = 14) -> list:
    n = len(closes)
    if n < 2:
        return [0.0] * n
    dm_plus = [0.0] * n
    dm_minus = [0.0] * n
    tr_vals = [highs[0] - lows[0]]
    for i in range(1, n):
        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]
        dm_plus[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0.0
        dm_minus[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0.0
        tr_vals.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    alpha = 2.0 / (period + 1.0)
    atr_s = [tr_vals[0]]
    dip_s = [dm_plus[0]]
    dim_s = [dm_minus[0]]
    for i in range(1, n):
        atr_s.append(tr_vals[i] * alpha + atr_s[-1] * (1 - alpha))
        dip_s.append(dm_plus[i] * alpha + dip_s[-1] * (1 - alpha))
        dim_s.append(dm_minus[i] * alpha + dim_s[-1] * (1 - alpha))
    result = []
    for i in range(n):
        if atr_s[i] > 0:
            di_plus = dip_s[i] / atr_s[i]
            di_minus = dim_s[i] / atr_s[i]
            denom = di_plus + di_minus
            result.append(abs(di_plus - di_minus) / denom if denom > 0 else 0.0)
        else:
            result.append(0.0)
    return result


# ═══════════════════════════════════════════════════════════════════
# REGIME CLASSIFIER (bull-specific)
# ═══════════════════════════════════════════════════════════════════

def _classify_bull_regime(
    i: int,
    closes: list,
    ema_fast: list,
    ema_slow: list,
    ema_trend: list,
    adx: list,
    rsi: list,
    vix: float,
    cfg: BullBacktestConfig,
) -> str:
    """Classify the day's bull regime. Returns STRONG_BULL, MILD_BULL, or NO_EDGE."""
    ef, es, et = ema_fast[i], ema_slow[i], ema_trend[i]
    c = closes[i]

    full_stack = ef > es > et and c > et   # EMA8 > EMA21 > EMA50 and price above EMA50
    basic_stack = ef > es and c > es       # EMA8 > EMA21 and price above EMA21

    if not basic_stack:
        return "NO_EDGE"   # trend is broken — bear engine handles this

    if (full_stack
            and adx[i] >= cfg.adx_strong_bull
            and vix <= cfg.vix_strong_bull_max
            and rsi[i] >= 50.0):
        return "STRONG_BULL"

    if basic_stack and rsi[i] >= cfg.rsi_mild_bull_min and vix <= cfg.vix_mild_bull_max:
        return "MILD_BULL"

    return "NO_EDGE"


# ═══════════════════════════════════════════════════════════════════
# STRATEGIES
# ═══════════════════════════════════════════════════════════════════

def _check_bull_ema_pullback(
    i: int,
    highs: list, lows: list, closes: list, opens: list,
    ema_fast: list, ema_slow: list,
    rsi: list,
    cfg: BullBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """
    EMA21 PULLBACK — day's low dipped into the EMA21 support zone, then
    closed back above EMA8. Buying the dip at EMA21 support in an uptrend.

    Zone widened to 2% above EMA21 (from prior 0.8%) — the institutional
    support zone is not a hairline; price pulls back to within this range
    before buyers step in. Kept strict on the downside (must not break EMA21
    by >1%) to avoid catching breakdowns.

    Conditions:
      1. EMA8 > EMA21 (uptrend structure intact)
      2. Low within EMA21 support zone: low ≤ EMA21 × 1.020 (within 2% above EMA21)
         AND low > EMA21 × 0.990 (didn't break below EMA21 by more than 1%)
      3. Close > EMA8 (bounced back above fast EMA — recovery confirmed)
      4. Close ≥ Open × 0.998 (roughly green — buyers took control by close)
      5. RSI 42–65 (moderate momentum — not overbought after bounce)
      6. Prior day's close > EMA8 (uptrend was intact before the pullback)
    """
    if i < 4:
        return None

    ef, es = ema_fast[i], ema_slow[i]
    if ef <= es:
        return None

    ema21 = es
    # Low within EMA21 support zone (within 2% above EMA21 — widened from 0.8%)
    if lows[i] > ema21 * 1.020:     # too far above EMA21 — no meaningful test
        return None
    # Low must not break below EMA21 by more than 1% (support held)
    if lows[i] < ema21 * 0.990:
        return None

    # Close must bounce back above EMA8 (recovery confirmed)
    if closes[i] <= ef:
        return None
    # Roughly green or neutral candle (buyers won)
    if closes[i] < opens[i] * 0.998:
        return None
    # RSI in moderate zone (not overbought, not broken trend)
    if not (42.0 <= rsi[i] <= 65.0):
        return None
    # Prior day was in uptrend (close above EMA8)
    if i >= 1 and closes[i - 1] <= ema_fast[i - 1]:
        return None

    bounce_strength = round((closes[i] - ema21) / ema21 * 100, 2)
    pullback_depth = round((ema21 - lows[i]) / ema21 * 100, 2)
    body = abs(closes[i] - opens[i])
    rng = highs[i] - lows[i]
    body_ratio = round(body / rng, 2) if rng > 0 else 0.0

    fl: dict = {
        "ema8_above_ema21":   {"passed": True, "value": round(ef - es, 1)},
        "low_touched_ema21":  {"passed": True, "value": round(lows[i] - ema21, 1)},
        "close_above_ema8":   {"passed": True, "value": round(closes[i] - ef, 1)},
        "bounce_from_ema21":  {"passed": True, "value": bounce_strength},
        "rsi_moderate":       {"passed": True, "value": round(rsi[i], 1)},
        "pullback_depth_pct": {"passed": True, "value": pullback_depth},
        "body_ratio":         {"passed": body_ratio >= 0.20, "value": body_ratio},
    }
    return "CALL", "BULL_EMA_PULLBACK", fl


def _check_bull_vwap_reclaim(
    i: int,
    highs: list, lows: list, closes: list, opens: list,
    ema_fast: list, ema_slow: list,
    rsi: list,
    vwap_vals: list,
    cfg: BullBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """
    TRUE VWAP RECLAIM — price dipped below VWAP intraday, then closed back
    above VWAP. Institutional buyers stepped in at VWAP support and pushed
    price back above. Classic dip-buy at VWAP in an uptrend.

    The key "reclaim" mechanic: low < VWAP (actual dip below), close > VWAP
    (buyers won by end of day). This is more selective than "close near VWAP"
    and delivers a higher win rate.

    Conditions:
      1. EMA8 > EMA21 (primary uptrend intact)
      2. Low < VWAP × 0.998 (actually dipped below VWAP, at least 0.2%)
      3. Low > VWAP × 0.990 (dip < 1% — not a full breakdown)
      4. Close > VWAP × 1.001 (reclaimed VWAP, closed 0.1%+ above it)
      5. RSI 44–68 (moderate momentum — no overbought)
      6. Prior day's close > EMA21 (uptrend context was valid)
    """
    if i < 2:
        return None
    vwap = vwap_vals[i]
    if vwap <= 0:
        return None
    if ema_fast[i] <= ema_slow[i]:
        return None

    # Must have actually dipped BELOW VWAP (real reclaim, not just hovering)
    if lows[i] >= vwap * 0.998:      # low didn't go below VWAP — not a reclaim
        return None
    # Dip must not be catastrophic (> 1% below VWAP = failed reclaim, trend broken)
    if lows[i] < vwap * 0.990:
        return None

    # Close must reclaim VWAP (0.1%+ above)
    if closes[i] <= vwap * 1.001:
        return None

    # RSI zone (moderate, not overbought)
    if not (44.0 <= rsi[i] <= 68.0):
        return None

    # Prior day uptrend context (prior close above EMA21)
    if i >= 1 and closes[i - 1] <= ema_slow[i - 1]:
        return None

    dip_pct   = round((vwap - lows[i]) / vwap * 100, 2)
    reclaim_pct = round((closes[i] - vwap) / vwap * 100, 2)
    body = abs(closes[i] - opens[i])
    rng  = highs[i] - lows[i]
    body_ratio = round(body / rng, 2) if rng > 0 else 0.0

    fl: dict = {
        "ema_uptrend":       {"passed": True, "value": round(ema_fast[i] - ema_slow[i], 1)},
        "dipped_below_vwap": {"passed": True, "value": round(lows[i] - vwap, 1)},
        "reclaimed_vwap":    {"passed": True, "value": reclaim_pct},
        "rsi_moderate":      {"passed": True, "value": round(rsi[i], 1)},
        "dip_depth_pct":     {"passed": True, "value": dip_pct},
        "body_ratio":        {"passed": body_ratio >= 0.20, "value": body_ratio},
    }
    return "CALL", "BULL_VWAP_RECLAIM", fl


def _check_bull_ema8_touch(
    i: int,
    highs: list, lows: list, closes: list, opens: list,
    ema_fast: list, ema_slow: list,
    rsi: list,
    cfg: BullBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """
    BULL_EMA8_TOUCH — day's low dips to the EMA8 zone (within 0.3% above EMA8),
    price holds support and closes back above EMA8. Pullback to the fast EMA
    in an uptrend — EMA8 acts as dynamic support on strong bull days.

    More frequent than EMA21 pullbacks because price tests EMA8 every 2-3 days
    in a trending market. Unlike BULL_TREND_CONTINUATION (which requires the low
    to stay ABOVE EMA8 × 0.994), this strategy captures the actual touch-and-bounce.

    Conditions:
      1. EMA8 > EMA21 and EMA21 rising (strong uptrend structure)
      2. Low ≤ EMA8 × 1.003 (actually touched the EMA8 zone, within 0.3% above)
         AND low > EMA8 × 0.990 (support held — didn't break below by >1%)
      3. Close > EMA8 (bounced back above fast EMA)
      4. RSI 44–68 (moderate momentum — not oversold, not overbought)
      5. Prior close > EMA21 (uptrend context valid before the dip)
    """
    if i < 4:
        return None

    ef, es = ema_fast[i], ema_slow[i]
    if ef <= es:
        return None
    # EMA21 must be rising — confirms trend is NOT just hovering (2-day slope)
    if ema_slow[i] <= ema_slow[i - 2]:
        return None

    # Low must have touched the EMA8 zone (within 0.3% above EMA8)
    if lows[i] > ef * 1.003:         # low stayed too far above EMA8 — no real test
        return None
    # Support held — didn't break below EMA8 by more than 1%
    if lows[i] < ef * 0.990:
        return None

    # Close back above EMA8 (bounce confirmed)
    if closes[i] <= ef:
        return None

    # RSI moderate zone
    if not (44.0 <= rsi[i] <= 68.0):
        return None

    # Prior close above EMA21 (uptrend was intact)
    if i >= 1 and closes[i - 1] <= ema_slow[i - 1]:
        return None

    touch_depth = round((ef - lows[i]) / ef * 100, 2)   # how far below EMA8 the low went
    bounce_pct  = round((closes[i] - lows[i]) / lows[i] * 100, 2)
    body = abs(closes[i] - opens[i])
    rng  = highs[i] - lows[i]
    body_ratio = round(body / rng, 2) if rng > 0 else 0.0

    fl: dict = {
        "ema_uptrend":      {"passed": True,              "value": round(ef - es, 1)},
        "ema21_rising":     {"passed": True,              "value": round(es - ema_slow[i-2], 1)},
        "low_touched_ema8": {"passed": True,              "value": round(lows[i] - ef, 1)},
        "close_above_ema8": {"passed": True,              "value": round(closes[i] - ef, 1)},
        "touch_depth_pct":  {"passed": True,              "value": touch_depth},
        "bounce_pct":       {"passed": bounce_pct >= 0.3, "value": bounce_pct},
        "rsi_moderate":     {"passed": True,              "value": round(rsi[i], 1)},
        "body_ratio":       {"passed": body_ratio >= 0.15,"value": body_ratio},
    }
    return "CALL", "BULL_EMA8_TOUCH", fl


def _check_bull_reversal_dip(
    i: int,
    highs: list, lows: list, closes: list, opens: list,
    ema_fast: list, ema_slow: list,
    rsi: list,
    cfg: BullBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """
    BULL_REVERSAL_DIP — price opens flat or down (fear/profit-taking at open)
    in a bull trend but buyers step in and close the day above EMA8 with a
    strong recovery body. Classic "shakeout and recovery" pattern in an uptrend.

    In a bull market, early weakness that resolves to strength by close is a
    high-conviction buy signal — weak hands shaken out, strong hands absorbed.

    Conditions:
      1. EMA8 > EMA21 (uptrend intact)
      2. Open ≤ prior close × 0.998 (opened flat or down — early weakness)
      3. Close > Open + 0.2% (net recovered — buyers dominated by end of day)
      4. Close > EMA8 (back in bullish zone)
      5. Low > EMA21 × 0.992 (EMA21 support not broken — still in bull structure)
      6. RSI 40–65 (moderate — not overbought, has room to run)
      7. Body ratio > 0.35 (strong reversal body — not a doji)
    """
    if i < 3:
        return None

    ef, es = ema_fast[i], ema_slow[i]
    if ef <= es:
        return None

    # Opened flat or down (early weakness)
    if opens[i] > closes[i - 1] * 0.998:
        return None

    # Net recovered — closed higher than open (buyers dominated)
    if closes[i] <= opens[i] * 1.002:
        return None

    # Close above EMA8 (back in bull zone)
    if closes[i] <= ef:
        return None

    # EMA21 support held (no regime break)
    if lows[i] < es * 0.992:
        return None

    # RSI moderate — room to run (cap raised 65→70: early bull recovery has RSI climbing fast)
    if not (40.0 <= rsi[i] <= 70.0):
        return None

    # Strong recovery body (real buyers, not just a doji)
    body = abs(closes[i] - opens[i])
    rng  = highs[i] - lows[i]
    body_ratio = round(body / rng, 2) if rng > 0 else 0.0
    if body_ratio < 0.35:
        return None

    open_gap_pct  = round((opens[i] - closes[i - 1]) / closes[i - 1] * 100, 2)
    recovery_pct  = round((closes[i] - opens[i]) / opens[i] * 100, 2)
    above_ema8_pct = round((closes[i] - ef) / ef * 100, 2)

    fl: dict = {
        "ema_uptrend":      {"passed": True,                     "value": round(ef - es, 1)},
        "open_weakness":    {"passed": True,                     "value": open_gap_pct},
        "close_recovered":  {"passed": True,                     "value": recovery_pct},
        "close_above_ema8": {"passed": True,                     "value": above_ema8_pct},
        "ema21_held":       {"passed": True,                     "value": round(lows[i] - es, 1)},
        "rsi_moderate":     {"passed": True,                     "value": round(rsi[i], 1)},
        "body_ratio":       {"passed": body_ratio >= 0.35,       "value": body_ratio},
    }
    return "CALL", "BULL_REVERSAL_DIP", fl


def _check_bull_higher_low(
    i: int,
    highs: list, lows: list, closes: list, opens: list,
    ema_fast: list, ema_slow: list,
    rsi_vals: list,
    cfg: BullBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """
    BULL_HIGHER_LOW — 4 consecutive higher lows + green candle + rising RSI.

    This is the strongest bull signal: multiple sessions of higher lows
    means institutional buyers are consistently stepping in at higher prices.

    Conditions:
      1. 4 consecutive higher lows: low[i] > low[i-1] > low[i-2] > low[i-3]
      2. EMA8 > EMA21 (trend confirmation)
      3. Green candle today (close > open)
      4. RSI > 50 AND rising vs yesterday (momentum is accelerating)
    """
    if i < 4:
        return None
    # 4 consecutive higher lows
    if not (lows[i] > lows[i-1] > lows[i-2] > lows[i-3]):
        return None
    # EMA uptrend
    if ema_fast[i] <= ema_slow[i]:
        return None
    # Green candle
    if closes[i] <= opens[i]:
        return None
    # RSI > 50 and rising
    if rsi_vals[i] < 50.0:
        return None
    if rsi_vals[i] <= rsi_vals[i - 1]:
        return None

    low_climb = round(lows[i] - lows[i-3], 1)
    fl: dict = {
        "higher_lows_4":  {"passed": True, "value": low_climb},
        "ema_uptrend":    {"passed": True, "value": round(ema_fast[i] - ema_slow[i], 1)},
        "green_candle":   {"passed": True, "value": round(closes[i] - opens[i], 1)},
        "rsi_rising":     {"passed": True, "value": round(rsi_vals[i], 1)},
        "rsi_above_50":   {"passed": True, "value": round(rsi_vals[i] - rsi_vals[i-1], 1)},
    }
    return "CALL", "BULL_HIGHER_LOW", fl


def _check_bull_trend_continuation(
    i: int,
    highs: list, lows: list, closes: list, opens: list,
    ema_fast: list, ema_slow: list,
    rsi: list,
    cfg: BullBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """
    BULL_TREND_CONTINUATION — STRONG_BULL only. Full EMA stack with price
    holding above EMA8, green candle, RSI 55-72. Classic momentum continuation
    for very strong trending days. Only fires on STRONG_BULL regime.

    Conditions:
      1. EMA8 > EMA21, and EMA21 is rising (proxy for full EMA stack)
      2. Low ≥ EMA8 × 0.994 — intraday dip stayed near EMA8 (trend is strong)
      3. Close > EMA8 (closed in bullish zone)
      4. Green candle (close ≥ open)
      5. RSI 55–72 (strong momentum, not overbought)
      6. Close > prior close (price is advancing, not stalling)
    """
    if i < 4:
        return None

    ef, es = ema_fast[i], ema_slow[i]
    if ef <= es:
        return None
    # EMA21 must be rising (strong trend — prevents firing on stalling trend days)
    if ema_slow[i] <= ema_slow[i - 2]:
        return None

    # Low held near EMA8 (strong trend — no deep pullback)
    if lows[i] < ef * 0.994:
        return None
    # Close above EMA8
    if closes[i] <= ef:
        return None
    # Green candle
    if closes[i] < opens[i]:
        return None
    # Momentum RSI zone — not oversold, not extreme overbought
    if not (50.0 <= rsi[i] <= 75.0):
        return None
    # Price advancing
    if closes[i] < closes[i - 1] * 0.999:
        return None

    body = abs(closes[i] - opens[i])
    rng  = highs[i] - lows[i]
    body_ratio = round(body / rng, 2) if rng > 0 else 0.0
    above_ema8_pct = round((closes[i] - ef) / ef * 100, 2)

    fl: dict = {
        "full_ema_stack": {"passed": True, "value": round(ef - es, 1)},
        "low_above_ema8": {"passed": True, "value": round(lows[i] - ef, 1)},
        "green_candle":   {"passed": True, "value": round(closes[i] - opens[i], 1)},
        "rsi_strong":     {"passed": True, "value": round(rsi[i], 1)},
        "above_ema8_pct": {"passed": above_ema8_pct >= 0, "value": above_ema8_pct},
        "body_ratio":     {"passed": body_ratio >= 0.20, "value": body_ratio},
    }
    return "CALL", "BULL_TREND_CONTINUATION", fl


def _check_bull_fresh_crossover(
    i: int,
    highs: list, lows: list, closes: list, opens: list,
    ema_fast: list, ema_slow: list,
    rsi: list,
    adx: float,
    cfg: BullBacktestConfig,
) -> Optional[Tuple[str, str, dict]]:
    """
    BULL_FRESH_CROSSOVER — EMA8 crossed above EMA21 within the last 4 bars.

    This is specifically designed for the "market dropped for weeks, just turned bullish"
    scenario. When EMA8 crosses above EMA21 the first time after a bear period, CALL
    options are cheap (IV still elevated from bear), trend is fresh and has maximum
    room to run, and institutional buyers are committing capital for the new trend.

    Key difference from BULL_TREND_CONTINUATION: does NOT require EMA21 to be rising.
    EMA21 is a lagging indicator — during the first 5-10 days of a fresh bull reversal,
    EMA21 is still declining (reflecting the prior bear). TC's EMA21 slope requirement
    correctly blocks stalling old trends, but it incorrectly blocks these highest-conviction
    fresh reversal entries. This strategy handles exactly those days.

    Conditions:
      1. EMA8 > EMA21 today (crossover intact)
      2. EMA8 crossed above EMA21 within the last 4 bars (fresh reversal, not old trend)
      3. Close > EMA8 (price confirmed above fast EMA — buyers in control)
      4. Green candle (close > open × 0.999)
      5. RSI 45-72 (recovering from oversold — ample room to run)
      6. Low > EMA21 × 0.988 (EMA21 support held — bull structure not broken)
      7. ADX >= 0.14 (some directional movement building)
    """
    if i < 6:
        return None

    ef, es = ema_fast[i], ema_slow[i]
    if ef <= es:
        return None

    # EMA8 must have crossed above EMA21 within the last 4 bars
    # (crossover at bar j means: ema_fast[j] > ema_slow[j] AND ema_fast[j-1] <= ema_slow[j-1])
    crossed_recently = False
    for k in range(1, 5):  # k=1..4 → check crossover 1 to 4 bars ago
        if i - k - 1 < 0:
            break
        if ema_fast[i - k] > ema_slow[i - k] and ema_fast[i - k - 1] <= ema_slow[i - k - 1]:
            crossed_recently = True
            break
    if not crossed_recently:
        return None

    # Price confirmed above EMA8
    if closes[i] <= ef:
        return None

    # Green candle (buyers dominating)
    if closes[i] < opens[i] * 0.999:
        return None

    # RSI in recovery zone (coming off oversold — fresh bull entry, not overbought chasing)
    if not (45.0 <= rsi[i] <= 72.0):
        return None

    # EMA21 support held (not a false crossover that immediately fails)
    if lows[i] < es * 0.988:
        return None

    # Some directional strength (trend is building — tighter than 0.14 to avoid false crossovers)
    if adx < 0.17:
        return None

    # 3-day price momentum: close must be above the close 3 bars ago.
    # A genuine bull recovery has price making progress. A brief relief bounce in a downtrend
    # often reverses within 1-2 bars, leaving the 3-day momentum negative. This is the single
    # most effective filter against false EMA crossovers during bear markets.
    if closes[i] <= closes[i - 3]:
        return None

    days_since_cross = next(
        (k for k in range(1, 5) if i - k - 1 >= 0
         and ema_fast[i - k] > ema_slow[i - k]
         and ema_fast[i - k - 1] <= ema_slow[i - k - 1]),
        4,
    )
    cross_gap = round(ef - es, 1)
    above_ema8_pct = round((closes[i] - ef) / ef * 100, 2)
    body = abs(closes[i] - opens[i])
    rng = highs[i] - lows[i]
    body_ratio = round(body / rng, 2) if rng > 0 else 0.0

    fl: dict = {
        "ema8_crossed_above_ema21":  {"passed": True, "value": days_since_cross},
        "ema8_above_ema21":          {"passed": True, "value": cross_gap},
        "close_above_ema8":          {"passed": True, "value": above_ema8_pct},
        "green_candle":              {"passed": True, "value": round(closes[i] - opens[i], 1)},
        "rsi_recovery_zone":         {"passed": True, "value": round(rsi[i], 1)},
        "ema21_support_held":        {"passed": True, "value": round(lows[i] - es, 1)},
        "adx_building":              {"passed": adx >= 0.14, "value": round(adx, 3)},
        "body_ratio":                {"passed": body_ratio >= 0.20, "value": body_ratio},
    }
    return "CALL", "BULL_FRESH_CROSSOVER", fl


def _check_bull_momentum_breakout(
    i: int,
    highs: list, lows: list, closes: list, opens: list,
    ema_fast: list, ema_slow: list,
    rsi: list,
    adx: float,
    cfg: BullBacktestConfig,
    lookback_days: int = 5,
) -> Optional[Tuple[str, str, dict]]:
    """
    BULL_MOMENTUM_BREAKOUT — close breaks above the prior 5-day high in an established
    bull trend. When price makes a new 5-session high with strong RSI and an established
    rising EMA21, breakout traders and momentum algorithms pile in for a strong follow-through.

    Unlike BULL_TREND_CONTINUATION (which requires the intraday low to stay above EMA8),
    this fires even when there was an intraday dip below EMA8. The defining condition is
    that buyers pushed the close to a new 5-day high — an incredibly bullish outcome after
    any intraday weakness. These "dip-and-rip to new highs" days have outstanding follow-through.

    Conditions:
      1. EMA8 > EMA21 (uptrend intact)
      2. EMA21 is rising: ema_slow[i] > ema_slow[i-2] (established trend, not fresh crossover)
      3. Close > max(highs[i-5:i]) — actual breakout above prior 5-day high
      4. Green candle (close > open × 1.001 — buyers drove the breakout)
      5. RSI 53-76 (strong momentum, not dangerously overbought)
      6. ADX >= 0.20 (trend has meaningful directional strength)
      7. Close > EMA8 (price confirmed above fast EMA)
    """
    if i < 7:
        return None

    ef, es = ema_fast[i], ema_slow[i]
    if ef <= es:
        return None

    # EMA21 must be rising — ensures this is an established trend, not a fresh crossover
    # (fresh crossover days are handled by BULL_FRESH_CROSSOVER)
    if ema_slow[i] <= ema_slow[i - 2]:
        return None

    # Compute prior N-day high (bars i-lookback to i-1, not including today)
    if i < lookback_days:
        return None
    prior_nd_high = max(highs[i - lookback_days: i])

    # Today's close must break above the prior N-day high (actual breakout)
    if closes[i] <= prior_nd_high:
        return None

    # Strong green candle (buyers drove the breakout — not a marginal close above)
    if closes[i] < opens[i] * 1.001:
        return None

    # RSI momentum zone — strong but not dangerously overbought
    if not (53.0 <= rsi[i] <= 76.0):
        return None

    # ADX confirms directional strength
    if adx < 0.20:
        return None

    # Price above EMA8 (in bullish zone at close)
    if closes[i] <= ef:
        return None

    breakout_pct = round((closes[i] - prior_nd_high) / prior_nd_high * 100, 2)
    above_ema8_pct = round((closes[i] - ef) / ef * 100, 2)
    ema21_slope = round(ema_slow[i] - ema_slow[i - 2], 1)
    body = abs(closes[i] - opens[i])
    rng = highs[i] - lows[i]
    body_ratio = round(body / rng, 2) if rng > 0 else 0.0

    fl: dict = {
        "ema_uptrend":       {"passed": True, "value": round(ef - es, 1)},
        "ema21_rising":      {"passed": True, "value": ema21_slope},
        "broke_5d_high":     {"passed": True, "value": breakout_pct},
        "green_candle":      {"passed": True, "value": round(closes[i] - opens[i], 1)},
        "rsi_strong":        {"passed": True, "value": round(rsi[i], 1)},
        "adx_strength":      {"passed": adx >= 0.20, "value": round(adx, 3)},
        "close_above_ema8":  {"passed": True, "value": above_ema8_pct},
        "body_ratio":        {"passed": body_ratio >= 0.20, "value": body_ratio},
    }
    return "CALL", "BULL_MOMENTUM_BREAKOUT", fl


# ═══════════════════════════════════════════════════════════════════
# QUALITY SCORING (bull-specific calibration)
# ═══════════════════════════════════════════════════════════════════

_BULL_STRATEGY_TIER: Dict[str, float] = {
    "BULL_VWAP_RECLAIM":        17.0,   # excellent: VWAP dip + reclaim — MILD_BULL only (44%+ WR)
    "BULL_TREND_CONTINUATION":  15.0,   # best workhorse: STRONG_BULL 61% WR, MILD_BULL 43% WR
    "BULL_MOMENTUM_BREAKOUT":   14.0,   # breakout: close > 5-day high — dip-and-rip days
    "BULL_REVERSAL_DIP":        13.0,   # disabled; 25% WR across runs, hurts P&L
    "BULL_FRESH_CROSSOVER":     12.0,   # below TC: fires as fallback when TC blocked by EMA21 slope check
    "BULL_EMA_PULLBACK":         8.0,   # disabled; unreliable in backtests
    "BULL_EMA8_TOUCH":           8.0,   # disabled; MILD_BULL 21% WR, hurts P&L
    "BULL_HIGHER_LOW":           6.0,   # disabled; WR=8-12%
}

_BULL_REGIME_QUALITY: Dict[str, float] = {
    "STRONG_BULL": 25.0,
    "MILD_BULL":   15.0,
    "NO_EDGE":     -20.0,
}


def _compute_bull_quality_score(
    strategy_name: str,
    filter_log: dict,
    rsi: float,
    adx: float,
    vix: float,
    regime: str,
) -> float:
    """Quality score 0-100 for a bull entry signal."""
    score = 0.0

    # 1. Strategy tier (0-18)
    score += _BULL_STRATEGY_TIER.get(strategy_name, 8.0)

    # 2. Regime edge (−20 to +25)
    score += _BULL_REGIME_QUALITY.get(regime, 0.0)

    # 3. Filter checks passed (0-20)
    checks = [v for v in filter_log.values() if isinstance(v, dict) and "passed" in v]
    if checks:
        passed = sum(1 for c in checks if c.get("passed"))
        score += (passed / len(checks)) * 20

    # 4. ADX: moderate trend = ideal for pullback entries (0-20)
    # Too weak = choppy; too strong = might be overextended
    if 0.20 <= adx <= 0.40:
        score += 20
    elif 0.40 < adx <= 0.50:
        score += 12
    elif 0.14 <= adx < 0.20:
        score += 8
    elif adx > 0.50:
        score += 4

    # 5. RSI zone for CALL (0-17)
    # Ideal: 48-65 (momentum present but not overbought)
    if 48.0 <= rsi <= 65.0:
        score += 17
    elif 42.0 <= rsi < 48.0 or 65.0 < rsi <= 72.0:
        score += 8
    # RSI < 42 (trend broken) or > 72 (overbought) = 0

    return round(max(0.0, min(100.0, score)), 1)


# ═══════════════════════════════════════════════════════════════════
# OPTION TRADE SIMULATION (mirrors bear engine exactly)
# ═══════════════════════════════════════════════════════════════════

def _get_weekly_expiry(trade_date: date) -> date:
    days_until_thursday = (3 - trade_date.weekday()) % 7
    return trade_date + timedelta(days=days_until_thursday)


def _simulate_bull_option_trade(
    spot_entry: float,
    direction: str,   # always "CALL" for bull engine
    trade_date: date,
    vix: float,
    day_high: float,
    day_low: float,
    day_close: float,
    sl_pct: float,
    target_pct: float,
    cfg: BullBacktestConfig,
    lots_override: int = 0,
) -> Optional[Dict[str, Any]]:
    expiry = _get_weekly_expiry(trade_date)
    strike = atm_strike(spot_entry, cfg.strike_step)
    opt_type = "CE"  # bull engine = CALL = CE only
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

    # CALL: best = day_high, worst = day_low
    opt_best  = price_option(day_high,  strike, T_exit, RISK_FREE_RATE, sigma_exit, opt_type)["price"]
    opt_worst = price_option(day_low,   strike, T_exit, RISK_FREE_RATE, sigma_exit, opt_type)["price"]
    opt_close = price_option(day_close, strike, T_exit, RISK_FREE_RATE, sigma_exit, opt_type)["price"]

    # Time-based SL: dead-trade exit if no upside momentum
    time_sl_price = entry_price * (1 - cfg.time_sl_exit_pct)
    if (cfg.enable_time_sl
            and opt_best < entry_price * (1 + cfg.time_sl_no_momentum_pct)
            and opt_close < time_sl_price):
        exit_price_raw = time_sl_price
        exit_reason = "TIME_SL"
        exit_slip = realistic_slippage(cfg.slippage_pct, vix, dte, exit_price_raw)
        exit_price = exit_price_raw * (1 - exit_slip)
        effective_lots = lots_override if lots_override > 0 else cfg.lots
        qty = effective_lots * cfg.lot_size
        gross_pnl = (exit_price - entry_price) * qty
        charges = charges_estimate(entry_price, exit_price, qty)
        return {
            "status": "COMPLETED", "direction": direction, "option_type": opt_type,
            "strike": strike, "expiry": expiry.isoformat(),
            "entry_ts": f"{trade_date}T09:30:00", "exit_ts": f"{trade_date}T10:15:00",
            "entry_price": round(entry_price, 2), "exit_price": round(exit_price, 2),
            "sl_price": round(sl_price, 2), "target_price": round(target_price, 2),
            "exit_reason": exit_reason,
            "gross_pnl": round(gross_pnl, 2), "charges": round(charges, 2),
            "net_pnl": round(gross_pnl - charges, 2), "qty": qty, "lots": effective_lots,
            "spot_at_entry": round(spot_entry, 2), "delta_at_entry": round(entry_opt.get("delta", 0.5), 4),
            "iv_at_entry": round(sigma, 4), "vix": vix,
            "trade_date": trade_date.isoformat(), "entry_slippage_pct": round(entry_slip * 100, 2),
        }

    # Normal exit logic
    if opt_worst <= sl_price and opt_best < target_price:
        exit_price_raw, exit_reason = sl_price, "SL_HIT"
    elif opt_worst <= sl_price and opt_best >= target_price:
        random.seed(int(spot_entry * 100 + dte * 10))
        if random.random() < 0.30:  # bull strategies slightly better on ambiguous days
            exit_price_raw, exit_reason = target_price, "TARGET_HIT"
        else:
            exit_price_raw, exit_reason = sl_price, "SL_HIT"
    elif opt_best >= target_price:
        exit_price_raw, exit_reason = target_price, "TARGET_HIT"
    elif opt_close >= entry_price * (1 + cfg.break_even_trigger_pct):
        exit_price_raw, exit_reason = opt_close, "EOD_PROFIT"
    else:
        exit_price_raw, exit_reason = opt_close, "EOD_EXIT"

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
# MAIN BACKTEST RUNNER
# ═══════════════════════════════════════════════════════════════════

def evaluate_live_bull(
    nifty_daily: pd.DataFrame,
    vix: float,
    cfg: Optional[BullBacktestConfig] = None,
    drop_incomplete_today: bool = True,
    capital: float = 0.0,
    consecutive_losses: int = 0,
) -> Dict[str, Any]:
    """
    Evaluate bull strategies on the last completed daily bar (for live routing).
    Mirrors evaluate_live_daily_adaptive() interface so trader.py can call either.
    Returns same schema: ok, regime, executable_legs, breakout_watch, etc.
    """
    from datetime import date as _date
    if cfg is None:
        cfg = BullBacktestConfig()

    df = nifty_daily.copy()
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values("ts").reset_index(drop=True)
    if drop_incomplete_today:
        today = _date.today()
        df = df[df["ts"].dt.date < today].reset_index(drop=True)

    if len(df) < 60:
        return {"ok": False, "error": "insufficient_daily_bars", "matches": [], "regime": None}

    # Ensure volume column exists (yfinance may omit it on network errors)
    if "volume" not in df.columns:
        df["volume"] = 1.0

    closes  = df["close"].tolist()
    highs   = df["high"].tolist()
    lows    = df["low"].tolist()
    opens   = df["open"].tolist()
    dates   = df["ts"].dt.date.tolist()

    ema_fast_vals  = _ema(closes, cfg.ema_fast)
    ema_slow_vals  = _ema(closes, cfg.ema_slow)
    ema_trend_vals = _ema(closes, cfg.ema_trend)
    rsi_vals       = _rsi(closes, cfg.rsi_period)
    adx_vals       = _directional_movement(highs, lows, closes, cfg.atr_period)

    df["tp"]     = (df["high"] + df["low"] + df["close"]) / 3
    df["tp_vol"] = df["tp"] * df["volume"].clip(lower=1)
    df["vol_sum"] = df["volume"].clip(lower=1).rolling(cfg.vwap_lookback, min_periods=1).sum()
    df["vwap"]   = df["tp_vol"].rolling(cfg.vwap_lookback, min_periods=1).sum() / df["vol_sum"]
    vwap_vals = df["vwap"].tolist()

    warmup = max(cfg.ema_trend + 1, cfg.rsi_period + 1, 10)
    i = len(closes) - 1
    if i < warmup:
        return {"ok": False, "error": "warmup_not_met", "matches": [], "regime": None}

    regime = _classify_bull_regime(
        i, closes, ema_fast_vals, ema_slow_vals, ema_trend_vals,
        adx_vals, rsi_vals, vix, cfg,
    )

    matches = []
    if vix <= cfg.vix_max:
        adx_now = adx_vals[i]

        # FRESH_CROSSOVER and VWAP/TC/BREAKOUT — use inline calls to handle varied signatures
        if cfg.enable_bull_fresh_crossover and i >= 6:
            result = _check_bull_fresh_crossover(
                i, highs, lows, closes, opens,
                ema_fast_vals, ema_slow_vals, rsi_vals, adx_now, cfg)
            if result is not None:
                matches.append(result)

        if cfg.enable_bull_ema_pullback and regime == "STRONG_BULL":
            result = _check_bull_ema_pullback(i, highs, lows, closes, opens,
                                              ema_fast_vals, ema_slow_vals, rsi_vals, cfg)
            if result is not None:
                matches.append(result)

        if cfg.enable_bull_ema8_touch:
            result = _check_bull_ema8_touch(i, highs, lows, closes, opens,
                                            ema_fast_vals, ema_slow_vals, rsi_vals, cfg)
            if result is not None:
                matches.append(result)

        if cfg.enable_bull_vwap_reclaim and regime != "STRONG_BULL":
            result = _check_bull_vwap_reclaim(i, highs, lows, closes, opens,
                                              ema_fast_vals, ema_slow_vals, rsi_vals, vwap_vals, cfg)
            if result is not None:
                matches.append(result)

        if cfg.enable_bull_reversal_dip:
            result = _check_bull_reversal_dip(i, highs, lows, closes, opens,
                                              ema_fast_vals, ema_slow_vals, rsi_vals, cfg)
            if result is not None:
                matches.append(result)

        if cfg.enable_bull_trend_continuation:
            result = _check_bull_trend_continuation(i, highs, lows, closes, opens,
                                                    ema_fast_vals, ema_slow_vals, rsi_vals, cfg)
            if result is not None:
                matches.append(result)

        if cfg.enable_bull_momentum_breakout and i >= 7:
            mb_lb = 3 if regime == "STRONG_BULL" else 5
            result = _check_bull_momentum_breakout(
                i, highs, lows, closes, opens,
                ema_fast_vals, ema_slow_vals, rsi_vals, adx_now, cfg,
                lookback_days=mb_lb)
            if result is not None:
                matches.append(result)

        if cfg.enable_bull_higher_low:
            result = _check_bull_higher_low(i, highs, lows, closes, opens,
                                            ema_fast_vals, ema_slow_vals, rsi_vals, cfg)
            if result is not None:
                matches.append(result)

        # Score all matches, sort best first, build output list
        scored_live = []
        for sig, sname, fl in matches:
            q = _compute_bull_quality_score(sname, fl, rsi_vals[i], adx_now, vix, regime)
            scored_live.append((sig, sname, fl, q))
        scored_live.sort(key=lambda x: x[3], reverse=True)

        final_matches = []
        for idx, (sig, sname, fl, _q) in enumerate(scored_live[:cfg.max_trades_per_day]):
            if sname in ("BULL_EMA_PULLBACK", "BULL_EMA8_TOUCH", "BULL_TREND_CONTINUATION",
                         "BULL_FRESH_CROSSOVER"):
                sl_b, tgt_b = cfg.sl_pct_bep, cfg.target_pct_bep
            elif sname == "BULL_REVERSAL_DIP":
                sl_b, tgt_b = cfg.sl_pct_brd, cfg.target_pct_brd
            elif sname in ("BULL_VWAP_RECLAIM", "BULL_MOMENTUM_BREAKOUT"):
                sl_b, tgt_b = cfg.sl_pct_bvr, cfg.target_pct_bvr
            else:
                sl_b, tgt_b = cfg.sl_pct_bhl, cfg.target_pct_bhl
            final_matches.append({
                "leg":        idx + 1,
                "direction":  sig,
                "bias":       "BULLISH",
                "bias_strength": 0.80,
                "setup_type": "BULL_PULLBACK",
                "strategy":   sname,
                "sl_pct":     round(sl_b, 4),
                "target_pct": round(tgt_b, 4),
                "lots":       cfg.lots,
                "filter_log": {**fl, "regime": {"value": regime}, "daily_leg": idx + 1},
            })
    else:
        final_matches = []

    signal_date = dates[i]

    return {
        "ok":               True,
        "signal_bar_date":  signal_date.isoformat(),
        "trade_session_date": _date.today().isoformat(),
        "regime":           regime,
        "vix":              round(vix, 2),
        "day_trade_cap":    cfg.max_trades_per_day,
        "raw_matches":      len(final_matches),
        "executable_legs":  final_matches,
        "strategy_filter":  "BULL",
        "engine":           "BULL",
        "breakout_watch": {
            "last_close":   closes[i],
            "ema8":         ema_fast_vals[i],
            "ema21":        ema_slow_vals[i],
            "rsi14":        round(rsi_vals[i], 1),
            "vwap5":        round(vwap_vals[i], 2),
            "prior_5d_high": max(highs[i-5:i]) if i >= 5 else None,
            "prior_5d_low":  min(lows[i-5:i])  if i >= 5 else None,
        },
    }


def run_bull_backtest(
    nifty_daily: pd.DataFrame,
    vix_df: pd.DataFrame,
    cfg: Optional[BullBacktestConfig] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    verbose: bool = False,
    only_strong_bull_days: bool = False,   # True = skip MILD_BULL (used in combined runner)
) -> Dict[str, Any]:
    """
    Run bull backtest on daily Nifty OHLC data.

    Args:
        nifty_daily:         DataFrame with ts, open, high, low, close, volume
        vix_df:              India VIX DataFrame
        cfg:                 BullBacktestConfig (defaults used if None)
        start_date/end_date: Date range (inclusive)
        verbose:             Print per-trade output
        only_strong_bull_days: If True, skip MILD_BULL — used when combined with bear engine
                               so MILD_BULL days are handled by the bear engine's MILD_TREND
    """
    if cfg is None:
        cfg = BullBacktestConfig()

    df = nifty_daily.copy()
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values("ts").reset_index(drop=True)

    # Ensure volume column exists (yfinance may omit it on network errors)
    if "volume" not in df.columns:
        df["volume"] = 1.0

    closes  = df["close"].tolist()
    highs   = df["high"].tolist()
    lows    = df["low"].tolist()
    opens   = df["open"].tolist()
    dates   = df["ts"].dt.date.tolist()

    ema_fast_vals  = _ema(closes, cfg.ema_fast)
    ema_slow_vals  = _ema(closes, cfg.ema_slow)
    ema_trend_vals = _ema(closes, cfg.ema_trend)
    rsi_vals       = _rsi(closes, cfg.rsi_period)
    adx_vals       = _directional_movement(highs, lows, closes, cfg.atr_period)

    # 5-day rolling VWAP (same as bear engine)
    df["tp"]     = (df["high"] + df["low"] + df["close"]) / 3
    df["tp_vol"] = df["tp"] * df["volume"].clip(lower=1)
    df["vol_sum"] = df["volume"].clip(lower=1).rolling(cfg.vwap_lookback, min_periods=1).sum()
    df["vwap"]   = df["tp_vol"].rolling(cfg.vwap_lookback, min_periods=1).sum() / df["vol_sum"]
    vwap_vals = df["vwap"].tolist()

    warmup = max(cfg.ema_trend + 1, cfg.rsi_period + 1, 10)
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
    regime_counts: Dict[str, int] = {r: 0 for r in BULL_REGIME_NAMES}
    strategy_counts: Dict[str, int] = {}
    skip_reasons: Dict[str, int] = {}
    start_ym = (dates[start_idx].year, dates[start_idx].month)
    last_trade_was_loss = False
    last_exit_direction: Optional[str] = None

    if verbose:
        print(f"\n{'='*72}")
        print(f" BULL ENGINE BACKTEST — {end_idx - start_idx} trading days")
        print(f" Range: {dates[start_idx]} → {dates[min(end_idx-1, len(dates)-1)]}")
        print(f" Capital: ₹{cfg.capital:,.0f} | Lots: {cfg.lots} | Lot size: {cfg.lot_size}")
        print(f" Strategies: BULL_EMA_PULLBACK (pullback), BULL_VWAP_RECLAIM (reclaim), BULL_TREND_CONTINUATION (strong-bull only)")
        print(f"{'='*72}\n")

    # Momentum strategies: signal detected at open (same as bear engine).
    # Enter at opens[i], simulate exits on same day's highs/lows/close (like bear engine).
    # Strategies require low > EMA8 (no deep pullback) so intraday dip < 22% option SL.
    for i in range(start_idx, end_idx):
        trade_date = dates[i]
        vix = get_vix_for_date(vix_df, trade_date)

        if vix > cfg.vix_max:
            skip_reasons["vix_too_high"] = skip_reasons.get("vix_too_high", 0) + 1
            continue

        peak_equity = max(peak_equity, capital)
        dd_pct = (peak_equity - capital) / peak_equity if peak_equity > 0 else 0.0

        if consecutive_losses >= cfg.max_consecutive_losses:
            consecutive_losses = max(0, consecutive_losses - 1)
            skip_reasons["consec_loss"] = skip_reasons.get("consec_loss", 0) + 1
            continue

        regime = _classify_bull_regime(
            i, closes, ema_fast_vals, ema_slow_vals, ema_trend_vals,
            adx_vals, rsi_vals, vix, cfg,
        )
        regime_counts[regime] = regime_counts.get(regime, 0) + 1

        if regime == "NO_EDGE":
            skip_reasons["no_bull_regime"] = skip_reasons.get("no_bull_regime", 0) + 1
            continue

        if only_strong_bull_days and regime == "MILD_BULL":
            skip_reasons["mild_bull_skipped"] = skip_reasons.get("mild_bull_skipped", 0) + 1
            continue

        rsi = rsi_vals[i]

        # ── Scan all strategies ───────────────────────────────────────────
        # Architecture: pullback strategies detect the signal on the PRIOR bar (i-1)
        # and enter at TODAY's open (i). This avoids the option SL being hit during
        # the same-day pullback — we only enter AFTER the bounce is confirmed at prior close.
        #
        # Momentum/continuation strategies detect and enter on the SAME day (i), because
        # their conditions (low stays above EMA8, green candle) mean no intraday SL risk.
        matches: List[Tuple[str, str, dict]] = []

        # ── PRIOR-DAY DETECTION (enter today after signal confirmed at prior close) ──

        # EMA_PULLBACK: prior day's low tested EMA21 zone and bounced → enter today
        # STRONG_BULL only (on MILD_BULL, EMA21 touch often signals trend weakening)
        if cfg.enable_bull_ema_pullback and i >= 5:
            prev_regime = _classify_bull_regime(
                i-1, closes, ema_fast_vals, ema_slow_vals, ema_trend_vals,
                adx_vals, rsi_vals, vix, cfg)
            if prev_regime == "STRONG_BULL":
                r = _check_bull_ema_pullback(
                    i-1, highs, lows, closes, opens,
                    ema_fast_vals, ema_slow_vals, rsi_vals, cfg)
                if r:
                    matches.append(r)

        # EMA8_TOUCH: prior day's low touched EMA8 zone and closed above → enter today
        # Works on both regimes; EMA21 must be rising to confirm trend not stalling
        if cfg.enable_bull_ema8_touch and i >= 5:
            r = _check_bull_ema8_touch(
                i-1, highs, lows, closes, opens,
                ema_fast_vals, ema_slow_vals, rsi_vals, cfg)
            if r:
                matches.append(r)

        # REVERSAL_DIP: prior day opened down in bull trend but recovered above EMA8 → enter today
        if cfg.enable_bull_reversal_dip and i >= 3:
            r = _check_bull_reversal_dip(
                i-1, highs, lows, closes, opens,
                ema_fast_vals, ema_slow_vals, rsi_vals, cfg)
            if r:
                matches.append(r)

        # ── SAME-DAY DETECTION (enter today, conditions confirmed at open or intraday) ──

        # FRESH_CROSSOVER: EMA8 crossed above EMA21 within last 4 bars — post-bear recovery entry
        # Does NOT require EMA21 slope (which TC requires) — EMA21 is still declining on fresh crossovers
        if cfg.enable_bull_fresh_crossover and i >= 6:
            r = _check_bull_fresh_crossover(
                i, highs, lows, closes, opens,
                ema_fast_vals, ema_slow_vals, rsi_vals, adx_vals[i], cfg)
            if r:
                matches.append(r)

        # VWAP_RECLAIM: MILD_BULL only — on STRONG_BULL, VWAP dip is a warning not a buy (0% WR tested)
        if cfg.enable_bull_vwap_reclaim and regime != "STRONG_BULL":
            r = _check_bull_vwap_reclaim(
                i, highs, lows, closes, opens,
                ema_fast_vals, ema_slow_vals, rsi_vals, vwap_vals, cfg)
            if r:
                matches.append(r)

        # TREND_CONTINUATION: both regimes — low stays above EMA8 (no intraday SL risk)
        # STRONG_BULL quality score (25) vs MILD_BULL (15) naturally tiers the quality gate
        if cfg.enable_bull_trend_continuation:
            r = _check_bull_trend_continuation(
                i, highs, lows, closes, opens,
                ema_fast_vals, ema_slow_vals, rsi_vals, cfg)
            if r:
                matches.append(r)

        # MOMENTUM_BREAKOUT: close > prior N-day high — dip-and-rip, captures days TC misses
        # STRONG_BULL: 3-day lookback (price makes new highs frequently in strong trends)
        # MILD_BULL: 5-day lookback (stricter — prevent triggering on minor bounces in weaker trend)
        if cfg.enable_bull_momentum_breakout and i >= 7:
            mb_lookback = 3 if regime == "STRONG_BULL" else 5
            r = _check_bull_momentum_breakout(
                i, highs, lows, closes, opens,
                ema_fast_vals, ema_slow_vals, rsi_vals, adx_vals[i], cfg,
                lookback_days=mb_lookback)
            if r:
                matches.append(r)

        if cfg.enable_bull_higher_low:
            r = _check_bull_higher_low(
                i, highs, lows, closes, opens,
                ema_fast_vals, ema_slow_vals, rsi_vals, cfg)
            if r:
                matches.append(r)

        if not matches:
            skip_reasons["no_bull_signal"] = skip_reasons.get("no_bull_signal", 0) + 1
            continue

        # ── Quality scoring → pick best ───────────────────────────────────
        scored = []
        for sig, sname, fl in matches:
            q = _compute_bull_quality_score(sname, fl, rsi, adx_vals[i], vix, regime)
            scored.append((sig, sname, fl, q))
        scored.sort(key=lambda x: x[3], reverse=True)

        in_first_month = (trade_date.year, trade_date.month) == start_ym
        daily_realized_pnl = 0.0
        lost_directions_today: set = set()

        for leg_idx, (signal, strategy_name, filter_log, quality) in enumerate(scored[:cfg.max_trades_per_day]):
            filter_log = dict(filter_log)
            filter_log["regime"] = {"value": regime}
            filter_log["quality_score"] = quality

            # Quality gate
            eff_min = cfg.min_quality_score - (cfg.strong_bull_quality_discount if regime == "STRONG_BULL" else 0)
            if cfg.enable_quality_gate and quality < eff_min:
                skip_reasons["low_quality"] = skip_reasons.get("low_quality", 0) + 1
                continue

            # Daily loss cap
            if cfg.enable_daily_loss_cap:
                if daily_realized_pnl < -(capital * cfg.max_daily_loss_pct):
                    skip_reasons["daily_loss_cap"] = skip_reasons.get("daily_loss_cap", 0) + 1
                    break

            # Direction correlation block
            if cfg.enable_direction_correlation_block and signal in lost_directions_today:
                skip_reasons["direction_block"] = skip_reasons.get("direction_block", 0) + 1
                continue

            # Skip-after-loss
            if cfg.enable_skip_after_loss and last_trade_was_loss and last_exit_direction == signal:
                if quality < cfg.skip_after_loss_min_quality:
                    skip_reasons["skip_after_loss"] = skip_reasons.get("skip_after_loss", 0) + 1
                    continue

            # Lot sizing
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

            effective_lots = max(1, min(effective_lots, cfg.max_lots_cap))
            if leg_idx == 1:
                effective_lots = max(1, int(round(effective_lots * cfg.second_trade_lot_fraction)))

            # Contextual SL
            if strategy_name in ("BULL_EMA_PULLBACK", "BULL_EMA8_TOUCH", "BULL_TREND_CONTINUATION",
                                 "BULL_FRESH_CROSSOVER"):
                # Fresh crossover: same wider SL as TC — volatility is higher in early trend days
                sl_base, tgt_base = cfg.sl_pct_bep, cfg.target_pct_bep
            elif strategy_name == "BULL_REVERSAL_DIP":
                sl_base, tgt_base = cfg.sl_pct_brd, cfg.target_pct_brd
            elif strategy_name in ("BULL_VWAP_RECLAIM", "BULL_MOMENTUM_BREAKOUT"):
                # Breakout: tighter SL since trend is established — breakout fails fast or works
                sl_base, tgt_base = cfg.sl_pct_bvr, cfg.target_pct_bvr
            else:
                sl_base, tgt_base = cfg.sl_pct_bhl, cfg.target_pct_bhl

            if cfg.enable_contextual_sl:
                if quality >= cfg.sl_aplus_quality_min:
                    sl_mult = cfg.sl_mult_aplus
                elif quality >= cfg.sl_strong_quality_min:
                    sl_mult = cfg.sl_mult_strong
                else:
                    sl_mult = cfg.sl_mult_normal
            else:
                sl_mult = 1.0

            sl_pct = sl_base * sl_mult
            tgt_pct = tgt_base

            # Simulate on same day: enter at open, exits within day's range (like bear engine)
            trade = _simulate_bull_option_trade(
                spot_entry=opens[i],
                direction=signal,
                trade_date=trade_date,
                vix=vix,
                day_high=highs[i],
                day_low=lows[i],
                day_close=closes[i],
                sl_pct=sl_pct,
                target_pct=tgt_pct,
                cfg=cfg,
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
            daily_realized_pnl += net
            if net > 0:
                consecutive_losses = 0
                last_trade_was_loss = False
            else:
                consecutive_losses += 1
                last_trade_was_loss = True
                lost_directions_today.add(signal)
            last_exit_direction = signal

            if verbose:
                sign = "+" if net >= 0 else ""
                print(
                    f"  [{trade_date}] [{leg_idx+1}] {regime:<12} {strategy_name:<22} {signal:4s} | "
                    f"E={trade['entry_price']:.0f} X={trade['exit_price']:.0f} | "
                    f"{sign}₹{net:>7,.0f} | {trade['exit_reason']:10s} | L={effective_lots} V={vix:.0f} | ₹{capital:>10,.0f}"
                )

    metrics = compute_metrics(all_trades, cfg.capital)

    if verbose:
        total_days = end_idx - start_idx
        wins = sum(1 for t in all_trades if t["net_pnl"] > 0)
        print(f"\n{'='*72}")
        print(f" BULL ENGINE SUMMARY — {len(all_trades)} trades ({wins}W/{len(all_trades)-wins}L)")
        print(f" Capital: ₹{cfg.capital:,.0f} → ₹{capital:,.0f}  ({(capital-cfg.capital)/cfg.capital*100:+.1f}%)")
        print(f" Strategies: {strategy_counts}")
        print(f" Regimes: {regime_counts}")
        print(f" Skipped: {skip_reasons}")
        print(f"{'='*72}\n")

    return {
        "trades": all_trades,
        "metrics": metrics,
        "config": cfg.__dict__,
        "start_date": dates[start_idx].isoformat() if start_idx < len(dates) else None,
        "end_date": dates[min(end_idx - 1, len(dates) - 1)].isoformat() if end_idx > 0 else None,
        "timeframe": "daily_bull",
        "regime_counts": regime_counts,
        "strategy_counts": strategy_counts,
        "skip_reasons": skip_reasons,
    }
