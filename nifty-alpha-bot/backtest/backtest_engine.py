"""
Main backtest engine — walks forward through every trading day,
evaluates ORB and VWAP Reclaim signals, simulates option trades.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, time as dtime
from typing import Any, Dict, List, Optional

from backtest.data_downloader import get_daily_candles, get_vix_for_date
from backtest.options_simulator import run_intraday_simulation
from backtest.metrics import compute_metrics
from shared.orb_engine import evaluate_orb_signal, compute_sl_target
from shared.vwap_reclaim_engine import evaluate_vwap_reclaim_signal


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

    # VWAP Reclaim
    enable_vwap_reclaim: bool = True
    reclaim_window_start: str = "10:00"
    reclaim_window_end: str = "13:30"
    reclaim_min_rejection_points: float = 15.0

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
        print(f" Strategy: ORB {cfg.orb_start}-{cfg.orb_end} + VWAP Reclaim")
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
        reclaim_signal_used = False

        # Allow one attempt per day even after consecutive loss streak
        if consecutive_losses >= cfg.max_consecutive_losses:
            consecutive_losses = cfg.max_consecutive_losses - 1

        for i, candle in enumerate(candles):
            if trades_today >= cfg.max_trades_per_day:
                break
            if consecutive_losses >= cfg.max_consecutive_losses:
                break
            if daily_pnl <= -daily_loss_limit:
                break

            c_time = candle["ts"].time()

            # ORB entry window
            if not orb_signal_used and orb_end <= c_time <= entry_close:
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
                    sl_target = compute_sl_target(
                        100.0,
                        result["signal"],
                        result["atr"],
                        atr_sl_multiplier=cfg.atr_sl_multiplier,
                        atr_sl_min_pct=cfg.atr_sl_min_pct,
                        atr_sl_max_pct=cfg.atr_sl_max_pct,
                        rr_min=cfg.rr_min,
                        is_thursday=is_thursday,
                        thursday_max_loss_pct=cfg.thursday_max_loss_pct,
                    )

                    trade = run_intraday_simulation(
                        entry_candle_idx=i,
                        entry_spot=float(candle["close"]),
                        direction=result["signal"],
                        candles=candles,
                        trade_date=trade_date,
                        vix=vix,
                        sl_pct=sl_target["sl_pct"],
                        target_pct=sl_target["target_pct"],
                        trail_trigger_pct=cfg.trail_trigger_pct,
                        trail_lock_step_pct=cfg.trail_lock_step_pct,
                        break_even_trigger_pct=cfg.break_even_trigger_pct,
                        force_exit_time_str=cfg.force_exit_time,
                        strike_step=cfg.strike_step,
                        lot_size=cfg.lot_size,
                        lots=cfg.lots,
                        slippage_pct=cfg.slippage_pct,
                    )

                    if trade["status"] == "COMPLETED":
                        trade["strategy"] = "ORB"
                        trade["filter_log"] = result["filters"]
                        all_trades.append(trade)
                        net = trade["net_pnl"]
                        daily_pnl += net
                        capital += net
                        trades_today += 1
                        orb_signal_used = True

                        if net > 0:
                            consecutive_losses = 0
                        else:
                            consecutive_losses += 1

                        if verbose:
                            sign = "+" if net >= 0 else ""
                            print(
                                f"  [{trade_date}] ORB {result['signal']:4s} | "
                                f"Entry={trade['entry_price']:.0f} Exit={trade['exit_price']:.0f} | "
                                f"P&L: {sign}₹{net:.0f} | {trade['exit_reason']}"
                            )

            # VWAP Reclaim window
            if (
                cfg.enable_vwap_reclaim
                and not reclaim_signal_used
                and reclaim_start <= c_time <= reclaim_end
                and trades_today < cfg.max_trades_per_day
            ):
                reclaim = evaluate_vwap_reclaim_signal(
                    candles[:i + 1], i, vix,
                    reclaim_min_rejection_points=cfg.reclaim_min_rejection_points,
                    rsi_period=cfg.rsi_period, atr_period=cfg.atr_period,
                    vix_max=cfg.vix_max,
                )

                if reclaim["all_passed"] and reclaim["signal"]:
                    sl_target = compute_sl_target(
                        100.0,
                        reclaim["signal"],
                        reclaim["atr"],
                        atr_sl_multiplier=cfg.atr_sl_multiplier,
                        atr_sl_min_pct=cfg.atr_sl_min_pct,
                        atr_sl_max_pct=cfg.atr_sl_max_pct,
                        rr_min=cfg.rr_min,
                        is_thursday=is_thursday,
                    )

                    trade = run_intraday_simulation(
                        entry_candle_idx=i,
                        entry_spot=float(candle["close"]),
                        direction=reclaim["signal"],
                        candles=candles,
                        trade_date=trade_date,
                        vix=vix,
                        sl_pct=sl_target["sl_pct"],
                        target_pct=sl_target["target_pct"],
                        trail_trigger_pct=cfg.trail_trigger_pct,
                        trail_lock_step_pct=cfg.trail_lock_step_pct,
                        break_even_trigger_pct=cfg.break_even_trigger_pct,
                        force_exit_time_str=cfg.force_exit_time,
                        strike_step=cfg.strike_step,
                        lot_size=cfg.lot_size,
                        lots=cfg.lots,
                        slippage_pct=cfg.slippage_pct,
                    )

                    if trade["status"] == "COMPLETED":
                        trade["strategy"] = "VWAP_RECLAIM"
                        trade["filter_log"] = reclaim["filters"]
                        all_trades.append(trade)
                        net = trade["net_pnl"]
                        daily_pnl += net
                        capital += net
                        trades_today += 1
                        reclaim_signal_used = True

                        if net > 0:
                            consecutive_losses = 0
                        else:
                            consecutive_losses += 1

                        if verbose:
                            sign = "+" if net >= 0 else ""
                            print(
                                f"  [{trade_date}] RCL {reclaim['signal']:4s} | "
                                f"Entry={trade['entry_price']:.0f} Exit={trade['exit_price']:.0f} | "
                                f"P&L: {sign}₹{net:.0f} | {trade['exit_reason']}"
                            )

        sys.stdout.flush()

    metrics = compute_metrics(all_trades, cfg.capital)
    return {
        "trades": all_trades,
        "metrics": metrics,
        "config": cfg.__dict__,
        "start_date": all_dates[0].isoformat() if all_dates else None,
        "end_date": all_dates[-1].isoformat() if all_dates else None,
    }
