"""
Trade Quality Filter — the professional decision engine layer.

Scores every setup 0-5 BEFORE entering. Blocks low-quality trades even if
individual strategy filters all pass. Adds market-state awareness.

Score breakdown (each +1):
  1. Strong trend       — EMA9/21 gap ≥ 0.15%, direction aligned
  2. Clean structure    — HH/HL for bull, LH/LL for bear (last 5 candles)
  3. Volume spike       — current candle ≥ 1.5x average volume
  4. Clean candle       — body ≥ 50%, no dominant adverse wick
  5. No nearby S/R      — price not within 0.3% of a recent pivot

Minimum to trade: score ≥ 3

Additional market-state checks:
  - is_choppy_market()     — 8-candle range < 60pts + EMA flat → skip ALL
  - is_overextended()      — price > 1% from EMA21 → avoid new entry
  - is_late_move()         — move already > 120pts from breakout → skip/reduce
  - get_htf_direction()    — 15-min EMA trend for higher-timeframe context
  - get_dynamic_blocklist()— disable strategies based on market regime
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from shared.indicators import ema_at, volume_surge_ratio, has_volume_data, body_ratio, vwap_at


def compute_trade_quality(
    candles: List[Dict[str, Any]],
    current_idx: int,
    direction: str,          # "CALL" or "PUT"
    *,
    ema_fast: int = 9,
    ema_slow: int = 21,
    structure_lookback: int = 5,
    min_volume_surge: float = 1.5,
    min_body_ratio: float = 0.50,
    sr_proximity_pct: float = 0.003,
    sr_lookback: int = 20,
) -> Dict[str, Any]:
    """
    Returns:
      {"score": int, "max": 5, "details": {filter: bool}, "tradeable": bool}

    Call AFTER all strategy-specific filters pass, as a final gate.
    """
    if current_idx < ema_slow + 2:
        return {"score": 0, "max": 5, "details": {}, "tradeable": False, "reason": "insufficient_candles"}

    current = candles[current_idx]
    ts = current["ts"]
    close = float(current["close"])
    details: Dict[str, bool] = {}

    # ── 1. Strong trend (EMA9 > EMA21 with clear gap) ────────────
    ema9  = ema_at(candles[:current_idx + 1], ts, ema_fast)
    ema21 = ema_at(candles[:current_idx + 1], ts, ema_slow)
    if ema9 is not None and ema21 is not None and ema21 > 0:
        gap_pct = abs(ema9 - ema21) / ema21
        if direction == "CALL":
            details["strong_trend"] = (ema9 > ema21) and (gap_pct >= 0.0015)
        else:
            details["strong_trend"] = (ema9 < ema21) and (gap_pct >= 0.0015)
    else:
        details["strong_trend"] = False

    # ── 2. Clean structure (HH/HL or LH/LL) ─────────────────────
    lb = min(structure_lookback, current_idx)
    if lb >= 2:
        recent = candles[current_idx - lb: current_idx + 1]
        highs = [float(c["high"]) for c in recent]
        lows  = [float(c["low"])  for c in recent]
        if direction == "CALL":
            hh = all(highs[i] >= highs[i - 1] for i in range(1, len(highs)))
            hl = all(lows[i]  >= lows[i - 1]  for i in range(1, len(lows)))
            details["clean_structure"] = hh or hl
        else:
            lh = all(highs[i] <= highs[i - 1] for i in range(1, len(highs)))
            ll = all(lows[i]  <= lows[i - 1]  for i in range(1, len(lows)))
            details["clean_structure"] = lh or ll
    else:
        details["clean_structure"] = False

    # ── 3. Volume spike ───────────────────────────────────────────
    if has_volume_data(candles[max(0, current_idx - 20):current_idx]):
        surge = volume_surge_ratio(current, candles[:current_idx])
        details["volume_spike"] = surge is not None and surge >= min_volume_surge
    else:
        details["volume_spike"] = True  # No data → skip (benefit of doubt)

    # ── 4. Clean candle (body + no dominant adverse wick) ─────────
    br = body_ratio(current)
    hi = float(current["high"])
    lo = float(current["low"])
    open_ = float(current["open"])
    body_top    = max(close, open_)
    body_bottom = min(close, open_)
    candle_range = hi - lo
    if candle_range > 0:
        if direction == "CALL":
            # Upper wick should not dominate (no shooting star)
            upper_wick = hi - body_top
            wick_ok = upper_wick <= (body_top - body_bottom) * 0.8
        else:
            # Lower wick should not dominate (no hammer reversal)
            lower_wick = body_bottom - lo
            wick_ok = lower_wick <= (body_top - body_bottom) * 0.8
        details["clean_candle"] = (br >= min_body_ratio) and wick_ok
    else:
        details["clean_candle"] = False

    # ── 5. No nearby S/R (recent pivot check) ────────────────────
    pivot_lb = min(sr_lookback, current_idx)
    pivots = []
    for j in range(current_idx - pivot_lb, current_idx):
        pivots.append(float(candles[j]["high"]))
        pivots.append(float(candles[j]["low"]))

    near_sr = False
    if direction == "CALL":
        resistances = [p for p in pivots if p > close * 1.001]
        if resistances:
            nearest = min(resistances)
            near_sr = (nearest - close) / close <= sr_proximity_pct
    else:
        supports = [p for p in pivots if p < close * 0.999]
        if supports:
            nearest = max(supports)
            near_sr = (close - nearest) / close <= sr_proximity_pct

    details["no_nearby_sr"] = not near_sr

    score = sum(1 for v in details.values() if v)
    return {
        "score": score,
        "max": 5,
        "details": details,
        "tradeable": score >= 3,
        "reason": f"quality={score}/5 ({', '.join(k for k, v in details.items() if v)})",
    }


def is_choppy_market(
    candles: List[Dict[str, Any]],
    current_idx: int,
    *,
    lookback: int = 8,
    max_range_pts: float = 60.0,
    ema_flat_pct: float = 0.0005,
    ema_fast: int = 9,
    ema_slow: int = 21,
) -> bool:
    """
    True if market is sideways/choppy — skip ALL strategy scans.

    Both conditions must be true:
      - Last 8 candles high-low range < 60 points
      - EMA9 ≈ EMA21 gap < 0.05% (flat, no trend)
    """
    if current_idx < max(lookback, ema_slow + 1):
        return False

    recent = candles[current_idx - lookback: current_idx + 1]
    hi = max(float(c["high"]) for c in recent)
    lo = min(float(c["low"])  for c in recent)
    if (hi - lo) >= max_range_pts:
        return False  # Wide range = not choppy

    ts = candles[current_idx]["ts"]
    ema9  = ema_at(candles[:current_idx + 1], ts, ema_fast)
    ema21 = ema_at(candles[:current_idx + 1], ts, ema_slow)
    if ema9 is None or ema21 is None or ema21 == 0:
        return False

    return abs(ema9 - ema21) / ema21 < ema_flat_pct


def is_overextended(
    candles: List[Dict[str, Any]],
    current_idx: int,
    direction: str,
    *,
    ema_slow: int = 21,
    max_distance_pct: float = 0.010,
) -> bool:
    """
    True if price is > 1% away from EMA21 in the trade direction.
    Avoid chasing overextended price — mean reversion risk is high.
    """
    if current_idx < ema_slow + 1:
        return False

    ts = candles[current_idx]["ts"]
    close = float(candles[current_idx]["close"])
    ema21 = ema_at(candles[:current_idx + 1], ts, ema_slow)
    if ema21 is None or ema21 == 0:
        return False

    dist_pct = abs(close - ema21) / ema21
    if dist_pct < max_distance_pct:
        return False

    if direction == "CALL" and close > ema21:
        return True
    if direction == "PUT" and close < ema21:
        return True
    return False


def is_late_move(
    entry_price: float,
    breakout_level: float,
    direction: str,
    *,
    max_move_pts: float = 120.0,
) -> bool:
    """
    True if price has already moved > 120pts from the breakout/signal level.
    This means the best part of the move is over — late entry = bad risk/reward.
    """
    if breakout_level <= 0:
        return False
    move = entry_price - breakout_level if direction == "CALL" else breakout_level - entry_price
    return move > max_move_pts


def get_htf_direction(
    candles: List[Dict[str, Any]],
    current_idx: int,
    *,
    htf_bars: int = 3,   # 3 × 5-min = 15-min candles
    ema_fast: int = 9,
    ema_slow: int = 21,
) -> str:
    """
    Aggregate 5-min candles into 15-min bars and return EMA trend direction.
    Returns "CALL", "PUT", or "NEUTRAL".

    If 5-min says CALL but 15-min is a downtrend → skip (counter-trend risk).
    """
    min_htf = (ema_slow + 2) * htf_bars
    if current_idx < min_htf:
        return "NEUTRAL"

    day_candles = candles[:current_idx + 1]
    htf: List[Dict[str, Any]] = []
    for i in range(0, len(day_candles) - htf_bars + 1, htf_bars):
        group = day_candles[i: i + htf_bars]
        if len(group) < htf_bars:
            continue
        htf.append({
            "ts":     group[-1]["ts"],
            "open":   float(group[0]["open"]),
            "high":   max(float(c["high"]) for c in group),
            "low":    min(float(c["low"])  for c in group),
            "close":  float(group[-1]["close"]),
            "volume": sum(float(c.get("volume", 0)) for c in group),
        })

    if len(htf) < ema_slow + 2:
        return "NEUTRAL"

    ts = htf[-1]["ts"]
    ema9_htf  = ema_at(htf, ts, ema_fast)
    ema21_htf = ema_at(htf, ts, ema_slow)
    if ema9_htf is None or ema21_htf is None or ema21_htf == 0:
        return "NEUTRAL"

    gap_pct = (ema9_htf - ema21_htf) / ema21_htf
    if gap_pct > 0.0008:
        return "CALL"
    if gap_pct < -0.0008:
        return "PUT"
    return "NEUTRAL"


def get_daily_bias(
    nifty_df,
    trade_date,
    *,
    bias_threshold: int = 3,   # net score needed to declare BULL or BEAR
) -> str:
    """
    Multi-factor daily bias — determines whether to only take CALL, only PUT,
    or allow both directions today.

    Three independent factors are scored:

      Factor 1 — 5-day return (primary trend signal, most weight):
        > +1.5%  → +3   (strong bull swing)
        > +0.5%  → +1
        < -1.5%  → -3   (strong bear swing — captures Sep/May corrections)
        < -0.5%  → -1

      Factor 2 — Yesterday's candle (momentum continuation):
        > +0.5%  → +2
        > +0.2%  → +1
        < -0.5%  → -2
        < -0.2%  → -1

      Factor 3 — 5-day SMA slope (is trend accelerating?):
        SMA5 (now) vs SMA5 (5 days ago)
        Rising >0.3%  → +1
        Falling <-0.3% → -1

    Total score ≥ +3 → BULL  (only CALL trades allowed today)
    Total score ≤ -3 → BEAR  (only PUT trades allowed today)
    Otherwise        → NEUTRAL (use intraday trend as normal)
    """
    all_dates = sorted(nifty_df["ts"].dt.date.unique())
    prev_dates = [d for d in all_dates if d < trade_date]

    if len(prev_dates) < 10:
        return "NEUTRAL"

    # Build daily OHLCV from 5-min candles
    daily = []
    for d in prev_dates[-12:]:
        day_df = nifty_df[nifty_df["ts"].dt.date == d]
        if len(day_df) < 10:
            continue
        d_open  = float(day_df.iloc[0]["open"])
        d_close = float(day_df.iloc[-1]["close"])
        if d_open > 0:
            daily.append({"date": d, "open": d_open, "close": d_close,
                          "ret": (d_close - d_open) / d_open})

    if len(daily) < 6:
        return "NEUTRAL"

    score = 0

    # ── Factor 1: 5-day return (captures sustained corrections/rallies) ──
    if len(daily) >= 5:
        ret_5d = (daily[-1]["close"] - daily[-5]["close"]) / daily[-5]["close"]
        if ret_5d > 0.015:
            score += 3
        elif ret_5d > 0.005:
            score += 1
        elif ret_5d < -0.015:
            score -= 3
        elif ret_5d < -0.005:
            score -= 1

    # ── Factor 2: yesterday's return ────────────────────────────────────
    yest = daily[-1]["ret"]
    if yest > 0.005:
        score += 2
    elif yest > 0.002:
        score += 1
    elif yest < -0.005:
        score -= 2
    elif yest < -0.002:
        score -= 1

    # ── Factor 3: SMA5 slope ─────────────────────────────────────────────
    if len(daily) >= 10:
        sma5_now  = sum(d["close"] for d in daily[-5:]) / 5
        sma5_prev = sum(d["close"] for d in daily[-10:-5]) / 5
        if sma5_prev > 0:
            slope = (sma5_now - sma5_prev) / sma5_prev
            if slope > 0.003:
                score += 1
            elif slope < -0.003:
                score -= 1

    if score >= bias_threshold:
        return "BULL"
    elif score <= -bias_threshold:
        return "BEAR"
    return "NEUTRAL"


def get_dynamic_blocklist(
    trend_state: str,
    is_choppy: bool,
) -> List[str]:
    """
    Returns list of strategy names to BLOCK given current market conditions.

    Logic:
      CHOPPY market          → block momentum + ORB (false breakouts dominate)
      STRONG_BULL/BEAR       → block VWAP_RECLAIM (fading strong trends fails)
      NEUTRAL/RANGING        → block ORB + MOMENTUM (need direction to work)
    """
    if is_choppy:
        return ["MOMENTUM_BREAKOUT", "ORB", "RELAXED_ORB", "EMA_PULLBACK"]

    if trend_state in ("STRONG_BULL", "STRONG_BEAR"):
        return ["VWAP_RECLAIM"]

    if trend_state == "NEUTRAL":
        return ["MOMENTUM_BREAKOUT", "ORB", "EMA_PULLBACK"]

    return []  # BULL / BEAR — all strategies eligible
