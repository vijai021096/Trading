"""
Dynamic Multi-Strategy Backtest Engine — 8-Regime + Tier-based sizing.

Architecture:
  Layer 1: Daily Regime (8 regimes) — gates direction + strategy pool + max trades
  Layer 2: Intraday Trend (every 6 bars) — priority + risk multiplier
  Layer 3: Strategy engines — RELAXED_ORB, EMA Pullback, VWAP Reclaim, Momentum Breakout
  Layer 4: Quality filter + Tier assignment — determines position size per trade

Trade Tiers (same SL/target/trail, different SIZING):
  Tier 1 (High Conviction): quality >= 4, strong trend -> 2.5% risk
  Tier 2 (Standard):        quality  = 3              -> 1.8% risk
  Tier 3 (Exploratory):     quality  = 2              -> 1.0% risk

CRITICAL: Regime = Permission, NOT Entry.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, time as dtime
from typing import Any, Dict, List, Optional

from backtest.data_downloader import get_daily_candles, get_vix_for_date
from backtest.options_simulator import run_intraday_simulation
from backtest.metrics import compute_metrics
from shared.orb_engine import evaluate_orb_signal, compute_sl_target
from shared.vwap_reclaim_engine import evaluate_vwap_reclaim_signal
from shared.ema_pullback_engine import evaluate_ema_pullback_signal
from shared.momentum_breakout_engine import evaluate_momentum_breakout_signal
from shared.trend_detector import (
    detect_trend, TrendState, STRATEGY_PRIORITY_BY_TREND,
    SL_TARGET_BY_STRATEGY, TREND_RISK_MULTIPLIER, TIER_PARAMS, assign_tier,
)
from shared.quality_filter import (
    compute_trade_quality, is_choppy_market, is_overextended,
    is_late_move, get_htf_direction, get_dynamic_blocklist, get_daily_bias,
)
from shared.regime_classifier import (
    classify_regime, DailyRegime, RegimeClassifierConfig, regime_conflicts_with_trend,
)


@dataclass
class BacktestConfig:
    capital: float = 100_000.0
    lot_size: int = 65
    lots: int = 1

    # ORB
    orb_start: str = "09:15"
    orb_end: str = "09:30"
    entry_window_close: str = "10:30"
    min_orb_range_points: float = 20.0
    max_orb_range_points: float = 200.0
    breakout_buffer_pct: float = 0.0003
    min_breakout_body_ratio: float = 0.40
    min_volume_surge_ratio: float = 1.0

    # RELAXED ORB
    relaxed_orb_max_range_points: float = 320.0

    # VWAP Reclaim
    enable_vwap_reclaim: bool = True
    reclaim_window_start: str = "10:00"
    reclaim_window_end: str = "14:00"
    reclaim_min_rejection_points: float = 15.0

    # EMA Pullback
    enable_ema_pullback: bool = True
    ema_pullback_window_start: str = "09:30"
    ema_pullback_window_end: str = "13:00"
    ema_pullback_proximity_pct: float = 0.006
    ema_pullback_lookback_candles: int = 4

    # Momentum Breakout
    enable_momentum_breakout: bool = False
    momentum_breakout_window_start: str = "09:30"
    momentum_breakout_window_end: str = "11:30"
    momentum_breakout_lookback: int = 20
    momentum_breakout_min_body_ratio: float = 0.50
    momentum_breakout_rsi_bull_min: float = 55.0
    momentum_breakout_rsi_bull_max: float = 78.0
    momentum_breakout_rsi_bear_min: float = 22.0
    momentum_breakout_rsi_bear_max: float = 45.0
    momentum_breakout_min_volume_surge: float = 1.3

    # Indicators
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    atr_period: int = 14

    # Filters
    require_vwap_confirmation: bool = True
    vwap_buffer_points: float = 5.0
    rsi_bull_min: float = 45.0
    rsi_bear_max: float = 55.0
    rsi_overbought_skip: float = 78.0
    rsi_oversold_skip: float = 22.0
    vix_max: float = 22.0

    # SL / Target (defaults — tier overrides risk_pct only)
    atr_sl_multiplier: float = 2.0
    atr_sl_min_pct: float = 0.15
    atr_sl_max_pct: float = 0.40
    rr_min: float = 1.4
    trail_trigger_pct: float = 0.30
    trail_lock_step_pct: float = 0.15
    break_even_trigger_pct: float = 0.15

    # Quality Filter
    min_quality_score: int = 3
    enable_quality_filter: bool = True
    enable_choppy_filter: bool = True
    enable_htf_filter: bool = True
    enable_overextended_filter: bool = True
    enable_dynamic_blocklist: bool = True
    enable_reentry: bool = True
    reentry_window_min: int = 30       # Re-entry allowed within 30 min of SL hit
    enable_daily_bias_filter: bool = True  # Gate trades on previous days' direction

    # Execution
    force_exit_time: str = "15:15"
    max_trades_per_day: int = 3
    max_consecutive_losses: int = 7
    max_daily_loss_pct: float = 0.04
    slippage_pct: float = 0.005
    strike_step: int = 50

    # Regime Classifier (8-regime)
    enable_regime_classifier: bool = True
    regime_vix_skip_threshold: float = 22.0
    regime_gap_skip_pct: float = 0.012
    regime_strong_gap_pct: float = 0.003
    regime_strong_5d_ret_pct: float = 0.01
    regime_breakout_prev_range_max: float = 120.0
    regime_pullback_5d_ret_pct: float = 0.005
    regime_pullback_flat_open_pct: float = 0.002
    regime_trend_conflict_after: str = "10:30"
    stop_after_2r_profit: bool = True
    max_entry_option_price: float = 120.0

    # EMA dead zone (11:00-11:30 empirically toxic)
    ema_pullback_dead_zone_start: str = "11:00"
    ema_pullback_dead_zone_end: str = "11:30"

    # Early session fast mode (9:15–10:00) — relaxed filters for strong early moves
    enable_early_session_mode: bool = True
    early_session_end: str = "10:00"
    early_session_body_ratio: float = 0.30      # relaxed from ~0.40
    early_session_rsi_bull_min: float = 38.0    # relaxed from 45
    early_session_rsi_bear_max: float = 62.0    # relaxed from 55
    early_session_volume_ratio: float = 0.9     # relaxed from 1.0

    # Missed move filter — skip entries if Nifty already moved too far
    enable_missed_move_filter: bool = True
    missed_move_pts: float = 175.0              # skip if >175pt move in last 30min
    missed_move_lookback_bars: int = 6          # 6 bars × 5min = 30min


def _quality_check(
    candles: List[Dict],
    i: int,
    signal: str,
    strategy_name: str,
    cfg: "BacktestConfig",
    blocklist: List[str],
    allowed_direction: Optional[str],
    htf_dir: str,
) -> Optional[str]:
    """Returns None if trade should be taken, or a rejection reason string."""
    if strategy_name in blocklist:
        return f"blocked:{strategy_name}"

    if allowed_direction and signal != allowed_direction:
        return f"counter_direction:{signal}!={allowed_direction}"

    if cfg.enable_htf_filter and htf_dir not in (signal, "NEUTRAL"):
        return f"htf_conflict:{htf_dir}"

    if cfg.enable_overextended_filter and is_overextended(candles, i, signal):
        return "overextended"

    return None


def _simulate_trade(
    i: int,
    candle: Dict,
    signal: str,
    atr: float,
    strategy_name: str,
    candles: List[Dict],
    trade_date: date,
    vix: Optional[float],
    is_thursday: bool,
    cfg: BacktestConfig,
    tier: int,
    risk_multiplier: float = 1.0,
    filters: Optional[Dict] = None,
    otm_offset: int = 0,
) -> Optional[Dict]:
    """Run simulation using tier-specific risk sizing."""
    tp = TIER_PARAMS[tier]

    sl_pct = tp["sl_pct"]
    target_pct = tp["target_pct"]
    trail_trigger = tp["trail_trigger"]
    trail_lock = tp["trail_lock"]

    sl_pct = max(cfg.atr_sl_min_pct, min(cfg.atr_sl_max_pct, sl_pct))

    effective_lots = max(1, int(cfg.lots * risk_multiplier))

    trade = run_intraday_simulation(
        entry_candle_idx=i,
        entry_spot=float(candle["close"]),
        direction=signal,
        candles=candles,
        trade_date=trade_date,
        vix=vix,
        sl_pct=sl_pct,
        target_pct=target_pct,
        trail_trigger_pct=trail_trigger,
        trail_lock_step_pct=trail_lock,
        break_even_trigger_pct=cfg.break_even_trigger_pct,
        force_exit_time_str=cfg.force_exit_time,
        strike_step=cfg.strike_step,
        lot_size=cfg.lot_size,
        lots=effective_lots,
        slippage_pct=cfg.slippage_pct,
        otm_offset=otm_offset,
    )

    if trade["status"] != "COMPLETED":
        return None

    if cfg.max_entry_option_price > 0 and trade["entry_price"] > cfg.max_entry_option_price:
        return None

    trade["strategy"] = strategy_name
    trade["tier"] = tier
    trade["filter_log"] = filters or {}
    trade["risk_multiplier"] = risk_multiplier
    return trade


def run_backtest(
    nifty_df,
    vix_df,
    cfg: BacktestConfig,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    import pandas as pd

    orb_start = dtime(*map(int, cfg.orb_start.split(":")))
    orb_end = dtime(*map(int, cfg.orb_end.split(":")))
    reclaim_start = dtime(*map(int, cfg.reclaim_window_start.split(":")))
    reclaim_end = dtime(*map(int, cfg.reclaim_window_end.split(":")))
    pb_start = dtime(*map(int, cfg.ema_pullback_window_start.split(":")))
    pb_end = dtime(*map(int, cfg.ema_pullback_window_end.split(":")))
    mb_start = dtime(*map(int, cfg.momentum_breakout_window_start.split(":")))
    mb_end = dtime(*map(int, cfg.momentum_breakout_window_end.split(":")))
    conflict_time = dtime(*map(int, cfg.regime_trend_conflict_after.split(":")))
    ema_dead_start = dtime(*map(int, cfg.ema_pullback_dead_zone_start.split(":")))
    ema_dead_end = dtime(*map(int, cfg.ema_pullback_dead_zone_end.split(":")))
    early_session_end = dtime(*map(int, cfg.early_session_end.split(":")))

    all_candles_list = nifty_df.to_dict("records")

    regime_cfg = RegimeClassifierConfig(
        vix_skip_threshold=cfg.regime_vix_skip_threshold,
        gap_skip_pct=cfg.regime_gap_skip_pct,
        strong_gap_pct=cfg.regime_strong_gap_pct,
        strong_5d_ret_pct=cfg.regime_strong_5d_ret_pct,
        breakout_prev_range_max=cfg.regime_breakout_prev_range_max,
        pullback_5d_ret_pct=cfg.regime_pullback_5d_ret_pct,
        pullback_flat_open_pct=cfg.regime_pullback_flat_open_pct,
    )

    all_dates = sorted(nifty_df["ts"].dt.date.unique())
    if start_date:
        all_dates = [d for d in all_dates if d >= start_date]
    if end_date:
        all_dates = [d for d in all_dates if d <= end_date]

    all_trades: List[Dict[str, Any]] = []
    capital = cfg.capital
    consecutive_losses = 0
    daily_loss_limit = cfg.capital * cfg.max_daily_loss_pct

    regime_counts: Dict[str, int] = {}

    if verbose:
        print(f"\n{'='*70}")
        print(f" DYNAMIC MULTI-STRATEGY BACKTEST: {len(all_dates)} trading days")
        print(f" Capital: ₹{cfg.capital:,.0f} | Lots: {cfg.lots} | Lot size: {cfg.lot_size}")
        print(f" Strategies: RELAXED_ORB + EMA_PULLBACK + VWAP_RECLAIM (regime-gated)")
        print(f" Tier system: T1(q>=4,2.5%) T2(q=3,1.8%) T3(q=2,1%)")
        print(f" Max trades/day: regime-defined (up to 3)")
        print(f"{'='*70}\n")

    for trade_date in all_dates:
        candles = get_daily_candles(nifty_df, trade_date)
        if len(candles) < 20:
            continue

        vix = get_vix_for_date(vix_df, trade_date)
        is_thursday = trade_date.weekday() == 3

        # ── LAYER 1: Daily Regime ──────────────────────────────
        if cfg.enable_regime_classifier:
            regime = classify_regime(all_candles_list, trade_date, vix, regime_cfg)
            regime_counts[regime.name] = regime_counts.get(regime.name, 0) + 1

            if not regime.should_trade:
                if verbose:
                    print(f"  [{trade_date}] REGIME: {regime.name} — SKIP ({regime.detail})")
                continue

            regime_direction = regime.allowed_direction
            regime_strategies = set(regime.allowed_strategies)
            regime_max_trades = regime.execution.max_trades
            regime_min_quality = regime.execution.min_quality_score
            regime_risk_pct = regime.execution.risk_pct
            regime_otm = regime.otm_offset
            regime_window_start = dtime(*map(int, regime.execution.window_start.split(":")))
            regime_window_end = dtime(*map(int, regime.execution.window_end.split(":")))
        else:
            regime = None
            regime_direction = None
            regime_strategies = {"RELAXED_ORB", "EMA_PULLBACK", "VWAP_RECLAIM"}
            regime_max_trades = cfg.max_trades_per_day
            regime_min_quality = cfg.min_quality_score
            regime_risk_pct = 0.02
            regime_otm = 0
            regime_window_start = dtime(9, 30)
            regime_window_end = dtime(15, 15)

        if verbose:
            r_name = regime.name if regime else "OFF"
            print(f"  [{trade_date}] REGIME: {r_name} | dir={regime_direction} | "
                  f"strats={sorted(regime_strategies)} | max={regime_max_trades}")

        daily_pnl = 0.0
        trades_today = 0
        strategies_used: Dict[str, int] = {}
        day_stopped_profit = False

        last_sl_time: Optional[Any] = None
        last_sl_direction: Optional[str] = None
        reentry_used = False

        if consecutive_losses >= cfg.max_consecutive_losses:
            consecutive_losses = cfg.max_consecutive_losses - 1

        # Daily bias gate — look at last 3 days to set allowed direction for today
        # Prevents taking CALL trades when daily context is clearly bearish (Sep 2025 fix)
        daily_bias = get_daily_bias(nifty_df, trade_date) if cfg.enable_daily_bias_filter else "NEUTRAL"
        daily_bias_direction: Optional[str] = (
            "CALL" if daily_bias == "BULL" else
            "PUT"  if daily_bias == "BEAR" else
            None
        )

        # Detect trend at start of day (use first 12 candles = ~60 min for initial read)
        # We'll update it every 30 min as candles accumulate
        trend_result = None
        trend_updated_idx = 0

        for i, candle in enumerate(candles):
            if trades_today >= regime_max_trades:
                break
            if consecutive_losses >= cfg.max_consecutive_losses:
                break
            if daily_pnl <= -daily_loss_limit:
                break
            if day_stopped_profit:
                break

            c_time = candle["ts"].time()

            if c_time < regime_window_start or c_time > regime_window_end:
                continue

            # ── LAYER 2: Intraday Trend (refresh every 6 bars ~30 min) ──
            if i >= 12 and (trend_result is None or (i - trend_updated_idx) >= 6):
                trend_result = detect_trend(candles[:i + 1], vix=vix or 15.0)
                trend_updated_idx = i

            risk_multiplier = 1.0
            allowed_direction = regime_direction

            if trend_result is not None:
                risk_multiplier = TREND_RISK_MULTIPLIER.get(trend_result.state, 1.0)
                if vix is not None:
                    if vix > 25:
                        risk_multiplier = min(risk_multiplier, 0.55)
                    elif vix > 20:
                        risk_multiplier = min(risk_multiplier, 0.75)

                if (cfg.enable_regime_classifier
                        and regime is not None
                        and c_time >= conflict_time
                        and regime_conflicts_with_trend(regime, trend_result.direction)):
                    risk_multiplier *= 0.5
                    if risk_multiplier < 0.3:
                        continue

                if allowed_direction is None and trend_result.direction in ("CALL", "PUT"):
                    allowed_direction = trend_result.direction

            # Apply daily bias — overrides intraday direction when daily context is clear
            # If daily says BEAR but intraday says CALL → conflict → skip (set to None which blocks)
            if daily_bias_direction is not None:
                if allowed_direction is None:
                    allowed_direction = daily_bias_direction   # daily fills neutral intraday
                elif allowed_direction != daily_bias_direction:
                    allowed_direction = daily_bias_direction   # daily wins over intraday conflict

            # ── FIX 5: Missed move filter — skip if market moved too far already ──
            if cfg.enable_missed_move_filter and i >= cfg.missed_move_lookback_bars:
                start_close = float(candles[i - cfg.missed_move_lookback_bars]["close"])
                current_close = float(candle["close"])
                move_pts = abs(current_close - start_close)
                if move_pts >= cfg.missed_move_pts:
                    continue  # Missed the move — late entry risk

            # ── FIX 3: Early session flag (9:15-10:00) ──
            is_early_session = cfg.enable_early_session_mode and c_time < early_session_end

            # When trend is unknown (early session), only run ORB-family — no MB/EMA_PB
            strategy_priority = trend_result.strategy_priority if trend_result else [
                "ORB", "RELAXED_ORB"
            ]
            strategy_priority = [s for s in strategy_priority if s in regime_strategies]

            trend_state = trend_result.state if trend_result else TrendState.NEUTRAL
            trend_state_str = trend_state.value if trend_result else "NEUTRAL"
            choppy = cfg.enable_choppy_filter and is_choppy_market(candles, i)
            blocklist = get_dynamic_blocklist(trend_state_str, choppy) if cfg.enable_dynamic_blocklist else []
            htf_dir = get_htf_direction(candles, i) if cfg.enable_htf_filter else "NEUTRAL"

            def _try_trade(strategy_name, result, window_ok):
                nonlocal trades_today, daily_pnl, capital, consecutive_losses
                nonlocal day_stopped_profit, last_sl_time, last_sl_direction

                if not window_ok:
                    return False
                if not (result["all_passed"] and result["signal"]):
                    return False

                max_per_strategy = 2
                if strategies_used.get(strategy_name, 0) >= max_per_strategy:
                    return False

                sig = result["signal"]
                skip = _quality_check(candles, i, sig, strategy_name, cfg, blocklist, allowed_direction, htf_dir)
                if skip:
                    return False

                if cfg.enable_quality_filter:
                    q = compute_trade_quality(candles, i, sig)
                    if q["score"] < regime_min_quality:
                        return False
                    quality_score = q["score"]
                else:
                    quality_score = 3

                tier = assign_tier(quality_score, trend_state)

                trade = _simulate_trade(
                    i, candle, sig, result.get("atr", 0),
                    strategy_name, candles, trade_date, vix, is_thursday, cfg,
                    tier=tier, risk_multiplier=risk_multiplier,
                    filters=result.get("filters"),
                    otm_offset=regime_otm,
                )
                if not trade:
                    return False

                trade["regime"] = regime.name if regime else "NONE"
                trade["quality_score"] = quality_score
                trade["otm_offset"] = regime_otm
                all_trades.append(trade)

                net = trade["net_pnl"]
                daily_pnl += net
                capital += net
                trades_today += 1
                strategies_used[strategy_name] = strategies_used.get(strategy_name, 0) + 1

                if net <= 0:
                    consecutive_losses += 1
                    last_sl_time = candle["ts"]
                    last_sl_direction = sig
                else:
                    consecutive_losses = 0

                if cfg.stop_after_2r_profit and net > 0:
                    tp = TIER_PARAMS[tier]
                    entry_risk = trade["entry_price"] * tp["sl_pct"] * trade["qty"]
                    if daily_pnl >= entry_risk * 2:
                        day_stopped_profit = True

                if verbose:
                    sign = "+" if net >= 0 else ""
                    r_name = regime.name if regime else "?"
                    print(f"  [{trade_date}] T{tier} {strategy_name:15s} {sig:4s} [{r_name}] "
                          f"| Entry={trade['entry_price']:.0f} Exit={trade['exit_price']:.0f} "
                          f"| P&L: {sign}₹{net:.0f} | {trade['exit_reason']} | Q={quality_score}/5")

                return True

            # ── RELAXED ORB ────────────────────────────────────
            if "RELAXED_ORB" in strategy_priority:
                orb_window = orb_end <= c_time <= min(dtime(*map(int, cfg.entry_window_close.split(":"))), regime_window_end)
                # FIX 3/4: Early session uses relaxed filters (FAST MODE)
                _body = cfg.early_session_body_ratio if is_early_session else 0.35
                _vol = cfg.early_session_volume_ratio if is_early_session else 0.8
                _rsi_bull = cfg.early_session_rsi_bull_min if is_early_session else cfg.rsi_bull_min
                _rsi_bear = cfg.early_session_rsi_bear_max if is_early_session else cfg.rsi_bear_max
                result = evaluate_orb_signal(
                    candles[:i + 1], candle, vix,
                    orb_start=orb_start, orb_end=orb_end,
                    trade_date=trade_date,
                    min_orb_range_points=cfg.min_orb_range_points,
                    max_orb_range_points=cfg.relaxed_orb_max_range_points,
                    breakout_buffer_pct=cfg.breakout_buffer_pct,
                    min_breakout_body_ratio=_body,
                    min_volume_surge_ratio=_vol,
                    ema_fast=cfg.ema_fast, ema_slow=cfg.ema_slow,
                    rsi_period=cfg.rsi_period, atr_period=cfg.atr_period,
                    require_vwap_confirmation=cfg.require_vwap_confirmation,
                    vwap_buffer_points=cfg.vwap_buffer_points,
                    rsi_bull_min=_rsi_bull, rsi_bear_max=_rsi_bear,
                    rsi_overbought_skip=cfg.rsi_overbought_skip,
                    rsi_oversold_skip=cfg.rsi_oversold_skip,
                    vix_max=cfg.vix_max,
                ) if orb_window else {"all_passed": False, "signal": None}
                if _try_trade("RELAXED_ORB", result, orb_window):
                    if trades_today >= regime_max_trades or day_stopped_profit:
                        continue

            # ── MOMENTUM BREAKOUT ──────────────────────────────
            if (cfg.enable_momentum_breakout
                    and "MOMENTUM_BREAKOUT" in strategy_priority
                    and trend_state in (TrendState.STRONG_BULL, TrendState.STRONG_BEAR)):
                mb_window = mb_start <= c_time <= min(mb_end, regime_window_end) and i >= 20
                result = evaluate_momentum_breakout_signal(
                    candles[:i + 1], i, vix,
                    breakout_lookback=cfg.momentum_breakout_lookback,
                    min_body_ratio=cfg.momentum_breakout_min_body_ratio,
                    rsi_period=cfg.rsi_period, atr_period=cfg.atr_period,
                    rsi_bull_min=cfg.momentum_breakout_rsi_bull_min,
                    rsi_bull_max=cfg.momentum_breakout_rsi_bull_max,
                    rsi_bear_min=cfg.momentum_breakout_rsi_bear_min,
                    rsi_bear_max=cfg.momentum_breakout_rsi_bear_max,
                    min_volume_surge_ratio=cfg.momentum_breakout_min_volume_surge,
                    vix_max=cfg.vix_max,
                    ema_fast=cfg.ema_fast, ema_slow=cfg.ema_slow,
                ) if mb_window else {"all_passed": False, "signal": None}
                if _try_trade("MOMENTUM_BREAKOUT", result, mb_window):
                    if trades_today >= regime_max_trades or day_stopped_profit:
                        continue

            # ── EMA PULLBACK ───────────────────────────────────
            if cfg.enable_ema_pullback and "EMA_PULLBACK" in strategy_priority:
                ema_window = (pb_start <= c_time <= min(pb_end, regime_window_end)
                              and not (ema_dead_start <= c_time < ema_dead_end)
                              and i >= 20)
                # FIX 3/4: Early session uses relaxed EMA pullback proximity (wider catch zone)
                _pb_prox = cfg.ema_pullback_proximity_pct * 1.5 if is_early_session else cfg.ema_pullback_proximity_pct
                _pb_body = max(0.28, 0.38 - 0.10) if is_early_session else 0.38
                result = evaluate_ema_pullback_signal(
                    candles[:i + 1], i, vix,
                    ema_fast=cfg.ema_fast, ema_slow=cfg.ema_slow,
                    rsi_period=cfg.rsi_period, atr_period=cfg.atr_period,
                    pullback_proximity_pct=_pb_prox,
                    min_body_ratio=_pb_body,
                    lookback_candles=cfg.ema_pullback_lookback_candles,
                    vix_max=cfg.vix_max,
                ) if ema_window else {"all_passed": False, "signal": None}
                if _try_trade("EMA_PULLBACK", result, ema_window):
                    if trades_today >= regime_max_trades or day_stopped_profit:
                        continue

            # ── VWAP RECLAIM ───────────────────────────────────
            if cfg.enable_vwap_reclaim and "VWAP_RECLAIM" in strategy_priority:
                vwap_window = reclaim_start <= c_time <= min(reclaim_end, regime_window_end)
                result = evaluate_vwap_reclaim_signal(
                    candles[:i + 1], i, vix,
                    reclaim_min_rejection_points=cfg.reclaim_min_rejection_points,
                    rsi_period=cfg.rsi_period, atr_period=cfg.atr_period,
                    vix_max=cfg.vix_max,
                ) if vwap_window else {"all_passed": False, "signal": None}
                if _try_trade("VWAP_RECLAIM", result, vwap_window):
                    if trades_today >= regime_max_trades or day_stopped_profit:
                        continue

            # ── RE-ENTRY ───────────────────────────────────────
            if (cfg.enable_reentry
                    and not reentry_used
                    and last_sl_time is not None
                    and last_sl_direction is not None
                    and trades_today < regime_max_trades
                    and consecutive_losses < cfg.max_consecutive_losses
                    and daily_pnl > -daily_loss_limit
                    and not day_stopped_profit
                    and "VWAP_RECLAIM" in regime_strategies):
                from datetime import timedelta
                reentry_window = timedelta(minutes=cfg.reentry_window_min)
                if candle["ts"] - last_sl_time <= reentry_window:
                    if reclaim_start <= c_time <= min(reclaim_end, regime_window_end):
                        re_reclaim = evaluate_vwap_reclaim_signal(
                            candles[:i + 1], i, vix,
                            reclaim_min_rejection_points=cfg.reclaim_min_rejection_points,
                            rsi_period=cfg.rsi_period, atr_period=cfg.atr_period,
                            vix_max=cfg.vix_max,
                        )
                        if (re_reclaim["all_passed"] and re_reclaim["signal"] == last_sl_direction):
                            q = compute_trade_quality(candles, i, re_reclaim["signal"])
                            if q["tradeable"] and not (allowed_direction and re_reclaim["signal"] != allowed_direction):
                                tier = assign_tier(q["score"], trend_state)
                                trade = _simulate_trade(
                                    i, candle, re_reclaim["signal"], re_reclaim.get("atr", 0),
                                    "VWAP_RECLAIM", candles, trade_date, vix, is_thursday, cfg,
                                    tier=tier, risk_multiplier=risk_multiplier * 0.75,
                                    filters=re_reclaim.get("filters"),
                                    otm_offset=regime_otm,
                                )
                                if trade:
                                    trade["strategy"] = "VWAP_RECLAIM_REENTRY"
                                    trade["regime"] = regime.name if regime else "NONE"
                                    trade["quality_score"] = q["score"]
                                    trade["otm_offset"] = regime_otm
                                    all_trades.append(trade)
                                    net = trade["net_pnl"]
                                    daily_pnl += net
                                    capital += net
                                    trades_today += 1
                                    reentry_used = True
                                    if net <= 0:
                                        consecutive_losses += 1
                                    else:
                                        consecutive_losses = 0
                                        last_sl_time = None
                                    if verbose:
                                        sign = "+" if net >= 0 else ""
                                        print(f"  [{trade_date}] T{tier} RE-ENTRY     {re_reclaim['signal']:4s} | "
                                              f"Entry={trade['entry_price']:.0f} | P&L: {sign}₹{net:.0f}")

        sys.stdout.flush()

    if verbose and cfg.enable_regime_classifier:
        print(f"\n{'='*70}")
        print(f" REGIME DISTRIBUTION ({len(all_dates)} trading days)")
        print(f"{'='*70}")
        for name, count in sorted(regime_counts.items(), key=lambda x: -x[1]):
            pct = count / len(all_dates) * 100
            print(f"  {name:20s}: {count:4d} days ({pct:5.1f}%)")
        print()

    metrics = compute_metrics(all_trades, cfg.capital)
    return {
        "trades": all_trades,
        "metrics": metrics,
        "config": cfg.__dict__,
        "start_date": all_dates[0].isoformat() if all_dates else None,
        "end_date": all_dates[-1].isoformat() if all_dates else None,
        "regime_distribution": regime_counts if cfg.enable_regime_classifier else {},
    }
