"""
Early-session impulse detector — identifies strong directional moves in the
first 4 candles (20 minutes) before the slow 5-indicator trend system has
enough data to reach a reliable verdict.

Six rules, all directional (bullish/bearish mirrors):

  R0 (Early override) — Hard 15-min (3-candle) move gate.
               move_from_open >= 0.7% in first 3 candles → minimum STRONG.
               Catches violent opens (gap-and-go bear days) that the ATR-adaptive
               R1 might miss when ATR threshold exceeds 0.7% on high-vol days.

  R1 (Gate)  — Move exceeds ATR-adaptive threshold.
               move_from_open > max(0.4%, ATR_5min × 1.2)
               Prevents small drifts and static 0.4% threshold misfires on
               high-volatility gap days.

  R2         — Body-strength check.
               ≥2 candles close in bottom 30% of their range (bearish).
               Ensures actual selling pressure, not just tiny red candles.

  R3         — No-pullback with hidden-reversal filter.
               Max counter-move < 0.15% AND no candle closes above the
               fixed impulse midpoint: (open + lowest_low_of_4_candles) / 2
               Catches hidden reversals even when the net counter-move is small.

  R4         — Wick rejection guard.
               No candle's lower-wick recovery exceeds 60% of its range.
               Filters "fake sell → buyback" / exhaustion candles.

  R5         — Progressive move confirmation.
               c2.close < c1.close, c3.close < c2.close, c4.close ≤ c3.close
               Prevents "big first candle + flat after" spike-and-stall patterns.

Grading:
  R0 early-move override:
    If R0 passes → minimum grade = STRONG (regardless of R1).
    Quality rules R2–R5 can still push it to EXTREME.
  R1 is a hard gate for the normal path — if R0 and R1 both fail, grade = NONE.
  R2–R5 are quality validators:
    EXTREME  →  R1 + all of R2–R5        bonus_votes = +3
    STRONG   →  R1 + any 3 of {R2–R5}   bonus_votes = +2
    WEAK     →  R1 + any 1–2 of {R2–R5} bonus_votes = +1
    NONE     →  R1 fails                 bonus_votes =  0

bonus_votes are added to the slow-path trend score in detect_trend(), allowing
early confirmation on genuine trend days without replacing the full indicator system.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class ImpulseGrade(str, Enum):
    EXTREME = "EXTREME"   # All 5 rules pass — enter at 9:35
    STRONG  = "STRONG"    # R1 + 3 quality rules — high confidence
    WEAK    = "WEAK"      # R1 + 1–2 quality rules — supplementary signal
    NONE    = "NONE"      # R1 fails — slow path only


IMPULSE_BONUS_VOTES: Dict[str, int] = {
    ImpulseGrade.EXTREME: 3,
    ImpulseGrade.STRONG:  2,
    ImpulseGrade.WEAK:    1,
    ImpulseGrade.NONE:    0,
}


@dataclass
class ImpulseResult:
    grade: ImpulseGrade
    direction: str          # "PUT", "CALL", or "NONE"
    bonus_votes: int        # 0–3, added to trend score when directions agree
    rules: Dict[str, bool] = field(default_factory=dict)
    detail: str = ""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _atr_5min(candles: List[Dict[str, Any]]) -> float:
    """Average true range of the provided candles (high - low per candle)."""
    ranges = [float(c["high"]) - float(c["low"]) for c in candles]
    return sum(ranges) / len(ranges) if ranges else 0.0


def _check_bearish(c4: List[Dict[str, Any]], open_price: float) -> Dict[str, bool]:
    """Evaluate all 5 rules for a bearish impulse move."""
    rules: Dict[str, bool] = {}

    lows   = [float(c["low"])   for c in c4]
    highs  = [float(c["high"])  for c in c4]
    closes = [float(c["close"]) for c in c4]
    ranges = [h - l for h, l in zip(highs, lows)]

    # ── R0: Early strong-move override (15-min / 3-candle hard gate) ────
    # If first 3 candles drop >= 0.7% from open, this is a conviction signal
    # regardless of ATR threshold — catches violent bearish opens.
    early_move = (open_price - closes[2]) / open_price   # drop after 3rd candle
    rules["R0_early_move"] = early_move >= 0.007

    # ── R1: ATR-adaptive move gate ────────────────────────────────────────
    atr     = _atr_5min(c4)
    threshold = max(0.004, (atr * 1.2) / open_price) if open_price > 0 else 0.004
    net_move  = (open_price - closes[-1]) / open_price   # positive = bearish drop
    rules["R1_move_gate"] = net_move > threshold

    # ── R2: Body-strength — ≥2 closes in bottom 30% of candle range ──────
    strong_closes = 0
    for i, rng in enumerate(ranges):
        if rng > 0:
            # (close - low) / range < 0.30  → close in bottom 30%
            if (closes[i] - lows[i]) / rng < 0.30:
                strong_closes += 1
    rules["R2_body_strength"] = strong_closes >= 2

    # ── R3: No-pullback with hidden-reversal check ────────────────────────
    lowest_low      = min(lows)
    impulse_midpoint = (open_price + lowest_low) / 2   # fixed reference

    # Max single-candle recovery against the bearish move
    max_counter = 0.0
    for i in range(len(closes)):
        prev = open_price if i == 0 else closes[i - 1]
        move_up = (float(c4[i]["high"]) - prev) / open_price
        if move_up > max_counter:
            max_counter = move_up

    no_large_pullback   = max_counter < 0.0015           # < 0.15% counter-move
    no_midpoint_breach  = all(cl < impulse_midpoint for cl in closes)
    rules["R3_no_pullback"] = no_large_pullback and no_midpoint_breach

    # ── R4: Wick rejection guard — no candle closes back above 60% of range
    no_wick_rejection = all(
        (closes[i] - lows[i]) / ranges[i] < 0.60
        for i in range(len(c4))
        if ranges[i] > 0
    )
    rules["R4_wick_guard"] = no_wick_rejection

    # ── R5: Progressive close — each candle closes lower than the previous ─
    rules["R5_progressive"] = (
        closes[1] < closes[0] and
        closes[2] < closes[1] and
        closes[3] <= closes[2]   # <= allows final consolidation candle
    )

    return rules


def _check_bullish(c4: List[Dict[str, Any]], open_price: float) -> Dict[str, bool]:
    """Evaluate all 5 rules for a bullish impulse move (mirror of bearish)."""
    rules: Dict[str, bool] = {}

    lows   = [float(c["low"])   for c in c4]
    highs  = [float(c["high"])  for c in c4]
    closes = [float(c["close"]) for c in c4]
    ranges = [h - l for h, l in zip(highs, lows)]

    # ── R0: Early strong-move override (15-min / 3-candle hard gate) ────
    # If first 3 candles rise >= 0.7% from open, this is a conviction signal
    # regardless of ATR threshold — catches violent bullish opens.
    early_move = (closes[2] - open_price) / open_price   # rise after 3rd candle
    rules["R0_early_move"] = early_move >= 0.007

    # ── R1: ATR-adaptive move gate ────────────────────────────────────────
    atr       = _atr_5min(c4)
    threshold = max(0.004, (atr * 1.2) / open_price) if open_price > 0 else 0.004
    net_move  = (closes[-1] - open_price) / open_price   # positive = bullish rise
    rules["R1_move_gate"] = net_move > threshold

    # ── R2: Body-strength — ≥2 closes in top 30% of candle range ─────────
    strong_closes = 0
    for i, rng in enumerate(ranges):
        if rng > 0:
            # (close - low) / range > 0.70  → close in top 30%
            if (closes[i] - lows[i]) / rng > 0.70:
                strong_closes += 1
    rules["R2_body_strength"] = strong_closes >= 2

    # ── R3: No-pullback with hidden-reversal check ────────────────────────
    highest_high     = max(highs)
    impulse_midpoint = (open_price + highest_high) / 2   # fixed reference

    max_counter = 0.0
    for i in range(len(closes)):
        prev = open_price if i == 0 else closes[i - 1]
        move_down = (prev - float(c4[i]["low"])) / open_price
        if move_down > max_counter:
            max_counter = move_down

    no_large_pullback  = max_counter < 0.0015
    no_midpoint_breach = all(cl > impulse_midpoint for cl in closes)
    rules["R3_no_pullback"] = no_large_pullback and no_midpoint_breach

    # ── R4: Wick rejection guard — no candle has upper wick > 60% of range
    no_wick_rejection = all(
        (highs[i] - closes[i]) / ranges[i] < 0.60
        for i in range(len(c4))
        if ranges[i] > 0
    )
    rules["R4_wick_guard"] = no_wick_rejection

    # ── R5: Progressive close — each candle closes higher than the previous
    rules["R5_progressive"] = (
        closes[1] > closes[0] and
        closes[2] > closes[1] and
        closes[3] >= closes[2]   # >= allows final consolidation candle
    )

    return rules


def _grade(rules: Dict[str, bool]) -> ImpulseGrade:
    """Derive impulse grade from rule results.

    R0 early-move override: 0.7% drop/rise in first 3 candles → minimum STRONG.
    R1 is the normal hard gate for the standard path.
    """
    gate_keys = {"R0_early_move", "R1_move_gate"}
    quality_passed = sum(1 for k, v in rules.items() if k not in gate_keys and v)

    # R0 override: violent early move → guaranteed minimum STRONG
    if rules.get("R0_early_move", False):
        if quality_passed >= 4:
            return ImpulseGrade.EXTREME
        return ImpulseGrade.STRONG

    # Normal path: R1 is a hard gate
    if not rules.get("R1_move_gate", False):
        return ImpulseGrade.NONE

    if quality_passed == 4:
        return ImpulseGrade.EXTREME
    if quality_passed == 3:
        return ImpulseGrade.STRONG
    if quality_passed >= 1:
        return ImpulseGrade.WEAK
    return ImpulseGrade.NONE   # R1 passed but all quality rules failed → no signal


# ── Public API ────────────────────────────────────────────────────────────────

def detect_impulse(candles: List[Dict[str, Any]]) -> ImpulseResult:
    """
    Analyse the first 4 intraday 5-min candles for a strong directional impulse.

    Args:
        candles:  Intraday 5-min candles, oldest first. Must have at least 4.
                  Each candle: {"open", "high", "low", "close", "volume", "ts"}
                  The first candle's open is used as the session open reference.

    Returns:
        ImpulseResult with grade, direction, bonus_votes, and per-rule breakdown.
    """
    if len(candles) < 4:
        return ImpulseResult(
            grade=ImpulseGrade.NONE,
            direction="NONE",
            bonus_votes=0,
            detail="Fewer than 4 candles — impulse check skipped",
        )

    c4         = candles[:4]
    open_price = float(c4[0]["open"])

    if open_price <= 0:
        return ImpulseResult(
            grade=ImpulseGrade.NONE,
            direction="NONE",
            bonus_votes=0,
            detail="Invalid open price",
        )

    close_4   = float(c4[-1]["close"])
    net_bearish = (open_price - close_4) / open_price
    net_bullish = (close_4 - open_price) / open_price

    # Evaluate whichever direction shows the larger raw move
    if net_bearish >= net_bullish:
        rules     = _check_bearish(c4, open_price)
        direction = "PUT"
    else:
        rules     = _check_bullish(c4, open_price)
        direction = "CALL"

    grade        = _grade(rules)
    bonus_votes  = IMPULSE_BONUS_VOTES[grade]

    # Clear direction if no grade (R1 failed)
    if grade == ImpulseGrade.NONE:
        direction = "NONE"

    # Build detail string
    rule_summary = " ".join(
        f"{k}={'✓' if v else '✗'}" for k, v in rules.items()
    )
    atr = _atr_5min(c4)
    threshold = max(0.004, (atr * 1.2) / open_price) if open_price > 0 else 0.004
    actual_move = max(net_bearish, net_bullish)
    early_flag = " [R0_OVERRIDE]" if rules.get("R0_early_move") else ""
    detail = (
        f"grade={grade} dir={direction} bonus=+{bonus_votes}{early_flag} | "
        f"move={actual_move:.3%} threshold={threshold:.3%} ATR={atr:.1f} | "
        f"{rule_summary}"
    )

    return ImpulseResult(
        grade=grade,
        direction=direction,
        bonus_votes=bonus_votes,
        rules=rules,
        detail=detail,
    )
