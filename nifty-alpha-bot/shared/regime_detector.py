"""
Regime detector for live trading — mirrors the daily backtest engine logic.

Uses the last N candles (5-min or daily) to classify current market regime
as TRENDING, RANGING, or VOLATILE. This drives strategy selection in the live bot.

The regime determines which strategies get priority:
  TRENDING  → ORB > EMA_PULLBACK > VWAP_RECLAIM
  RANGING   → VWAP_RECLAIM > EMA_PULLBACK > MEAN_REVERSION > RANGE_FADE
  VOLATILE  → VWAP_RECLAIM > MEAN_REVERSION (tighter SL, smaller size)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RegimeConfig:
    adx_trending_threshold: float = 0.30
    atr_volatile_multiplier: float = 1.8
    vix_max: float = 28.0
    lookback_period: int = 14
    atr_sma_period: int = 50


STRATEGY_PRIORITY = {
    "TRENDING": ["ORB", "EMA_PULLBACK", "VWAP_RECLAIM", "RELAXED_ORB"],
    "RANGING":  ["VWAP_RECLAIM", "EMA_PULLBACK", "MEAN_REVERSION", "RANGE_FADE", "RELAXED_ORB"],
    "VOLATILE": ["VWAP_RECLAIM", "MEAN_REVERSION", "RANGE_FADE"],
}

SL_TARGET_MAP = {
    "ORB":             (0.30, 0.65),
    "VWAP_RECLAIM":    (0.30, 0.65),
    "MEAN_REVERSION":  (0.20, 0.50),
    "RELAXED_ORB":     (0.30, 0.55),
    "RANGE_FADE":      (0.25, 0.50),
    "EMA_PULLBACK":    (0.35, 0.65),
}


def _ema(series: List[float], period: int) -> List[float]:
    if not series:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [series[0]]
    for v in series[1:]:
        out.append(v * alpha + out[-1] * (1 - alpha))
    return out


def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
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


def _adx_proxy(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    """Ratio of net directional move to total range over a window. >0.30 = trending."""
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


def _rsi(closes: List[float], period: int = 14) -> List[float]:
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


@dataclass
class RegimeResult:
    regime: str
    adx_proxy: float
    atr_current: float
    atr_avg: float
    atr_ratio: float
    vix: float
    rsi: float
    ema_fast: float
    ema_slow: float
    strategy_priority: List[str]
    sl_target: Dict[str, Tuple[float, float]]
    detail: str
    strong_trend_override: bool = False  # VOLATILE but strong trend detected — trend strategies allowed


def detect_strong_trend_in_volatile(
    candles: List[Dict[str, Any]],
) -> bool:
    """
    Returns True when market shows strong trending characteristics even in VOLATILE regime.

    Criteria (ALL must be true):
      - EMA8 > EMA21 > EMA50 (bullish) OR EMA8 < EMA21 < EMA50 (bearish)
      - Price above VWAP proxy (bull) or below VWAP proxy (bear)
      - At least 2 of first 3 candles directional (match EMA stack direction)
      - No deep pullback through EMA21 in last 8 candles
    """
    if len(candles) < 55:
        return False

    closes = [float(c["close"]) for c in candles]

    ema8_vals = _ema(closes, 8)
    ema21_vals = _ema(closes, 21)
    ema50_vals = _ema(closes, 50)

    if len(ema50_vals) < 50:
        return False

    ema8 = ema8_vals[-1]
    ema21 = ema21_vals[-1]
    ema50 = ema50_vals[-1]
    current_close = closes[-1]

    # 1. Triple EMA stack
    bullish_stack = ema8 > ema21 > ema50
    bearish_stack = ema8 < ema21 < ema50
    if not (bullish_stack or bearish_stack):
        return False

    # 2. Price vs VWAP (simple 20-period mean as proxy when volume unavailable)
    vwap_proxy = sum(closes[-20:]) / 20
    if bullish_stack and current_close <= vwap_proxy:
        return False
    if bearish_stack and current_close >= vwap_proxy:
        return False

    # 3. First 3 candles directional (2 of 3 must match EMA stack)
    if len(candles) >= 3:
        first3 = candles[:3]
        if bullish_stack:
            directional = sum(1 for c in first3 if float(c["close"]) > float(c["open"])) >= 2
        else:
            directional = sum(1 for c in first3 if float(c["close"]) < float(c["open"])) >= 2
        if not directional:
            return False

    # 4. No deep pullback through EMA21 in last 8 candles
    recent = candles[-8:]
    if bullish_stack:
        deep_pullback = any(float(c["low"]) < ema21 * 0.998 for c in recent)
    else:
        deep_pullback = any(float(c["high"]) > ema21 * 1.002 for c in recent)
    if deep_pullback:
        return False

    return True


def detect_regime(
    candles: List[Dict[str, Any]],
    vix: float = 15.0,
    cfg: Optional[RegimeConfig] = None,
) -> RegimeResult:
    """
    Detect market regime from recent candle history.

    Works with both 5-min intraday candles and daily candles.
    For live use with 5-min candles, pass the last ~70+ candles.
    """
    if cfg is None:
        cfg = RegimeConfig()

    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]

    adx_vals = _adx_proxy(highs, lows, closes, cfg.lookback_period)
    atr_vals = _atr(highs, lows, closes, cfg.lookback_period)
    rsi_vals = _rsi(closes, 14)
    ema_fast_vals = _ema(closes, 5)
    ema_slow_vals = _ema(closes, 13)

    adx = adx_vals[-1] if adx_vals else 0.5
    atr_current = atr_vals[-1] if atr_vals else 0.0
    atr_avg = sum(atr_vals[-cfg.atr_sma_period:]) / max(1, len(atr_vals[-cfg.atr_sma_period:])) if atr_vals else 1.0
    rsi = rsi_vals[-1] if rsi_vals else 50.0
    ema_f = ema_fast_vals[-1] if ema_fast_vals else closes[-1]
    ema_s = ema_slow_vals[-1] if ema_slow_vals else closes[-1]

    atr_ratio = atr_current / atr_avg if atr_avg > 0 else 1.0

    strong_trend_override = False
    if vix > cfg.vix_max or atr_ratio > cfg.atr_volatile_multiplier:
        regime = "VOLATILE"
        # Check if this volatile day is actually a strong trend day
        strong_trend_override = detect_strong_trend_in_volatile(candles)
        if strong_trend_override:
            # Allow trend strategies despite volatility
            priority = ["EMA_PULLBACK", "MOMENTUM_BREAKOUT", "ORB", "VWAP_RECLAIM"]
        else:
            priority = STRATEGY_PRIORITY["VOLATILE"]
    elif adx >= cfg.adx_trending_threshold:
        regime = "TRENDING"
        priority = STRATEGY_PRIORITY[regime]
    else:
        regime = "RANGING"
        priority = STRATEGY_PRIORITY[regime]

    detail = (
        f"ADX_proxy={adx:.3f} (thresh={cfg.adx_trending_threshold}), "
        f"ATR={atr_current:.1f}, ATR_ratio={atr_ratio:.2f} (volatile>{cfg.atr_volatile_multiplier}), "
        f"VIX={vix:.1f} (max={cfg.vix_max}), RSI={rsi:.1f}, "
        f"EMA5={ema_f:.1f} vs EMA13={ema_s:.1f}"
        + (" [STRONG_TREND_OVERRIDE]" if strong_trend_override else "")
    )

    return RegimeResult(
        regime=regime,
        adx_proxy=round(adx, 4),
        atr_current=round(atr_current, 2),
        atr_avg=round(atr_avg, 2),
        atr_ratio=round(atr_ratio, 3),
        vix=vix,
        rsi=round(rsi, 1),
        ema_fast=round(ema_f, 2),
        ema_slow=round(ema_s, 2),
        strategy_priority=priority,
        sl_target=SL_TARGET_MAP,
        detail=detail,
        strong_trend_override=strong_trend_override,
    )
