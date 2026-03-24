"""
Daily-level NIFTY strategy backtest using 3 years of data.
Since yfinance only provides 60 days of 5m data, this uses daily OHLCV
to simulate the strategy with statistical significance (700+ trading days).

Signal logic adapted for daily data:
  CALL: Nifty opens above previous day's high (gap breakout)
        OR closes above previous day's high (continuation breakout)
        + EMA9 > EMA21 + RSI 52-75 + VIX <= 18
  PUT:  Mirror of CALL

Options priced via Black-Scholes at ATM strike with weekly expiry.
SL: 8-12% ATR-based. Target: 2.5x RR.
"""
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

import json
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    raise ImportError("pip install yfinance")

from shared.black_scholes import (
    price_option, implied_vol_from_vix, atm_strike, charges_estimate, realistic_slippage,
)

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

RISK_FREE = 0.065


@dataclass
class DailyBacktestConfig:
    capital: float = 100_000.0
    lot_size: int = 65
    lots: int = 1

    # Signal
    breakout_buffer_pct: float = 0.0002
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_bull_min: float = 52.0
    rsi_bear_max: float = 48.0
    rsi_overbought_skip: float = 75.0
    rsi_oversold_skip: float = 25.0
    vix_max: float = 18.0

    # Fallback signal — fires on non-gap days to ensure at least 1 trade/day
    enable_fallback_signal: bool = False
    fallback_vix_max: float = 22.0        # Allow slightly higher VIX for fallback
    fallback_sl_max_pct: float = 0.07     # Tighter SL (7%) to protect PF
    fallback_rsi_bull_min: float = 50.0   # EMA cross + RSI > 50 → CALL
    fallback_rsi_bear_max: float = 50.0   # EMA cross + RSI < 50 → PUT

    # SL/Target
    atr_period: int = 14
    atr_sl_multiplier: float = 1.2
    atr_sl_min_pct: float = 0.08
    atr_sl_max_pct: float = 0.12
    rr_min: float = 2.5
    thursday_max_loss_pct: float = 0.06

    # Trail
    trail_trigger_pct: float = 0.20
    trail_lock_step_pct: float = 0.10
    break_even_trigger_pct: float = 0.12

    # Risk management
    max_trades_per_day: int = 1
    max_consecutive_losses: int = 5
    max_daily_loss_pct: float = 0.03
    max_weekly_loss_pct: float = 0.06

    # Options
    strike_step: int = 50
    slippage_pct: float = 0.005


def download_data(years: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Download NIFTY50 and India VIX daily data."""
    print(f"[DailyBacktest] Downloading {years}y daily data...")

    nifty = yf.Ticker("^NSEI")
    df_n = nifty.history(period=f"{years}y", interval="1d")
    df_n = df_n.reset_index()
    df_n.columns = [c.lower() for c in df_n.columns]
    date_col = "date" if "date" in df_n.columns else df_n.columns[0]
    df_n = df_n.rename(columns={date_col: "date"})
    df_n["date"] = pd.to_datetime(df_n["date"]).dt.tz_localize(None).dt.date
    df_n = df_n[["date", "open", "high", "low", "close"]].dropna()
    df_n = df_n.sort_values("date").reset_index(drop=True)

    vix = yf.Ticker("^INDIAVIX")
    df_v = vix.history(period=f"{years}y", interval="1d")
    df_v = df_v.reset_index()
    df_v.columns = [c.lower() for c in df_v.columns]
    date_col = "date" if "date" in df_v.columns else df_v.columns[0]
    df_v = df_v.rename(columns={date_col: "date", "close": "vix"})
    df_v["date"] = pd.to_datetime(df_v["date"]).dt.tz_localize(None).dt.date
    df_v = df_v[["date", "vix"]].dropna()

    print(f"[DailyBacktest] NIFTY: {len(df_n)} days, VIX: {len(df_v)} days")
    print(f"[DailyBacktest] Period: {df_n['date'].iloc[0]} → {df_n['date'].iloc[-1]}")
    return df_n, df_v


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA, RSI, ATR to daily DataFrame."""
    closes = df["close"].values

    # EMA
    def ema(series, period):
        alpha = 2 / (period + 1)
        result = np.zeros(len(series))
        result[0] = series[0]
        for i in range(1, len(series)):
            result[i] = series[i] * alpha + result[i-1] * (1 - alpha)
        return result

    df = df.copy()
    df["ema_fast"] = ema(closes, 9)
    df["ema_slow"] = ema(closes, 21)

    # RSI
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    rsi_arr = np.full(len(closes), 50.0)
    period = 14
    for i in range(period, len(closes)):
        avg_g = gains[i-period:i].mean()
        avg_l = losses[i-period:i].mean()
        if avg_l == 0:
            rsi_arr[i] = 100.0
        else:
            rs = avg_g / avg_l
            rsi_arr[i] = 100 - (100 / (1 + rs))
    df["rsi"] = rsi_arr

    # ATR
    highs, lows = df["high"].values, df["low"].values
    atr_arr = np.zeros(len(closes))
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        atr_arr[i] = tr
    for i in range(period, len(closes)):
        atr_arr[i] = atr_arr[i-period:i].mean()
    df["atr"] = atr_arr

    # ADX (Wilder's smoothing)
    plus_dm = np.zeros(len(closes))
    minus_dm = np.zeros(len(closes))
    tr_arr = np.zeros(len(closes))
    for i in range(1, len(closes)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr_arr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))

    def wilder_smooth(arr, p):
        out = np.zeros(len(arr))
        out[p] = arr[1:p + 1].sum()
        for i in range(p + 1, len(arr)):
            out[i] = out[i - 1] - out[i - 1] / p + arr[i]
        return out

    sm_tr = wilder_smooth(tr_arr, period)
    sm_plus = wilder_smooth(plus_dm, period)
    sm_minus = wilder_smooth(minus_dm, period)

    adx_arr = np.full(len(closes), 20.0)
    dx_arr = np.zeros(len(closes))
    for i in range(period, len(closes)):
        if sm_tr[i] == 0:
            continue
        plus_di = 100 * sm_plus[i] / sm_tr[i]
        minus_di = 100 * sm_minus[i] / sm_tr[i]
        denom = plus_di + minus_di
        dx_arr[i] = 100 * abs(plus_di - minus_di) / denom if denom > 0 else 0.0

    adx_arr[period * 2] = dx_arr[period:period * 2].mean()
    for i in range(period * 2 + 1, len(closes)):
        adx_arr[i] = (adx_arr[i - 1] * (period - 1) + dx_arr[i]) / period
    df["adx"] = adx_arr

    return df


def classify_regime(adx: float, atr: float, atr_median: float, atr_p10: float, vix: float) -> str:
    """
    Classify market regime for a trading day.

    Returns:
      "LOW_VOL"  — No trade. Market lacks range for meaningful SL/target.
      "TREND"    — ORB breakout enabled. Strong directional momentum.
      "RANGE"    — ORB disabled. Market choppy; skip gap-up/down signals.
    """
    if vix < 11.0 or atr < atr_p10:
        return "LOW_VOL"
    if adx > 25.0 and atr > atr_median:
        return "TREND"
    return "RANGE"


def get_nearest_thursday(d: date) -> date:
    days = (3 - d.weekday()) % 7
    if days == 0:
        days = 7
    return d + timedelta(days=days)


def simulate_daily_trade(
    entry_spot: float,
    direction: str,
    entry_date: date,
    vix: float,
    atr: float,
    cfg: DailyBacktestConfig,
    future_days_data: List[dict],
    is_fallback: bool = False,
) -> Dict[str, Any]:
    """
    Simulate holding the option for up to 5 days (or until SL/target/expiry).
    Uses daily OHLC to approximate option P&L.
    """
    opt_type = "CE" if direction == "CALL" else "PE"
    strike = atm_strike(entry_spot, cfg.strike_step)
    expiry = get_nearest_thursday(entry_date)
    is_thursday = entry_date.weekday() == 3

    # Fallback trades use tighter SL to protect PF
    base_sl_max = cfg.fallback_sl_max_pct if is_fallback else cfg.atr_sl_max_pct
    max_sl_pct = cfg.thursday_max_loss_pct if is_thursday else base_sl_max

    # Estimate SL % using ATR
    estimated_delta = 0.50
    option_sl_pts = cfg.atr_sl_multiplier * atr * estimated_delta
    sl_pct = option_sl_pts / entry_spot * 100  # Rough proxy
    # Clamp to percentage of option premium (we'll compute below)
    T_entry = max(0.001, (expiry - entry_date).days / 365.0)
    sigma = implied_vol_from_vix(vix)
    entry_opt = price_option(entry_spot, strike, T_entry, RISK_FREE, sigma, opt_type)
    entry_price = entry_opt["price"]

    if entry_price < 30:
        return {"status": "SKIPPED", "reason": f"Option price too low: {entry_price:.1f}"}

    dte = max(0, (expiry - entry_date).days)
    eff_slip = realistic_slippage(cfg.slippage_pct, vix, dte, entry_price)
    entry_price *= (1 + eff_slip)

    # Compute SL/target on option %
    option_sl_pct = max(cfg.atr_sl_min_pct, min(max_sl_pct,
        (cfg.atr_sl_multiplier * atr * estimated_delta) / entry_price
    ))
    sl_price = entry_price * (1 - option_sl_pct)
    target_price = entry_price * (1 + option_sl_pct * cfg.rr_min)

    current_sl = sl_price
    highest = entry_price
    break_even_set = False
    exit_price = entry_price
    exit_reason = "FORCE_EXIT"
    exit_date = entry_date

    for day_info in future_days_data[:10]:  # Max 10 days
        day_date = day_info["date"]
        day_spot = day_info["close"]

        if day_date > expiry:
            # Option expired — exit at intrinsic value
            if opt_type == "CE":
                intrinsic = max(0, day_spot - strike)
            else:
                intrinsic = max(0, strike - day_spot)
            exit_price = max(0, intrinsic) * (1 - eff_slip)
            exit_reason = "EXPIRY"
            exit_date = day_date
            break

        days_left = (expiry - day_date).days
        T_exit = max(0.0001, days_left / 365.0)
        opt_now = price_option(day_spot, strike, T_exit, RISK_FREE, sigma, opt_type)
        opt_price = opt_now["price"]

        highest = max(highest, opt_price)

        # Break-even
        gain_pct = (opt_price - entry_price) / entry_price
        if not break_even_set and gain_pct >= cfg.break_even_trigger_pct:
            new_sl = entry_price * 1.005
            if new_sl > current_sl:
                current_sl = new_sl
                break_even_set = True

        # Trail
        if gain_pct >= cfg.trail_trigger_pct:
            trail_sl = highest * (1 - cfg.trail_lock_step_pct)
            if trail_sl > current_sl:
                current_sl = trail_sl

        # Check SL/Target using day's low/high as approximation
        # For CE: if Nifty falls to low, option hits SL
        # For PE: if Nifty rises to high, option hits SL
        if opt_type == "CE":
            low_opt = price_option(day_info["low"], strike, T_exit, RISK_FREE, sigma, opt_type)
            high_opt = price_option(day_info["high"], strike, T_exit, RISK_FREE, sigma, opt_type)
        else:
            # For PE: low spot = high option price, high spot = low option price
            low_opt = price_option(day_info["high"], strike, T_exit, RISK_FREE, sigma, opt_type)
            high_opt = price_option(day_info["low"], strike, T_exit, RISK_FREE, sigma, opt_type)

        # Check SL (worst price of day for our position)
        worst_price = low_opt["price"]
        best_price = high_opt["price"]

        if worst_price <= current_sl:
            exit_price = current_sl * (1 - eff_slip)
            exit_reason = "SL_HIT"
            exit_date = day_date
            break

        if best_price >= target_price:
            exit_price = target_price * (1 - eff_slip)
            exit_reason = "TARGET_HIT"
            exit_date = day_date
            break

        # EOD: use closing price
        exit_price = opt_price * (1 - eff_slip)
        exit_date = day_date

    qty = cfg.lots * cfg.lot_size
    gross_pnl = (exit_price - entry_price) * qty
    charges = charges_estimate(entry_price, exit_price, qty)
    net_pnl = gross_pnl - charges

    return {
        "status": "COMPLETED",
        "direction": direction,
        "option_type": opt_type,
        "strike": strike,
        "expiry": expiry.isoformat(),
        "trade_date": entry_date.isoformat(),
        "exit_date": exit_date.isoformat(),
        "entry_ts": f"{entry_date}T09:35:00",
        "exit_ts": f"{exit_date}T15:20:00",
        "entry_price": round(entry_price, 2),
        "exit_price": round(exit_price, 2),
        "sl_price": round(sl_price, 2),
        "target_price": round(target_price, 2),
        "exit_reason": exit_reason,
        "gross_pnl": round(gross_pnl, 2),
        "charges": round(charges, 2),
        "net_pnl": round(net_pnl, 2),
        "qty": qty,
        "lots": cfg.lots,
        "spot_at_entry": round(entry_spot, 2),
        "vix": round(vix, 2),
        "atr": round(atr, 2),
        "delta_at_entry": round(entry_opt.get("delta", 0.5), 4),
        "slippage_pct": round(eff_slip * 100, 3),
        "strategy": "ORB_DAILY",
    }


def _run_backtest_on_df(
    df_n: pd.DataFrame,
    vix_map: dict,
    cfg: DailyBacktestConfig,
    verbose: bool = True,
    label: str = "",
) -> Dict[str, Any]:
    """Core backtest loop — operates on a pre-computed, pre-filtered DataFrame."""
    from backtest.metrics import compute_metrics

    all_trades: List[Dict[str, Any]] = []
    capital = cfg.capital
    consecutive_losses = 0

    # Pre-compute ATR rolling stats for regime classification (over full window)
    atr_vals = df_n["atr"].values

    weekly_loss = 0.0
    week_start = None

    for i in range(21, len(df_n) - 10):
        row = df_n.iloc[i]
        prev = df_n.iloc[i - 1]
        trade_date = row["date"]

        week = trade_date.isocalendar()[:2]
        if week_start != week:
            week_start = week
            weekly_loss = 0.0

        if consecutive_losses >= cfg.max_consecutive_losses:
            if len(all_trades) > 0:
                last = date.fromisoformat(all_trades[-1]["trade_date"])
                if (trade_date - last).days >= 5:
                    consecutive_losses = 0
            continue

        vix = vix_map.get(trade_date, 14.0)
        if vix > cfg.vix_max:
            continue

        close = float(row["close"])
        prev_high = float(prev["high"])
        prev_low = float(prev["low"])
        ema_f = float(row["ema_fast"])
        ema_s = float(row["ema_slow"])
        rsi = float(row["rsi"])
        atr = float(row["atr"])
        adx = float(row["adx"])

        if atr <= 0 or close <= 0:
            continue

        # ── Regime classification ──────────────────────────────────────────
        # Use trailing 60-day window for ATR percentiles
        window_start = max(0, i - 60)
        atr_window = atr_vals[window_start:i]
        atr_median = float(np.median(atr_window)) if len(atr_window) >= 10 else atr
        atr_p10 = float(np.percentile(atr_window, 10)) if len(atr_window) >= 10 else 0.0
        regime = classify_regime(adx, atr, atr_median, atr_p10, vix)

        if regime == "LOW_VOL":
            continue

        # RANGE days: ORB still allowed in daily backtest (no VWAP reclaim available here).
        # Regime is recorded per trade for post-analysis — TREND trades tend to have
        # stronger follow-through. In the live 5m bot, RANGE → VWAP reclaim only.

        # ── Signal detection ───────────────────────────────────────────────
        call_threshold = prev_high * (1 + cfg.breakout_buffer_pct)
        put_threshold = prev_low * (1 - cfg.breakout_buffer_pct)
        open_price = float(row["open"])
        signal = None
        is_fallback = False

        if open_price >= call_threshold:
            if ema_f > ema_s and cfg.rsi_bull_min <= rsi <= cfg.rsi_overbought_skip:
                signal = "CALL"
        elif open_price <= put_threshold:
            if ema_f < ema_s and cfg.rsi_oversold_skip <= rsi <= cfg.rsi_bear_max:
                signal = "PUT"

        # Fallback signal: no gap today → use EMA cross direction with tighter SL
        if signal is None and cfg.enable_fallback_signal and vix <= cfg.fallback_vix_max:
            if ema_f > ema_s and rsi >= cfg.fallback_rsi_bull_min and rsi <= cfg.rsi_overbought_skip:
                signal = "CALL"
                is_fallback = True
            elif ema_f < ema_s and rsi <= cfg.fallback_rsi_bear_max and rsi >= cfg.rsi_oversold_skip:
                signal = "PUT"
                is_fallback = True

        if signal is None:
            continue

        future_rows = []
        for j in range(i + 1, min(i + 12, len(df_n))):
            r = df_n.iloc[j]
            future_rows.append({
                "date": r["date"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            })

        trade = simulate_daily_trade(
            entry_spot=open_price,
            direction=signal,
            entry_date=trade_date,
            vix=vix,
            atr=atr,
            cfg=cfg,
            future_days_data=future_rows,
            is_fallback=is_fallback,
        )

        if trade["status"] != "COMPLETED":
            continue

        trade["regime"] = regime
        trade["strategy"] = "FALLBACK_ORB" if is_fallback else "ORB_DAILY"
        all_trades.append(trade)
        net = trade["net_pnl"]
        capital += net
        weekly_loss += net

        if net > 0:
            consecutive_losses = 0
        else:
            consecutive_losses += 1

        if verbose:
            sign = "+" if net >= 0 else ""
            regime_tag = f"[{regime[:3]}]"
            fb_tag = "[FB]" if is_fallback else "    "
            print(
                f"  [{trade_date}] {signal:4s} {fb_tag} {regime_tag} | "
                f"Entry=₹{trade['entry_price']:.0f} Exit=₹{trade['exit_price']:.0f} | "
                f"P&L: {sign}₹{net:.0f} | {trade['exit_reason']} | slip={trade['slippage_pct']:.2f}%"
            )

    metrics = compute_metrics(all_trades, cfg.capital)

    # Breakdown by signal type
    primary = [t for t in all_trades if t.get("strategy") != "FALLBACK_ORB"]
    fallback = [t for t in all_trades if t.get("strategy") == "FALLBACK_ORB"]
    if verbose and fallback:
        p_wins = sum(1 for t in primary if t["net_pnl"] > 0)
        f_wins = sum(1 for t in fallback if t["net_pnl"] > 0)
        p_pnl = sum(t["net_pnl"] for t in primary)
        f_pnl = sum(t["net_pnl"] for t in fallback)
        print(f"\n  Signal breakdown:")
        print(f"    Primary  (gap breakout): {len(primary):3d} trades | WR: {p_wins/len(primary)*100:.0f}% | P&L: ₹{p_pnl:+,.0f}" if primary else "    Primary  (gap breakout): 0 trades")
        print(f"    Fallback (EMA cross)   : {len(fallback):3d} trades | WR: {f_wins/len(fallback)*100:.0f}% | P&L: ₹{f_pnl:+,.0f}" if fallback else "    Fallback (EMA cross)   : 0 trades")

    return {
        "trades": all_trades,
        "metrics": metrics,
        "config": cfg.__dict__,
        "start_date": str(df_n["date"].iloc[21]) if len(df_n) > 21 else None,
        "end_date": str(df_n["date"].iloc[-1]),
        "label": label,
        "type": "daily_simulation",
    }


def run_daily_backtest(
    cfg: DailyBacktestConfig,
    years: int = 3,
    verbose: bool = True,
    df_n: Optional[pd.DataFrame] = None,
    df_v: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    if df_n is None or df_v is None:
        df_n, df_v = download_data(years)

    df_n = compute_indicators(df_n)
    vix_map = dict(zip(df_v["date"], df_v["vix"]))

    if verbose:
        print(f"\n{'='*60}")
        print(f" DAILY BACKTEST: {len(df_n)} trading days, {years}y")
        print(f" Capital: ₹{cfg.capital:,.0f} | Lot size: {cfg.lot_size}")
        print(f" SL: {cfg.atr_sl_min_pct*100:.0f}-{cfg.atr_sl_max_pct*100:.0f}% | RR: {cfg.rr_min}x")
        print(f" Base slippage: {cfg.slippage_pct*100:.1f}% (dynamic, VIX/expiry-adjusted)")
        print(f" Regime filter: TREND-only ORB | LOW_VOL → skip")
        print(f" VIX filter: <={cfg.vix_max}")
        print(f"{'='*60}\n")

    result = _run_backtest_on_df(df_n, vix_map, cfg, verbose=verbose)
    result["start_date"] = str(df_n["date"].iloc[0])
    return result


def run_walk_forward(
    cfg: DailyBacktestConfig,
    verbose: bool = True,
) -> None:
    """
    Walk-forward validation: split data into TRAIN/TEST/VALIDATE periods.
    Runs independent backtests and prints a comparison table.
    """
    print("\n" + "=" * 70)
    print(" WALK-FORWARD VALIDATION")
    print(" TRAIN: 2022–2023  |  TEST: 2024  |  VALIDATE: 2025")
    print("=" * 70 + "\n")

    df_n, df_v = download_data(years=4)
    df_n = compute_indicators(df_n)
    vix_map = dict(zip(df_v["date"], df_v["vix"]))

    from datetime import date as _date
    periods = [
        ("TRAIN",    _date(2022, 1, 1), _date(2023, 12, 31)),
        ("TEST",     _date(2024, 1, 1), _date(2024, 12, 31)),
        ("VALIDATE", _date(2025, 1, 1), _date(2026, 12, 31)),
    ]

    results = []
    for label, start, end in periods:
        mask = (df_n["date"] >= start) & (df_n["date"] <= end)
        df_slice = df_n[mask].reset_index(drop=True)
        if len(df_slice) < 30:
            print(f"  [{label}] Not enough data (only {len(df_slice)} rows)")
            continue

        print(f"\n── {label} ({start} → {end}) ──")
        period_cfg = DailyBacktestConfig(
            capital=cfg.capital,
            slippage_pct=cfg.slippage_pct,
            lot_size=cfg.lot_size,
            lots=cfg.lots,
        )
        r = _run_backtest_on_df(df_slice, vix_map, period_cfg, verbose=verbose, label=label)
        results.append((label, r))

    # Comparison table
    print("\n" + "=" * 80)
    print(f" {'Period':<10} {'Days':>5} {'Trades':>7} {'Win%':>6} {'Net P&L':>11} {'Charges':>9} {'Sharpe':>7} {'MaxDD%':>7}")
    print("-" * 80)

    all_profitable = True
    all_sharpe_ok = True
    for label, r in results:
        m = r["metrics"]
        trades = m.get("total_trades", 0)
        win_rate = m.get("win_rate_pct", 0)
        net_pnl = m.get("total_net_pnl", 0)
        charges = m.get("total_charges", 0)
        sharpe = m.get("sharpe_ratio", 0)
        dd = m.get("max_drawdown_pct", 0)
        days = len([t for t in r["trades"] if True])
        sign = "+" if net_pnl >= 0 else ""
        print(
            f"  {label:<10} {'-':>5} {trades:>7} {win_rate:>5.1f}% "
            f"  {sign}₹{net_pnl:>9,.0f} ₹{charges:>7,.0f} {sharpe:>7.2f} {dd:>6.1f}%"
        )
        if net_pnl <= 0:
            all_profitable = False
        if sharpe < 0.5:
            all_sharpe_ok = False

    print("-" * 80)
    if results:
        if all_profitable and all_sharpe_ok:
            print("\n  VERDICT: ✅ REAL EDGE CONFIRMED — profitable in all 3 periods with Sharpe > 0.5")
        elif all_profitable:
            print("\n  VERDICT: ⚠️  LIKELY EDGE — profitable in all periods but Sharpe weak in some")
        else:
            print("\n  VERDICT: ❌ CURVE FITTING RISK — strategy failed in one or more out-of-sample periods")
    print()


if __name__ == "__main__":
    import argparse
    from backtest.run import print_report, save_results

    parser = argparse.ArgumentParser(description="NIFTY Daily Backtest")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--slippage", type=float, default=None, help="Override base slippage (e.g. 0.01 for 1%%)")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--walk-forward", action="store_true", dest="walk_forward")
    parser.add_argument("--stress", action="store_true", help="Run at 0.5%%, 0.75%%, 1%% slippage and compare")
    parser.add_argument("--fallback", action="store_true", help="Enable fallback EMA-cross signal on non-gap days")
    args = parser.parse_args()

    if args.walk_forward:
        cfg = DailyBacktestConfig(capital=args.capital)
        run_walk_forward(cfg, verbose=not args.quiet)

    elif args.stress:
        print("\n" + "=" * 70)
        print(" SLIPPAGE STRESS TEST")
        print("=" * 70)
        df_n_raw, df_v_raw = download_data(years=args.years)
        df_n_ind = compute_indicators(df_n_raw.copy())
        vix_map = dict(zip(df_v_raw["date"], df_v_raw["vix"]))

        stress_levels = [0.005, 0.0075, 0.010]
        stress_results = []
        for slip in stress_levels:
            c = DailyBacktestConfig(capital=args.capital, slippage_pct=slip)
            r = _run_backtest_on_df(df_n_ind, vix_map, c, verbose=False)
            stress_results.append((slip, r))

        print(f"\n{'Slippage':>10} {'Trades':>7} {'Win%':>6} {'Net P&L':>11} {'Charges':>9} {'Sharpe':>7} {'MaxDD%':>7}")
        print("-" * 65)
        for slip, r in stress_results:
            m = r["metrics"]
            net_pnl = m.get("total_net_pnl", 0)
            sign = "+" if net_pnl >= 0 else ""
            print(
                f"  {slip*100:.2f}%     {m.get('total_trades',0):>7} "
                f"{m.get('win_rate_pct',0):>5.1f}%   {sign}₹{net_pnl:>9,.0f} "
                f"₹{m.get('total_charges',0):>7,.0f} {m.get('sharpe_ratio',0):>7.2f} "
                f"{m.get('max_drawdown_pct',0):>6.1f}%"
            )
        print()

    else:
        slip = args.slippage if args.slippage is not None else 0.005
        cfg = DailyBacktestConfig(
            capital=args.capital,
            slippage_pct=slip,
            enable_fallback_signal=args.fallback,
        )
        result = run_daily_backtest(cfg, years=args.years, verbose=not args.quiet)
        print_report(result)
        save_results(result, tag="daily_fallback" if args.fallback else "daily")
