"""
Simulates Nifty options pricing for backtesting using Black-Scholes.

For each signal:
  1. Find ATM strike based on spot price
  2. Calculate option entry price using BS with current VIX as IV
  3. Track spot moves and re-price the option each bar
  4. Apply SL / target / trailing stop on option price
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from shared.black_scholes import price_option, implied_vol_from_vix, atm_strike, charges_estimate

# Risk-free rate (approximate RBI repo rate)
RISK_FREE_RATE = 0.065


def get_weekly_expiry(trade_date: date) -> date:
    """Return the nearest upcoming Thursday (Nifty weekly expiry)."""
    days_until_thursday = (3 - trade_date.weekday()) % 7
    if days_until_thursday == 0:
        days_until_thursday = 0  # Same-day expiry is valid on Thursday
    return trade_date + timedelta(days=days_until_thursday)


def simulate_option_price(
    spot: float,
    strike: float,
    trade_date: date,
    expiry_date: date,
    vix: float,
    option_type: str,
    entry_time_fraction: float = 0.5,  # 0=market open, 1=market close
) -> Dict[str, Any]:
    """
    Price an option using Black-Scholes.
    entry_time_fraction adjusts T slightly for intraday (0.5 = mid-session).
    """
    sigma = implied_vol_from_vix(vix)
    # Calendar days to expiry, adjusted for intraday position
    calendar_days = (expiry_date - trade_date).days
    intraday_adjustment = (1 - entry_time_fraction) / 365.0
    T = max(0.0001, calendar_days / 365.0 + intraday_adjustment)

    return price_option(spot, strike, T, RISK_FREE_RATE, sigma, option_type)


class OptionTradeSimulator:
    """
    Simulates a single options trade over a sequence of 5-min candles.

    Usage:
        sim = OptionTradeSimulator(signal, entry_candle, option_info, sl, target, cfg)
        for candle in subsequent_candles:
            result = sim.tick(candle, current_spot, current_vix, expiry)
            if result["status"] != "OPEN":
                break
    """

    def __init__(
        self,
        direction: str,
        entry_price: float,
        sl_price: float,
        target_price: float,
        trail_trigger_pct: float = 0.20,
        trail_lock_step_pct: float = 0.10,
        break_even_trigger_pct: float = 0.12,
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

    def tick(
        self,
        option_price: float,
        exit_time: Optional[datetime] = None,
        force_exit: bool = False,
    ) -> Dict[str, Any]:
        """
        Process one candle tick for the open position.
        Returns: {"status": "OPEN"|"CLOSED", "exit_price": float, "exit_reason": str}
        """
        self.highest_price = max(self.highest_price, option_price)

        # Force exit (EOD)
        if force_exit:
            return {"status": "CLOSED", "exit_price": option_price, "exit_reason": "FORCE_EXIT"}

        # Stop loss
        if option_price <= self.current_sl:
            return {"status": "CLOSED", "exit_price": self.current_sl, "exit_reason": "SL_HIT"}

        # Target
        if option_price >= self.target_price:
            return {"status": "CLOSED", "exit_price": self.target_price, "exit_reason": "TARGET_HIT"}

        # Break-even: move SL to entry after break_even_trigger_pct gain
        gain_pct = (option_price - self.entry_price) / self.entry_price
        if not self.break_even_set and gain_pct >= self.break_even_trigger_pct:
            new_sl = self.entry_price * 1.005  # Slightly above entry to lock small profit
            if new_sl > self.current_sl:
                self.current_sl = new_sl
                self.break_even_set = True

        # Trailing stop: activate after trail_trigger_pct gain
        if gain_pct >= self.trail_trigger_pct:
            trail_sl = self.highest_price * (1 - self.trail_lock_step_pct)
            if trail_sl > self.current_sl:
                self.current_sl = trail_sl

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
    trail_trigger_pct: float = 0.20,
    trail_lock_step_pct: float = 0.10,
    break_even_trigger_pct: float = 0.12,
    force_exit_time_str: str = "15:15",
    strike_step: int = 50,
    lot_size: int = 65,
    lots: int = 1,
    slippage_pct: float = 0.005,  # 0.5% bid-ask slippage on entry and exit
) -> Dict[str, Any]:
    """
    Full intraday simulation from entry_candle_idx onwards.
    Returns complete trade record.
    """
    from datetime import time as dtime
    h, m = map(int, force_exit_time_str.split(":"))
    force_exit_time = dtime(h, m)

    expiry = get_weekly_expiry(trade_date)
    strike = atm_strike(entry_spot, strike_step)
    opt_type = "CE" if direction == "CALL" else "PE"

    # Price the option at entry
    entry_opt = simulate_option_price(
        entry_spot, strike, trade_date, expiry, vix, opt_type, entry_time_fraction=0.3
    )
    raw_entry_price = entry_opt["price"]

    if raw_entry_price < 10:
        return {
            "status": "SKIPPED",
            "reason": f"Option price too low: {raw_entry_price:.1f}",
        }

    # Apply buy-side slippage
    entry_price = raw_entry_price * (1 + slippage_pct)
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

    # Walk forward through remaining candles
    for i in range(entry_candle_idx + 1, len(candles)):
        c = candles[i]
        c_ts = c["ts"]
        is_force_exit = c_ts.time() >= force_exit_time

        # Reprice the option using current spot
        time_frac = 0.3 + 0.7 * (i - entry_candle_idx) / max(1, len(candles) - entry_candle_idx)
        opt = simulate_option_price(
            float(c["close"]), strike, trade_date, expiry, vix, opt_type, time_frac
        )
        opt_price = opt["price"]

        result = sim.tick(opt_price, exit_time=c_ts, force_exit=is_force_exit)
        if result["status"] == "CLOSED":
            exit_ts = c_ts
            # Apply sell-side slippage
            exit_price = result["exit_price"] * (1 - slippage_pct)
            exit_reason = result["exit_reason"]
            break
    else:
        # End of day without hitting exit — force exit at last candle
        last_c = candles[-1]
        opt = simulate_option_price(float(last_c["close"]), strike, trade_date, expiry, vix, opt_type, 0.99)
        exit_ts = last_c["ts"]
        exit_price = opt["price"] * (1 - slippage_pct)
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
    }
