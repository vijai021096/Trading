"""
Regime V2 — Clean 5-state daily regime classifier.

States:
  SKIP        — VIX > 30 or abs(gap) > 3%. Do not trade.
  DIRECTIONAL — Gap 0.5–3% OR strong 5d trend. Direction = BIAS (not locked).
                Entry only when live candles confirm. Gap reversals handled naturally.
  RANGE_BREAK — Prev day range < 100 pts + 5d momentum. Breakout setup.
  PULLBACK    — Strong 5d trend but flat/opposing open. Wait, then follow trend.
  UNCERTAIN   — No clear signal. Highest bar, 1 trade max.

KEY DESIGN: direction_bias is a SUGGESTION. The live entry engine confirms with candles.
If candles oppose the bias, entry is blocked or direction is flipped.
This correctly handles gap reversals (yesterday's problem).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional


@dataclass
class RegimeV2:
    name: str                           # SKIP | DIRECTIONAL | RANGE_BREAK | PULLBACK | UNCERTAIN
    direction_bias: Optional[str]       # CALL | PUT | None (both allowed)
    should_trade: bool
    window_start: str                   # "09:30"
    window_end: str                     # "13:00"
    base_sl_pct: float                  # base SL% of option premium
    target_rr: float                    # target = SL × target_rr
    max_trades: int
    risk_pct: float                     # % of capital risked per trade
    detail: str
    scores: Dict[str, Any] = field(default_factory=dict)


def classify_regime_v2(
    candles_5m: List[Dict[str, Any]],
    trade_date: date,
    vix: Optional[float],
) -> RegimeV2:
    """
    Classify today's regime using daily bars built from 5-min candles.
    Called at ~9:20 after first candle is available.
    """
    daily_bars = _build_daily_bars(candles_5m, trade_date)
    today_candles = [c for c in candles_5m if c["ts"].date() == trade_date]

    effective_vix = vix if vix is not None else 15.0
    scores: Dict[str, Any] = {"vix": effective_vix}

    # ── Not enough data yet ────────────────────────────────────────────
    if len(daily_bars) < 3 or not today_candles:
        return _regime(
            "UNCERTAIN", None, True,
            "10:00", "13:00", 0.20, 2.5, 1, 0.015,
            "insufficient_history", scores,
        )

    prev = daily_bars[-1]
    prev2 = daily_bars[-2]
    today_open = float(today_candles[0]["open"])
    prev_close = float(prev["close"])
    prev_range = float(prev["high"]) - float(prev["low"])
    prev_is_green = float(prev["close"]) > float(prev["open"])
    prev_is_red = float(prev["close"]) < float(prev["open"])

    gap_pct = (today_open - prev_close) / prev_close if prev_close > 0 else 0.0

    # 5-day return (trend context)
    closes = [float(b["close"]) for b in daily_bars[-5:]]
    five_d_ret = (closes[-1] - closes[0]) / closes[0] if len(closes) >= 2 else 0.0

    scores.update({
        "gap_pct": round(gap_pct, 4),
        "prev_range": round(prev_range, 1),
        "five_d_ret": round(five_d_ret, 4),
        "prev_is_green": prev_is_green,
        "today_open": today_open,
        "prev_close": prev_close,
    })

    # ── 1. SKIP — true panic ──────────────────────────────────────────
    if effective_vix > 30.0 or abs(gap_pct) > 0.030:
        return _regime(
            "SKIP", None, False,
            "09:30", "13:00", 0.20, 2.5, 0, 0.0,
            f"skip: VIX={effective_vix:.1f} gap={gap_pct*100:.1f}%", scores,
        )

    # ── 2. DIRECTIONAL — clear gap (0.5–3%) ──────────────────────────
    if abs(gap_pct) >= 0.005:
        bias = "CALL" if gap_pct > 0 else "PUT"
        base_sl = 0.25 if abs(gap_pct) >= 0.015 else 0.20
        return _regime(
            "DIRECTIONAL", bias, True,
            "09:30", "11:30", base_sl, 2.5, 2, 0.025,
            f"gap {'up' if gap_pct > 0 else 'down'} {gap_pct*100:.2f}% — bias {bias}, entry confirms via candles",
            scores,
        )

    # ── 3. RANGE_BREAK — tight prev range + 5d momentum ──────────────
    if prev_range < 100 and abs(five_d_ret) >= 0.005:
        bias = "CALL" if five_d_ret > 0 else "PUT"
        return _regime(
            "RANGE_BREAK", bias, True,
            "09:30", "12:00", 0.20, 3.0, 2, 0.025,
            f"tight range {prev_range:.0f}pts, 5d_ret={five_d_ret*100:.1f}% — breakout setup bias {bias}",
            scores,
        )

    # ── 4. PULLBACK — strong 5d trend + flat open ─────────────────────
    if abs(five_d_ret) >= 0.010 and abs(gap_pct) < 0.003:
        bias = "CALL" if five_d_ret > 0 else "PUT"
        return _regime(
            "PULLBACK", bias, True,
            "10:00", "13:00", 0.20, 2.5, 1, 0.020,
            f"5d_ret={five_d_ret*100:.1f}% trend, flat open — pullback continuation bias {bias}",
            scores,
        )

    # ── 5. UNCERTAIN — no clear pattern ──────────────────────────────
    return _regime(
        "UNCERTAIN", None, True,
        "10:00", "12:00", 0.20, 2.5, 1, 0.015,
        f"no clear pattern: gap={gap_pct*100:.2f}% 5d={five_d_ret*100:.2f}%",
        scores,
    )


def _regime(
    name: str, bias: Optional[str], should_trade: bool,
    w_start: str, w_end: str, sl_pct: float, rr: float,
    max_t: int, risk_pct: float, detail: str, scores: dict,
) -> RegimeV2:
    return RegimeV2(
        name=name, direction_bias=bias, should_trade=should_trade,
        window_start=w_start, window_end=w_end,
        base_sl_pct=sl_pct, target_rr=rr,
        max_trades=max_t, risk_pct=risk_pct,
        detail=detail, scores=scores,
    )


def _build_daily_bars(candles_5m: List[Dict], trade_date: date) -> List[Dict]:
    """Build daily OHLC bars from 5-min candles, excluding today."""
    dates = sorted(set(c["ts"].date() for c in candles_5m if c["ts"].date() < trade_date))[-10:]
    bars = []
    for d in dates:
        day = [c for c in candles_5m if c["ts"].date() == d]
        if day:
            bars.append({
                "date": d,
                "open": float(day[0]["open"]),
                "high": max(float(c["high"]) for c in day),
                "low": min(float(c["low"]) for c in day),
                "close": float(day[-1]["close"]),
            })
    return bars


def classify_regime_v2_live(kite_client, today: date, vix: Optional[float]) -> RegimeV2:
    """Live version: fetches candles from Kite and classifies."""
    from datetime import datetime
    token = kite_client.get_nifty_token()
    if token is None:
        return _regime("UNCERTAIN", None, True, "10:00", "12:00", 0.20, 2.5, 1, 0.015,
                       "no_nifty_token", {})
    from_dt = datetime(today.year, today.month, today.day) - timedelta(days=20)
    to_dt = datetime(today.year, today.month, today.day, 15, 30)
    try:
        candles = kite_client.get_candles(token, from_dt, to_dt, "5minute")
        if not candles or len(candles) < 10:
            return _regime("UNCERTAIN", None, True, "10:00", "12:00", 0.20, 2.5, 1, 0.015,
                           "insufficient_candle_data", {"count": len(candles) if candles else 0})
        return classify_regime_v2(candles, today, vix)
    except Exception as e:
        return _regime("UNCERTAIN", None, True, "10:00", "12:00", 0.20, 2.5, 1, 0.015,
                       f"api_error: {e}", {})
