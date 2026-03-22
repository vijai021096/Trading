"""Black-Scholes options pricing + Greeks for Nifty options simulation."""
from __future__ import annotations

import math
from typing import Optional

try:
    from scipy.stats import norm as _norm
    _USE_SCIPY = True
except ImportError:
    _USE_SCIPY = False


def _norm_cdf(x: float) -> float:
    if _USE_SCIPY:
        return float(_norm.cdf(x))
    # Pure Python fallback (Abramowitz & Stegun approximation)
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    d = 0.3989422820 * math.exp(-0.5 * x * x)
    p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.7814780 + t * (-1.8212560 + t * 1.3302744))))
    return 1.0 - p if x >= 0 else p


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def price_option(
    S: float,        # Spot price (Nifty index level)
    K: float,        # Strike price
    T: float,        # Time to expiry in years (e.g. 7/365 for 1 week)
    r: float,        # Risk-free rate (0.065 for India)
    sigma: float,    # Implied volatility (annualized, e.g. 0.15 for 15%)
    option_type: str,  # "CE" or "PE"
) -> dict:
    """
    Returns:
        price   - Option theoretical price
        delta   - Rate of change w.r.t. spot
        gamma   - Rate of change of delta
        theta   - Daily time decay (in rupees)
        vega    - Sensitivity to 1% IV change
        iv      - Same sigma passed in (for convenience)
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return {"price": 0.0, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "iv": sigma}

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    if option_type.upper() in ("CE", "CALL", "C"):
        price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
    else:  # PE / PUT
        price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0

    pdf_d1 = _norm_pdf(d1)
    gamma = pdf_d1 / (S * sigma * sqrt_T)
    # Theta per calendar day (not trading day)
    theta_annual = -(S * pdf_d1 * sigma / (2 * sqrt_T)) - r * K * math.exp(-r * T) * _norm_cdf(d2 if option_type.upper() in ("CE", "CALL", "C") else -d2)
    theta = theta_annual / 365.0
    vega = S * sqrt_T * pdf_d1 * 0.01  # Vega per 1% change in IV

    return {
        "price": max(0.0, price),
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "iv": sigma,
    }


def implied_vol_from_vix(vix: float) -> float:
    """Convert India VIX to annualized IV for Black-Scholes.

    India VIX is already an annualized percentage. E.g. VIX=14 → sigma=0.14.
    """
    return max(0.05, vix / 100.0)


def days_to_nearest_thursday(trade_date_str: str) -> int:
    """Calculate calendar days to the next Thursday (Nifty weekly expiry)."""
    from datetime import date, timedelta
    d = date.fromisoformat(trade_date_str)
    days_ahead = (3 - d.weekday()) % 7  # Thursday = weekday 3
    if days_ahead == 0:
        days_ahead = 7  # If today IS Thursday, next expiry is in 7 days (unless same-day)
    return days_ahead


def time_to_expiry_years(trade_date: str, expiry_date: str) -> float:
    """Fraction of a year until expiry."""
    from datetime import date
    d1 = date.fromisoformat(trade_date)
    d2 = date.fromisoformat(expiry_date)
    calendar_days = (d2 - d1).days
    return max(0.0, calendar_days / 365.0)


def atm_strike(spot: float, step: int = 50) -> float:
    """Round spot to nearest ATM strike."""
    return round(spot / step) * step


def realistic_slippage(
    base_slippage: float = 0.005,
    vix: float = 14.0,
    days_to_expiry: int = 5,
    option_price: float = 100.0,
) -> float:
    """
    Compute realistic slippage for an options trade, adjusted for market conditions.

    Factors:
      - High VIX widens bid-ask spreads
      - Near-expiry options are illiquid (gamma risk)
      - Cheap options (<₹50) have wider spreads as % of price
    """
    slippage = base_slippage

    # VIX premium: each point above 18 adds 0.1% slippage
    if vix > 18.0:
        slippage += (vix - 18.0) * 0.001

    # Expiry penalty: options near expiry have wider spreads
    if days_to_expiry <= 1:
        slippage += 0.005
    elif days_to_expiry <= 2:
        slippage += 0.003

    # Illiquidity penalty: cheap options have large relative spreads
    if option_price < 50.0:
        slippage += 0.005

    return min(slippage, 0.02)  # Cap at 2%


def charges_estimate(
    entry_price: float,
    exit_price: float,
    qty: int,
) -> float:
    """
    Estimate total Zerodha charges for a round-trip options trade.
    Returns total charges in ₹.
    """
    buy_value = entry_price * qty
    sell_value = exit_price * qty

    brokerage = 20 + 20  # ₹20 per order, 2 orders
    stt = sell_value * 0.000625         # STT: 0.0625% on sell side only
    exchange_charge = (buy_value + sell_value) * 0.00053
    sebi = (buy_value + sell_value) * 0.000001  # ₹10 per crore
    stamp_duty = buy_value * 0.00003    # 0.003% on buy
    gst = (brokerage + exchange_charge) * 0.18

    return brokerage + stt + exchange_charge + sebi + stamp_duty + gst
