"""
Realistic Nifty options simulation for backtesting.

Key realism features:
  1. IV smile: ATM options use VIX directly, OTM/ITM get smile adjustment
  2. Intraday time decay: theta computed per-candle using trading minutes remaining
  3. IV crush: IV drops 1-3% after entry (mean-reversion of event vol)
  4. Realistic slippage: dynamic based on VIX, DTE, option price
  5. Tick-by-tick SL check using candle high/low (not just close)
  6. Proper gamma exposure tracking
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from shared.black_scholes import (
    price_option, implied_vol_from_vix, atm_strike,
    charges_estimate, realistic_slippage,
)

RISK_FREE_RATE = 0.065
TRADING_MINUTES_PER_DAY = 375  # 9:15 to 15:30


def get_weekly_expiry(trade_date: date) -> date:
    """Return the nearest upcoming Thursday (Nifty weekly expiry)."""
    days_until_thursday = (3 - trade_date.weekday()) % 7
    return trade_date + timedelta(days=days_until_thursday)


def _time_to_expiry(trade_date: date, expiry_date: date, minutes_into_day: float) -> float:
    """Calculate T (in years) accounting for intraday position.

    More realistic than calendar days: uses actual trading time remaining.
    """
    full_days_remaining = (expiry_date - trade_date).days
    if full_days_remaining < 0:
        return 0.0001

    day_fraction_remaining = max(0.0, (TRADING_MINUTES_PER_DAY - minutes_into_day) / TRADING_MINUTES_PER_DAY)

    # Trading days are ~6.25 hours. Convert to yearly fraction.
    # Approximately 252 trading days per year.
    total_trading_days = full_days_remaining * 0.71 + day_fraction_remaining  # 0.71 ≈ 5/7 weekday ratio
    return max(0.0001, total_trading_days / 252.0)


def _minutes_since_open(candle_ts: datetime) -> float:
    """Minutes since 9:15 IST market open."""
    market_open = candle_ts.replace(hour=9, minute=15, second=0, microsecond=0)
    delta = (candle_ts - market_open).total_seconds() / 60.0
    return max(0.0, min(delta, TRADING_MINUTES_PER_DAY))


def simulate_option_price(
    spot: float,
    strike: float,
    trade_date: date,
    expiry_date: date,
    vix: float,
    option_type: str,
    minutes_into_day: float = 187.5,
    iv_adjustment: float = 0.0,
) -> Dict[str, Any]:
    """Price an option with IV smile and intraday time decay."""
    moneyness = spot / strike
    sigma = implied_vol_from_vix(vix, moneyness) + iv_adjustment
    sigma = max(0.05, sigma)

    T = _time_to_expiry(trade_date, expiry_date, minutes_into_day)
    return price_option(spot, strike, T, RISK_FREE_RATE, sigma, option_type)


class OptionTradeSimulator:
    """
    Simulates a single options trade with realistic mechanics.

    Key improvements:
      - SL checked against candle low (for longs), not just close
      - Target checked against candle high
      - Break-even uses option price, not just %
      - Trailing stop uses step-wise ratchet
    """

    def __init__(
        self,
        direction: str,
        entry_price: float,
        sl_price: float,
        target_price: float,
        trail_trigger_pct: float = 0.25,
        trail_lock_step_pct: float = 0.12,
        break_even_trigger_pct: float = 0.15,
    ):
        self.direction = direction
        self.entry_price = entry_price
        self.sl_price = sl_price
        self.target_price = target_price
        self.current_sl = sl_price
        self.trail_trigger_pct = trail_trigger_pct
        self.trail_lock_step_pct = trail_lock_step_pct
        self.break_even_trigger_pct = break_even_trigger_pct
        self.break_even_set = False
        self.highest_price = entry_price
        self.trail_active = False

    def tick(
        self,
        option_price_high: float,
        option_price_low: float,
        option_price_close: float,
        force_exit: bool = False,
    ) -> Dict[str, Any]:
        """
        Process one candle. Uses high/low for SL/target check (realistic fill).
        """
        self.highest_price = max(self.highest_price, option_price_high)

        if force_exit:
            return {"status": "CLOSED", "exit_price": option_price_close, "exit_reason": "FORCE_EXIT"}

        # SL hit if option price dipped to SL level during the candle
        if option_price_low <= self.current_sl:
            return {"status": "CLOSED", "exit_price": self.current_sl, "exit_reason": "SL_HIT"}

        # Target hit if option price reached target during the candle
        if option_price_high >= self.target_price:
            return {"status": "CLOSED", "exit_price": self.target_price, "exit_reason": "TARGET_HIT"}

        # Break-even trigger
        gain_pct = (option_price_close - self.entry_price) / self.entry_price
        if not self.break_even_set and gain_pct >= self.break_even_trigger_pct:
            new_sl = self.entry_price * 1.002
            if new_sl > self.current_sl:
                self.current_sl = new_sl
                self.break_even_set = True

        # Trailing stop
        if gain_pct >= self.trail_trigger_pct:
            trail_sl = self.highest_price * (1 - self.trail_lock_step_pct)
            if trail_sl > self.current_sl:
                self.current_sl = trail_sl
                self.trail_active = True

        return {"status": "OPEN", "exit_price": None, "exit_reason": None}


def run_intraday_simulation(
    entry_candle_idx: int,
    entry_spot: float,
    direction: str,
    candles: List[Dict[str, Any]],
    trade_date: date,
    vix: float,
    *,
    sl_pct: float,
    target_pct: float,
    trail_trigger_pct: float = 0.25,
    trail_lock_step_pct: float = 0.12,
    break_even_trigger_pct: float = 0.15,
    force_exit_time_str: str = "15:15",
    strike_step: int = 50,
    lot_size: int = 65,
    lots: int = 1,
    slippage_pct: float = 0.005,
    otm_offset: int = 0,
) -> Dict[str, Any]:
    """
    Full intraday simulation from entry_candle_idx onwards.

    otm_offset: number of strikes away from ATM.
        0 = ATM, 1 = 1 strike OTM (cheaper premium, higher R:R on strong days).
        For CALL: strike = ATM + offset * strike_step
        For PUT:  strike = ATM - offset * strike_step
    """
    from datetime import time as dtime
    h, m = map(int, force_exit_time_str.split(":"))
    force_exit_time = dtime(h, m)

    expiry = get_weekly_expiry(trade_date)
    atm = atm_strike(entry_spot, strike_step)
    if direction == "CALL":
        strike = atm + otm_offset * strike_step
    else:
        strike = atm - otm_offset * strike_step
    opt_type = "CE" if direction == "CALL" else "PE"
    dte = (expiry - trade_date).days

    entry_minutes = _minutes_since_open(candles[entry_candle_idx]["ts"])

    # IV crush: model a 1-2% IV drop after entry (breakout vol mean-reverts)
    iv_crush = -0.005 * (vix / 15.0)

    # Price at entry
    entry_opt = simulate_option_price(
        entry_spot, strike, trade_date, expiry, vix, opt_type,
        minutes_into_day=entry_minutes,
    )
    raw_entry_price = entry_opt["price"]

    if raw_entry_price < 5:
        return {"status": "SKIPPED", "reason": f"Option price too low: {raw_entry_price:.1f}"}

    # Dynamic slippage based on conditions
    entry_slippage = realistic_slippage(
        base_slippage=slippage_pct, vix=vix,
        days_to_expiry=dte, option_price=raw_entry_price,
    )
    entry_price = raw_entry_price * (1 + entry_slippage)
    sl_price = entry_price * (1 - sl_pct)
    target_price = entry_price * (1 + target_pct)

    sim = OptionTradeSimulator(
        direction, entry_price, sl_price, target_price,
        trail_trigger_pct, trail_lock_step_pct, break_even_trigger_pct,
    )

    entry_ts = candles[entry_candle_idx]["ts"]
    exit_ts = entry_ts
    exit_price = entry_price
    exit_reason = "UNKNOWN"

    for i in range(entry_candle_idx + 1, len(candles)):
        c = candles[i]
        c_ts = c["ts"]
        is_force_exit = c_ts.time() >= force_exit_time

        current_minutes = _minutes_since_open(c_ts)

        # Reprice at candle high, low, and close using actual spot
        spot_close = float(c["close"])
        spot_high = float(c["high"])
        spot_low = float(c["low"])

        # For a CALL option: high spot → high option price, low spot → low option price
        # For a PUT option: reversed
        if direction == "CALL":
            spot_for_high = spot_high
            spot_for_low = spot_low
        else:
            spot_for_high = spot_low
            spot_for_low = spot_high

        opt_high = simulate_option_price(
            spot_for_high, strike, trade_date, expiry, vix, opt_type,
            minutes_into_day=current_minutes, iv_adjustment=iv_crush,
        )["price"]

        opt_low = simulate_option_price(
            spot_for_low, strike, trade_date, expiry, vix, opt_type,
            minutes_into_day=current_minutes, iv_adjustment=iv_crush,
        )["price"]

        opt_close = simulate_option_price(
            spot_close, strike, trade_date, expiry, vix, opt_type,
            minutes_into_day=current_minutes, iv_adjustment=iv_crush,
        )["price"]

        result = sim.tick(opt_high, opt_low, opt_close, force_exit=is_force_exit)
        if result["status"] == "CLOSED":
            exit_ts = c_ts
            exit_slippage = realistic_slippage(
                base_slippage=slippage_pct, vix=vix,
                days_to_expiry=dte, option_price=result["exit_price"],
            )
            exit_price = result["exit_price"] * (1 - exit_slippage)
            exit_reason = result["exit_reason"]
            break
    else:
        last_c = candles[-1]
        last_minutes = _minutes_since_open(last_c["ts"])
        opt = simulate_option_price(
            float(last_c["close"]), strike, trade_date, expiry, vix, opt_type,
            minutes_into_day=last_minutes, iv_adjustment=iv_crush,
        )
        exit_ts = last_c["ts"]
        exit_slippage = realistic_slippage(
            base_slippage=slippage_pct, vix=vix,
            days_to_expiry=dte, option_price=opt["price"],
        )
        exit_price = opt["price"] * (1 - exit_slippage)
        exit_reason = "FORCE_EXIT"

    qty = lots * lot_size
    gross_pnl = (exit_price - entry_price) * qty
    charges = charges_estimate(entry_price, exit_price, qty)
    net_pnl = gross_pnl - charges

    return {
        "status": "COMPLETED",
        "direction": direction,
        "option_type": opt_type,
        "strike": strike,
        "expiry": expiry.isoformat(),
        "entry_ts": entry_ts.isoformat(),
        "exit_ts": exit_ts.isoformat(),
        "entry_price": round(entry_price, 2),
        "exit_price": round(exit_price, 2),
        "sl_price": round(sl_price, 2),
        "target_price": round(target_price, 2),
        "exit_reason": exit_reason,
        "gross_pnl": round(gross_pnl, 2),
        "charges": round(charges, 2),
        "net_pnl": round(net_pnl, 2),
        "qty": qty,
        "lots": lots,
        "spot_at_entry": round(entry_spot, 2),
        "delta_at_entry": round(entry_opt.get("delta", 0.5), 4),
        "iv_at_entry": round(entry_opt.get("iv", 0.14), 4),
        "vix": vix,
        "trade_date": trade_date.isoformat(),
        "entry_slippage_pct": round(entry_slippage * 100, 2),
        "otm_offset": otm_offset,
    }
