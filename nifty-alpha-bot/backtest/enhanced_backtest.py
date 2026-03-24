"""
Enhanced Backtest: Tests three improvements over the baseline:

  1. ITM Strike Selection   — buy 1 or 2 strikes ITM instead of ATM
                              (better delta, less IV-crush risk)

  2. 5-min First-Candle     — confirm signal direction with 9:15 candle
     Confirmation            before entering; skip if first candle fights signal

  3. ORB Second-Chance      — when daily scan finds no signal, use the
                              9:15-9:30 Opening Range Breakout as entry

  4. 10:30 Trend Window     — if still no entry by 10:25, re-evaluate
                              the intraday VWAP trend for a late entry

Parts A & B run on full daily data (2+ years).
Parts C & D need 5-min data (37 days available from yfinance).

Results are combined at the end into a projected full-period estimate.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backtest.daily_backtest_engine import (
    DailyBacktestConfig,
    run_daily_backtest,
    _get_weekly_expiry,
    _classify_regime,
    _strategies_scan_order,
    _check_trend_continuation,
    _check_breakout_momentum,
    _check_reversal_snap,
    _check_gap_fade,
    _check_range_bounce,
    _check_inside_bar_break,
    _check_vwap_cross,
    _check_ema_fresh_cross,
    SL_TARGET_MAP,
    STRATEGY_FILTER_MAP,
    REGIME_SL_TARGET_ADJUST,
    _ema, _rsi, _atr, _directional_movement, _bollinger_bandwidth,
)
from backtest.data_downloader import download_nifty_daily, download_india_vix, download_nifty_spot, get_vix_for_date
from backtest.metrics import compute_metrics
from shared.black_scholes import (
    price_option, implied_vol_from_vix, atm_strike,
    charges_estimate, realistic_slippage,
)

RISK_FREE_RATE = 0.065

# Groww-style ORB parameters (mirrors groww.py LiveConfig)
ORB_RANGE_MIN = 50.0    # groww: min_orb_range_points = 50
ORB_RANGE_MAX = 180.0   # groww: max_orb_range_points = 180 (relaxed from 90)
ORB_BUFFER_PCT = 0.0005 # groww: breakout_buffer_pct = 0.0005 (0.05% of level)
ORB_FALLBACK_SL  = 0.18
ORB_FALLBACK_TGT = 0.38


def _orb_groww(day_candles: pd.DataFrame) -> Optional[Tuple[str, float]]:
    """
    Groww-style ORB: build 9:15–9:30 range, scan for clean break until 10:30.
    Returns (direction, entry_price) or None.
    """
    from datetime import time as dtime
    orb_bars = day_candles[
        (day_candles["ts"].dt.time >= dtime(9, 15)) &
        (day_candles["ts"].dt.time <  dtime(9, 30))
    ]
    if len(orb_bars) < 2:
        return None
    orb_high  = float(orb_bars["high"].max())
    orb_low   = float(orb_bars["low"].min())
    orb_range = orb_high - orb_low
    if not (ORB_RANGE_MIN <= orb_range <= ORB_RANGE_MAX):
        return None

    up_level = orb_high * (1 + ORB_BUFFER_PCT)
    dn_level = orb_low  * (1 - ORB_BUFFER_PCT)

    post_orb = day_candles[
        (day_candles["ts"].dt.time >= dtime(9, 30)) &
        (day_candles["ts"].dt.time <= dtime(10, 30))
    ]
    for _, bar in post_orb.iterrows():
        c = float(bar["close"])
        if c > up_level:
            return ("CALL", c)
        if c < dn_level:
            return ("PUT", c)
    return None


# ═══════════════════════════════════════════════════════════════════
# PART A: ITM COMPARISON
# ═══════════════════════════════════════════════════════════════════

def run_itm_backtest(
    nifty_df: pd.DataFrame,
    vix_df: pd.DataFrame,
    itm_offset_points: int = 0,   # 0=ATM, 50=1-strike ITM, 100=2-strike ITM
) -> Dict[str, Any]:
    """Same as standard backtest but with ITM strike selection."""
    from backtest.daily_backtest_engine import (
        _simulate_option_trade as _sim_orig
    )

    cfg = DailyBacktestConfig(
        capital=25000, lot_size=65, lots=1, max_lots_cap=1,
    )

    # Monkey-patch strike selection for this run
    _orig_atm = atm_strike.__module__

    def _simulate_itm(
        spot_entry, direction, trade_date, vix,
        day_high, day_low, day_close, sl_pct, target_pct, cfg,
        lots_override=0,
    ):
        from shared.black_scholes import price_option, implied_vol_from_vix, charges_estimate, realistic_slippage

        expiry = _get_weekly_expiry(trade_date)
        # ITM offset: CE → strike BELOW spot, PE → strike ABOVE spot
        base_strike = atm_strike(spot_entry, cfg.strike_step)
        if direction == "CALL":
            strike = max(base_strike - itm_offset_points, base_strike - 200)
        else:
            strike = min(base_strike + itm_offset_points, base_strike + 200)
        # Round to nearest strike_step
        strike = round(strike / cfg.strike_step) * cfg.strike_step

        opt_type = "CE" if direction == "CALL" else "PE"
        dte = (expiry - trade_date).days
        moneyness = spot_entry / strike
        sigma = implied_vol_from_vix(vix, moneyness)
        iv_crush = -0.005 * (vix / 15.0)

        T_entry = max(0.0001, (dte * 0.71 + 0.5) / 252.0)
        entry_opt = price_option(spot_entry, strike, T_entry, RISK_FREE_RATE, sigma, opt_type)
        raw_entry = entry_opt["price"]
        if raw_entry < cfg.min_option_premium:
            return None

        entry_slip = realistic_slippage(cfg.slippage_pct, vix, dte, raw_entry)
        entry_price = raw_entry * (1 + entry_slip)
        sl_price = entry_price * (1 - sl_pct)
        target_price = entry_price * (1 + target_pct)

        # Simulate intraday path
        spot_move_range = day_high - day_low
        if direction == "CALL":
            best_spot = spot_entry + spot_move_range * 0.62
            worst_spot = spot_entry - spot_move_range * 0.22
        else:
            best_spot = spot_entry - spot_move_range * 0.62
            worst_spot = spot_entry + spot_move_range * 0.22

        T_mid = max(0.0001, (dte * 0.71 + 0.2) / 252.0)
        sigma_mid = max(0.01, sigma + iv_crush * 0.5)

        best_opt = price_option(best_spot, strike, T_mid, RISK_FREE_RATE, sigma_mid, opt_type)
        worst_opt = price_option(worst_spot, strike, T_mid, RISK_FREE_RATE, sigma_mid, opt_type)

        best_price = best_opt["price"]
        worst_price = worst_opt["price"]

        exit_price_raw = entry_price
        exit_reason = "EOD_EXIT"

        if worst_price <= sl_price:
            exit_price_raw = sl_price
            exit_reason = "SL_HIT"
        elif best_price >= target_price:
            exit_price_raw = target_price
            exit_reason = "TARGET_HIT"
        else:
            T_eod = max(0.0001, (dte * 0.71 - 0.1) / 252.0)
            sigma_eod = max(0.01, sigma + iv_crush)
            eod_opt = price_option(day_close, strike, T_eod, RISK_FREE_RATE, sigma_eod, opt_type)
            eod_price = eod_opt["price"]
            if eod_price > entry_price * 1.08:
                exit_price_raw = eod_price
                exit_reason = "EOD_PROFIT"
            else:
                exit_price_raw = eod_price

        exit_slip = realistic_slippage(cfg.slippage_pct, vix, dte, exit_price_raw)
        exit_price = exit_price_raw * (1 - exit_slip)

        effective_lots = lots_override if lots_override > 0 else cfg.lots
        qty = effective_lots * cfg.lot_size
        gross_pnl = (exit_price - entry_price) * qty
        charges = charges_estimate(entry_price, exit_price, qty)
        net_pnl = gross_pnl - charges

        return {
            "status": "COMPLETED",
            "direction": direction,
            "option_type": opt_type,
            "strike": strike,
            "itm_offset": itm_offset_points,
            "expiry": expiry.isoformat(),
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "sl_price": round(sl_price, 2),
            "target_price": round(target_price, 2),
            "exit_reason": exit_reason,
            "gross_pnl": round(gross_pnl, 2),
            "charges": round(charges, 2),
            "net_pnl": round(net_pnl, 2),
            "qty": qty,
            "lots": effective_lots,
            "delta_at_entry": round(entry_opt.get("delta", 0.5), 4),
            "vix": vix,
            "trade_date": trade_date.isoformat(),
        }

    # Temporarily patch the backtest engine's simulate function
    import backtest.daily_backtest_engine as eng
    _orig_sim = eng._simulate_option_trade
    eng._simulate_option_trade = _simulate_itm
    try:
        result = run_daily_backtest(nifty_df, vix_df, cfg, verbose=False)
    finally:
        eng._simulate_option_trade = _orig_sim

    return result


# ═══════════════════════════════════════════════════════════════════
# PART B: 5-min indicator helpers
# ═══════════════════════════════════════════════════════════════════

def _compute_vwap_intraday(candles: pd.DataFrame) -> pd.Series:
    tp = (candles["high"] + candles["low"] + candles["close"]) / 3
    tp_vol = tp * candles["volume"].clip(lower=1)
    return tp_vol.cumsum() / candles["volume"].clip(lower=1).cumsum()


def _compute_ema_series(values: list, period: int) -> list:
    return _ema(values, period)


# ═══════════════════════════════════════════════════════════════════
# PART C: 5-min confirmation filter on real 5-min data
# ═══════════════════════════════════════════════════════════════════

def _five_min_confirmed(
    day_candles: pd.DataFrame,
    signal: str,
    max_wait_candles: int = 3,    # Wait up to 3 candles (9:15, 9:20, 9:25)
) -> Tuple[bool, Optional[float], str]:
    """
    Check if the first 1-3 5-min candles confirm the signal direction.
    Returns: (confirmed, entry_price, candle_time)
    - Signal CALL: need a GREEN candle (close > open)
    - Signal PUT: need a RED candle (close < open)

    Entry is at the CLOSE of the confirming candle (not blind open).
    """
    early = day_candles[
        (day_candles["ts"].dt.time >= datetime.strptime("09:15", "%H:%M").time()) &
        (day_candles["ts"].dt.time <= datetime.strptime("09:30", "%H:%M").time())
    ].copy()

    for _, row in early.iterrows():
        candle_dir = "CALL" if row["close"] > row["open"] else "PUT"
        if candle_dir == signal:
            return True, float(row["close"]), str(row["ts"].time())

    return False, None, ""


def _five_min_confirmation_backtest(
    nifty_5m: pd.DataFrame,
    nifty_daily: pd.DataFrame,
    vix_df: pd.DataFrame,
) -> Dict[str, Any]:
    """
    On the 37 days of 5-min data:
    - Run daily signal engine to get signal for each day
    - Apply 5-min first-candle confirmation gate
    - Measure: how many signals were confirmed vs skipped
    - Of the confirmed signals: what was the WR vs baseline (no confirmation)?
    """
    nifty_5m = nifty_5m.copy()
    nifty_5m["ts"] = pd.to_datetime(nifty_5m["ts"])
    nifty_5m["date"] = nifty_5m["ts"].dt.date
    days_5m = sorted(nifty_5m["date"].unique())

    cfg = DailyBacktestConfig(capital=25000, lot_size=65, lots=1, max_lots_cap=1)

    # Precompute daily indicators
    nifty_daily = nifty_daily.copy()
    nifty_daily["ts"] = pd.to_datetime(nifty_daily["ts"])
    nifty_daily = nifty_daily.sort_values("ts").reset_index(drop=True)
    closes = nifty_daily["close"].tolist()
    highs = nifty_daily["high"].tolist()
    lows = nifty_daily["low"].tolist()
    opens_d = nifty_daily["open"].tolist()
    volumes_d = nifty_daily["volume"].tolist()
    dates_d = nifty_daily["ts"].dt.date.tolist()

    ema_f = _ema(closes, cfg.ema_fast)
    ema_s = _ema(closes, cfg.ema_slow)
    ema_t = _ema(closes, cfg.ema_trend)
    rsi_v = _rsi(closes, cfg.rsi_period)
    atr_v = _atr(highs, lows, closes, cfg.atr_period)
    adx_v = _directional_movement(highs, lows, closes, cfg.atr_period)
    bb_w  = _bollinger_bandwidth(closes, cfg.bb_period, cfg.bb_std)
    atr_sma_period = 50
    atr_sma = [0.0] * len(atr_v)
    for idx in range(len(atr_v)):
        w = atr_v[max(0, idx - atr_sma_period + 1):idx + 1]
        atr_sma[idx] = sum(w) / len(w) if w else 1.0
    nifty_daily["tp"] = (nifty_daily["high"] + nifty_daily["low"] + nifty_daily["close"]) / 3
    nifty_daily["tp_vol"] = nifty_daily["tp"] * nifty_daily["volume"].clip(lower=1)
    nifty_daily["vol_sum"] = nifty_daily["volume"].clip(lower=1).rolling(cfg.vwap_lookback, min_periods=1).sum()
    nifty_daily["vwap"] = nifty_daily["tp_vol"].rolling(cfg.vwap_lookback, min_periods=1).sum() / nifty_daily["vol_sum"]
    vwap_d = nifty_daily["vwap"].tolist()

    allowed = STRATEGY_FILTER_MAP["BOTH"]
    warmup = max(cfg.ema_trend + 1, cfg.rsi_period + 1, atr_sma_period + 1, cfg.bb_period + 1, 5)

    results_no_confirm = []    # Baseline: enter without confirmation
    results_with_confirm = []  # With 5-min first-candle confirmation
    confirmation_stats = {"confirmed": 0, "skipped": 0, "no_signal": 0}

    for trade_date in days_5m:
        # Find daily index for this date
        try:
            i = dates_d.index(trade_date)
        except ValueError:
            continue
        if i < warmup:
            continue

        vix = get_vix_for_date(vix_df, trade_date)
        day_candles = nifty_5m[nifty_5m["date"] == trade_date].sort_values("ts").reset_index(drop=True)
        if len(day_candles) < 10:
            continue

        # Run daily strategy scan
        regime = _classify_regime(
            i, closes, highs, lows, ema_f, ema_s, ema_t,
            adx_v, atr_v, atr_sma, bb_w, rsi_v, vix, cfg,
        )
        rsi = rsi_v[i]
        scan_order = _strategies_scan_order(regime, allowed)
        matches = []
        seen = set()
        day_cap = cfg.max_trades_per_day
        if vix > 21: day_cap = 1
        elif vix > 19: day_cap = 2

        for sname in scan_order:
            sig_result = None
            if sname == "TREND_CONTINUATION":
                sig_result = _check_trend_continuation(i, highs, lows, closes, opens_d, ema_f, ema_s, ema_t, rsi, vwap_d, cfg)
            elif sname == "BREAKOUT_MOMENTUM":
                sig_result = _check_breakout_momentum(i, highs, lows, closes, opens_d, ema_f, ema_s, rsi, atr_v, atr_sma, volumes_d, cfg)
            elif sname == "REVERSAL_SNAP":
                sig_result = _check_reversal_snap(i, highs, lows, closes, opens_d, rsi, rsi_v, vwap_d, cfg)
            elif sname == "GAP_FADE":
                sig_result = _check_gap_fade(i, highs, lows, closes, opens_d, rsi, cfg)
            elif sname == "RANGE_BOUNCE":
                sig_result = _check_range_bounce(i, highs, lows, closes, opens_d, rsi, vwap_d, cfg)
            elif sname == "INSIDE_BAR_BREAK":
                sig_result = _check_inside_bar_break(i, highs, lows, closes, opens_d, ema_f, ema_s, rsi, cfg)
            elif sname == "VWAP_CROSS":
                sig_result = _check_vwap_cross(i, closes, opens_d, highs, lows, vwap_d, rsi, ema_f, ema_s, cfg)
            elif sname == "EMA_FRESH_CROSS":
                if vix <= 21.0:
                    sig_result = _check_ema_fresh_cross(i, highs, lows, closes, opens_d, ema_f, ema_s, ema_t, rsi, vwap_d, cfg)
            if sig_result and sname not in seen:
                seen.add(sname)
                matches.append(sig_result)
                if len(matches) >= day_cap:
                    break

        if not matches:
            confirmation_stats["no_signal"] += 1
            continue

        signal, strategy_name, filter_log = matches[0]
        sl_key, tgt_key = SL_TARGET_MAP.get(strategy_name, ("sl_pct_tc", "target_pct_tc"))
        sl = getattr(cfg, sl_key)
        tgt = getattr(cfg, tgt_key)
        sl_m, tgt_m = REGIME_SL_TARGET_ADJUST.get(regime, (1.0, 1.0))
        sl *= sl_m; tgt *= tgt_m

        # Entry price: open of day (baseline, no confirmation)
        spot_base = float(day_candles.iloc[0]["open"])
        day_high = highs[i]; day_low = lows[i]; day_close = closes[i]

        # Simulate option trade — baseline (no confirmation)
        trade_base = _sim_option_fast(spot_base, signal, trade_date, vix, day_high, day_low, day_close, sl, tgt, cfg, strategy_name, regime)
        if trade_base:
            results_no_confirm.append(trade_base)

        # With confirmation: check first 3 5-min candles
        confirmed, entry_price_5m, entry_time = _five_min_confirmed(day_candles, signal, max_wait_candles=3)
        if confirmed and entry_price_5m:
            confirmation_stats["confirmed"] += 1
            # Use 5-min entry price instead of open
            trade_conf = _sim_option_fast(entry_price_5m, signal, trade_date, vix, day_high, day_low, day_close, sl, tgt, cfg, strategy_name, regime)
            if trade_conf:
                trade_conf["entry_time"] = entry_time
                trade_conf["confirmation"] = "5MIN_CANDLE"
                results_with_confirm.append(trade_conf)
        else:
            confirmation_stats["skipped"] += 1

    return {
        "no_confirm": _summarise(results_no_confirm, "BASELINE (no confirmation)"),
        "with_confirm": _summarise(results_with_confirm, "WITH 5-min confirmation"),
        "confirmation_stats": confirmation_stats,
        "days_tested": len(days_5m),
    }


# ═══════════════════════════════════════════════════════════════════
# PART D: ORB Second-Chance + 10:30 Window
# ═══════════════════════════════════════════════════════════════════

def _orb_signal(
    day_candles: pd.DataFrame,
    ema_fast_val: float,
    ema_slow_val: float,
    rsi_val: float,
    vix: float,
    cfg: DailyBacktestConfig,
) -> Optional[Tuple[str, float, str]]:
    """
    Opening Range Breakout: 9:15–9:30 range break at 9:30 candle.
    Returns: (direction, entry_price, "ORB") or None
    """
    orb_candles = day_candles[
        (day_candles["ts"].dt.time >= datetime.strptime("09:15", "%H:%M").time()) &
        (day_candles["ts"].dt.time < datetime.strptime("09:30", "%H:%M").time())
    ]
    if len(orb_candles) < 2:
        return None

    orb_high = float(orb_candles["high"].max())
    orb_low  = float(orb_candles["low"].min())
    orb_range = orb_high - orb_low

    # ORB must be meaningful but not too wide
    if not (15 <= orb_range <= 90):   # 15–90 pts = quality range
        return None

    # The breakout candle is 9:30
    brk_candles = day_candles[
        day_candles["ts"].dt.time == datetime.strptime("09:30", "%H:%M").time()
    ]
    if brk_candles.empty:
        return None
    brk = brk_candles.iloc[0]

    # Check volume on ORB candles
    vol_avg = float(day_candles["volume"].mean())
    vol_orb = float(orb_candles["volume"].mean())
    vol_ratio = vol_orb / vol_avg if vol_avg > 0 else 1.0

    buffer = orb_range * 0.08   # 8% of ORB range as buffer to avoid false breakouts

    # Bullish ORB breakout
    if (float(brk["close"]) > orb_high + buffer
        and float(brk["close"]) > float(brk["open"])  # green breakout candle
        and ema_fast_val > ema_slow_val                # EMA aligned
        and 45 <= rsi_val <= 72                        # RSI healthy
        and vix < 22):
        entry_price = float(brk["close"])
        return ("CALL", entry_price, "ORB")

    # Bearish ORB breakdown
    if (float(brk["close"]) < orb_low - buffer
        and float(brk["close"]) < float(brk["open"])  # red breakdown candle
        and ema_fast_val < ema_slow_val
        and 28 <= rsi_val <= 55
        and vix < 22):
        entry_price = float(brk["close"])
        return ("PUT", entry_price, "ORB")

    return None


def _late_trend_signal(
    day_candles: pd.DataFrame,
    ema_fast_val: float,
    ema_slow_val: float,
    rsi_val: float,
    vix: float,
) -> Optional[Tuple[str, float, str]]:
    """
    10:30 AM trend window: if VWAP + EMA clearly biased for 75+ min, enter.
    Entry at 10:30 candle close. Tighter SL (15%) due to less time remaining.
    """
    early = day_candles[
        day_candles["ts"].dt.time <= datetime.strptime("10:25", "%H:%M").time()
    ].copy()
    if len(early) < 10:
        return None

    vwap = _compute_vwap_intraday(early)
    last_vwap = float(vwap.iloc[-1])

    # Check 10:30 candle
    ten30 = day_candles[
        day_candles["ts"].dt.time == datetime.strptime("10:30", "%H:%M").time()
    ]
    if ten30.empty:
        return None
    c10 = ten30.iloc[0]
    price_10 = float(c10["close"])

    # Count how many of last 10 candles closed above/below VWAP
    last_10 = early.tail(10)
    closes_10 = last_10["close"].tolist()
    above_vwap_count = sum(1 for p in closes_10 if p > last_vwap)
    below_vwap_count = sum(1 for p in closes_10 if p < last_vwap)

    body = abs(float(c10["close"]) - float(c10["open"]))
    rng = float(c10["high"]) - float(c10["low"])
    body_ratio = body / rng if rng > 0 else 0

    # Strong bullish VWAP trend: 8/10 candles above, EMA aligned, RSI healthy, 10:30 green
    if (above_vwap_count >= 8
        and price_10 > last_vwap
        and ema_fast_val > ema_slow_val
        and 48 <= rsi_val <= 70
        and float(c10["close"]) > float(c10["open"])
        and body_ratio >= 0.35
        and vix < 22):
        return ("CALL", price_10, "LATE_TREND_1030")

    # Strong bearish VWAP trend
    if (below_vwap_count >= 8
        and price_10 < last_vwap
        and ema_fast_val < ema_slow_val
        and 30 <= rsi_val <= 52
        and float(c10["close"]) < float(c10["open"])
        and body_ratio >= 0.35
        and vix < 22):
        return ("PUT", price_10, "LATE_TREND_1030")

    return None


def run_orb_combined(
    nifty_5m: pd.DataFrame,
    nifty_daily: pd.DataFrame,
    vix_df: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Combined ORB + daily regime backtest using groww-style ORB.

    Tests 4 scenarios:
      1. daily_only    — current system (daily signal, enter at open)
      2. orb_confirmed — daily signal + ORB breaks same direction (better timing)
      3. orb_fallback  — no daily signal but ORB fires (groww fallback)
      4. orb_only      — pure ORB, no regime filter (baseline groww behavior)
    """
    nifty_5m = nifty_5m.copy()
    nifty_5m["ts"] = pd.to_datetime(nifty_5m["ts"])
    nifty_5m["date"] = nifty_5m["ts"].dt.date
    days_5m = sorted(nifty_5m["date"].unique())

    cfg = DailyBacktestConfig(capital=25000, lot_size=65, lots=1, max_lots_cap=1)

    nifty_daily = nifty_daily.copy()
    nifty_daily["ts"] = pd.to_datetime(nifty_daily["ts"])
    nifty_daily = nifty_daily.sort_values("ts").reset_index(drop=True)
    closes = nifty_daily["close"].tolist()
    highs  = nifty_daily["high"].tolist()
    lows   = nifty_daily["low"].tolist()
    opens_d = nifty_daily["open"].tolist()
    volumes_d = nifty_daily["volume"].tolist()
    dates_d   = nifty_daily["ts"].dt.date.tolist()

    ema_f = _ema(closes, cfg.ema_fast)
    ema_s = _ema(closes, cfg.ema_slow)
    ema_t = _ema(closes, cfg.ema_trend)
    rsi_v = _rsi(closes, cfg.rsi_period)
    atr_v = _atr(highs, lows, closes, cfg.atr_period)
    adx_v = _directional_movement(highs, lows, closes, cfg.atr_period)
    bb_w  = _bollinger_bandwidth(closes, cfg.bb_period, cfg.bb_std)
    atr_sma_period = 50
    atr_sma = [0.0] * len(atr_v)
    for idx in range(len(atr_v)):
        w = atr_v[max(0, idx - atr_sma_period + 1):idx + 1]
        atr_sma[idx] = sum(w) / len(w) if w else 1.0
    nifty_daily["tp"] = (nifty_daily["high"] + nifty_daily["low"] + nifty_daily["close"]) / 3
    nifty_daily["tp_vol"] = nifty_daily["tp"] * nifty_daily["volume"].clip(lower=1)
    nifty_daily["vol_sum"] = nifty_daily["volume"].clip(lower=1).rolling(cfg.vwap_lookback, min_periods=1).sum()
    nifty_daily["vwap"] = nifty_daily["tp_vol"].rolling(cfg.vwap_lookback, min_periods=1).sum() / nifty_daily["vol_sum"]
    vwap_d = nifty_daily["vwap"].tolist()
    allowed = STRATEGY_FILTER_MAP["BOTH"]
    warmup = max(cfg.ema_trend + 1, cfg.rsi_period + 1, atr_sma_period + 1, cfg.bb_period + 1, 5)

    # Accumulators for 4 scenarios
    t_daily_only    = []   # 1: current system
    t_orb_confirmed = []   # 2: daily signal + ORB confirms same direction
    t_orb_fallback  = []   # 3: no daily signal, raw ORB fires
    t_orb_only      = []   # 4: pure ORB (groww.py) — no regime filter

    stats = {"daily_signal": 0, "no_signal": 0, "orb_fired": 0,
             "orb_matches_daily": 0, "orb_conflicts_daily": 0}

    for trade_date in days_5m:
        try:
            i = dates_d.index(trade_date)
        except ValueError:
            continue
        if i < warmup:
            continue

        vix = get_vix_for_date(vix_df, trade_date)
        day_candles = nifty_5m[nifty_5m["date"] == trade_date].sort_values("ts").reset_index(drop=True)
        if len(day_candles) < 15:
            continue

        regime = _classify_regime(
            i, closes, highs, lows, ema_f, ema_s, ema_t,
            adx_v, atr_v, atr_sma, bb_w, rsi_v, vix, cfg,
        )
        rsi = rsi_v[i]
        scan_order = _strategies_scan_order(regime, allowed)
        matches = []
        seen = set()
        day_cap = 1 if vix > 21 else (2 if vix > 19 else cfg.max_trades_per_day)

        for sname in scan_order:
            sig_result = None
            if sname == "TREND_CONTINUATION":
                sig_result = _check_trend_continuation(i, highs, lows, closes, opens_d, ema_f, ema_s, ema_t, rsi, vwap_d, cfg)
            elif sname == "BREAKOUT_MOMENTUM":
                sig_result = _check_breakout_momentum(i, highs, lows, closes, opens_d, ema_f, ema_s, rsi, atr_v, atr_sma, volumes_d, cfg)
            elif sname == "REVERSAL_SNAP":
                sig_result = _check_reversal_snap(i, highs, lows, closes, opens_d, rsi, rsi_v, vwap_d, cfg)
            elif sname == "GAP_FADE":
                sig_result = _check_gap_fade(i, highs, lows, closes, opens_d, rsi, cfg)
            elif sname == "RANGE_BOUNCE":
                sig_result = _check_range_bounce(i, highs, lows, closes, opens_d, rsi, vwap_d, cfg)
            elif sname == "INSIDE_BAR_BREAK":
                sig_result = _check_inside_bar_break(i, highs, lows, closes, opens_d, ema_f, ema_s, rsi, cfg)
            elif sname == "VWAP_CROSS":
                sig_result = _check_vwap_cross(i, closes, opens_d, highs, lows, vwap_d, rsi, ema_f, ema_s, cfg)
            elif sname == "EMA_FRESH_CROSS":
                if vix <= 21.0:
                    sig_result = _check_ema_fresh_cross(i, highs, lows, closes, opens_d, ema_f, ema_s, ema_t, rsi, vwap_d, cfg)
            if sig_result and sname not in seen:
                seen.add(sname); matches.append(sig_result)
                if len(matches) >= day_cap: break

        day_high = highs[i]; day_low = lows[i]; day_close = closes[i]

        # ── ORB signal (groww-style) ──────────────────────────────
        orb_result = _orb_groww(day_candles)
        if orb_result:
            stats["orb_fired"] += 1

        # ── Pure ORB (scenario 4) — always try ───────────────────
        if orb_result and vix <= 22:
            orb_dir, orb_px = orb_result
            t = _sim_option_fast(orb_px, orb_dir, trade_date, vix,
                                 day_high, day_low, day_close,
                                 ORB_FALLBACK_SL, ORB_FALLBACK_TGT,
                                 cfg, "ORB_PURE", regime)
            if t:
                t_orb_only.append(t)

        if matches:
            stats["daily_signal"] += 1
            signal, strategy_name, filter_log = matches[0]
            sl_key, tgt_key = SL_TARGET_MAP.get(strategy_name, ("sl_pct_tc", "target_pct_tc"))
            sl = getattr(cfg, sl_key)
            tgt = getattr(cfg, tgt_key)
            sl_m, tgt_m = REGIME_SL_TARGET_ADJUST.get(regime, (1.0, 1.0))
            sl *= sl_m; tgt *= tgt_m
            spot_base = float(day_candles.iloc[0]["open"])

            # Scenario 1: daily only (enter at open)
            t1 = _sim_option_fast(spot_base, signal, trade_date, vix,
                                  day_high, day_low, day_close, sl, tgt,
                                  cfg, strategy_name, regime)
            if t1:
                t_daily_only.append(t1)

            # Scenario 2: ORB-confirmed — wait for ORB to break same way
            if orb_result and vix <= 22:
                orb_dir, orb_px = orb_result
                if orb_dir == signal:
                    stats["orb_matches_daily"] += 1
                    t2 = _sim_option_fast(orb_px, signal, trade_date, vix,
                                         day_high, day_low, day_close, sl, tgt,
                                         cfg, strategy_name, regime)
                    if t2:
                        t2["entry_mode"] = "ORB_CONFIRMED"
                        t_orb_confirmed.append(t2)
                else:
                    stats["orb_conflicts_daily"] += 1
            # If ORB didn't fire or conflicts: ORB-confirmed misses this day
        else:
            stats["no_signal"] += 1
            # Scenario 3: ORB fallback — no daily signal, use raw ORB
            if orb_result and vix <= 22:
                orb_dir, orb_px = orb_result
                t3 = _sim_option_fast(orb_px, orb_dir, trade_date, vix,
                                      day_high, day_low, day_close,
                                      ORB_FALLBACK_SL, ORB_FALLBACK_TGT,
                                      cfg, "ORB_FALLBACK", regime)
                if t3:
                    t3["entry_mode"] = "ORB_FALLBACK"
                    t_orb_fallback.append(t3)

    # Combined = ORB-confirmed + ORB-fallback
    t_combined = t_orb_confirmed + t_orb_fallback

    return {
        "days_tested": len(days_5m),
        "stats": stats,
        "daily_only":    _summarise(t_daily_only,    "Daily-only (baseline)"),
        "orb_confirmed": _summarise(t_orb_confirmed, "ORB-confirmed daily"),
        "orb_fallback":  _summarise(t_orb_fallback,  "ORB fallback (no signal)"),
        "orb_combined":  _summarise(t_combined,      "ORB combined (2+3)"),
        "orb_only":      _summarise(t_orb_only,      "Pure ORB (groww-style)"),
    }


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _sim_option_fast(
    spot_entry: float, direction: str, trade_date: date, vix: float,
    day_high: float, day_low: float, day_close: float,
    sl_pct: float, target_pct: float,
    cfg: DailyBacktestConfig,
    strategy_name: str = "", regime: str = "",
) -> Optional[Dict[str, Any]]:
    """Lightweight option simulation using standard ATM strike."""
    expiry = _get_weekly_expiry(trade_date)
    strike = atm_strike(spot_entry, cfg.strike_step)
    opt_type = "CE" if direction == "CALL" else "PE"
    dte = (expiry - trade_date).days
    moneyness = spot_entry / strike
    sigma = implied_vol_from_vix(vix, moneyness)
    iv_crush = -0.005 * (vix / 15.0)

    T_entry = max(0.0001, (dte * 0.71 + 0.5) / 252.0)
    entry_opt = price_option(spot_entry, strike, T_entry, RISK_FREE_RATE, sigma, opt_type)
    raw_entry = entry_opt["price"]
    if raw_entry < cfg.min_option_premium:
        return None

    entry_slip = realistic_slippage(cfg.slippage_pct, vix, dte, raw_entry)
    entry_price = raw_entry * (1 + entry_slip)
    sl_price = entry_price * (1 - sl_pct)
    target_price = entry_price * (1 + target_pct)

    spot_move_range = day_high - day_low
    if direction == "CALL":
        best_spot = spot_entry + spot_move_range * 0.62
        worst_spot = spot_entry - spot_move_range * 0.22
    else:
        best_spot = spot_entry - spot_move_range * 0.62
        worst_spot = spot_entry + spot_move_range * 0.22

    T_mid = max(0.0001, (dte * 0.71 + 0.2) / 252.0)
    sigma_mid = max(0.01, sigma + iv_crush * 0.5)

    best_price  = price_option(best_spot,  strike, T_mid, RISK_FREE_RATE, sigma_mid, opt_type)["price"]
    worst_price = price_option(worst_spot, strike, T_mid, RISK_FREE_RATE, sigma_mid, opt_type)["price"]

    exit_reason = "EOD_EXIT"
    if worst_price <= sl_price:
        exit_price_raw = sl_price; exit_reason = "SL_HIT"
    elif best_price >= target_price:
        exit_price_raw = target_price; exit_reason = "TARGET_HIT"
    else:
        T_eod = max(0.0001, (dte * 0.71 - 0.1) / 252.0)
        eod_price = price_option(day_close, strike, T_eod, RISK_FREE_RATE, max(0.01, sigma + iv_crush), opt_type)["price"]
        exit_price_raw = eod_price
        if eod_price > entry_price * 1.08:
            exit_reason = "EOD_PROFIT"

    exit_slip = realistic_slippage(cfg.slippage_pct, vix, dte, exit_price_raw)
    exit_price = exit_price_raw * (1 - exit_slip)
    qty = cfg.lots * cfg.lot_size
    net_pnl = (exit_price - entry_price) * qty - charges_estimate(entry_price, exit_price, qty)

    return {
        "status": "COMPLETED", "direction": direction,
        "strategy": strategy_name, "regime": regime,
        "entry_price": round(entry_price, 2), "exit_price": round(exit_price, 2),
        "sl_price": round(sl_price, 2), "target_price": round(target_price, 2),
        "exit_reason": exit_reason, "net_pnl": round(net_pnl, 2),
        "qty": qty, "trade_date": str(trade_date),
    }


def _summarise(trades: list, label: str) -> Dict[str, Any]:
    if not trades:
        return {"label": label, "trades": 0}
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    gross_w = sum(t["net_pnl"] for t in wins)
    gross_l = abs(sum(t["net_pnl"] for t in losses))
    pf = gross_w / gross_l if gross_l > 0 else 0
    exits = {}
    for t in trades:
        exits[t.get("exit_reason", "?")] = exits.get(t.get("exit_reason", "?"), 0) + 1
    return {
        "label": label,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "profit_factor": round(pf, 2),
        "net_pnl": round(sum(t["net_pnl"] for t in trades), 0),
        "avg_win": round(gross_w / max(len(wins), 1), 0),
        "avg_loss": round(-gross_l / max(len(losses), 1), 0),
        "exits": exits,
    }


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def run_all(verbose: bool = True) -> None:
    print("\n" + "="*72)
    print(" ENHANCED BACKTEST — ITM + 5min Confirm + ORB + 10:30 Window")
    print("="*72)

    nifty_daily = download_nifty_daily()
    vix_df      = download_india_vix()
    nifty_5m    = download_nifty_spot()

    # ── Part A: ITM comparison ────────────────────────────────────
    print("\n[PART A] ITM vs ATM — full daily history")
    print("-"*50)
    r_atm  = run_daily_backtest(nifty_daily, vix_df,
                                DailyBacktestConfig(capital=25000, lot_size=65, lots=1, max_lots_cap=1),
                                verbose=False)
    r_itm1 = run_itm_backtest(nifty_daily, vix_df, itm_offset_points=50)
    r_itm2 = run_itm_backtest(nifty_daily, vix_df, itm_offset_points=100)

    def show_m(label, r):
        m = r["metrics"]
        mb = r.get("monthly_breakdown", m.get("monthly_breakdown", []))
        months = len(set(t["month"] for t in mb)) if mb else 1
        print(f"  {label:<28} Trades:{m['total_trades']:>4}  WR:{m['win_rate_pct']:>5.1f}%"
              f"  PF:{m['profit_factor']:>5.2f}x  Net:₹{m['total_net_pnl']:>8,.0f}"
              f"  DD:{m['max_drawdown_pct']:>5.1f}%  Sharpe:{m['sharpe_ratio']:>5.2f}")

    show_m("ATM (current)", r_atm)
    show_m("1-strike ITM (50 pts)", r_itm1)
    show_m("2-strike ITM (100 pts)", r_itm2)

    # ── Part B: 5-min confirmation ────────────────────────────────
    print(f"\n[PART B] 5-min First-Candle Confirmation ({nifty_5m['ts'].nunique() if 'ts' not in nifty_5m.columns else len(nifty_5m['ts'].unique())} 5-min candles, "
          f"{len(nifty_5m.assign(date=pd.to_datetime(nifty_5m['ts']).dt.date)['date'].unique())} days)")
    print("-"*50)
    conf_results = _five_min_confirmation_backtest(nifty_5m, nifty_daily, vix_df)
    cs = conf_results["confirmation_stats"]
    print(f"  Days tested: {conf_results['days_tested']}")
    print(f"  Daily signals found: {cs['confirmed'] + cs['skipped']}")
    print(f"  Confirmed by 5-min candle: {cs['confirmed']} ({cs['confirmed']/(max(cs['confirmed']+cs['skipped'],1))*100:.0f}%)")
    print(f"  Skipped (first candles fought signal): {cs['skipped']}")
    print(f"  No daily signal: {cs['no_signal']}")
    nc = conf_results["no_confirm"]
    wc = conf_results["with_confirm"]
    if nc["trades"] > 0:
        print(f"\n  Without confirm: {nc['trades']} trades | WR:{nc['win_rate']}% | PF:{nc['profit_factor']}x | Net:₹{nc['net_pnl']:,}")
    if wc["trades"] > 0:
        print(f"  With 5-min confirm: {wc['trades']} trades | WR:{wc['win_rate']}% | PF:{wc['profit_factor']}x | Net:₹{wc['net_pnl']:,}")

    # ── Part C: ORB Combined (groww-style) ───────────────────────
    print(f"\n[PART C] ORB Combined — groww-style ORB (range {ORB_RANGE_MIN:.0f}–{ORB_RANGE_MAX:.0f} pts, {ORB_BUFFER_PCT*100:.2f}% buffer)")
    print("-"*50)
    oc = run_orb_combined(nifty_5m, nifty_daily, vix_df)
    st = oc["stats"]
    print(f"  Days tested: {oc['days_tested']}  |  Daily signal: {st['daily_signal']}  |  No signal: {st['no_signal']}")
    print(f"  ORB fired: {st['orb_fired']}  |  ORB matches daily dir: {st['orb_matches_daily']}  |  ORB conflicts: {st['orb_conflicts_daily']}")

    def show_s(r):
        if r["trades"] == 0:
            print(f"  {r['label']:<35}  0 trades")
            return
        print(f"  {r['label']:<35}  Trades:{r['trades']:>3}  WR:{r['win_rate']:>5.1f}%  "
              f"PF:{r['profit_factor']:>5.2f}x  Net:₹{r['net_pnl']:>8,.0f}  Exits:{r['exits']}")

    print()
    show_s(oc["daily_only"])
    show_s(oc["orb_confirmed"])
    show_s(oc["orb_fallback"])
    show_s(oc["orb_combined"])
    show_s(oc["orb_only"])

    # ── Summary ───────────────────────────────────────────────────
    print("\n" + "="*72)
    print(" VERDICT & PROJECTION")
    print("="*72)
    mb_atm = r_atm.get("metrics", {}).get("monthly_breakdown", [])
    months = max(len(set(t["month"] for t in mb_atm)), 1)
    baseline_per_month = r_atm["metrics"]["total_trades"] / months

    # From 37-day sample, extrapolate to monthly
    days = max(oc["days_tested"], 1)
    daily_pm  = oc["daily_only"]["trades"]    / days * 21
    conf_pm   = oc["orb_confirmed"]["trades"] / days * 21
    fb_pm     = oc["orb_fallback"]["trades"]  / days * 21
    comb_pm   = oc["orb_combined"]["trades"]  / days * 21
    orb_pm    = oc["orb_only"]["trades"]      / days * 21

    print(f"\n  Full 2-yr baseline (ATM):  {baseline_per_month:.1f} trades/month | PF:{r_atm['metrics']['profit_factor']:.2f}x | WR:{r_atm['metrics']['win_rate_pct']:.1f}%")
    print(f"\n  37-day window estimates:")
    print(f"    Daily-only:        {daily_pm:.1f} trades/month  | PF:{oc['daily_only']['profit_factor']:.2f}x | WR:{oc['daily_only']['win_rate']:.1f}%")
    print(f"    ORB-confirmed:     {conf_pm:.1f} trades/month  | PF:{oc['orb_confirmed']['profit_factor']:.2f}x | WR:{oc['orb_confirmed']['win_rate']:.1f}%")
    print(f"    ORB-fallback:      {fb_pm:.1f} trades/month  | PF:{oc['orb_fallback']['profit_factor']:.2f}x | WR:{oc['orb_fallback']['win_rate']:.1f}%")
    print(f"    Combined (rec.):   {comb_pm:.1f} trades/month  | PF:{oc['orb_combined']['profit_factor']:.2f}x | WR:{oc['orb_combined']['win_rate']:.1f}%")
    print(f"    Pure ORB (groww):  {orb_pm:.1f} trades/month  | PF:{oc['orb_only']['profit_factor']:.2f}x | WR:{oc['orb_only']['win_rate']:.1f}%")
    print(f"\n  NOTE: 37-day sample is small. 2-yr daily engine (2.69x PF) remains primary reference.")
    print()


if __name__ == "__main__":
    run_all()
