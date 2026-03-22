"""
VWAP Reclaim secondary strategy engine.
Works 10:00–14:00. Triggers when price reclaims VWAP after a meaningful rejection.

Institution-grade design:
  - Requires sustained time below/above VWAP (not just a single candle)
  - Rejection magnitude must be ATR-proportional
  - Reclaim candle must be strong (body > 40%, directional)
  - Supertrend trend must align
  - RSI must show momentum building, not exhaustion
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from shared.indicators import (
    vwap_at, rsi_at, atr_at, supertrend_series,
    body_ratio, has_volume_data, volume_surge_ratio,
    is_bullish_candle, is_bearish_candle,
    vwap_cross_up, vwap_cross_down,
)


def evaluate_vwap_reclaim_signal(
    candles: List[Dict[str, Any]],
    current_idx: int,
    vix: Optional[float],
    *,
    reclaim_min_rejection_points: float = 15.0,
    reclaim_confirmation_candles: int = 2,
    supertrend_period: int = 10,
    supertrend_multiplier: float = 3.0,
    rsi_period: int = 14,
    atr_period: int = 14,
    min_volume_surge_ratio: float = 1.2,
    rsi_min: float = 40.0,
    rsi_max: float = 65.0,
    vix_max: float = 22.0,
) -> Dict[str, Any]:
    filters: Dict[str, Dict] = {}
    result_base = {"signal": None, "atr": None, "filters": filters, "all_passed": False}

    if current_idx < max(5, reclaim_confirmation_candles + 1):
        filters["data"] = {"passed": False, "detail": "Not enough candles for reclaim eval"}
        return result_base

    current = candles[current_idx]
    ts = current["ts"]
    close = float(current["close"])

    # ── 1. Detect VWAP cross ──────────────────────────────────────
    is_cross_up = vwap_cross_up(candles, current_idx, lookback=reclaim_confirmation_candles)
    is_cross_down = vwap_cross_down(candles, current_idx, lookback=reclaim_confirmation_candles)

    if not is_cross_up and not is_cross_down:
        filters["vwap_cross"] = {"passed": False, "detail": "No VWAP cross detected"}
        return result_base

    direction = "CALL" if is_cross_up else "PUT"
    vwap_now = vwap_at(candles, ts)
    filters["vwap_cross"] = {
        "passed": True,
        "direction": direction,
        "detail": f"{direction}: price {close:.1f} crossed {'above' if direction=='CALL' else 'below'} VWAP {vwap_now:.1f if vwap_now else 0:.1f}",
    }

    # ── 2. Rejection magnitude (ATR-proportional) ─────────────────
    atr = atr_at(candles, ts, atr_period)
    result_base["atr"] = atr
    if current_idx >= 1 and vwap_now is not None:
        prev_close = float(candles[current_idx - 1]["close"])
        rejection_pts = abs(vwap_now - prev_close)
        min_rejection = reclaim_min_rejection_points
        if atr is not None and atr > 0:
            min_rejection = max(reclaim_min_rejection_points, atr * 0.3)
        reject_ok = rejection_pts >= min_rejection
        filters["rejection_magnitude"] = {
            "passed": reject_ok,
            "value": round(rejection_pts, 1),
            "detail": f"Rejection {rejection_pts:.1f}pt (need>={min_rejection:.1f}pt)",
        }
    else:
        filters["rejection_magnitude"] = {"passed": True, "detail": "Skipped"}

    # ── 3. Candle quality ─────────────────────────────────────────
    br = body_ratio(current)
    directional = (
        (direction == "CALL" and is_bullish_candle(current)) or
        (direction == "PUT" and is_bearish_candle(current))
    )
    body_ok = br >= 0.40 and directional
    filters["candle_body"] = {
        "passed": body_ok,
        "value": round(br, 2),
        "detail": f"Body ratio {br:.2f} (need>=0.40), directional={directional}",
    }

    # ── 4. Supertrend ─────────────────────────────────────────────
    st_series = supertrend_series(candles[: current_idx + 1], supertrend_period, supertrend_multiplier)
    if st_series:
        st = st_series[-1]
        st_ok = (
            (direction == "CALL" and st["trend"] == "UP") or
            (direction == "PUT" and st["trend"] == "DOWN")
        )
        filters["supertrend"] = {
            "passed": st_ok,
            "value": st["trend"],
            "detail": f"Supertrend={st['trend']}, need {'UP' if direction=='CALL' else 'DOWN'}",
        }
    else:
        filters["supertrend"] = {"passed": True, "detail": "Supertrend skipped (insufficient data)"}

    # ── 5. RSI ────────────────────────────────────────────────────
    rsi = rsi_at(candles, ts, rsi_period)
    if rsi is not None:
        rsi_ok = rsi_min <= rsi <= rsi_max
        filters["rsi"] = {
            "passed": rsi_ok,
            "value": round(rsi, 1),
            "detail": f"RSI={rsi:.1f} (need {rsi_min}-{rsi_max})",
        }
    else:
        filters["rsi"] = {"passed": True, "detail": "RSI skipped"}

    # ── 6. Volume ─────────────────────────────────────────────────
    if has_volume_data(candles[max(0, current_idx - 20):current_idx]):
        surge = volume_surge_ratio(current, candles[:current_idx])
        vol_ok = surge is not None and surge >= min_volume_surge_ratio
        filters["volume_surge"] = {
            "passed": vol_ok,
            "value": round(surge, 2) if surge else None,
            "detail": f"Volume surge {surge:.1f}x (need>={min_volume_surge_ratio}x)" if surge else "Insufficient history",
        }
    else:
        filters["volume_surge"] = {
            "passed": True,
            "value": None,
            "detail": "Volume data unavailable — filter skipped",
        }

    # ── 7. VIX ───────────────────────────────────────────────────
    if vix is not None:
        vix_ok = vix <= vix_max
        filters["vix"] = {"passed": vix_ok, "value": round(vix, 2), "detail": f"VIX={vix:.1f} (max={vix_max})"}
    else:
        filters["vix"] = {"passed": True, "detail": "VIX skipped"}

    # ── Final ─────────────────────────────────────────────────────
    critical = ["vwap_cross", "rejection_magnitude", "candle_body", "supertrend", "rsi", "volume_surge", "vix"]
    all_passed = all(filters.get(f, {}).get("passed", True) for f in critical)
    result_base["signal"] = direction if all_passed else None
    result_base["all_passed"] = all_passed
    return result_base
