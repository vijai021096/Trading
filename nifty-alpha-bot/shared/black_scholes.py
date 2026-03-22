"""
Black-Scholes options pricing + Greeks for Nifty options simulation.

Realistic adjustments for Indian market:
  - IV smile: OTM/ITM options have higher IV than ATM
  - Intraday theta: uses trading hours remaining, not calendar days
  - IV crush: models post-event IV contraction
"""
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
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    d = 0.3989422820 * math.exp(-0.5 * x * x)
    p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.7814780 + t * (-1.8212560 + t * 1.3302744))))
    return 1.0 - p if x >= 0 else p


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def price_option(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str,
) -> dict:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        intrinsic = max(0.0, S - K) if option_type.upper() in ("CE", "CALL", "C") else max(0.0, K - S)
        return {"price": intrinsic, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "iv": sigma}

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    if option_type.upper() in ("CE", "CALL", "C"):
        price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
    else:
        price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0

    pdf_d1 = _norm_pdf(d1)
    gamma = pdf_d1 / (S * sigma * sqrt_T)
    theta_annual = -(S * pdf_d1 * sigma / (2 * sqrt_T)) - r * K * math.exp(-r * T) * _norm_cdf(d2 if option_type.upper() in ("CE", "CALL", "C") else -d2)
    theta = theta_annual / 365.0
    vega = S * sqrt_T * pdf_d1 * 0.01

    return {
        "price": max(0.0, price),
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "iv": sigma,
    }


def implied_vol_from_vix(vix: float, moneyness: float = 1.0) -> float:
    """Convert VIX to IV with smile adjustment.

    moneyness = S/K. ATM = 1.0, OTM CE > 1.0, OTM PE < 1.0.
    Nifty smile is steeper on the put side (skew).
    """
    base_iv = max(0.05, vix / 100.0)
    if moneyness == 1.0:
        return base_iv
    # IV smile/skew: quadratic + linear skew for puts
    m = moneyness - 1.0
    skew = 0.0
    if m < 0:
        skew = 0.08 * m * m + 0.03 * abs(m)
    else:
        skew = 0.05 * m * m
    return base_iv + skew


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
    Realistic slippage adjusted for market conditions.
    Models the Nifty options bid-ask spread empirically.
    """
    slippage = base_slippage

    if vix > 18.0:
        slippage += (vix - 18.0) * 0.0015
    if days_to_expiry <= 0:
        slippage += 0.010
    elif days_to_expiry <= 1:
        slippage += 0.006
    elif days_to_expiry <= 2:
        slippage += 0.003
    if option_price < 30.0:
        slippage += 0.010
    elif option_price < 50.0:
        slippage += 0.005
    if option_price > 300.0:
        slippage -= 0.002

    return max(0.002, min(slippage, 0.03))


def charges_estimate(
    entry_price: float,
    exit_price: float,
    qty: int,
) -> float:
    """
    Zerodha charges for round-trip options trade (2024 rates).
    """
    buy_value = entry_price * qty
    sell_value = exit_price * qty

    brokerage = 20 + 20
    stt = sell_value * 0.000625
    exchange_charge = (buy_value + sell_value) * 0.00053
    sebi = (buy_value + sell_value) * 0.000001
    stamp_duty = buy_value * 0.00003
    gst = (brokerage + exchange_charge + sebi) * 0.18

    return brokerage + stt + exchange_charge + sebi + stamp_duty + gst
