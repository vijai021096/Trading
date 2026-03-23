"""
Momentum Breakout strategy — captures explosive directional moves.

Setup:
  - Price closes above/below the N-candle range (default: 20 candles = 100 min)
  - Strong breakout candle: body ratio > 50%, directional
  - RSI shows momentum (55-78 for bull, 22-45 for bear) — not overbought
  - Volume surge above average
  - Close on correct side of VWAP

Best for: STRONG_BULL / STRONG_BEAR days where price is making sustained
          directional moves. Fires on morning sessions (9:30–12:00) when
          momentum is freshest.

NOT suitable for: NEUTRAL or low-conviction days — false breakouts common.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from shared.indicators import (
    rsi_at, atr_at, vwap_at, ema_at,
    body_ratio, has_volume_data, volume_surge_ratio,
    is_bullish_candle, is_bearish_candle,
)


def evaluate_momentum_breakout_signal(
    candles: List[Dict[str, Any]],
    current_idx: int,
    vix: Optional[float],
    *,
    breakout_lookback: int = 20,
    min_body_ratio: float = 0.50,
    rsi_period: int = 14,
    atr_period: int = 14,
    rsi_bull_min: float = 55.0,
    rsi_bull_max: float = 78.0,
    rsi_bear_min: float = 22.0,
    rsi_bear_max: float = 45.0,
    vix_max: float = 28.0,
    min_volume_surge_ratio: float = 1.3,
    ema_fast: int = 9,
    ema_slow: int = 21,
) -> Dict[str, Any]:
    """
    Fires when price closes above/below the last N-candle range with strong momentum.

    Returns:
        {"signal": "CALL"|"PUT"|None, "atr": float, "filters": {...}, "all_passed": bool}
    """
    filters: Dict[str, Dict] = {}
    result_base = {"signal": None, "atr": None, "filters": filters, "all_passed": False}

    if current_idx < breakout_lookback + 2:
        filters["data"] = {"passed": False, "detail": f"Need {breakout_lookback + 2} candles, have {current_idx}"}
        return result_base

    current = candles[current_idx]
    ts = current["ts"]
    close = float(current["close"])

    # ── 1. Breakout of N-candle range ────────────────────────────
    lookback = candles[current_idx - breakout_lookback:current_idx]
    recent_high = max(float(c["high"]) for c in lookback)
    recent_low  = min(float(c["low"])  for c in lookback)

    bull_break = close > recent_high
    bear_break = close < recent_low

    if not bull_break and not bear_break:
        filters["breakout"] = {
            "passed": False,
            "detail": f"No breakout: close={close:.1f}, range=[{recent_low:.1f}, {recent_high:.1f}]",
        }
        return result_base

    direction = "CALL" if bull_break else "PUT"
    breakout_mag = (close - recent_high) if bull_break else (recent_low - close)
    filters["breakout"] = {
        "passed": True,
        "direction": direction,
        "value": round(breakout_mag, 1),
        "detail": (
            f"{direction}: close={close:.1f} beyond "
            f"{'high' if direction == 'CALL' else 'low'}="
            f"{recent_high if direction == 'CALL' else recent_low:.1f} "
            f"(+{breakout_mag:.1f}pt)"
        ),
    }

    # ── 2. EMA trend must align with breakout direction ───────────
    ema_f = ema_at(candles, ts, ema_fast)
    ema_s = ema_at(candles, ts, ema_slow)
    if ema_f is not None and ema_s is not None:
        ema_aligned = (
            (direction == "CALL" and ema_f > ema_s) or
            (direction == "PUT"  and ema_f < ema_s)
        )
        filters["ema_trend"] = {
            "passed": ema_aligned,
            "value": {"fast": round(ema_f, 2), "slow": round(ema_s, 2)},
            "detail": f"EMA{ema_fast}={ema_f:.1f} vs EMA{ema_slow}={ema_s:.1f}: {'aligned' if ema_aligned else 'COUNTER-TREND — skip'}",
        }
        if not ema_aligned:
            return result_base
    else:
        filters["ema_trend"] = {"passed": True, "detail": "EMA insufficient — skipped"}

    # ── 3. Candle body quality ────────────────────────────────────
    br = body_ratio(current)
    directional = (
        (direction == "CALL" and is_bullish_candle(current)) or
        (direction == "PUT"  and is_bearish_candle(current))
    )
    body_ok = br >= min_body_ratio and directional
    filters["candle_body"] = {
        "passed": body_ok,
        "value": round(br, 2),
        "detail": f"Body={br:.2f} (need>={min_body_ratio}), directional={directional}",
    }
    if not body_ok:
        return result_base

    # ── 4. ATR (for sizing context) ──────────────────────────────
    atr = atr_at(candles, ts, atr_period)
    result_base["atr"] = atr

    # ── 5. RSI must show momentum — not overbought/oversold ───────
    rsi = rsi_at(candles, ts, rsi_period)
    if rsi is not None:
        if direction == "CALL":
            rsi_ok = rsi_bull_min <= rsi <= rsi_bull_max
            rsi_range = f"{rsi_bull_min}-{rsi_bull_max}"
        else:
            rsi_ok = rsi_bear_min <= rsi <= rsi_bear_max
            rsi_range = f"{rsi_bear_min}-{rsi_bear_max}"
        filters["rsi"] = {
            "passed": rsi_ok,
            "value": round(rsi, 1),
            "detail": f"RSI={rsi:.1f} (momentum zone: {rsi_range})",
        }
    else:
        filters["rsi"] = {"passed": True, "detail": "RSI insufficient — skipped"}

    # ── 6. VWAP — close must be on correct side ──────────────────
    vwap = vwap_at(candles, ts)
    if vwap is not None:
        vwap_ok = (
            (direction == "CALL" and close > vwap) or
            (direction == "PUT"  and close < vwap)
        )
        filters["vwap"] = {
            "passed": vwap_ok,
            "value": round(vwap, 2),
            "detail": (
                f"Close={close:.1f} {'above' if close > vwap else 'below'} VWAP={vwap:.1f}: "
                f"{'OK' if vwap_ok else 'WRONG SIDE — counter-trend'}"
            ),
        }
    else:
        filters["vwap"] = {"passed": True, "detail": "VWAP unavailable — skipped"}

    # ── 7. Volume surge ───────────────────────────────────────────
    if has_volume_data(candles[max(0, current_idx - 20):current_idx]):
        surge = volume_surge_ratio(current, candles[:current_idx])
        vol_ok = surge is not None and surge >= min_volume_surge_ratio
        filters["volume_surge"] = {
            "passed": vol_ok,
            "value": round(surge, 2) if surge is not None else None,
            "detail": (
                f"Vol surge {surge:.1f}x (need>={min_volume_surge_ratio}x)"
                if surge else "Insufficient history"
            ),
        }
    else:
        filters["volume_surge"] = {"passed": True, "detail": "Volume data unavailable — skipped"}

    # ── 8. VIX guard ─────────────────────────────────────────────
    if vix is not None:
        vix_ok = vix <= vix_max
        filters["vix"] = {
            "passed": vix_ok,
            "value": round(vix, 2),
            "detail": f"VIX={vix:.1f} (max={vix_max})",
        }
    else:
        filters["vix"] = {"passed": True, "detail": "VIX unavailable — skipped"}

    # ── Final decision ────────────────────────────────────────────
    critical = ["breakout", "ema_trend", "candle_body", "rsi", "vwap", "volume_surge", "vix"]
    all_passed = all(filters.get(f, {}).get("passed", True) for f in critical)
    result_base["signal"] = direction if all_passed else None
    result_base["all_passed"] = all_passed
    return result_base
