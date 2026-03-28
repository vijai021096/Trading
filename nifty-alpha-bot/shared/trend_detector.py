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

from shared.impulse_detector import ImpulseGrade, ImpulseResult, detect_impulse
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
    "ORB":                (0.28, 0.65),
    "RELAXED_ORB":        (0.28, 0.58),
    "EMA_PULLBACK":       (0.30, 0.65),
    "VWAP_RECLAIM":       (0.28, 0.65),
    "MOMENTUM_BREAKOUT":  (0.22, 0.55),
}

# ── Tier System ────────────────────────────────────────────────────
# All tiers use SAME wide SL/target (trail mechanism = edge).
# Tiers only differ in POSITION SIZE (risk_pct).
# Tier 1 = High Conviction: quality >= 4, strong trend -> big size
# Tier 2 = Standard:        quality  = 3 -> normal size
# Tier 3 = Exploratory:     quality  = 2 -> small size
TIER_PARAMS: Dict[int, Dict[str, float]] = {
    1: {"sl_pct": 0.28, "target_pct": 0.60, "trail_trigger": 0.30, "trail_lock": 0.15, "risk_pct": 0.025},
    2: {"sl_pct": 0.28, "target_pct": 0.60, "trail_trigger": 0.30, "trail_lock": 0.15, "risk_pct": 0.018},
    3: {"sl_pct": 0.28, "target_pct": 0.60, "trail_trigger": 0.30, "trail_lock": 0.15, "risk_pct": 0.010},
}


def assign_tier(quality_score: int, trend_state: "TrendState") -> int:
    """Assign trade tier based on quality score and trend strength."""
    if quality_score >= 4 and trend_state in (TrendState.STRONG_BULL, TrendState.STRONG_BEAR, TrendState.BULL, TrendState.BEAR):
        return 1
    if quality_score >= 3:
        return 2
    return 3


@dataclass
class TrendResult:
    state: TrendState
    direction: str              # "CALL", "PUT", or "NEUTRAL"
    conviction: float           # 0.0 – 1.0 (fraction of indicators agreeing)
    risk_multiplier: float      # final risk scaling factor (VIX-adjusted)
    strategy_priority: List[str]
    scores: Dict[str, int] = field(default_factory=dict)
    impulse_grade: str = ImpulseGrade.NONE   # NONE/WEAK/STRONG/EXTREME
    detail: str = ""


def detect_trend(
    candles: List[Dict[str, Any]],
    vix: float = 15.0,
    structure_lookback: int = 5,
    impulse: Optional["ImpulseResult"] = None,
    move_from_open_pct: float = 0.0,
) -> TrendResult:
    """
    Detect intraday bullish/bearish trend from recent 5-min candles.

    Args:
        candles:              All intraday 5-min candles so far (oldest first)
        vix:                  Current India VIX value
        structure_lookback:   How many recent candles to analyse for HH/LL structure
        impulse:              Optional pre-computed ImpulseResult from detect_impulse().
                              When provided and directions agree, bonus votes are added
                              to the score — allowing early confirmation before the slow
                              5-indicator path has 14 candles.
        move_from_open_pct:   Live % move from today's open (e.g. -0.85 means -0.85%).
                              When <= -0.70% or >= +0.70%, activates hard trend override:
                              state forced to STRONG_BEAR/STRONG_BULL and conviction
                              raised to ≥0.75 regardless of slow-path indicator score.
    """
    # ── Fast path: impulse-only detection (before slow indicators have data) ─
    # If we have fewer than 14 candles but a qualifying impulse exists, use it
    # to produce an early directional verdict rather than defaulting to NEUTRAL.
    if len(candles) < 14:
        if (
            impulse is not None
            and impulse.grade in (ImpulseGrade.EXTREME, ImpulseGrade.STRONG)
            and impulse.direction in ("CALL", "PUT")
        ):
            # Map STRONG→BEAR/BULL, EXTREME→STRONG_BEAR/STRONG_BULL
            if impulse.grade == ImpulseGrade.EXTREME:
                state     = TrendState.STRONG_BEAR if impulse.direction == "PUT" else TrendState.STRONG_BULL
            else:
                state     = TrendState.BEAR if impulse.direction == "PUT" else TrendState.BULL
            direction = impulse.direction
            conviction = 0.80   # high but not 1.0 — slow path hasn't confirmed yet
            risk_mult  = TREND_RISK_MULTIPLIER[state]
            return TrendResult(
                state=state,
                direction=direction,
                conviction=conviction,
                risk_multiplier=round(risk_mult, 2),
                strategy_priority=STRATEGY_PRIORITY_BY_TREND[state],
                impulse_grade=impulse.grade,
                detail=f"EARLY via impulse ({impulse.grade}) — {impulse.detail}",
            )
        # Hard override even in early fast-path: strong 15-min move overrides NEUTRAL default
        if move_from_open_pct <= -0.70:
            return TrendResult(
                state=TrendState.STRONG_BEAR, direction="PUT", conviction=0.75,
                risk_multiplier=TREND_RISK_MULTIPLIER[TrendState.STRONG_BEAR],
                strategy_priority=STRATEGY_PRIORITY_BY_TREND[TrendState.STRONG_BEAR],
                detail=f"[HARD_OVERRIDE move={move_from_open_pct:+.2f}%] early candles — forced STRONG_BEAR",
            )
        if move_from_open_pct >= 0.70:
            return TrendResult(
                state=TrendState.STRONG_BULL, direction="CALL", conviction=0.75,
                risk_multiplier=TREND_RISK_MULTIPLIER[TrendState.STRONG_BULL],
                strategy_priority=STRATEGY_PRIORITY_BY_TREND[TrendState.STRONG_BULL],
                detail=f"[HARD_OVERRIDE move={move_from_open_pct:+.2f}%] early candles — forced STRONG_BULL",
            )
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

    # ── 5b. Bearish confirmation pattern: 3 consecutive lower highs + VWAP rejection
    # Three straight candles each making a lower high confirms a downtrend structure.
    # VWAP rejection (high touched VWAP but close below it) adds institutional confirmation.
    if vwap is not None and len(candles) >= 3:
        last3 = candles[-3:]
        h3 = [float(c["high"]) for c in last3]
        consecutive_lower_highs = h3[2] < h3[1] < h3[0]
        last_c = last3[-1]
        vwap_rejection = float(last_c["high"]) >= vwap * 0.9995 and float(last_c["close"]) < vwap
        if consecutive_lower_highs and vwap_rejection:
            scores["bear_pattern"] = -2   # strengthened: was -1 (structure + institutional)

    # ── Impulse bonus votes ───────────────────────────────────────
    # Add impulse bonus only when impulse direction agrees with slow-path lean.
    # "Lean" = sign of current slow-path total before impulse is added.
    # DIRECTION CONSISTENCY CHECK: conflicting impulse is silently ignored + logged.
    impulse_grade     = ImpulseGrade.NONE
    impulse_bonus     = 0
    impulse_conflict  = False
    slow_total        = sum(scores.values())
    slow_direction    = "CALL" if slow_total > 0 else ("PUT" if slow_total < 0 else "NEUTRAL")

    if impulse is not None and impulse.grade != ImpulseGrade.NONE:
        impulse_grade = impulse.grade
        if impulse.direction == slow_direction or slow_direction == "NEUTRAL":
            impulse_bonus = impulse.bonus_votes
            # Apply sign: PUT impulse → negative bonus, CALL → positive
            if impulse.direction == "PUT":
                impulse_bonus = -abs(impulse_bonus)
        else:
            # Direction conflict — impulse says one thing, indicators say the opposite.
            # Do NOT add bonus; flag for logging so the operator can see what happened.
            impulse_conflict = True
            from loguru import logger as _logger
            _logger.info(
                f"IMPULSE_CONFLICT: grade={impulse_grade} dir={impulse.direction} "
                f"conflicts with indicator lean={slow_direction} (slow_total={slow_total}) — bonus ignored"
            )

    # ── Aggregate score → state ───────────────────────────────────
    total   = slow_total + impulse_bonus
    n_votes = len(scores)   # denominator stays slow-path only (for conviction purity)
    conviction = abs(slow_total) / n_votes if n_votes > 0 else 0.0

    # VIX dampens conviction ONLY when direction is genuinely unclear (NEUTRAL).
    # Bear/bull trend days naturally carry higher VIX — don't penalise them twice.
    is_directional = abs(total) >= 2
    if not is_directional:
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

    # ── Hard trend override: 15-min move gate ────────────────────────────────
    # If price moved ≥0.7% from the session open, the market has declared direction.
    # Override the slow-path state to STRONG_BEAR/STRONG_BULL and floor conviction
    # at 0.75 — prevents NEUTRAL on genuine sell-off / gap-and-go days.
    # move_from_open_pct is expressed as a plain percentage (e.g. -0.85 = -0.85%).
    _hard_override = False
    if move_from_open_pct <= -0.70:            # bearish override
        if state != TrendState.STRONG_BEAR:
            state     = TrendState.STRONG_BEAR
            direction = "PUT"
            _hard_override = True
        conviction = max(conviction, 0.75)
    elif move_from_open_pct >= 0.70:           # bullish override
        if state != TrendState.STRONG_BULL:
            state     = TrendState.STRONG_BULL
            direction = "CALL"
            _hard_override = True
        conviction = max(conviction, 0.75)

    # Risk multiplier — start from trend-state base.
    # VIX caps apply in all states, but are less aggressive for confirmed trends.
    risk_mult = TREND_RISK_MULTIPLIER[state]
    if state in (TrendState.STRONG_BULL, TrendState.STRONG_BEAR):
        # Confirmed strong trend — only extreme VIX warrants a cap
        if vix > 30:
            risk_mult = min(risk_mult, 0.55)
    else:
        if vix > 20:
            risk_mult = min(risk_mult, 0.75)
        if vix > 25:
            risk_mult = min(risk_mult, 0.55)
        if vix > 30:
            risk_mult = min(risk_mult, 0.40)

    # Build detail string for logging
    parts = [
        f"base_score={slow_total} bonus={impulse_bonus:+d} → total={total}",
        f"conviction={conviction:.2f}",
    ]
    if _hard_override:
        parts.insert(0, f"[HARD_OVERRIDE move={move_from_open_pct:+.2f}%]")
    if ema9 and ema21:
        parts.append(f"EMA9={ema9:.0f} EMA21={ema21:.0f}")
    if vwap:
        parts.append(f"VWAP={vwap:.0f}")
    if rsi:
        parts.append(f"RSI={rsi:.1f}")
    parts.append(f"VIX={vix:.1f}")
    parts.append(f"votes={scores}")
    if impulse_grade != ImpulseGrade.NONE:
        parts.append(f"impulse={impulse_grade}({impulse_bonus:+d}{'✓' if not impulse_conflict else ' CONFLICT'})")

    return TrendResult(
        state=state,
        direction=direction,
        conviction=round(conviction, 3),
        risk_multiplier=round(risk_mult, 2),
        strategy_priority=STRATEGY_PRIORITY_BY_TREND[state],
        scores=scores,
        impulse_grade=impulse_grade,
        detail=" | ".join(parts),
    )


# ── Signal Confidence Scoring ─────────────────────────────────────
# Backtest win-rate per strategy (from 2-year optimized results)
STRATEGY_BACKTEST_WR = {
    "EMA_PULLBACK":       0.54,
    "RELAXED_ORB":        0.55,
    "VWAP_RECLAIM":       0.50,
    "ORB":                0.34,
    "MOMENTUM_BREAKOUT":  0.40,
    "MEAN_REVERSION":     0.50,
    "RANGE_FADE":         0.40,
}

# Backtest profit factor per strategy
STRATEGY_BACKTEST_PF = {
    "EMA_PULLBACK":       3.35,
    "RELAXED_ORB":        3.45,
    "VWAP_RECLAIM":       2.84,
    "ORB":                1.34,
    "MOMENTUM_BREAKOUT":  1.50,
    "MEAN_REVERSION":     4.09,
    "RANGE_FADE":         1.31,
}

# Which regime each strategy is strongest in
STRATEGY_REGIME_AFFINITY = {
    "ORB":                {"TRENDING": 1.2, "RANGING": 0.6, "VOLATILE": 0.4},
    "RELAXED_ORB":        {"TRENDING": 1.0, "RANGING": 0.8, "VOLATILE": 0.5},
    "EMA_PULLBACK":       {"TRENDING": 1.3, "RANGING": 0.9, "VOLATILE": 0.5},
    "VWAP_RECLAIM":       {"TRENDING": 0.9, "RANGING": 1.2, "VOLATILE": 0.8},
    "MOMENTUM_BREAKOUT":  {"TRENDING": 1.3, "RANGING": 0.5, "VOLATILE": 0.3},
    "MEAN_REVERSION":     {"TRENDING": 0.5, "RANGING": 1.3, "VOLATILE": 0.7},
    "RANGE_FADE":         {"TRENDING": 0.4, "RANGING": 1.2, "VOLATILE": 0.6},
}


@dataclass
class SignalCandidate:
    strategy: str
    signal: str       # CALL / PUT
    confidence: float  # 0-100
    regime_fit: float  # multiplier
    filters: dict
    sl_pct: float
    target_pct: float
    detail: str = ""


def compute_signal_confidence(
    strategy: str,
    signal: str,
    regime: str,
    trend: TrendResult,
    filters: dict,
    vix: float = 15.0,
) -> float:
    """
    Score 0-100 based on how many quality factors align.
    Used to rank multiple concurrent signals and pick the strongest.
    """
    score = 40.0  # base

    # 1. Backtest win-rate bonus (0-15 pts)
    wr = STRATEGY_BACKTEST_WR.get(strategy, 0.40)
    score += (wr - 0.35) * 75  # 50% WR → +11.25 pts, 55% → +15 pts

    # 2. Regime alignment (0-15 pts)
    affinity = STRATEGY_REGIME_AFFINITY.get(strategy, {}).get(regime, 0.8)
    score += (affinity - 0.5) * 20  # 1.3 → +16 pts, 0.5 → 0 pts

    # 3. Trend-signal alignment (0-12 pts)
    if trend.direction == signal:
        score += 8 + trend.conviction * 4  # aligned with trend → big bonus
    elif trend.direction == "NEUTRAL":
        score += 2  # neutral is ok
    else:
        score -= 5  # counter-trend penalty

    # 4. VIX penalty — high VIX reduces confidence
    if vix > 25:
        score -= (vix - 25) * 0.8
    elif vix < 15:
        score += 3  # calm market bonus

    # 5. Filter quality bonus — count how many extra filters passed
    if filters:
        passed = 0
        total = 0
        for k, v in filters.items():
            if k == "regime":
                continue
            total += 1
            if v is True:
                passed += 1
            elif isinstance(v, dict) and v.get("passed"):
                passed += 1
        if total > 0:
            quality = passed / total
            score += quality * 8  # all filters pass → +8 pts

    # 6. Profit factor bonus (0-10 pts)
    pf = STRATEGY_BACKTEST_PF.get(strategy, 1.5)
    score += min(10, (pf - 1.0) * 5)  # PF 3.0 → +10 pts

    return round(max(0, min(100, score)), 1)
