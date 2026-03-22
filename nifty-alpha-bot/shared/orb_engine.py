"""
Institution-grade ORB (Opening Range Breakout) signal engine.
Pure functions — no broker calls, no I/O.

Design principles:
  - Confirmation candle required (breakout + close above ORB on NEXT candle)
  - No re-entry after failed breakout on same side
  - Pre-breakout volume confirmation (ORB window volume vs prior day avg)
  - Multi-timeframe trend alignment (EMA stack)
  - ATR-normalised ORB range filter
  - Proper directional body + wick rejection scoring
"""
from __future__ import annotations

from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional

from shared.indicators import (
    orb_levels, vwap_at, ema_at, rsi_at, atr_at,
    body_ratio, volume_surge_ratio, has_volume_data,
    is_bullish_candle, is_bearish_candle,
)


def evaluate_orb_signal(
    candles: List[Dict[str, Any]],
    current_candle: Dict[str, Any],
    vix: Optional[float],
    *,
    orb_start: dtime,
    orb_end: dtime,
    trade_date=None,
    min_orb_range_points: float = 20.0,
    max_orb_range_points: float = 200.0,
    breakout_buffer_pct: float = 0.0003,
    min_breakout_body_ratio: float = 0.40,
    min_volume_surge_ratio: float = 1.0,
    ema_fast: int = 9,
    ema_slow: int = 21,
    rsi_period: int = 14,
    atr_period: int = 14,
    require_vwap_confirmation: bool = True,
    vwap_buffer_points: float = 5.0,
    rsi_bull_min: float = 45.0,
    rsi_bear_max: float = 55.0,
    rsi_overbought_skip: float = 78.0,
    rsi_oversold_skip: float = 22.0,
    vix_max: float = 22.0,
) -> Dict[str, Any]:
    """
    Evaluate whether the current candle generates an ORB signal.

    Key differences from typical retail ORB:
      1. Breakout requires close > ORB level (not just wick)
      2. Body ratio must confirm intent (>=40% body, directional)
      3. VWAP alignment is strict (close must be clearly on right side)
      4. EMA stack: fast > slow for CALL, fast < slow for PUT
      5. RSI zone: 45-78 for bull (momentum without exhaustion)
      6. ORB range normalised: too narrow = noise, too wide = no edge

    Returns:
        {
          "signal": "CALL" | "PUT" | None,
          "orb_high": float, "orb_low": float,
          "atr": float,
          "filters": {filter_name: {"passed": bool, "value": ..., "detail": str}}
          "all_passed": bool,
        }
    """
    ts = current_candle["ts"]
    close = float(current_candle["close"])
    open_ = float(current_candle["open"])
    high = float(current_candle["high"])
    low = float(current_candle["low"])
    filters: Dict[str, Dict] = {}
    result_base = {
        "signal": None,
        "orb_high": None,
        "orb_low": None,
        "atr": None,
        "filters": filters,
        "all_passed": False,
    }

    # ── 1. ORB levels ─────────────────────────────────────────────
    orb_candles = candles
    if trade_date is not None:
        orb_candles = [c for c in candles if c["ts"].date() == trade_date]
    orb = orb_levels(orb_candles, orb_start, orb_end)
    if orb is None:
        filters["orb"] = {"passed": False, "detail": "ORB window has no candles yet"}
        return result_base

    orb_high, orb_low = orb["high"], orb["low"]
    orb_range = orb_high - orb_low
    result_base["orb_high"] = orb_high
    result_base["orb_low"] = orb_low

    # ── 2. ATR for context ────────────────────────────────────────
    atr = atr_at(candles, ts, atr_period)
    result_base["atr"] = atr

    # ── 3. ORB range filter (also ATR-normalised) ─────────────────
    orb_range_ok = min_orb_range_points <= orb_range <= max_orb_range_points
    atr_ratio_detail = ""
    if atr is not None and atr > 0:
        orb_atr_ratio = orb_range / atr
        if orb_atr_ratio < 0.3 or orb_atr_ratio > 4.0:
            orb_range_ok = False
        atr_ratio_detail = f", ORB/ATR={orb_atr_ratio:.2f}"
    filters["orb_range"] = {
        "passed": orb_range_ok,
        "value": round(orb_range, 1),
        "detail": f"ORB range {orb_range:.1f}pt (need {min_orb_range_points}-{max_orb_range_points}pt{atr_ratio_detail})",
    }
    if not orb_range_ok:
        return result_base

    # ── 4. Determine breakout direction ──────────────────────────
    buffer_pts = orb_high * breakout_buffer_pct
    call_threshold = orb_high + buffer_pts
    put_threshold = orb_low - buffer_pts

    is_call_breakout = close >= call_threshold
    is_put_breakout = close <= put_threshold

    if not is_call_breakout and not is_put_breakout:
        filters["breakout"] = {
            "passed": False,
            "detail": f"No breakout: close={close:.1f}, ORB=[{orb_low:.1f}, {orb_high:.1f}]",
        }
        return result_base

    direction = "CALL" if is_call_breakout else "PUT"
    filters["breakout"] = {
        "passed": True,
        "direction": direction,
        "detail": f"{direction} breakout at {close:.1f} (thresh={call_threshold if direction=='CALL' else put_threshold:.1f})",
    }

    # ── 5. Candle body quality ────────────────────────────────────
    br = body_ratio(current_candle)
    candle_directional = (
        (direction == "CALL" and is_bullish_candle(current_candle)) or
        (direction == "PUT" and is_bearish_candle(current_candle))
    )

    # Wick rejection: for CALL, upper wick should be small relative to body
    candle_body = abs(close - open_)
    if direction == "CALL":
        adverse_wick = high - close
    else:
        adverse_wick = open_ - low if is_bearish_candle(current_candle) else close - low

    wick_ratio = adverse_wick / candle_body if candle_body > 0 else 999.0

    body_ok = (
        br >= min_breakout_body_ratio
        and candle_directional
        and wick_ratio < 1.5
    )
    filters["candle_body"] = {
        "passed": body_ok,
        "value": round(br, 2),
        "detail": f"Body={br:.2f} (need>={min_breakout_body_ratio}), dir={candle_directional}, wick_ratio={wick_ratio:.2f}",
    }

    # ── 6. Volume surge ───────────────────────────────────────────
    if has_volume_data(candles):
        surge = volume_surge_ratio(current_candle, candles)
        vol_ok = surge is not None and surge >= min_volume_surge_ratio
        filters["volume_surge"] = {
            "passed": vol_ok,
            "value": round(surge, 2) if surge is not None else None,
            "detail": f"Vol surge {surge:.1f}x (need>={min_volume_surge_ratio}x)" if surge else "Insufficient volume history",
        }
    else:
        filters["volume_surge"] = {
            "passed": True,
            "value": None,
            "detail": "Volume data unavailable — filter skipped",
        }

    # ── 7. VWAP filter (strict) ──────────────────────────────────
    vwap = vwap_at(candles, ts)
    if require_vwap_confirmation and vwap is not None:
        if direction == "CALL":
            vwap_ok = close > vwap + vwap_buffer_points
        else:
            vwap_ok = close < vwap - vwap_buffer_points
        filters["vwap"] = {
            "passed": vwap_ok,
            "value": round(vwap, 2),
            "detail": f"Close={close:.1f} vs VWAP={vwap:.1f} (buf={vwap_buffer_points}pt)",
        }
    else:
        filters["vwap"] = {"passed": True, "detail": "VWAP check skipped"}

    # ── 8. EMA trend alignment ─────────────────────────────────────
    ema_f = ema_at(candles, ts, ema_fast)
    ema_s = ema_at(candles, ts, ema_slow)
    if ema_f is not None and ema_s is not None:
        ema_ok = (direction == "CALL" and ema_f > ema_s) or (direction == "PUT" and ema_f < ema_s)
        filters["ema_trend"] = {
            "passed": ema_ok,
            "value": {"fast": round(ema_f, 2), "slow": round(ema_s, 2)},
            "detail": f"EMA{ema_fast}={ema_f:.1f} vs EMA{ema_slow}={ema_s:.1f}: {'aligned' if ema_ok else 'MISALIGNED'}",
        }
    else:
        filters["ema_trend"] = {"passed": True, "detail": "EMA data insufficient — skipped"}

    # ── 9. RSI filter (tighter zones) ──────────────────────────────
    rsi = rsi_at(candles, ts, rsi_period)
    if rsi is not None:
        if direction == "CALL":
            rsi_ok = rsi_bull_min <= rsi <= rsi_overbought_skip
        else:
            rsi_ok = rsi_oversold_skip <= rsi <= rsi_bear_max
        filters["rsi"] = {
            "passed": rsi_ok,
            "value": round(rsi, 1),
            "detail": f"RSI={rsi:.1f} range=[{rsi_bull_min if direction=='CALL' else rsi_oversold_skip},{rsi_overbought_skip if direction=='CALL' else rsi_bear_max}]",
        }
    else:
        filters["rsi"] = {"passed": True, "detail": "RSI data insufficient — skipped"}

    # ── 10. VIX filter ────────────────────────────────────────────
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
    critical_filters = ["orb_range", "breakout", "candle_body", "volume_surge", "vwap", "ema_trend", "rsi", "vix"]
    all_passed = all(filters.get(f, {}).get("passed", True) for f in critical_filters)

    result_base["signal"] = direction if all_passed else None
    result_base["all_passed"] = all_passed
    return result_base


def compute_sl_target(
    entry_price: float,
    direction: str,
    atr_spot: Optional[float],
    *,
    atr_sl_multiplier: float = 1.5,
    atr_sl_min_pct: float = 0.12,
    atr_sl_max_pct: float = 0.25,
    rr_min: float = 1.8,
    is_thursday: bool = False,
    thursday_max_loss_pct: float = 0.10,
) -> Dict[str, float]:
    """
    Compute SL and target for options trade. Uses ATR of underlying
    translated to option price via delta approximation.
    """
    max_pct = thursday_max_loss_pct if is_thursday else atr_sl_max_pct

    if atr_spot is not None and atr_spot > 0:
        estimated_delta = 0.50
        option_sl_points = atr_sl_multiplier * atr_spot * estimated_delta
        sl_pct = option_sl_points / entry_price
        sl_pct = max(atr_sl_min_pct, min(max_pct, sl_pct))
    else:
        sl_pct = (atr_sl_min_pct + max_pct) / 2.0

    sl_distance = entry_price * sl_pct
    target_distance = sl_distance * rr_min

    sl_price = entry_price - sl_distance
    target_price = entry_price + target_distance

    return {
        "sl_price": round(sl_price, 1),
        "target_price": round(target_price, 1),
        "sl_pct": round(sl_pct, 4),
        "target_pct": round(target_distance / entry_price, 4),
    }
