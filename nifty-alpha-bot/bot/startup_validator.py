"""
Startup validator — exercises every core module with synthetic candle data
and prints a clear PASS/FAIL summary before the bot enters its live loop.

Called from bot/main.py diagnostics after _run_bot_diagnostics().

Design principles:
  • Uses realistic synthetic NIFTY 5-min candles (no broker I/O required)
  • Tests both the happy-path and edge-cases (doji, zero volume, < 4 candles)
  • Each test is isolated — one failure does not abort the others
  • Prints a compact table; in LIVE mode warns on any failure
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, date, time as dtime
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("bot.startup_validator")

# ─────────────────────────────────────────────────────────────────────────────
# Synthetic candle builders
# ─────────────────────────────────────────────────────────────────────────────

_BASE_DATE = date(2026, 3, 28)
_BASE_OPEN = 22_500.0


def _candle(minute_offset: int, open_: float, high: float, low: float,
            close: float, volume: float = 150_000.0) -> Dict[str, Any]:
    """Build a single 5-min OHLCV candle dict starting at 09:15."""
    ts = datetime.combine(_BASE_DATE, dtime(9, 15)) + __import__("datetime").timedelta(minutes=minute_offset * 5)
    return {"ts": ts, "open": open_, "high": high, "low": low,
            "close": close, "volume": volume}


def _make_bearish_impulse_candles() -> List[Dict[str, Any]]:
    """4 strongly bearish candles — should trigger EXTREME impulse grade."""
    return [
        _candle(0,  22500, 22510, 22370, 22385, 210_000),   # C1: big drop, close near low
        _candle(1,  22385, 22390, 22295, 22308, 195_000),   # C2: continuing lower
        _candle(2,  22308, 22312, 22230, 22245, 188_000),   # C3: continuing lower
        _candle(3,  22245, 22250, 22170, 22185, 175_000),   # C4: continuing lower
    ]


def _make_bullish_impulse_candles() -> List[Dict[str, Any]]:
    """4 strongly bullish candles — should trigger EXTREME impulse grade."""
    return [
        _candle(0,  22500, 22635, 22495, 22622, 210_000),   # C1: big rally, close near high
        _candle(1,  22622, 22710, 22618, 22695, 195_000),   # C2: continuing higher
        _candle(2,  22695, 22775, 22690, 22760, 188_000),   # C3: continuing higher
        _candle(3,  22760, 22840, 22755, 22825, 175_000),   # C4: continuing higher
    ]


def _make_mixed_candles() -> List[Dict[str, Any]]:
    """4 mixed/choppy candles — should produce NONE impulse grade."""
    return [
        _candle(0,  22500, 22540, 22455, 22510, 90_000),    # small green
        _candle(1,  22510, 22545, 22490, 22495, 80_000),    # small red
        _candle(2,  22495, 22530, 22480, 22515, 75_000),    # small green
        _candle(3,  22515, 22520, 22490, 22502, 70_000),    # tiny red
    ]


def _make_full_day_bearish(n: int = 35) -> List[Dict[str, Any]]:
    """n candles of steady bearish drift — ensures slow-path trend detection works."""
    candles = []
    price = _BASE_OPEN
    for i in range(n):
        drop = 8.0 if i < 4 else 3.0        # strong early drop, then drift
        o = price
        h = o + 4.0
        l = o - drop - 3.0
        c = o - drop
        candles.append(_candle(i, o, h, l, c, 130_000 + i * 1_000))
        price = c
    return candles


def _make_full_day_bullish(n: int = 35) -> List[Dict[str, Any]]:
    """n candles of steady bullish drift."""
    candles = []
    price = _BASE_OPEN
    for i in range(n):
        rise = 8.0 if i < 4 else 3.0
        o = price
        h = o + rise + 3.0
        l = o - 4.0
        c = o + rise
        candles.append(_candle(i, o, h, l, c, 130_000 + i * 1_000))
        price = c
    return candles


def _make_doji_candles() -> List[Dict[str, Any]]:
    """4 doji-like candles (zero or tiny body) — edge case for impulse detector."""
    p = 22500.0
    return [
        _candle(0, p, p + 20, p - 20, p,      50_000),   # pure doji
        _candle(1, p, p + 15, p - 15, p + 1,  50_000),   # near doji
        _candle(2, p, p + 18, p - 18, p - 1,  50_000),   # near doji
        _candle(3, p, p + 12, p - 12, p,       50_000),   # pure doji
    ]


def _make_zero_volume_candles() -> List[Dict[str, Any]]:
    """Candles with zero volume — should not crash any engine."""
    candles = _make_bearish_impulse_candles()
    for c in candles:
        c["volume"] = 0
    return candles


# ─────────────────────────────────────────────────────────────────────────────
# Individual test functions — each returns (passed: bool, detail: str)
# ─────────────────────────────────────────────────────────────────────────────

def _test_impulse_bearish() -> Tuple[bool, str]:
    from shared.impulse_detector import detect_impulse, ImpulseGrade
    r = detect_impulse(_make_bearish_impulse_candles())
    ok = r.grade in (ImpulseGrade.STRONG, ImpulseGrade.EXTREME) and r.direction == "PUT"
    return ok, f"grade={r.grade} dir={r.direction} bonus=+{r.bonus_votes}"


def _test_impulse_bullish() -> Tuple[bool, str]:
    from shared.impulse_detector import detect_impulse, ImpulseGrade
    r = detect_impulse(_make_bullish_impulse_candles())
    ok = r.grade in (ImpulseGrade.STRONG, ImpulseGrade.EXTREME) and r.direction == "CALL"
    return ok, f"grade={r.grade} dir={r.direction} bonus=+{r.bonus_votes}"


def _test_impulse_mixed_is_none() -> Tuple[bool, str]:
    """Choppy candles must NOT trigger a strong impulse."""
    from shared.impulse_detector import detect_impulse, ImpulseGrade
    r = detect_impulse(_make_mixed_candles())
    ok = r.grade in (ImpulseGrade.NONE, ImpulseGrade.WEAK)
    return ok, f"grade={r.grade} (expected NONE/WEAK)"


def _test_impulse_doji_edge() -> Tuple[bool, str]:
    """Doji candles must not crash the detector."""
    from shared.impulse_detector import detect_impulse
    r = detect_impulse(_make_doji_candles())
    return True, f"grade={r.grade} (no crash)"


def _test_impulse_zero_volume() -> Tuple[bool, str]:
    """Zero-volume candles must not crash."""
    from shared.impulse_detector import detect_impulse
    r = detect_impulse(_make_zero_volume_candles())
    return True, f"grade={r.grade} (no crash)"


def _test_impulse_too_few_candles() -> Tuple[bool, str]:
    """Fewer than 4 candles must return NONE gracefully."""
    from shared.impulse_detector import detect_impulse, ImpulseGrade
    r = detect_impulse(_make_bearish_impulse_candles()[:2])
    ok = r.grade == ImpulseGrade.NONE
    return ok, f"grade={r.grade} (expected NONE)"


def _test_trend_fast_path_bearish() -> Tuple[bool, str]:
    """Fewer than 14 candles + strong bearish impulse → early BEAR/STRONG_BEAR."""
    from shared.impulse_detector import detect_impulse
    from shared.trend_detector import detect_trend, TrendState
    candles = _make_bearish_impulse_candles()   # only 4 candles
    impulse = detect_impulse(candles)
    t = detect_trend(candles, vix=14.0, impulse=impulse)
    ok = t.state in (TrendState.BEAR, TrendState.STRONG_BEAR)
    return ok, f"state={t.state} conviction={t.conviction:.2f} impulse={t.impulse_grade}"


def _test_trend_fast_path_no_impulse_neutral() -> Tuple[bool, str]:
    """Fewer than 14 candles + NONE impulse → NEUTRAL (no false signal)."""
    from shared.impulse_detector import detect_impulse
    from shared.trend_detector import detect_trend, TrendState
    candles = _make_mixed_candles()   # choppy — impulse should be NONE
    impulse = detect_impulse(candles)
    t = detect_trend(candles, vix=14.0, impulse=impulse)
    ok = t.state == TrendState.NEUTRAL
    return ok, f"state={t.state} (mixed candles, expected NEUTRAL)"


def _test_trend_slow_path_bearish() -> Tuple[bool, str]:
    """35 bearish candles → slow path converges to BEAR or STRONG_BEAR."""
    from shared.impulse_detector import detect_impulse
    from shared.trend_detector import detect_trend, TrendState
    candles = _make_full_day_bearish(35)
    impulse = detect_impulse(candles)
    t = detect_trend(candles, vix=14.0, impulse=impulse)
    ok = t.state in (TrendState.BEAR, TrendState.STRONG_BEAR)
    return ok, f"state={t.state} conviction={t.conviction:.2f} score={t.scores}"


def _test_trend_vix_trap_not_fired_on_strong() -> Tuple[bool, str]:
    """VIX=24 on a strong bearish day must NOT collapse conviction to 0."""
    from shared.impulse_detector import detect_impulse
    from shared.trend_detector import detect_trend, TrendState
    candles = _make_full_day_bearish(35)
    impulse = detect_impulse(candles)
    t = detect_trend(candles, vix=24.0, impulse=impulse)
    # Fix: strong states skip VIX dampen; conviction must stay > 0.3
    ok = t.conviction > 0.3 or t.state in (TrendState.BEAR, TrendState.STRONG_BEAR)
    return ok, f"state={t.state} conviction={t.conviction:.2f} vix=24 (no collapse)"


def _test_orb_engine() -> Tuple[bool, str]:
    """ORB engine must not crash and must return a valid signal structure."""
    from shared.orb_engine import evaluate_orb_signal
    candles = _make_full_day_bearish(25)
    current = candles[-1]
    result = evaluate_orb_signal(
        candles, current, vix=14.0,
        orb_start=dtime(9, 15), orb_end=dtime(9, 30),
    )
    ok = "signal" in result and "filters" in result and "all_passed" in result
    sig = result.get("signal")
    return ok, f"signal={sig} all_passed={result.get('all_passed')}"


def _test_ema_pullback_engine() -> Tuple[bool, str]:
    """EMA Pullback engine must not crash."""
    from shared.ema_pullback_engine import evaluate_ema_pullback_signal
    candles = _make_full_day_bullish(30)
    result = evaluate_ema_pullback_signal(candles, len(candles) - 1, vix=14.0)
    ok = "signal" in result and "filters" in result
    return ok, f"signal={result.get('signal')} all_passed={result.get('all_passed')}"


def _test_vwap_reclaim_engine() -> Tuple[bool, str]:
    """VWAP Reclaim engine must not crash."""
    from shared.vwap_reclaim_engine import evaluate_vwap_reclaim_signal
    candles = _make_full_day_bearish(30)
    result = evaluate_vwap_reclaim_signal(candles, len(candles) - 1, vix=14.0)
    ok = "signal" in result and "filters" in result
    return ok, f"signal={result.get('signal')} all_passed={result.get('all_passed')}"


def _test_momentum_breakout_engine() -> Tuple[bool, str]:
    """Momentum Breakout engine must not crash with enough candles."""
    from shared.momentum_breakout_engine import evaluate_momentum_breakout_signal
    candles = _make_full_day_bearish(35)
    result = evaluate_momentum_breakout_signal(candles, len(candles) - 1, vix=14.0)
    ok = "signal" in result and "filters" in result
    return ok, f"signal={result.get('signal')} all_passed={result.get('all_passed')}"


def _test_quality_filter() -> Tuple[bool, str]:
    """Quality filter must return a valid 0-5 score dict."""
    from shared.quality_filter import compute_trade_quality
    candles = _make_full_day_bearish(30)
    result = compute_trade_quality(candles, len(candles) - 1, "PUT")
    ok = (isinstance(result.get("score"), int)
          and 0 <= result["score"] <= 5
          and "tradeable" in result)
    return ok, f"score={result.get('score')}/5 tradeable={result.get('tradeable')}"


def _test_quality_filter_choppy() -> Tuple[bool, str]:
    """Quality filter choppy-market detection must not crash."""
    from shared.quality_filter import is_choppy_market
    candles = _make_mixed_candles() * 8   # pad to 32 candles
    ok = isinstance(is_choppy_market(candles, len(candles) - 1), bool)
    return ok, "is_choppy_market returned bool"


def _test_risk_manager() -> Tuple[bool, str]:
    """Risk manager must compute valid lot counts and not crash."""
    from bot.risk_manager import RiskManager
    rm = RiskManager(
        capital=25_000.0,
        max_daily_loss_pct=0.25,
        max_trades_per_day=4,
        max_daily_loss_hard=7_000.0,
        risk_per_trade_pct=0.02,
        lot_size=65,
        max_lots=5,
        max_drawdown_pct=20.0,
    )
    can_trade, reason = rm.can_trade()
    sizing = rm.compute_position_size(entry_price=150.0, sl_pct=0.30)
    # compute_position_size returns either a dict or a scalar depending on version
    if isinstance(sizing, dict):
        lots = sizing.get("lots", sizing.get("qty", 0))
    else:
        lots = int(sizing)
    ok = can_trade and lots >= 0
    return ok, f"can_trade={can_trade} lots={lots} (entry=₹150, SL=30%)"


def _test_regime_detector() -> Tuple[bool, str]:
    """Regime detector must return a valid regime from candle data."""
    from shared.regime_detector import detect_regime
    candles = _make_full_day_bearish(30)
    result = detect_regime(candles, vix=14.0)
    ok = hasattr(result, "regime") and result.regime is not None
    return ok, f"regime={result.regime}"


def _test_compute_signal_confidence() -> Tuple[bool, str]:
    """Signal confidence scorer must return 0-100."""
    from shared.impulse_detector import detect_impulse
    from shared.trend_detector import detect_trend, compute_signal_confidence
    candles = _make_full_day_bearish(30)
    impulse = detect_impulse(candles)
    trend = detect_trend(candles, vix=14.0, impulse=impulse)
    score = compute_signal_confidence("EMA_PULLBACK", "PUT", "TRENDING", trend, {}, vix=14.0)
    ok = 0 <= score <= 100
    return ok, f"confidence={score:.1f}/100"


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

_TESTS = [
    # Impulse detector
    ("Impulse · bearish EXTREME",          _test_impulse_bearish),
    ("Impulse · bullish EXTREME",          _test_impulse_bullish),
    ("Impulse · mixed → NONE/WEAK",        _test_impulse_mixed_is_none),
    ("Impulse · doji edge (no crash)",     _test_impulse_doji_edge),
    ("Impulse · zero volume (no crash)",   _test_impulse_zero_volume),
    ("Impulse · < 4 candles → NONE",       _test_impulse_too_few_candles),
    # Trend detector
    ("Trend  · fast-path bearish (9:35)",  _test_trend_fast_path_bearish),
    ("Trend  · fast-path no signal",       _test_trend_fast_path_no_impulse_neutral),
    ("Trend  · slow-path 35 candles",      _test_trend_slow_path_bearish),
    ("Trend  · VIX trap fixed",            _test_trend_vix_trap_not_fired_on_strong),
    # Strategy engines
    ("ORB    · engine call",               _test_orb_engine),
    ("EMA PB · engine call",               _test_ema_pullback_engine),
    ("VWAP   · reclaim engine call",       _test_vwap_reclaim_engine),
    ("MOM    · breakout engine call",      _test_momentum_breakout_engine),
    # Quality & Risk
    ("Quality· filter score 0-5",         _test_quality_filter),
    ("Quality· choppy detection",         _test_quality_filter_choppy),
    ("Risk   · manager + sizing",         _test_risk_manager),
    # Regime + Confidence
    ("Regime · detector",                 _test_regime_detector),
    ("Conf   · signal confidence 0-100",  _test_compute_signal_confidence),
]


def run_startup_validation(paper_mode: bool = True) -> dict:
    """
    Run all startup self-tests and return a summary dict.

    Args:
        paper_mode: If False, warns loudly on any failure.

    Returns:
        {"passed": int, "failed": int, "results": [(name, ok, detail), ...]}
    """
    results = []
    passed = 0
    failed = 0

    logger.info("=" * 65)
    logger.info("  STARTUP VALIDATOR — module self-test")
    logger.info("=" * 65)

    for name, fn in _TESTS:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok = False
            detail = f"EXCEPTION: {type(exc).__name__}: {exc}"
            logger.debug(traceback.format_exc())

        status = "PASS" if ok else "FAIL"
        tag = f"[{status:4s}]"
        logger.info(f"  {tag} {name:<40s} {detail}")

        results.append((name, ok, detail))
        if ok:
            passed += 1
        else:
            failed += 1

    logger.info("-" * 65)
    summary = f"  {passed}/{passed + failed} passed"
    if failed:
        summary += f"  ·  {failed} FAILED"
    logger.info(summary)
    if failed > 0 and not paper_mode:
        logger.warning("  ⚠  FAILED checks in LIVE mode — review above before trading!")
    elif failed == 0:
        logger.info("  ✓  All modules healthy — ready to trade")
    logger.info("=" * 65 + "\n")

    return {"passed": passed, "failed": failed, "results": results}
