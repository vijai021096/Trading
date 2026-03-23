"""
EMA Pullback strategy — captures trend continuation trades after a pullback.

Setup:
  - Clear trend: EMA9 > EMA21 (CALL) or EMA9 < EMA21 (PUT)
  - Price recently pulled back and touched/approached EMA21
  - Current candle bounces off EMA21 with directional body
  - Price above VWAP (CALL) or below VWAP (PUT) — confirms trend
  - RSI in momentum zone, not overbought/oversold

This strategy fires on wide-range days where ORB range filter rejects
but price has already shown its direction and is pulling back to reload.

Window: 9:30 AM – 1:00 PM
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from shared.indicators import (
    ema_at, rsi_at, atr_at, vwap_at,
    body_ratio, has_volume_data, volume_surge_ratio,
    is_bullish_candle, is_bearish_candle,
)


def evaluate_ema_pullback_signal(
    candles: List[Dict[str, Any]],
    current_idx: int,
    vix: Optional[float],
    *,
    ema_fast: int = 9,
    ema_slow: int = 21,
    pullback_proximity_pct: float = 0.006,   # within 0.6% of EMA21
    min_body_ratio: float = 0.38,
    rsi_period: int = 14,
    atr_period: int = 14,
    rsi_bull_min: float = 38.0,
    rsi_bull_max: float = 70.0,
    rsi_bear_min: float = 30.0,
    rsi_bear_max: float = 62.0,
    vix_max: float = 28.0,
    min_volume_surge_ratio: float = 1.0,
    lookback_candles: int = 4,
    min_ema_gap_pct: float = 0.0008,   # 0.08% min separation — avoids choppy flat EMA
) -> Dict[str, Any]:
    """
    Evaluate EMA Pullback signal at current_idx.

    Returns same structure as other signal engines:
      {"signal": "CALL"|"PUT"|None, "atr": float, "filters": {...}, "all_passed": bool}
    """
    filters: Dict[str, Dict] = {}
    result_base = {"signal": None, "atr": None, "filters": filters, "all_passed": False}

    if current_idx < max(22, lookback_candles + 1):
        filters["data"] = {"passed": False, "detail": "Insufficient candles for EMA calculation"}
        return result_base

    current = candles[current_idx]
    ts = current["ts"]
    close = float(current["close"])

    # ── 1. Trend direction (EMA stack) ───────────────────────────
    ema_f = ema_at(candles, ts, ema_fast)
    ema_s = ema_at(candles, ts, ema_slow)

    if ema_f is None or ema_s is None:
        filters["ema_trend"] = {"passed": False, "detail": "EMA data unavailable"}
        return result_base

    ema_gap_pct = abs(ema_f - ema_s) / ema_s if ema_s > 0 else 0
    trend_ok = ema_gap_pct >= min_ema_gap_pct
    direction = "CALL" if ema_f > ema_s else "PUT"

    filters["ema_trend"] = {
        "passed": trend_ok,
        "value": {"fast": round(ema_f, 2), "slow": round(ema_s, 2), "gap_pct": round(ema_gap_pct * 100, 3)},
        "detail": (
            f"EMA{ema_fast}={ema_f:.1f} {'>' if ema_f > ema_s else '<'} EMA{ema_slow}={ema_s:.1f} "
            f"(gap={ema_gap_pct*100:.2f}%, need>={min_ema_gap_pct*100:.2f}%): "
            f"{'OK' if trend_ok else 'TOO FLAT'} → {direction}"
        ),
    }
    if not trend_ok:
        return result_base

    # ── 2. Pullback: any recent candle touched EMA21 ─────────────
    pullback_found = False
    pullback_detail = ""
    for i in range(max(0, current_idx - lookback_candles), current_idx + 1):
        c = candles[i]
        c_ema_s = ema_at(candles, c["ts"], ema_slow)
        if c_ema_s is None or c_ema_s <= 0:
            continue
        c_low = float(c["low"])
        c_high = float(c["high"])

        if direction == "CALL":
            # Low came within proximity_pct of EMA21 (or briefly dipped below)
            proximity = (c_low - c_ema_s) / c_ema_s
            if proximity <= pullback_proximity_pct:
                pullback_found = True
                pullback_detail = f"Low={c_low:.1f} near EMA{ema_slow}={c_ema_s:.1f} ({proximity*100:+.2f}%)"
                break
        else:
            # High came within proximity_pct of EMA21 (or briefly rose above)
            proximity = (c_ema_s - c_high) / c_ema_s
            if proximity <= pullback_proximity_pct:
                pullback_found = True
                pullback_detail = f"High={c_high:.1f} near EMA{ema_slow}={c_ema_s:.1f} ({proximity*100:+.2f}%)"
                break

    filters["ema_pullback"] = {
        "passed": pullback_found,
        "detail": pullback_detail if pullback_found else f"No EMA{ema_slow} touch in last {lookback_candles} candles",
    }
    if not pullback_found:
        return result_base

    # ── 3. Bounce candle: directional body, closed away from EMA21 ─
    br = body_ratio(current)
    directional = (
        (direction == "CALL" and is_bullish_candle(current)) or
        (direction == "PUT" and is_bearish_candle(current))
    )
    closed_away = (
        (direction == "CALL" and close > ema_s) or
        (direction == "PUT" and close < ema_s)
    )
    bounce_ok = directional and br >= min_body_ratio and closed_away
    filters["candle_body"] = {
        "passed": bounce_ok,
        "value": round(br, 2),
        "detail": (
            f"Body={br:.2f} (need>={min_body_ratio}), directional={directional}, "
            f"close={'above' if close > ema_s else 'below'} EMA{ema_slow}={ema_s:.1f}"
        ),
    }
    if not bounce_ok:
        return result_base

    # ── 4. ATR (for SL/target sizing) ────────────────────────────
    atr = atr_at(candles, ts, atr_period)
    result_base["atr"] = atr

    # ── 5. RSI ────────────────────────────────────────────────────
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
            "detail": f"RSI={rsi:.1f} (need {rsi_range})",
        }
    else:
        filters["rsi"] = {"passed": True, "detail": "RSI skipped — insufficient data"}

    # ── 6. VWAP alignment ────────────────────────────────────────
    vwap = vwap_at(candles, ts)
    if vwap is not None:
        vwap_ok = (
            (direction == "CALL" and close > vwap) or
            (direction == "PUT" and close < vwap)
        )
        filters["vwap"] = {
            "passed": vwap_ok,
            "value": round(vwap, 2),
            "detail": (
                f"Close={close:.1f} {'above' if close > vwap else 'below'} VWAP={vwap:.1f}: "
                f"{'OK' if vwap_ok else 'WRONG SIDE'}"
            ),
        }
    else:
        filters["vwap"] = {"passed": True, "detail": "VWAP unavailable — skipped"}

    # ── 7. Volume ─────────────────────────────────────────────────
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

    # ── 8. VIX ────────────────────────────────────────────────────
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
    critical = ["ema_trend", "ema_pullback", "candle_body", "rsi", "vwap", "volume_surge", "vix"]
    all_passed = all(filters.get(f, {}).get("passed", True) for f in critical)
    result_base["signal"] = direction if all_passed else None
    result_base["all_passed"] = all_passed
    return result_base
