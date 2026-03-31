"""
Daily Regime Classifier — the PERMISSION layer.

Runs ONCE per day (pre-market / at 9:15) using daily OHLC data.
Classifies into 1 of 8 regimes that gate:
  - Which strategies are allowed
  - Direction (CALL / PUT only)
  - Max trades, time windows, risk sizing

CRITICAL RULE: Regime = Permission, NOT Entry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time as dtime
from typing import Any, Dict, List, Optional


@dataclass
class ExecutionParams:
    """Per-regime execution rules."""
    max_trades: int = 1
    window_start: str = "09:30"
    window_end: str = "13:00"
    sl_pct_override: Optional[float] = None
    target_pct_override: Optional[float] = None
    trail_trigger_pct: Optional[float] = None
    trail_lock_step_pct: Optional[float] = None
    risk_pct: float = 0.02
    min_quality_score: int = 3


@dataclass
class DailyRegime:
    """Output of daily regime classification."""
    name: str
    allowed_direction: Optional[str]       # "CALL", "PUT", or None (both)
    allowed_strategies: List[str]
    otm_offset: int = 0
    should_trade: bool = True
    execution: ExecutionParams = field(default_factory=ExecutionParams)
    detail: str = ""
    scores: Dict[str, Any] = field(default_factory=dict)


_STRONG_STRATEGIES = ["EMA_PULLBACK", "VWAP_RECLAIM"]
_PULLBACK_STRATEGIES = ["EMA_PULLBACK", "VWAP_RECLAIM"]

REGIME_DEFS: Dict[str, DailyRegime] = {
    "SKIP_VOLATILE": DailyRegime(
        name="SKIP_VOLATILE",
        allowed_direction=None,
        allowed_strategies=[],
        should_trade=False,
        execution=ExecutionParams(max_trades=0),
    ),
    "STRONG_BULL": DailyRegime(
        name="STRONG_BULL",
        allowed_direction="CALL",
        allowed_strategies=_STRONG_STRATEGIES,
        otm_offset=0,
        execution=ExecutionParams(
            max_trades=3,
            window_start="09:30",
            window_end="14:00",
            trail_trigger_pct=0.30,
            trail_lock_step_pct=0.15,
            risk_pct=0.025,
            min_quality_score=4,
        ),
    ),
    "STRONG_BEAR": DailyRegime(
        name="STRONG_BEAR",
        allowed_direction="PUT",
        allowed_strategies=_STRONG_STRATEGIES,
        otm_offset=0,
        execution=ExecutionParams(
            max_trades=3,
            window_start="09:30",
            window_end="14:00",
            trail_trigger_pct=0.30,
            trail_lock_step_pct=0.15,
            risk_pct=0.025,
            min_quality_score=4,
        ),
    ),
    "BULL_BREAKOUT": DailyRegime(
        name="BULL_BREAKOUT",
        allowed_direction="CALL",
        allowed_strategies=["EMA_PULLBACK", "VWAP_RECLAIM", "MOMENTUM_BREAKOUT"],
        otm_offset=1,       # 1-OTM: great R:R on a breakout day with volume
        should_trade=True,  # BREAKOUT DAYS = HIGHEST VALUE DAYS. Don't skip!
        execution=ExecutionParams(
            max_trades=3,
            window_start="09:20",
            window_end="13:30",
            risk_pct=0.03,
            min_quality_score=3,
            trail_trigger_pct=0.25,
            trail_lock_step_pct=0.12,
        ),
    ),
    "BEAR_BREAKOUT": DailyRegime(
        name="BEAR_BREAKOUT",
        allowed_direction="PUT",
        allowed_strategies=["EMA_PULLBACK", "VWAP_RECLAIM", "MOMENTUM_BREAKOUT"],
        otm_offset=1,       # 1-OTM: great R:R on a breakout day with volume
        should_trade=True,  # BREAKOUT DAYS = HIGHEST VALUE DAYS. Don't skip!
        execution=ExecutionParams(
            max_trades=3,
            window_start="09:20",
            window_end="13:30",
            risk_pct=0.03,
            min_quality_score=3,
            trail_trigger_pct=0.25,
            trail_lock_step_pct=0.12,
        ),
    ),
    "BULL_PULLBACK": DailyRegime(
        name="BULL_PULLBACK",
        allowed_direction="CALL",
        allowed_strategies=_PULLBACK_STRATEGIES,
        otm_offset=0,
        execution=ExecutionParams(
            max_trades=3,
            window_start="09:30",
            window_end="14:00",
            risk_pct=0.02,
            min_quality_score=3,
        ),
    ),
    "BEAR_PULLBACK": DailyRegime(
        name="BEAR_PULLBACK",
        allowed_direction="PUT",
        allowed_strategies=_PULLBACK_STRATEGIES,
        otm_offset=0,
        execution=ExecutionParams(
            max_trades=3,
            window_start="09:30",
            window_end="14:00",
            risk_pct=0.02,
            min_quality_score=4,
        ),
    ),
    "SKIP_RANGING": DailyRegime(
        name="SKIP_RANGING",
        allowed_direction=None,
        allowed_strategies=["VWAP_RECLAIM"],
        otm_offset=0,
        execution=ExecutionParams(
            max_trades=1,
            window_start="10:00",
            window_end="13:00",
            sl_pct_override=0.20,
            risk_pct=0.01,
            min_quality_score=3,
        ),
    ),
}


@dataclass
class RegimeClassifierConfig:
    vix_skip_threshold: float = 30.0
    gap_skip_pct: float = 0.015
    strong_gap_pct: float = 0.003
    strong_5d_ret_pct: float = 0.01
    breakout_prev_range_max: float = 120.0
    pullback_5d_ret_pct: float = 0.005
    pullback_flat_open_pct: float = 0.002


def _build_daily_ohlc(candles_5m: List[Dict[str, Any]], target_date: date) -> Optional[Dict[str, Any]]:
    day_candles = [c for c in candles_5m if c["ts"].date() == target_date]
    if not day_candles:
        return None
    return {
        "date": target_date,
        "open": float(day_candles[0]["open"]),
        "high": max(float(c["high"]) for c in day_candles),
        "low": min(float(c["low"]) for c in day_candles),
        "close": float(day_candles[-1]["close"]),
        "volume": sum(float(c.get("volume", 0)) for c in day_candles),
    }


def _get_daily_bars(candles_5m: List[Dict[str, Any]], up_to_date: date, n_days: int = 10) -> List[Dict[str, Any]]:
    all_dates = sorted(set(c["ts"].date() for c in candles_5m))
    relevant = [d for d in all_dates if d < up_to_date][-n_days:]
    bars = []
    for d in relevant:
        bar = _build_daily_ohlc(candles_5m, d)
        if bar:
            bars.append(bar)
    return bars


def classify_regime(
    candles_5m: List[Dict[str, Any]],
    trade_date: date,
    vix: Optional[float],
    cfg: Optional[RegimeClassifierConfig] = None,
) -> DailyRegime:
    if cfg is None:
        cfg = RegimeClassifierConfig()

    daily_bars = _get_daily_bars(candles_5m, trade_date, n_days=10)
    today_candles = [c for c in candles_5m if c["ts"].date() == trade_date]

    scores: Dict[str, Any] = {"vix": vix}

    if len(daily_bars) < 2 or not today_candles:
        regime = REGIME_DEFS["SKIP_RANGING"]
        return DailyRegime(
            name=regime.name,
            allowed_direction=regime.allowed_direction,
            allowed_strategies=list(regime.allowed_strategies),
            otm_offset=regime.otm_offset,
            should_trade=regime.should_trade,
            execution=regime.execution,
            detail="insufficient_history",
            scores=scores,
        )

    prev_day = daily_bars[-1]
    today_open = float(today_candles[0]["open"])
    prev_close = prev_day["close"]

    gap_pct = (today_open - prev_close) / prev_close if prev_close > 0 else 0
    prev_return = (prev_day["close"] - prev_day["open"]) / prev_day["open"] if prev_day["open"] > 0 else 0
    prev_range = prev_day["high"] - prev_day["low"]
    prev_is_green = prev_day["close"] > prev_day["open"]
    prev_is_red = prev_day["close"] < prev_day["open"]

    if len(daily_bars) >= 5:
        five_day_close = daily_bars[-5]["close"]
        five_day_ret = (prev_close - five_day_close) / five_day_close if five_day_close > 0 else 0
    else:
        five_day_ret = prev_return * 2

    scores.update({
        "gap_pct": round(gap_pct, 5),
        "prev_return": round(prev_return, 5),
        "prev_range": round(prev_range, 1),
        "prev_is_green": prev_is_green,
        "five_day_ret": round(five_day_ret, 5),
        "today_open": today_open,
        "prev_close": prev_close,
    })

    bias = "NEUTRAL"
    if five_day_ret > 0.003 and prev_is_green:
        bias = "BULL"
    elif five_day_ret < -0.003 and prev_is_red:
        bias = "BEAR"
    elif five_day_ret > 0.003:
        bias = "BULL"
    elif five_day_ret < -0.003:
        bias = "BEAR"
    scores["bias"] = bias

    effective_vix = vix if vix is not None else 14.0

    # 1. SKIP_VOLATILE
    if effective_vix > cfg.vix_skip_threshold or abs(gap_pct) > cfg.gap_skip_pct:
        return _make_regime("SKIP_VOLATILE", scores,
                           f"VIX={effective_vix:.1f} gap={gap_pct*100:.2f}%")

    # 2. STRONG_BULL
    if (gap_pct >= cfg.strong_gap_pct
            and prev_is_green
            and five_day_ret > cfg.strong_5d_ret_pct):
        return _make_regime("STRONG_BULL", scores,
                           f"gap={gap_pct*100:.2f}% prev_green 5d_ret={five_day_ret*100:.2f}%")

    # 3. STRONG_BEAR
    if (gap_pct <= -cfg.strong_gap_pct
            and prev_is_red
            and five_day_ret < -cfg.strong_5d_ret_pct):
        return _make_regime("STRONG_BEAR", scores,
                           f"gap={gap_pct*100:.2f}% prev_red 5d_ret={five_day_ret*100:.2f}%")

    # 4. BULL_BREAKOUT
    if prev_range < cfg.breakout_prev_range_max and bias == "BULL":
        return _make_regime("BULL_BREAKOUT", scores,
                           f"prev_range={prev_range:.0f}<{cfg.breakout_prev_range_max} bias=BULL")

    # 5. BEAR_BREAKOUT
    if prev_range < cfg.breakout_prev_range_max and bias == "BEAR":
        return _make_regime("BEAR_BREAKOUT", scores,
                           f"prev_range={prev_range:.0f}<{cfg.breakout_prev_range_max} bias=BEAR")

    # 6. BULL_PULLBACK
    if five_day_ret > cfg.pullback_5d_ret_pct and gap_pct < cfg.pullback_flat_open_pct:
        return _make_regime("BULL_PULLBACK", scores,
                           f"5d_ret={five_day_ret*100:.2f}% gap={gap_pct*100:.2f}% (flat/down)")

    # 7. BEAR_PULLBACK
    if five_day_ret < -cfg.pullback_5d_ret_pct and gap_pct > -cfg.pullback_flat_open_pct:
        return _make_regime("BEAR_PULLBACK", scores,
                           f"5d_ret={five_day_ret*100:.2f}% gap={gap_pct*100:.2f}% (flat/up)")

    # 8. SKIP_RANGING
    return _make_regime("SKIP_RANGING", scores,
                       f"no_clear_signal gap={gap_pct*100:.2f}% 5d={five_day_ret*100:.2f}%")


def _make_regime(name: str, scores: Dict[str, Any], detail: str) -> DailyRegime:
    template = REGIME_DEFS[name]
    return DailyRegime(
        name=template.name,
        allowed_direction=template.allowed_direction,
        allowed_strategies=list(template.allowed_strategies),
        otm_offset=template.otm_offset,
        should_trade=template.should_trade,
        execution=ExecutionParams(
            max_trades=template.execution.max_trades,
            window_start=template.execution.window_start,
            window_end=template.execution.window_end,
            sl_pct_override=template.execution.sl_pct_override,
            target_pct_override=template.execution.target_pct_override,
            trail_trigger_pct=template.execution.trail_trigger_pct,
            trail_lock_step_pct=template.execution.trail_lock_step_pct,
            risk_pct=template.execution.risk_pct,
            min_quality_score=template.execution.min_quality_score,
        ),
        detail=detail,
        scores=scores,
    )


def classify_regime_live(
    kite_client,
    today: date,
    vix: Optional[float],
    cfg: Optional[RegimeClassifierConfig] = None,
) -> DailyRegime:
    from datetime import datetime, timedelta

    if cfg is None:
        cfg = RegimeClassifierConfig()

    token = kite_client.get_nifty_token()
    if token is None:
        return _make_regime("SKIP_RANGING", {"error": "no_token"}, "cannot_get_nifty_token")

    from_dt = datetime(today.year, today.month, today.day) - timedelta(days=18)
    to_dt = datetime(today.year, today.month, today.day, 15, 30)

    try:
        candles = kite_client.get_candles(token, from_dt, to_dt, "5minute")
        if not candles or len(candles) < 20:
            return _make_regime("SKIP_RANGING", {"error": "no_candles"}, "insufficient_candle_data")
        return classify_regime(candles, today, vix, cfg)
    except Exception as e:
        return _make_regime("SKIP_RANGING", {"error": str(e)}, f"api_error: {e}")


def regime_conflicts_with_trend(regime: DailyRegime, trend_direction: str) -> bool:
    if regime.allowed_direction is None:
        return False
    if trend_direction == "NEUTRAL":
        return False
    return regime.allowed_direction != trend_direction
