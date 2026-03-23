"""
Main backtest engine — walks forward through every trading day,
evaluates ORB, VWAP Reclaim, EMA Pullback, and Momentum Breakout signals,
simulates option trades. Trend detection drives strategy priority + risk sizing.
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
from shared.trend_detector import detect_trend, STRATEGY_PRIORITY_BY_TREND, SL_TARGET_BY_STRATEGY, TREND_RISK_MULTIPLIER


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
    reclaim_window_end: str = "13:30"
    reclaim_min_rejection_points: float = 15.0

    # EMA Pullback
    enable_ema_pullback: bool = True
    ema_pullback_window_start: str = "09:30"
    ema_pullback_window_end: str = "13:00"
    ema_pullback_proximity_pct: float = 0.006
    ema_pullback_lookback_candles: int = 4

    # Momentum Breakout
    enable_momentum_breakout: bool = True
    momentum_breakout_window_start: str = "09:30"
    momentum_breakout_window_end: str = "12:00"
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

    # SL / Target
    atr_sl_multiplier: float = 2.0
    atr_sl_min_pct: float = 0.25
    atr_sl_max_pct: float = 0.40
    rr_min: float = 1.6
    trail_trigger_pct: float = 0.30
    trail_lock_step_pct: float = 0.15
    break_even_trigger_pct: float = 0.20
    thursday_max_loss_pct: float = 0.15

    # Execution
    force_exit_time: str = "15:15"
    max_trades_per_day: int = 2
    max_consecutive_losses: int = 5
    max_daily_loss_pct: float = 0.04
    slippage_pct: float = 0.005
    strike_step: int = 50


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
    risk_multiplier: float = 1.0,
    filters: Optional[Dict] = None,
) -> Optional[Dict]:
    """Run simulation for a signal and return completed trade dict or None."""
    # Per-strategy SL/target from trend_detector lookup
    sl_pct_base, target_pct_base = SL_TARGET_BY_STRATEGY.get(
        strategy_name, (cfg.atr_sl_min_pct, cfg.atr_sl_min_pct * cfg.rr_min)
    )
    # Clamp SL to configured range
    sl_pct = max(cfg.atr_sl_min_pct, min(cfg.atr_sl_max_pct, sl_pct_base))
    target_pct = sl_pct_base * cfg.rr_min if target_pct_base < sl_pct * cfg.rr_min else target_pct_base

    # Apply risk multiplier to lots (round down to nearest int, min 1)
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
        trail_trigger_pct=cfg.trail_trigger_pct,
        trail_lock_step_pct=cfg.trail_lock_step_pct,
        break_even_trigger_pct=cfg.break_even_trigger_pct,
        force_exit_time_str=cfg.force_exit_time,
        strike_step=cfg.strike_step,
        lot_size=cfg.lot_size,
        lots=effective_lots,
        slippage_pct=cfg.slippage_pct,
    )

    if trade["status"] != "COMPLETED":
        return None

    trade["strategy"] = strategy_name
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
    entry_close = dtime(*map(int, cfg.entry_window_close.split(":")))
    reclaim_start = dtime(*map(int, cfg.reclaim_window_start.split(":")))
    reclaim_end = dtime(*map(int, cfg.reclaim_window_end.split(":")))
    pb_start = dtime(*map(int, cfg.ema_pullback_window_start.split(":")))
    pb_end = dtime(*map(int, cfg.ema_pullback_window_end.split(":")))
    mb_start = dtime(*map(int, cfg.momentum_breakout_window_start.split(":")))
    mb_end = dtime(*map(int, cfg.momentum_breakout_window_end.split(":")))

    all_dates = sorted(nifty_df["ts"].dt.date.unique())
    if start_date:
        all_dates = [d for d in all_dates if d >= start_date]
    if end_date:
        all_dates = [d for d in all_dates if d <= end_date]

    all_trades: List[Dict[str, Any]] = []
    capital = cfg.capital
    consecutive_losses = 0
    daily_loss_limit = cfg.capital * cfg.max_daily_loss_pct

    if verbose:
        print(f"\n{'='*60}")
        print(f" BACKTEST: {len(all_dates)} trading days")
        print(f" Capital: ₹{cfg.capital:,.0f} | Lots: {cfg.lots} | Lot size: {cfg.lot_size}")
        print(f" Strategies: ORB + RELAXED_ORB + VWAP_RECLAIM + EMA_PULLBACK + MOMENTUM_BREAKOUT")
        print(f" SL: {cfg.atr_sl_min_pct*100:.0f}-{cfg.atr_sl_max_pct*100:.0f}% | RR: {cfg.rr_min}x | VIX<={cfg.vix_max}")
        print(f"{'='*60}\n")

    for trade_date in all_dates:
        candles = get_daily_candles(nifty_df, trade_date)
        if len(candles) < 20:
            continue

        vix = get_vix_for_date(vix_df, trade_date)
        is_thursday = trade_date.weekday() == 3

        daily_pnl = 0.0
        trades_today = 0
        orb_signal_used = False
        relaxed_orb_used = False
        reclaim_signal_used = False
        ema_pullback_used = False
        momentum_used = False

        # Allow one attempt per day even after consecutive loss streak
        if consecutive_losses >= cfg.max_consecutive_losses:
            consecutive_losses = cfg.max_consecutive_losses - 1

        # Detect trend at start of day (use first 12 candles = ~60 min for initial read)
        # We'll update it every 30 min as candles accumulate
        trend_result = None
        trend_updated_idx = 0

        for i, candle in enumerate(candles):
            if trades_today >= cfg.max_trades_per_day:
                break
            if consecutive_losses >= cfg.max_consecutive_losses:
                break
            if daily_pnl <= -daily_loss_limit:
                break

            c_time = candle["ts"].time()

            # Start trend detection after 12 candles (1 hour), refresh every 6 candles (30 min)
            if i >= 12 and (trend_result is None or (i - trend_updated_idx) >= 6):
                trend_result = detect_trend(candles[:i + 1], vix=vix)
                trend_updated_idx = i

            risk_multiplier = 1.0
            allowed_direction: Optional[str] = None   # None = both directions OK

            if trend_result is not None:
                risk_multiplier = TREND_RISK_MULTIPLIER.get(trend_result.state, 1.0)
                # VIX dampen
                if vix is not None:
                    if vix > 25:
                        risk_multiplier = min(risk_multiplier, 0.55)
                    elif vix > 20:
                        risk_multiplier = min(risk_multiplier, 0.75)

                # Direction alignment — only trade in trend direction on strong/moderate days
                if trend_result.direction in ("CALL", "PUT"):
                    allowed_direction = trend_result.direction

            strategy_priority = trend_result.strategy_priority if trend_result else [
                "ORB", "MOMENTUM_BREAKOUT", "EMA_PULLBACK", "VWAP_RECLAIM", "RELAXED_ORB"
            ]

            # ── ORB ───────────────────────────────────────────────────────
            if (
                not orb_signal_used
                and "ORB" in strategy_priority
                and orb_end <= c_time <= entry_close
            ):
                result = evaluate_orb_signal(
                    candles[:i + 1], candle, vix,
                    orb_start=orb_start, orb_end=orb_end,
                    trade_date=trade_date,
                    min_orb_range_points=cfg.min_orb_range_points,
                    max_orb_range_points=cfg.max_orb_range_points,
                    breakout_buffer_pct=cfg.breakout_buffer_pct,
                    min_breakout_body_ratio=cfg.min_breakout_body_ratio,
                    min_volume_surge_ratio=cfg.min_volume_surge_ratio,
                    ema_fast=cfg.ema_fast, ema_slow=cfg.ema_slow,
                    rsi_period=cfg.rsi_period, atr_period=cfg.atr_period,
                    require_vwap_confirmation=cfg.require_vwap_confirmation,
                    vwap_buffer_points=cfg.vwap_buffer_points,
                    rsi_bull_min=cfg.rsi_bull_min, rsi_bear_max=cfg.rsi_bear_max,
                    rsi_overbought_skip=cfg.rsi_overbought_skip,
                    rsi_oversold_skip=cfg.rsi_oversold_skip,
                    vix_max=cfg.vix_max,
                )

                if result["all_passed"] and result["signal"]:
                    if allowed_direction and result["signal"] != allowed_direction:
                        pass  # Skip counter-trend ORB signals
                    else:
                        trade = _simulate_trade(
                            i, candle, result["signal"], result["atr"],
                            "ORB", candles, trade_date, vix, is_thursday, cfg,
                            risk_multiplier=risk_multiplier, filters=result["filters"],
                        )
                        if trade:
                            all_trades.append(trade)
                            net = trade["net_pnl"]
                            daily_pnl += net
                            capital += net
                            trades_today += 1
                            orb_signal_used = True
                            consecutive_losses = 0 if net > 0 else consecutive_losses + 1
                            if verbose:
                                sign = "+" if net >= 0 else ""
                                print(f"  [{trade_date}] ORB  {result['signal']:4s} | "
                                      f"Entry={trade['entry_price']:.0f} Exit={trade['exit_price']:.0f} | "
                                      f"P&L: {sign}₹{net:.0f} | {trade['exit_reason']} | RM={risk_multiplier:.2f}")

            if trades_today >= cfg.max_trades_per_day:
                break

            # ── RELAXED ORB (wide-range days) ────────────────────────────
            if (
                not relaxed_orb_used
                and not orb_signal_used
                and "RELAXED_ORB" in strategy_priority
                and orb_end <= c_time <= entry_close
            ):
                result = evaluate_orb_signal(
                    candles[:i + 1], candle, vix,
                    orb_start=orb_start, orb_end=orb_end,
                    trade_date=trade_date,
                    min_orb_range_points=cfg.min_orb_range_points,
                    max_orb_range_points=cfg.relaxed_orb_max_range_points,
                    breakout_buffer_pct=cfg.breakout_buffer_pct,
                    min_breakout_body_ratio=0.35,
                    min_volume_surge_ratio=0.8,
                    ema_fast=cfg.ema_fast, ema_slow=cfg.ema_slow,
                    rsi_period=cfg.rsi_period, atr_period=cfg.atr_period,
                    require_vwap_confirmation=cfg.require_vwap_confirmation,
                    vwap_buffer_points=cfg.vwap_buffer_points,
                    rsi_bull_min=cfg.rsi_bull_min, rsi_bear_max=cfg.rsi_bear_max,
                    rsi_overbought_skip=cfg.rsi_overbought_skip,
                    rsi_oversold_skip=cfg.rsi_oversold_skip,
                    vix_max=cfg.vix_max,
                )

                if result["all_passed"] and result["signal"]:
                    if allowed_direction and result["signal"] != allowed_direction:
                        pass  # Skip counter-trend
                    else:
                        trade = _simulate_trade(
                            i, candle, result["signal"], result["atr"],
                            "RELAXED_ORB", candles, trade_date, vix, is_thursday, cfg,
                            risk_multiplier=risk_multiplier * 0.85, filters=result["filters"],
                        )
                        if trade:
                            all_trades.append(trade)
                            net = trade["net_pnl"]
                            daily_pnl += net
                            capital += net
                            trades_today += 1
                            relaxed_orb_used = True
                            orb_signal_used = True
                            consecutive_losses = 0 if net > 0 else consecutive_losses + 1
                            if verbose:
                                sign = "+" if net >= 0 else ""
                                print(f"  [{trade_date}] RORB {result['signal']:4s} | "
                                      f"Entry={trade['entry_price']:.0f} Exit={trade['exit_price']:.0f} | "
                                      f"P&L: {sign}₹{net:.0f} | {trade['exit_reason']}")

            if trades_today >= cfg.max_trades_per_day:
                break

            # ── MOMENTUM BREAKOUT ─────────────────────────────────────────
            if (
                cfg.enable_momentum_breakout
                and not momentum_used
                and "MOMENTUM_BREAKOUT" in strategy_priority
                and mb_start <= c_time <= mb_end
                and i >= 20
            ):
                mb = evaluate_momentum_breakout_signal(
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
                )

                if mb["all_passed"] and mb["signal"]:
                    if allowed_direction and mb["signal"] != allowed_direction:
                        pass  # Skip counter-trend
                    else:
                        trade = _simulate_trade(
                            i, candle, mb["signal"], mb["atr"],
                            "MOMENTUM_BREAKOUT", candles, trade_date, vix, is_thursday, cfg,
                            risk_multiplier=risk_multiplier, filters=mb["filters"],
                        )
                        if trade:
                            all_trades.append(trade)
                            net = trade["net_pnl"]
                            daily_pnl += net
                            capital += net
                            trades_today += 1
                            momentum_used = True
                            consecutive_losses = 0 if net > 0 else consecutive_losses + 1
                            if verbose:
                                sign = "+" if net >= 0 else ""
                                print(f"  [{trade_date}] MOM  {mb['signal']:4s} | "
                                      f"Entry={trade['entry_price']:.0f} Exit={trade['exit_price']:.0f} | "
                                      f"P&L: {sign}₹{net:.0f} | {trade['exit_reason']}")

            if trades_today >= cfg.max_trades_per_day:
                break

            # ── EMA PULLBACK ──────────────────────────────────────────────
            if (
                cfg.enable_ema_pullback
                and not ema_pullback_used
                and "EMA_PULLBACK" in strategy_priority
                and pb_start <= c_time <= pb_end
                and i >= 20
            ):
                pb = evaluate_ema_pullback_signal(
                    candles[:i + 1], i, vix,
                    ema_fast=cfg.ema_fast, ema_slow=cfg.ema_slow,
                    rsi_period=cfg.rsi_period, atr_period=cfg.atr_period,
                    pullback_proximity_pct=cfg.ema_pullback_proximity_pct,
                    lookback_candles=cfg.ema_pullback_lookback_candles,
                    vix_max=cfg.vix_max,
                )

                if pb["all_passed"] and pb["signal"]:
                    if allowed_direction and pb["signal"] != allowed_direction:
                        pass  # Skip counter-trend
                    else:
                        trade = _simulate_trade(
                            i, candle, pb["signal"], pb["atr"],
                            "EMA_PULLBACK", candles, trade_date, vix, is_thursday, cfg,
                            risk_multiplier=risk_multiplier, filters=pb["filters"],
                        )
                        if trade:
                            all_trades.append(trade)
                            net = trade["net_pnl"]
                            daily_pnl += net
                            capital += net
                            trades_today += 1
                            ema_pullback_used = True
                            consecutive_losses = 0 if net > 0 else consecutive_losses + 1
                            if verbose:
                                sign = "+" if net >= 0 else ""
                                print(f"  [{trade_date}] EMA  {pb['signal']:4s} | "
                                      f"Entry={trade['entry_price']:.0f} Exit={trade['exit_price']:.0f} | "
                                      f"P&L: {sign}₹{net:.0f} | {trade['exit_reason']}")

            if trades_today >= cfg.max_trades_per_day:
                break

            # ── VWAP RECLAIM ──────────────────────────────────────────────
            if (
                cfg.enable_vwap_reclaim
                and not reclaim_signal_used
                and "VWAP_RECLAIM" in strategy_priority
                and reclaim_start <= c_time <= reclaim_end
            ):
                reclaim = evaluate_vwap_reclaim_signal(
                    candles[:i + 1], i, vix,
                    reclaim_min_rejection_points=cfg.reclaim_min_rejection_points,
                    rsi_period=cfg.rsi_period, atr_period=cfg.atr_period,
                    vix_max=cfg.vix_max,
                )

                if reclaim["all_passed"] and reclaim["signal"]:
                    if allowed_direction and reclaim["signal"] != allowed_direction:
                        pass  # Skip counter-trend
                    else:
                        trade = _simulate_trade(
                            i, candle, reclaim["signal"], reclaim["atr"],
                            "VWAP_RECLAIM", candles, trade_date, vix, is_thursday, cfg,
                            risk_multiplier=risk_multiplier, filters=reclaim["filters"],
                        )
                        if trade:
                            all_trades.append(trade)
                            net = trade["net_pnl"]
                            daily_pnl += net
                            capital += net
                            trades_today += 1
                            reclaim_signal_used = True
                            consecutive_losses = 0 if net > 0 else consecutive_losses + 1
                            if verbose:
                                sign = "+" if net >= 0 else ""
                                print(f"  [{trade_date}] RCL  {reclaim['signal']:4s} | "
                                      f"Entry={trade['entry_price']:.0f} Exit={trade['exit_price']:.0f} | "
                                      f"P&L: {sign}₹{net:.0f} | {trade['exit_reason']}")

        sys.stdout.flush()

    metrics = compute_metrics(all_trades, cfg.capital)
    return {
        "trades": all_trades,
        "metrics": metrics,
        "config": cfg.__dict__,
        "start_date": all_dates[0].isoformat() if all_dates else None,
        "end_date": all_dates[-1].isoformat() if all_dates else None,
    }
