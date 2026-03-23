"""
Intraday trend detector — determines direction and conviction.

Outputs TrendState (STRONG_BULL, BULL, NEUTRAL, BEAR, STRONG_BEAR)
and a risk multiplier used to scale position size.

Scoring system — each indicator votes +1 (bullish) / -1 (bearish) / 0 (neutral):
  1. EMA9 vs EMA21   — short-term momentum direction
  2. Price vs EMA21  — is price riding the trend?
  3. VWAP position   — institutional price level
  4. RSI             — momentum strength
  5. Price structure — higher highs/lows or lower highs/lows

Score interpretation:
  +4 to +5  → STRONG_BULL  (risk ×1.00, direction=CALL)
  +2 to +3  → BULL         (risk ×0.85, direction=CALL)
  -1 to +1  → NEUTRAL      (risk ×0.60, no trade bias)
  -3 to -2  → BEAR         (risk ×0.85, direction=PUT)
  -5 to -4  → STRONG_BEAR  (risk ×1.00, direction=PUT)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from shared.indicators import ema_at, rsi_at, vwap_at


class TrendState(str, Enum):
    STRONG_BULL = "STRONG_BULL"
    BULL        = "BULL"
    NEUTRAL     = "NEUTRAL"
    BEAR        = "BEAR"
    STRONG_BEAR = "STRONG_BEAR"


# Risk multiplier — how much of base risk_per_trade_pct to use
TREND_RISK_MULTIPLIER = {
    TrendState.STRONG_BULL: 1.00,
    TrendState.BULL:        0.85,
    TrendState.NEUTRAL:     0.60,
    TrendState.BEAR:        0.85,
    TrendState.STRONG_BEAR: 1.00,
}

# Strategy priority by trend state.
# Strategies listed first get tried first (within their time windows).
STRATEGY_PRIORITY_BY_TREND: Dict[str, List[str]] = {
    TrendState.STRONG_BULL: ["ORB", "MOMENTUM_BREAKOUT", "EMA_PULLBACK", "VWAP_RECLAIM", "RELAXED_ORB"],
    TrendState.BULL:        ["EMA_PULLBACK", "VWAP_RECLAIM", "ORB", "RELAXED_ORB"],
    TrendState.NEUTRAL:     ["VWAP_RECLAIM", "RELAXED_ORB"],
    TrendState.BEAR:        ["EMA_PULLBACK", "VWAP_RECLAIM", "ORB", "RELAXED_ORB"],
    TrendState.STRONG_BEAR: ["ORB", "MOMENTUM_BREAKOUT", "EMA_PULLBACK", "VWAP_RECLAIM", "RELAXED_ORB"],
}

# SL / target multipliers per strategy (sl_pct, target_pct)
SL_TARGET_BY_STRATEGY: Dict[str, tuple] = {
    "ORB":                (0.28, 0.60),
    "RELAXED_ORB":        (0.30, 0.55),
    "EMA_PULLBACK":       (0.25, 0.55),
    "VWAP_RECLAIM":       (0.28, 0.60),
    "MOMENTUM_BREAKOUT":  (0.22, 0.55),   # Tighter SL — momentum trades reverse fast
}


@dataclass
class TrendResult:
    state: TrendState
    direction: str              # "CALL", "PUT", or "NEUTRAL"
    conviction: float           # 0.0 – 1.0 (fraction of indicators agreeing)
    risk_multiplier: float      # final risk scaling factor (VIX-adjusted)
    strategy_priority: List[str]
    scores: Dict[str, int] = field(default_factory=dict)
    detail: str = ""


def detect_trend(
    candles: List[Dict[str, Any]],
    vix: float = 15.0,
    structure_lookback: int = 5,
) -> TrendResult:
    """
    Detect intraday bullish/bearish trend from recent 5-min candles.

    Args:
        candles:            All intraday 5-min candles so far (oldest first)
        vix:                Current India VIX value
        structure_lookback: How many recent candles to analyse for HH/LL structure
    """
    if len(candles) < 14:
        # Too early in the day to have reliable signals
        return TrendResult(
            state=TrendState.NEUTRAL,
            direction="NEUTRAL",
            conviction=0.0,
            risk_multiplier=0.60,
            strategy_priority=STRATEGY_PRIORITY_BY_TREND[TrendState.NEUTRAL],
            detail="Insufficient candles — defaulting to NEUTRAL",
        )

    current = candles[-1]
    ts = current["ts"]
    close = float(current["close"])
    scores: Dict[str, int] = {}

    # ── 1. EMA9 vs EMA21 (short-term momentum) ───────────────────
    ema9  = ema_at(candles, ts, 9)
    ema21 = ema_at(candles, ts, 21)

    if ema9 is not None and ema21 is not None and ema21 > 0:
        gap_pct = (ema9 - ema21) / ema21
        if gap_pct > 0.0008:       # 0.08% minimum gap — avoids flat-EMA noise
            scores["ema_stack"] = 1
        elif gap_pct < -0.0008:
            scores["ema_stack"] = -1
        else:
            scores["ema_stack"] = 0
    # No EMA data yet → no vote

    # ── 2. Price vs EMA21 (trend riding) ─────────────────────────
    if ema21 is not None and ema21 > 0:
        price_gap_pct = (close - ema21) / ema21
        if price_gap_pct > 0.001:
            scores["price_ema21"] = 1
        elif price_gap_pct < -0.001:
            scores["price_ema21"] = -1
        else:
            scores["price_ema21"] = 0

    # ── 3. VWAP position (institutional bias) ────────────────────
    vwap = vwap_at(candles, ts)
    if vwap is not None and vwap > 0:
        vwap_gap_pct = (close - vwap) / vwap
        if vwap_gap_pct > 0.001:
            scores["vwap"] = 1
        elif vwap_gap_pct < -0.001:
            scores["vwap"] = -1
        else:
            scores["vwap"] = 0

    # ── 4. RSI momentum ──────────────────────────────────────────
    rsi = rsi_at(candles, ts, 14)
    if rsi is not None:
        if rsi > 58:
            scores["rsi"] = 1
        elif rsi < 42:
            scores["rsi"] = -1
        else:
            scores["rsi"] = 0

    # ── 5. Price structure — higher highs/lows vs lower highs/lows
    if len(candles) >= structure_lookback + 1:
        recent = candles[-(structure_lookback + 1):]
        prev_highs = [float(c["high"]) for c in recent[:-1]]
        prev_lows  = [float(c["low"])  for c in recent[:-1]]
        cur_high   = float(recent[-1]["high"])
        cur_low    = float(recent[-1]["low"])

        hh = cur_high > max(prev_highs)   # new high = bullish structure
        ll = cur_low  < min(prev_lows)    # new low  = bearish structure
        lh = cur_high < max(prev_highs)   # lower high = bearish
        hl = cur_low  > min(prev_lows)    # higher low = bullish

        bull_struct = (hh or hl) and not ll
        bear_struct = (ll or lh) and not hh
        if bull_struct:
            scores["structure"] = 1
        elif bear_struct:
            scores["structure"] = -1
        else:
            scores["structure"] = 0

    # ── Aggregate score → state ───────────────────────────────────
    total = sum(scores.values())
    n_votes = len(scores)
    conviction = abs(total) / n_votes if n_votes > 0 else 0.0

    # VIX dampens conviction (high uncertainty = less directional confidence)
    if vix > 20:
        conviction *= 0.80
    if vix > 25:
        conviction *= 0.75

    if total >= 4:
        state = TrendState.STRONG_BULL
        direction = "CALL"
    elif total >= 2:
        state = TrendState.BULL
        direction = "CALL"
    elif total <= -4:
        state = TrendState.STRONG_BEAR
        direction = "PUT"
    elif total <= -2:
        state = TrendState.BEAR
        direction = "PUT"
    else:
        state = TrendState.NEUTRAL
        direction = "NEUTRAL"

    # Risk multiplier — start from trend-state base, cap based on VIX
    risk_mult = TREND_RISK_MULTIPLIER[state]
    if vix > 20:
        risk_mult = min(risk_mult, 0.75)
    if vix > 25:
        risk_mult = min(risk_mult, 0.55)
    if vix > 30:
        risk_mult = min(risk_mult, 0.40)   # Extreme VIX: very small size

    # Build detail string for logging
    parts = [f"score={total}/{n_votes}", f"conviction={conviction:.2f}"]
    if ema9 and ema21:
        parts.append(f"EMA9={ema9:.0f} EMA21={ema21:.0f}")
    if vwap:
        parts.append(f"VWAP={vwap:.0f}")
    if rsi:
        parts.append(f"RSI={rsi:.1f}")
    parts.append(f"VIX={vix:.1f}")
    parts.append(f"votes={scores}")

    return TrendResult(
        state=state,
        direction=direction,
        conviction=round(conviction, 3),
        risk_multiplier=round(risk_mult, 2),
        strategy_priority=STRATEGY_PRIORITY_BY_TREND[state],
        scores=scores,
        detail=" | ".join(parts),
    )
