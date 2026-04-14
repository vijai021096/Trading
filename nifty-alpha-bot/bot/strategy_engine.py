"""
Strategy Engine V2 — Dynamic signal builder.

Handles:
  - Direction detection from live candles (not from regime lock)
  - Dynamic strike selection (ATM vs OTM)
  - Dynamic lot sizing based on option premium (cheap options = more lots)
  - Dynamic SL % based on regime and expiry
  - Dynamic target based on R:R

Entry logic is simple and explicit:
  1. At least 2 of last 3 completed 5-min candles match direction
  2. Spot above VWAP for CALL, below for PUT
  3. RSI not extreme (not > 78 for CALL, not < 22 for PUT)
  4. Option LTP in valid range [50, 450]
  5. All conditions = signal. If any fail = no trade.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple

from loguru import logger

from shared.regime_v2 import RegimeV2


@dataclass
class EntrySignal:
    direction: str          # CALL | PUT
    option_type: str        # CE | PE
    strike: float
    strike_type: str        # ATM | OTM1 | OTM2
    symbol: str             # full trading symbol e.g. NIFTY2441523700CE
    expiry: date
    ltp: float              # option last traded price at signal time
    entry_limit: float      # limit price to place order (ltp + buffer)
    sl_pct: float           # e.g. 0.20 = 20%
    sl_price: float         # absolute SL price
    target_pct: float       # e.g. 0.50 = 50%
    target_price: float
    lots: int
    qty: int
    risk_amount: float      # ₹ at risk
    conviction: float       # 0.0 – 1.0
    candle_confirm: str     # human-readable: "3/3 bull candles above VWAP"
    rsi: float
    vwap: float
    spot: float
    regime: str
    strategy: str


# ─── Main entry point ─────────────────────────────────────────────────────────

def build_entry_signal(
    now: datetime,
    candles: List[Dict],         # 5-min candles (today only, completed candles)
    spot: float,
    vix: float,
    regime: RegimeV2,
    capital: float,
    lot_size: int,
    kite_client,
    is_expiry_day: bool = False,
    direction_lost_today: Optional[str] = None,  # CALL or PUT if that direction already lost
) -> Optional[EntrySignal]:
    """
    Build a complete entry signal or return None if conditions not met.
    All logic is explicit and readable — no cascading overrides.
    """
    if not regime.should_trade:
        return None
    if spot <= 0 or len(candles) < 3:
        return None

    # ── 1. Compute indicators ──────────────────────────────────────────
    vwap = _compute_vwap(candles)
    rsi = _compute_rsi(candles)
    completed = [c for c in candles if c["ts"] < now.replace(second=0, microsecond=0)]
    if len(completed) < 3:
        return None

    last3 = completed[-3:]

    # ── 2. Detect direction from live candles ──────────────────────────
    direction, conviction, candle_str = _detect_direction(last3, spot, vwap, regime)
    if direction is None:
        return None

    # ── 3. Block re-entry in a direction that already lost today ──────
    if direction_lost_today and direction == direction_lost_today:
        logger.info(f"DIRECTION_BLOCKED: {direction} already lost today, skipping")
        return None

    # ── 4. RSI filter ──────────────────────────────────────────────────
    if direction == "CALL" and rsi > 78.0:
        logger.info(f"RSI_SKIP: CALL blocked, RSI={rsi:.1f} overbought (>78)")
        return None
    if direction == "PUT" and rsi < 22.0:
        logger.info(f"RSI_SKIP: PUT blocked, RSI={rsi:.1f} oversold (<22)")
        return None

    # ── 5. Select strike ───────────────────────────────────────────────
    expiry = kite_client.get_nearest_expiry("NIFTY")
    strike, strike_type = _select_strike(direction, spot, conviction, is_expiry_day)
    option_type = "CE" if direction == "CALL" else "PE"

    # ── 6. Find option symbol in instrument chain ──────────────────────
    chain = kite_client.get_option_chain_symbols("NIFTY", expiry)
    opt_candidates = [c for c in chain if c["option_type"] == option_type]
    opt_candidates.sort(key=lambda c: abs(c["strike"] - strike))
    if not opt_candidates:
        logger.warning(f"SYMBOL_NOT_FOUND: NIFTY {expiry} {strike} {option_type}")
        return None
    best = opt_candidates[0]
    symbol = best["symbol"]
    strike = best["strike"]   # snap to nearest available

    ltp = kite_client.get_quote(symbol, "NFO")
    if ltp <= 0:
        logger.warning(f"LTP_ZERO: {symbol}")
        return None

    # ── 7. Option price filter ─────────────────────────────────────────
    if ltp < 50 or ltp > 450:
        logger.info(f"PRICE_FILTER: {symbol} LTP={ltp:.0f} outside [50, 450]")
        return None

    # ── 8. Compute SL, target, lots ───────────────────────────────────
    sl_pct = _compute_sl(regime, is_expiry_day, strike_type, vix)
    target_pct = sl_pct * regime.target_rr
    lots = _compute_lots(ltp, sl_pct, capital, regime.risk_pct, lot_size, is_expiry_day)
    qty = lots * lot_size

    sl_price = round(ltp * (1 - sl_pct), 1)
    target_price = round(ltp * (1 + target_pct), 1)
    entry_limit = round(ltp * 1.005, 1)    # aggressive limit: LTP + 0.5%
    risk_amount = (ltp - sl_price) * qty

    strategy = _get_strategy_name(regime, conviction, strike_type)

    return EntrySignal(
        direction=direction,
        option_type=option_type,
        strike=strike,
        strike_type=strike_type,
        symbol=symbol,
        expiry=expiry,
        ltp=ltp,
        entry_limit=entry_limit,
        sl_pct=sl_pct,
        sl_price=sl_price,
        target_pct=target_pct,
        target_price=target_price,
        lots=lots,
        qty=qty,
        risk_amount=risk_amount,
        conviction=conviction,
        candle_confirm=candle_str,
        rsi=rsi,
        vwap=vwap,
        spot=spot,
        regime=regime.name,
        strategy=strategy,
    )


# ─── Direction detection ───────────────────────────────────────────────────────

def _detect_direction(
    last3: List[Dict],
    spot: float,
    vwap: float,
    regime: RegimeV2,
) -> Tuple[Optional[str], float, str]:
    """
    Detect entry direction from last 3 completed candles.

    Returns: (direction or None, conviction 0-1, human-readable string)

    Rules:
    - Need at least 2/3 candles green + spot above VWAP → CALL
    - Need at least 2/3 candles red + spot below VWAP → PUT
    - 3/3 candles = conviction 1.0, 2/3 = conviction 0.6
    - If regime has a bias and candles ALL oppose it → flip direction accepted
    - If candles are mixed (1/3 or 0/3) → no trade
    """
    bull = sum(1 for c in last3 if float(c["close"]) > float(c["open"]))
    bear = sum(1 for c in last3 if float(c["close"]) < float(c["open"]))

    above_vwap = spot > vwap
    below_vwap = spot < vwap

    bias = regime.direction_bias  # CALL, PUT, or None

    # ── CALL signal ───────────────────────────────────────────────────
    if bull >= 2 and above_vwap:
        # If regime bias is PUT and all 3 candles are opposite → accept reversal
        # If regime bias is PUT and only 2/3 → block (not strong enough to override)
        if bias == "PUT" and bull < 3:
            return None, 0.0, f"GAP_REVERSAL_WEAK: {bull}/3 bull vs PUT bias — need 3/3 to flip"
        conviction = 1.0 if bull == 3 else 0.65
        flipped = " (gap-reversal)" if bias == "PUT" else ""
        label = f"{bull}/3 bull candles above VWAP{flipped}"
        return "CALL", conviction, label

    # ── PUT signal ────────────────────────────────────────────────────
    if bear >= 2 and below_vwap:
        if bias == "CALL" and bear < 3:
            return None, 0.0, f"GAP_REVERSAL_WEAK: {bear}/3 bear vs CALL bias — need 3/3 to flip"
        conviction = 1.0 if bear == 3 else 0.65
        flipped = " (gap-reversal)" if bias == "CALL" else ""
        label = f"{bear}/3 bear candles below VWAP{flipped}"
        return "PUT", conviction, label

    # ── No clear direction ────────────────────────────────────────────
    desc = f"bull={bull}/3 bear={bear}/3 {'above' if above_vwap else 'below'} VWAP"
    return None, 0.0, f"mixed candles — {desc}"


# ─── Strike selection ──────────────────────────────────────────────────────────

def _select_strike(
    direction: str,
    spot: float,
    conviction: float,
    is_expiry_day: bool,
) -> Tuple[float, str]:
    """
    Select strike dynamically:
    - conviction < 0.70  → ATM
    - conviction 0.70-0.85 → ATM (safe)
    - conviction > 0.85 + not expiry → 1-OTM (more upside, less premium)
    - expiry day: always ATM (time decay kills OTM fast)
    """
    step = 50  # NIFTY strike step
    atm = round(spot / step) * step

    if is_expiry_day or conviction < 0.85:
        return atm, "ATM"
    else:
        # 1 OTM = one step further from ATM in trade direction
        otm = atm + step if direction == "CALL" else atm - step
        return otm, "OTM1"


# ─── SL computation ───────────────────────────────────────────────────────────

def _compute_sl(
    regime: RegimeV2,
    is_expiry_day: bool,
    strike_type: str,
    vix: float,
) -> float:
    """
    Dynamic SL % of option premium.
    Base from regime, adjusted for expiry, OTM, and VIX.
    """
    sl = regime.base_sl_pct

    if is_expiry_day:
        sl = min(sl, 0.18)   # tighter on expiry — time decay helps

    if strike_type == "OTM1":
        sl = sl + 0.05       # OTM needs more room to move

    if vix > 22:
        sl = sl + 0.03       # volatile day — extra room

    return min(round(sl, 2), 0.35)   # never more than 35%


# ─── Target computation ───────────────────────────────────────────────────────

def _compute_target_pct(sl_pct: float, regime: RegimeV2, conviction: float) -> float:
    """Target = SL × R:R ratio. Conviction boosts R:R slightly."""
    rr = regime.target_rr
    if conviction >= 1.0:
        rr = max(rr, 3.0)
    return round(sl_pct * rr, 2)


# ─── Lot sizing ───────────────────────────────────────────────────────────────

def _compute_lots(
    ltp: float,
    sl_pct: float,
    capital: float,
    risk_pct: float,
    lot_size: int,
    is_expiry_day: bool,
    max_lots: int = 6,
    min_lots: int = 1,
) -> int:
    """
    Dynamic lot sizing: how many lots can we buy within our risk budget?

    Formula:
      risk_budget = capital × risk_pct
      risk_per_lot = ltp × sl_pct × lot_size
      lots = floor(risk_budget / risk_per_lot)

    Example — cheap option:
      capital=₹1L, risk_pct=2.5%, ltp=₹60, sl_pct=20%, lot_size=65
      risk_budget = ₹2,500
      risk_per_lot = 60 × 0.20 × 65 = ₹780
      lots = floor(2500/780) = 3 lots ✓

    Example — expensive option:
      ltp=₹180, sl_pct=20%
      risk_per_lot = 180 × 0.20 × 65 = ₹2,340
      lots = floor(2500/2340) = 1 lot
    """
    risk_budget = capital * risk_pct
    risk_per_lot = ltp * sl_pct * lot_size

    if risk_per_lot <= 0:
        return min_lots

    lots = int(risk_budget / risk_per_lot)
    lots = max(min_lots, min(lots, max_lots))

    if is_expiry_day:
        lots = min(lots, 4)  # extra cap on expiry day (fast moves)

    return lots


# ─── Indicators ───────────────────────────────────────────────────────────────

def _compute_vwap(candles: List[Dict]) -> float:
    """Simple VWAP from today's candles (typical price average if no volume)."""
    tp_sum, vol_sum, count = 0.0, 0.0, 0
    for c in candles:
        h = float(c.get("high", 0))
        l = float(c.get("low", 0))
        cl = float(c.get("close", 0))
        v = float(c.get("volume", 0))
        tp = (h + l + cl) / 3
        if v > 0:
            tp_sum += tp * v
            vol_sum += v
        else:
            tp_sum += tp
            count += 1
    if vol_sum > 0:
        return round(tp_sum / vol_sum, 2)
    if count > 0:
        return round(tp_sum / count, 2)
    return 0.0


def _compute_rsi(candles: List[Dict], period: int = 14) -> float:
    """RSI from closes."""
    closes = [float(c["close"]) for c in candles]
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def _get_strategy_name(regime: RegimeV2, conviction: float, strike_type: str) -> str:
    names = {
        "DIRECTIONAL": "GAP_FOLLOW" if conviction >= 1.0 else "GAP_CONFIRM",
        "RANGE_BREAK": "BREAKOUT",
        "PULLBACK": "TREND_PULLBACK",
        "UNCERTAIN": "OPPORTUNISTIC",
    }
    base = names.get(regime.name, regime.name)
    if strike_type != "ATM":
        base += f"_{strike_type}"
    return base
