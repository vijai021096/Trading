"""
Adaptive Engine — the intelligence layer that makes DYNAMIC decisions.

Replaces hard-coded thresholds with conviction/session/impulse-aware logic:
  - Dynamic lot sizing: 1-5 lots based on impulse grade + trend conviction
  - Dynamic strike selection: ITM/ATM/OTM based on regime + P&L state
  - Session-aware confidence thresholds (opening = relaxed, late = tighter)
  - Smarter momentum confirmation (1 candle OK for EXTREME impulse)
  - Adaptive re-entry gating (direction block lifts after 45 min)

Design principle: be MORE aggressive on high-conviction setups and
MORE conservative on marginal ones — not uniformly conservative.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger


# ─────────────────────────────────────────────────────────────────────────────
# Session Classification
# ─────────────────────────────────────────────────────────────────────────────

class Session(str, Enum):
    OPENING   = "OPENING"    # 09:15 – 10:00: ORB, impulse, gap plays
    MORNING   = "MORNING"    # 10:00 – 11:30: EMA pullback, VWAP reclaim
    MIDDAY    = "MIDDAY"     # 11:30 – 13:30: Trend continuation
    AFTERNOON = "AFTERNOON"  # 13:30 – 15:00: Late plays, tight filters


def get_session(now: datetime) -> Session:
    """Classify current market session from IST time."""
    t = now.time()
    if t < dtime(10, 0):
        return Session.OPENING
    if t < dtime(11, 30):
        return Session.MORNING
    if t < dtime(13, 30):
        return Session.MIDDAY
    return Session.AFTERNOON


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Confidence Threshold
# ─────────────────────────────────────────────────────────────────────────────

_BASE_THRESHOLD = 52.0   # Base threshold — lower than old 65 to capture more trades

# Session adjustments (+/- on base threshold)
_SESSION_THRESHOLD_ADJ: Dict[Session, float] = {
    Session.OPENING:   -5.0,   # 47 — opening = best risk/reward, be aggressive
    Session.MORNING:   -2.0,   # 50 — strong morning continuation plays
    Session.MIDDAY:    +2.0,   # 54 — midday = more noise, slightly tighter
    Session.AFTERNOON: +8.0,   # 60 — late session = tight, only A+ allowed
}

# Impulse grade bonuses (reduce threshold when strong impulse detected)
_IMPULSE_THRESHOLD_ADJ: Dict[str, float] = {
    "EXTREME": -10.0,   # EXTREME impulse = highest conviction, big reduction
    "STRONG":  -5.0,    # STRONG impulse = good reduction
    "WEAK":    -2.0,    # WEAK impulse = small reduction
    "NONE":     0.0,
}

# VIX adjustments
def _vix_threshold_adj(vix: float) -> float:
    if vix < 13:   return -3.0   # Very calm = opportunity rich
    if vix < 17:   return  0.0   # Normal
    if vix < 22:   return +3.0   # Elevated = tighter
    if vix < 27:   return +6.0   # High VIX
    return +10.0                  # Extreme VIX = very tight


def get_entry_threshold(
    session: Session,
    impulse_grade: str = "NONE",
    vix: float = 15.0,
    is_strong_trend: bool = False,
    override_threshold: float = 0.0,  # From UI slider (0 = no override)
) -> float:
    """
    Compute adaptive confidence threshold for this entry.

    On EXTREME impulse + STRONG_BULL/BEAR morning session → threshold can be as
    low as ~32 (= 47 - 10 - 5) ensuring we NEVER miss a gap-and-go day.
    On late afternoon + high VIX → threshold rises to 70+ (very conservative).
    """
    if override_threshold > 0:
        return override_threshold

    thresh = _BASE_THRESHOLD
    thresh += _SESSION_THRESHOLD_ADJ[session]
    thresh += _IMPULSE_THRESHOLD_ADJ.get(impulse_grade, 0.0)
    thresh += _vix_threshold_adj(vix)

    # Strong trend bonus: market has declared direction, be more aggressive
    if is_strong_trend:
        thresh -= 5.0

    return max(30.0, min(75.0, thresh))   # Hard bounds: 30-75


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Lot Sizing
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LotDecision:
    lots: int
    reasoning: str
    risk_pct: float         # Actual risk % being used
    impulse_multiplier: float
    conviction_multiplier: float


def compute_dynamic_lots(
    base_lots: int,
    max_lots: int,
    capital: float,
    entry_price: float,
    sl_pct: float,
    conviction: float,          # 0.0 – 1.0 from TrendResult
    impulse_grade: str,         # NONE / WEAK / STRONG / EXTREME
    session: Session,
    daily_pnl: float = 0.0,     # Positive = profitable day so far
    base_risk_pct: float = 0.02,
    lot_size: int = 65,
) -> LotDecision:
    """
    Compute lots dynamically based on conviction + impulse + session + P&L state.

    Sizing philosophy:
      - EXTREME impulse + high conviction → max lots (we KNOW the direction)
      - WEAK impulse + low conviction → base lots (still enter, just smaller)
      - Profitable day → can size up slightly (house money)
      - Session matters: morning entries get more size than afternoon
    """
    # ── Conviction multiplier (0.6 → 1.0 maps to 0.7x → 1.3x lots)
    if conviction >= 0.85:       conv_mult = 1.30
    elif conviction >= 0.70:     conv_mult = 1.15
    elif conviction >= 0.55:     conv_mult = 1.00
    elif conviction >= 0.40:     conv_mult = 0.85
    else:                        conv_mult = 0.70

    # ── Impulse multiplier
    _impulse_mults: Dict[str, float] = {
        "EXTREME": 1.50,   # A+ setup — go bigger
        "STRONG":  1.25,   # Strong setup — size up
        "WEAK":    1.00,   # Normal
        "NONE":    0.85,   # No impulse — slight reduction
    }
    imp_mult = _impulse_mults.get(impulse_grade, 1.0)

    # ── Session multiplier (afternoon = smaller, opening = normal)
    _session_mults: Dict[Session, float] = {
        Session.OPENING:   1.10,   # Best risk/reward time
        Session.MORNING:   1.00,
        Session.MIDDAY:    0.90,
        Session.AFTERNOON: 0.75,   # Late = less time to work, smaller
    }
    sess_mult = _session_mults[session]

    # ── P&L state multiplier (profitable day = can be slightly more aggressive)
    if daily_pnl > 0:
        pnl_mult = min(1.20, 1.0 + (daily_pnl / capital) * 3)
    else:
        pnl_mult = max(0.80, 1.0 + (daily_pnl / capital) * 2)  # scale down on lossy day

    # ── Combined multiplier
    combined = conv_mult * imp_mult * sess_mult * pnl_mult

    # ── Risk-based sizing (independent check)
    effective_risk_pct = base_risk_pct * combined
    risk_amount = capital * effective_risk_pct
    risk_per_unit = entry_price * sl_pct
    risk_lots = max(1, int(risk_amount / (risk_per_unit * lot_size))) if risk_per_unit > 0 else 1

    # ── Final lots: combine risk-based with multiplier, cap at max_lots
    # Use round() not int() so a 1.5x conviction boost on 1 base lot gives 2 lots (not 1)
    raw_lots = max(1, round(base_lots * combined))
    lots = max(1, min(max_lots, max(risk_lots, raw_lots)))

    reasoning = (
        f"base={base_lots} × conv={conv_mult:.2f} × imp={imp_mult:.2f} × "
        f"sess={sess_mult:.2f} × pnl={pnl_mult:.2f} = {combined:.2f} → {lots} lots "
        f"(risk_lots={risk_lots})"
    )

    return LotDecision(
        lots=lots,
        reasoning=reasoning,
        risk_pct=round(effective_risk_pct * 100, 2),
        impulse_multiplier=imp_mult,
        conviction_multiplier=conv_mult,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Strike Selection
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StrikeDecision:
    otm_offset: int        # -1 = ITM, 0 = ATM, 1 = 1-OTM, 2 = 2-OTM
    reasoning: str
    strike_type: str       # "ITM" / "ATM" / "OTM1" / "OTM2"


def compute_strike_offset(
    conviction: float,
    impulse_grade: str,
    daily_pnl: float,
    capital: float,
    session: Session,
    vix: float,
) -> StrikeDecision:
    """
    Choose ITM / ATM / OTM based on conviction + P&L state + session.

    Philosophy:
      - High conviction (EXTREME impulse) → OTM2 (big bang for buck)
      - Normal conviction → ATM (balanced delta, liquid)
      - Low conviction / late session → ITM (more delta, less theta risk)
      - Profitable day → can go OTM (speculation with profits)
      - Losing day → stay ATM or ITM (capital preservation)
      - High VIX → ATM or ITM (OTM premiums are inflated)
    """
    score = 0  # Positive = go OTM, Negative = go ITM

    # Impulse votes
    if impulse_grade == "EXTREME":  score += 2
    elif impulse_grade == "STRONG": score += 1
    elif impulse_grade == "NONE":   score -= 1

    # Conviction votes
    if conviction >= 0.80:   score += 1
    elif conviction < 0.50:  score -= 1

    # P&L state votes
    pnl_pct = daily_pnl / capital if capital > 0 else 0
    if pnl_pct > 0.02:    score += 1    # Up 2%+ today → can go OTM
    elif pnl_pct < -0.01: score -= 1   # Down → stay conservative

    # Session votes
    if session == Session.OPENING:    score += 1   # Opening = momentum, OTM works
    elif session == Session.AFTERNOON: score -= 2  # Late = stay ATM/ITM for delta

    # VIX votes (high VIX = inflated OTM premiums, bad value)
    if vix > 22:   score -= 1
    if vix > 27:   score -= 1

    # Map score to offset
    if score >= 3:
        offset, stype = 2, "OTM2"
    elif score >= 1:
        offset, stype = 1, "OTM1"
    elif score >= -1:
        offset, stype = 0, "ATM"
    else:
        offset, stype = -1, "ITM"

    reasoning = (
        f"score={score} (impulse={impulse_grade}, conv={conviction:.2f}, "
        f"pnl_pct={pnl_pct*100:.1f}%, session={session.value}, vix={vix:.1f}) → {stype}"
    )

    return StrikeDecision(otm_offset=offset, reasoning=reasoning, strike_type=stype)


# ─────────────────────────────────────────────────────────────────────────────
# Adaptive Momentum Confirmation
# ─────────────────────────────────────────────────────────────────────────────

def confirm_momentum_adaptive(
    direction: str,
    candles: List[Dict[str, Any]],
    impulse_grade: str,
    conviction: float,
) -> tuple[bool, str]:
    """
    Smarter momentum confirmation than the old 2-of-3 candles check.

    EXTREME impulse → just 1 confirming candle is enough (we already KNOW)
    STRONG impulse  → 1 of last 2 candles must confirm
    No impulse      → 2 of last 3 candles must confirm (original logic)
    High conviction → slightly relax the bar
    """
    completed = [c for c in candles if c.get("ts") is not None][-4:-1]  # last 3 completed
    if len(completed) < 1:
        return True, "insufficient candles — skipping check"

    bull_count = sum(1 for c in completed if float(c["close"]) >= float(c["open"]))
    bear_count = len(completed) - bull_count
    current_close = float(completed[-1]["close"])
    avg_close = sum(float(c["close"]) for c in completed) / len(completed)

    # EXTREME impulse: just check that the LAST candle confirms
    if impulse_grade == "EXTREME":
        if direction == "PUT":
            ok = float(completed[-1]["close"]) < float(completed[-1]["open"])
            return ok, f"EXTREME_IMPULSE: last candle {'confirms' if ok else 'does not confirm'} PUT"
        else:
            ok = float(completed[-1]["close"]) > float(completed[-1]["open"])
            return ok, f"EXTREME_IMPULSE: last candle {'confirms' if ok else 'does not confirm'} CALL"

    # STRONG impulse or high conviction: 1 of last 2 is enough
    if impulse_grade == "STRONG" or conviction >= 0.75:
        last2 = completed[-2:]
        if direction == "PUT":
            ok = any(float(c["close"]) < float(c["open"]) for c in last2)
            return ok, f"STRONG: {sum(1 for c in last2 if c['close'] < c['open'])}/2 bear candles"
        else:
            ok = any(float(c["close"]) > float(c["open"]) for c in last2)
            return ok, f"STRONG: {sum(1 for c in last2 if c['close'] > c['open'])}/2 bull candles"

    # Normal: 2 of last 3 must confirm (same as original but with avg check removed for convicted trades)
    if direction == "PUT":
        momentum_ok = bear_count >= 2 and (current_close <= avg_close or conviction >= 0.60)
        reason = (
            f"PUT: {bear_count}/{len(completed)} bear candles, "
            f"price {current_close:.0f} vs avg {avg_close:.0f}, conv={conviction:.2f}"
        )
    else:
        momentum_ok = bull_count >= 2 and (current_close >= avg_close or conviction >= 0.60)
        reason = (
            f"CALL: {bull_count}/{len(completed)} bull candles, "
            f"price {current_close:.0f} vs avg {avg_close:.0f}, conv={conviction:.2f}"
        )

    return momentum_ok, reason


# ─────────────────────────────────────────────────────────────────────────────
# Adaptive Re-entry Gating
# ─────────────────────────────────────────────────────────────────────────────

def should_allow_reentry(
    direction: str,
    lost_at: Optional[datetime],
    current_trend_state: str,
    conviction: float,
    impulse_grade: str,
    reentries_today: int,
    max_reentries: int = 2,
    block_duration_minutes: int = 30,
) -> tuple[bool, str]:
    """
    Decide if re-entry in the same direction is allowed after a loss.

    Key improvement over old logic:
      - Block lifts after `block_duration_minutes` (default 30 min)
      - Re-entry allowed in ANY strong trend (not just STRONG_TREND_DOWN)
      - max_reentries raised to 2
      - EXTREME impulse bypasses time block (market is still running)
    """
    if reentries_today >= max_reentries:
        return False, f"Max re-entries reached ({reentries_today}/{max_reentries})"

    # EXTREME impulse always allows re-entry (market showing conviction)
    if impulse_grade == "EXTREME":
        return True, "EXTREME impulse — re-entry always allowed"

    # Time block: direction is blocked for `block_duration_minutes` after loss
    if lost_at is not None:
        from datetime import datetime as _dt
        elapsed = (_dt.now() - lost_at).total_seconds() / 60
        if elapsed < block_duration_minutes:
            return False, f"Direction block: {elapsed:.0f}/{block_duration_minutes} min elapsed"

    # Trend must still be strong in the same direction
    strong_states = {"STRONG_BULL", "STRONG_BEAR", "BULL", "BEAR",
                     "STRONG_TREND_UP", "STRONG_TREND_DOWN", "MILD_TREND"}
    if current_trend_state not in strong_states:
        return False, f"Trend not strong enough for re-entry: {current_trend_state}"

    # Conviction gate
    if conviction < 0.60:
        return False, f"Conviction too low for re-entry: {conviction:.2f}"

    return True, f"Re-entry OK: trend={current_trend_state} conv={conviction:.2f} elapsed={elapsed if lost_at else 'N/A':.0f}min"


# ─────────────────────────────────────────────────────────────────────────────
# Adaptive Trailing Parameters
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TrailParams:
    trigger_pct: float      # When to start trailing
    lock_step_pct: float    # How much to lock per step
    break_even_pct: float   # When to move to break-even


def compute_trail_params(
    impulse_grade: str,
    conviction: float,
    session: Session,
) -> TrailParams:
    """
    Adaptive trailing: stronger conviction = wider trail (let winners run).

    EXTREME impulse: trail trigger at 20%, lock 18% — wide trail, catch the move
    Normal: trail trigger at 25%, lock 12%
    Late session: tighter trail to capture gains before close
    """
    # Base params
    if impulse_grade == "EXTREME" and conviction >= 0.75:
        trigger, lock, be = 0.18, 0.18, 0.06
    elif impulse_grade == "STRONG" or conviction >= 0.75:
        trigger, lock, be = 0.22, 0.15, 0.06
    elif conviction >= 0.55:
        trigger, lock, be = 0.25, 0.12, 0.07
    else:
        trigger, lock, be = 0.28, 0.10, 0.08

    # Afternoon: tighten trail to capture profits before close
    if session == Session.AFTERNOON:
        trigger = max(0.12, trigger - 0.06)
        lock = max(0.08, lock - 0.03)

    return TrailParams(
        trigger_pct=round(trigger, 3),
        lock_step_pct=round(lock, 3),
        break_even_pct=round(be, 3),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Adaptive Profit Stop (replaces 2R day stop)
# ─────────────────────────────────────────────────────────────────────────────

def compute_profit_stop_threshold(
    impulse_grade: str,
    trend_state: str,
    base_r: float,
) -> float:
    """
    Dynamic profit stop: stop adding trades after this multiple of R.

    On EXTREME impulse days, the trend can run 5-10R — don't stop at 2R!
    On normal days, 3R is a great day — stop there.
    """
    if impulse_grade == "EXTREME" and trend_state in ("STRONG_BULL", "STRONG_BEAR"):
        return base_r * 6.0   # Let it run on gap-and-go days
    if trend_state in ("STRONG_BULL", "STRONG_BEAR"):
        return base_r * 4.0   # Strong trend days
    return base_r * 3.0       # Normal days


# ─────────────────────────────────────────────────────────────────────────────
# Adaptive Structure Exit
# ─────────────────────────────────────────────────────────────────────────────

def should_exit_on_structure(
    direction: str,
    candles: List[Dict[str, Any]],
    current_gain_pct: float,
    min_profit_pct: float = 0.08,
    consecutive_reversal_candles: int = 2,
) -> tuple[bool, str]:
    """
    Exit on structure break — but require MULTIPLE consecutive reversal candles.

    Old logic: 1 candle with lower high = exit (too trigger-happy!)
    New logic: Need N consecutive reversal candles to confirm structure break.

    Also requires min 8% profit (up from 5%) before structure exits fire.
    """
    if current_gain_pct < min_profit_pct:
        return False, f"Profit {current_gain_pct*100:.1f}% < {min_profit_pct*100:.0f}% min"

    if len(candles) < consecutive_reversal_candles + 1:
        return False, "insufficient candles"

    recent = candles[-(consecutive_reversal_candles + 1):]

    if direction == "PUT":
        # PUT: Nifty must make consecutive higher lows AND higher closes
        reversal_count = 0
        for i in range(1, len(recent)):
            curr, prev = recent[i], recent[i - 1]
            if float(curr["low"]) > float(prev["low"]) and float(curr["close"]) > float(prev["close"]):
                reversal_count += 1
        if reversal_count >= consecutive_reversal_candles:
            lows = [f"{float(c['low']):.0f}" for c in recent]
            return True, f"PUT STRUCTURE BREAK: {consecutive_reversal_candles} consecutive higher lows: {' → '.join(lows)}"

    elif direction == "CALL":
        # CALL: Nifty must make consecutive lower highs AND lower closes
        reversal_count = 0
        for i in range(1, len(recent)):
            curr, prev = recent[i], recent[i - 1]
            if float(curr["high"]) < float(prev["high"]) and float(curr["close"]) < float(prev["close"]):
                reversal_count += 1
        if reversal_count >= consecutive_reversal_candles:
            highs = [f"{float(c['high']):.0f}" for c in recent]
            return True, f"CALL STRUCTURE BREAK: {consecutive_reversal_candles} consecutive lower highs: {' → '.join(highs)}"

    return False, f"No structure break ({consecutive_reversal_candles} consecutive candles required)"


# ─────────────────────────────────────────────────────────────────────────────
# ATR-Based Dynamic SL (market-anchored, not fixed %)
# ─────────────────────────────────────────────────────────────────────────────

def compute_atm_sl_from_nifty_atr(
    candles: List[Dict[str, Any]],
    opt_price: float,
    otm_offset: int = 0,
    atr_multiplier: float = 1.5,
    atr_period: int = 14,
) -> tuple[float, str]:
    """
    Compute option SL % anchored to Nifty's ATR instead of a fixed % of option price.

    Steps:
      1. Compute Nifty ATR (14-period by default)
      2. Nifty stop distance = ATR × multiplier
      3. Estimate option delta by moneyness (otm_offset)
      4. Option SL % = (Nifty SL distance × delta) / option_price

    Clamped to [15%, 42%] for sanity. Wider OTM = lower delta = larger SL% needed.
    """
    if len(candles) < atr_period + 1 or opt_price <= 0:
        logger.warning(f"compute_atm_sl_from_nifty_atr: fallback SL 28% (candles={len(candles)}, opt_price={opt_price})")
        return 0.28, "insufficient candles — fallback 28%"

    trs: List[float] = []
    for i in range(1, min(atr_period + 1, len(candles))):
        c = candles[-i]
        p = candles[-(i + 1)]
        tr = max(
            float(c["high"]) - float(c["low"]),
            abs(float(c["high"]) - float(p["close"])),
            abs(float(c["low"]) - float(p["close"])),
        )
        trs.append(tr)

    if not trs:
        logger.warning("compute_atm_sl_from_nifty_atr: no TR data — fallback SL 28%")
        return 0.28, "no TR data — fallback 28%"

    atr = sum(trs) / len(trs)
    nifty_sl_pts = atr * atr_multiplier

    # Approximate delta by moneyness
    _delta_by_offset: Dict[int, float] = {-1: 0.65, 0: 0.50, 1: 0.35, 2: 0.25}
    delta = _delta_by_offset.get(otm_offset, 0.40)

    option_sl_move = nifty_sl_pts * delta
    sl_pct = option_sl_move / opt_price
    sl_pct = max(0.15, min(0.42, sl_pct))

    reason = (
        f"ATR={atr:.0f} × {atr_multiplier} = {nifty_sl_pts:.0f}pts | "
        f"delta≈{delta} → opt_move={option_sl_move:.1f} / ₹{opt_price:.0f} = {sl_pct*100:.1f}%"
    )
    return round(sl_pct, 3), reason


def compute_dynamic_target(
    sl_pct: float,
    impulse_grade: str,
    conviction: float,
    session: Session,
    trend_state: str,
) -> tuple[float, str]:
    """
    Compute target % dynamically as a multiple of the SL.

    Better R:R on high-conviction setups — let winners run further.
    On A+ (EXTREME impulse + STRONG trend) we target 4-5R.
    Normal setups: 2-3R.
    Late session: tighten to 2R (less time for premium to compound).
    """
    # R:R multiplier
    if impulse_grade == "EXTREME" and trend_state in ("STRONG_BULL", "STRONG_BEAR"):
        rr = 4.5   # A+ — huge move potential
    elif impulse_grade == "STRONG" or conviction >= 0.75:
        rr = 3.5   # Strong setup
    elif conviction >= 0.55:
        rr = 2.8   # Normal
    else:
        rr = 2.2   # Marginal — tight

    # Late session: less time, tighten target
    if session == Session.AFTERNOON:
        rr = min(rr, 2.5)

    target_pct = round(sl_pct * rr, 3)
    # Clamp 25% - 100%
    target_pct = max(0.25, min(1.00, target_pct))

    reason = (
        f"RR={rr:.1f}x | sl={sl_pct*100:.1f}% → target={target_pct*100:.1f}% "
        f"(impulse={impulse_grade}, conv={conviction:.2f}, session={session.value})"
    )
    return target_pct, reason


# ─────────────────────────────────────────────────────────────────────────────
# Bot Narrative Generator (for UI story panel)
# ─────────────────────────────────────────────────────────────────────────────

def generate_bot_narrative(
    session: Session,
    trend_state: str,
    conviction: float,
    impulse_grade: str,
    daily_regime: Optional[str],
    position_active: bool,
    daily_pnl: float,
    skip_reasons: List[Dict],
    trades_today: int,
    max_trades: int,
    vix: float,
) -> Dict[str, Any]:
    """
    Generate a human-readable narrative of what the bot is doing and why.
    This powers the UI 'Story Panel' — so you can understand the bot's mind.
    """
    lines = []
    status = "WATCHING"  # WATCHING / HUNTING / IN_TRADE / HALTED

    # ── Market context
    session_desc = {
        Session.OPENING:   "Opening session (9:15-10:00) — ORB & impulse plays active",
        Session.MORNING:   "Morning session (10:00-11:30) — EMA & VWAP plays active",
        Session.MIDDAY:    "Midday session (11:30-13:30) — Trend continuation mode",
        Session.AFTERNOON: "Afternoon session (13:30-15:00) — Tight filters, A+ only",
    }
    lines.append(f"📍 {session_desc[session]}")

    # ── Regime
    if daily_regime:
        lines.append(f"📊 Daily regime: {daily_regime}")

    # ── Trend
    trend_emoji = {
        "STRONG_BULL": "🟢🟢", "BULL": "🟢", "NEUTRAL": "⚪",
        "BEAR": "🔴", "STRONG_BEAR": "🔴🔴",
    }.get(trend_state, "⚪")
    lines.append(f"{trend_emoji} Intraday trend: {trend_state} (conviction {conviction*100:.0f}%)")

    # ── Impulse
    if impulse_grade not in ("NONE", None):
        imp_emoji = {"EXTREME": "⚡⚡", "STRONG": "⚡", "WEAK": "〰️"}.get(impulse_grade, "")
        lines.append(f"{imp_emoji} Opening impulse: {impulse_grade} — extra bonus votes added to trend score")

    # ── VIX
    if vix > 25:
        lines.append(f"⚠️ High VIX: {vix:.1f} — thresholds tightened, lot sizes reduced")
    elif vix < 14:
        lines.append(f"✅ Calm VIX: {vix:.1f} — ideal conditions, thresholds relaxed")

    # ── Position status
    if position_active:
        lines.append("🎯 IN TRADE — monitoring for target/trail/structure exit")
        status = "IN_TRADE"
    elif trades_today >= max_trades:
        lines.append(f"✋ Max trades reached ({trades_today}/{max_trades}) — done for the day")
        status = "HALTED"
    else:
        lines.append(f"👀 Scanning for entry ({trades_today}/{max_trades} trades today)")
        status = "HUNTING" if conviction >= 0.55 else "WATCHING"

    # ── Skip context
    if skip_reasons:
        recent_skip = skip_reasons[-1]
        lines.append(
            f"⏭️ Last skip: {recent_skip.get('strategy', '')} {recent_skip.get('direction', '')} "
            f"— {recent_skip.get('reason', 'unknown reason')}"
        )

    # ── P&L context
    if daily_pnl > 0:
        lines.append(f"💰 Up ₹{daily_pnl:.0f} today — playing with profits, can be slightly aggressive")
    elif daily_pnl < -1000:
        lines.append(f"🩸 Down ₹{abs(daily_pnl):.0f} today — being conservative, preserving capital")

    return {
        "status": status,
        "narrative": lines,
        "session": session.value,
        "trend_emoji": trend_emoji,
        "conviction_pct": round(conviction * 100, 1),
        "impulse_grade": impulse_grade,
        "vix": vix,
    }
