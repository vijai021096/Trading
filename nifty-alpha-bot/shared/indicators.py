"""
Pure indicator functions — no I/O, no dependencies on broker or config.
All functions operate on a list of OHLCV candle dicts:
  {"ts": datetime, "open": float, "high": float, "low": float, "close": float, "volume": float}
"""
from __future__ import annotations

from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional, Tuple


# ─── Candle normalisation ─────────────────────────────────────────────────────

def normalize_candles(raw: List[Any]) -> List[Dict[str, Any]]:
    """Convert broker-specific candle formats to a unified dict list."""
    out: List[Dict[str, Any]] = []
    for c in raw:
        if isinstance(c, dict):
            ts_raw = c.get("ts") or c.get("time") or c.get("datetime") or c.get("date")
            o, h, l, cl = c.get("open"), c.get("high"), c.get("low"), c.get("close")
            vol = c.get("volume", 0.0)
        elif isinstance(c, (list, tuple)) and len(c) >= 5:
            ts_raw, o, h, l, cl = c[0], c[1], c[2], c[3], c[4]
            vol = float(c[5]) if len(c) > 5 else 0.0
        else:
            continue
        ts = _parse_ts(ts_raw)
        if ts is None:
            continue
        try:
            out.append({
                "ts": ts,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(cl),
                "volume": float(vol),
            })
        except Exception:
            continue
    out.sort(key=lambda x: x["ts"])
    return out


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e12 else value)
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except Exception:
            return None
    return None


# ─── ORB ─────────────────────────────────────────────────────────────────────

def orb_levels(
    candles: List[Dict[str, Any]],
    start: dtime,
    end: dtime,
) -> Optional[Dict[str, float]]:
    """Return {"high": float, "low": float} for the opening range window."""
    window = [c for c in candles if start <= c["ts"].time() < end]
    if not window:
        return None
    return {
        "high": max(float(c["high"]) for c in window),
        "low": min(float(c["low"]) for c in window),
    }


# ─── VWAP ─────────────────────────────────────────────────────────────────────

def vwap_at(candles: List[Dict[str, Any]], ts: datetime) -> Optional[float]:
    """Cumulative VWAP from session start up to and including `ts`."""
    subset = [c for c in candles if c["ts"] <= ts]
    if not subset:
        return None
    cum_tpv = 0.0
    cum_vol = 0.0
    for c in subset:
        tp = (float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0
        vol = float(c.get("volume", 1.0)) or 1.0
        cum_tpv += tp * vol
        cum_vol += vol
    return cum_tpv / cum_vol if cum_vol > 0 else None


# ─── EMA ──────────────────────────────────────────────────────────────────────

def ema_at(
    candles: List[Dict[str, Any]],
    ts: datetime,
    period: int = 9,
) -> Optional[float]:
    """Exponential moving average up to `ts`."""
    subset = [c for c in candles if c["ts"] <= ts]
    if len(subset) < 3:
        return None
    effective = min(period, len(subset))
    alpha = 2.0 / (effective + 1.0)
    ema = float(subset[0]["close"])
    for c in subset[1:]:
        ema = float(c["close"]) * alpha + ema * (1.0 - alpha)
    return ema


def ema_series(candles: List[Dict[str, Any]], period: int = 9) -> List[float]:
    """Return EMA value at every candle (same length as input)."""
    if not candles:
        return []
    alpha = 2.0 / (period + 1.0)
    result = []
    ema = float(candles[0]["close"])
    for c in candles:
        ema = float(c["close"]) * alpha + ema * (1.0 - alpha)
        result.append(ema)
    return result


# ─── RSI ──────────────────────────────────────────────────────────────────────

def rsi_at(
    candles: List[Dict[str, Any]],
    ts: datetime,
    period: int = 14,
) -> Optional[float]:
    subset = [c for c in candles if c["ts"] <= ts]
    if len(subset) < max(4, period + 1):
        return None
    effective = min(period, len(subset) - 1)
    gains, losses = [], []
    for i in range(1, len(subset)):
        delta = float(subset[i]["close"]) - float(subset[i - 1]["close"])
        gains.append(max(0.0, delta))
        losses.append(max(0.0, -delta))
    avg_gain = sum(gains[-effective:]) / effective
    avg_loss = sum(losses[-effective:]) / effective
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ─── ATR ──────────────────────────────────────────────────────────────────────

def atr_at(
    candles: List[Dict[str, Any]],
    ts: datetime,
    period: int = 14,
) -> Optional[float]:
    subset = [c for c in candles if c["ts"] <= ts]
    if len(subset) < period + 1:
        return None
    trs = []
    prev_close = float(subset[0]["close"])
    for c in subset[1:]:
        hi, lo = float(c["high"]), float(c["low"])
        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        trs.append(tr)
        prev_close = float(c["close"])
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def atr_series(candles: List[Dict[str, Any]], period: int = 14) -> List[Optional[float]]:
    """ATR at every candle position."""
    result: List[Optional[float]] = []
    for i, c in enumerate(candles):
        result.append(atr_at(candles[: i + 1], c["ts"], period))
    return result


# ─── Supertrend ───────────────────────────────────────────────────────────────

def supertrend_series(
    candles: List[Dict[str, Any]],
    period: int = 10,
    multiplier: float = 3.0,
) -> List[Dict[str, Any]]:
    """
    Returns list of dicts: {"trend": "UP"/"DOWN", "line": float}
    One entry per candle.
    """
    n = len(candles)
    if n < period + 1:
        return [{"trend": "UNKNOWN", "line": 0.0}] * n

    atrs = atr_series(candles, period)
    results = []
    prev_upper = prev_lower = prev_trend = None

    for i, c in enumerate(candles):
        atr = atrs[i]
        if atr is None:
            results.append({"trend": "UNKNOWN", "line": 0.0})
            continue

        hl2 = (float(c["high"]) + float(c["low"])) / 2.0
        basic_upper = hl2 + multiplier * atr
        basic_lower = hl2 - multiplier * atr

        if prev_upper is None:
            upper, lower = basic_upper, basic_lower
            trend = "UP"
        else:
            close = float(candles[i - 1]["close"]) if i > 0 else float(c["close"])
            upper = basic_upper if basic_upper < prev_upper or close > prev_upper else prev_upper
            lower = basic_lower if basic_lower > prev_lower or close < prev_lower else prev_lower

            if prev_trend == "UP":
                trend = "DOWN" if float(c["close"]) < lower else "UP"
            else:
                trend = "UP" if float(c["close"]) > upper else "DOWN"

        line = lower if trend == "UP" else upper
        results.append({"trend": trend, "line": line})
        prev_upper, prev_lower, prev_trend = upper, lower, trend

    return results


# ─── Volume analysis ──────────────────────────────────────────────────────────

def avg_volume(
    candles: List[Dict[str, Any]],
    ts: datetime,
    lookback: int = 20,
) -> Optional[float]:
    """Average volume of the last `lookback` candles before (not including) `ts`."""
    subset = [c for c in candles if c["ts"] < ts]
    if len(subset) < lookback:
        return None
    recent = subset[-lookback:]
    vols = [float(c.get("volume", 0.0)) for c in recent]
    return sum(vols) / len(vols) if vols else None


def volume_surge_ratio(
    candle: Dict[str, Any],
    candles: List[Dict[str, Any]],
    lookback: int = 20,
) -> Optional[float]:
    """Ratio of this candle's volume to recent average."""
    avg = avg_volume(candles, candle["ts"], lookback)
    if avg is None or avg == 0:
        return None
    return float(candle.get("volume", 0.0)) / avg


# ─── Candle body quality ─────────────────────────────────────────────────────

def body_ratio(candle: Dict[str, Any]) -> float:
    """Body size as fraction of total high-low range."""
    hi, lo = float(candle["high"]), float(candle["low"])
    total_range = hi - lo
    if total_range == 0:
        return 0.0
    body = abs(float(candle["close"]) - float(candle["open"]))
    return body / total_range


def is_bullish_candle(candle: Dict[str, Any]) -> bool:
    return float(candle["close"]) > float(candle["open"])


def is_bearish_candle(candle: Dict[str, Any]) -> bool:
    return float(candle["close"]) < float(candle["open"])


# ─── VWAP cross detection ─────────────────────────────────────────────────────

def vwap_cross_up(
    candles: List[Dict[str, Any]],
    idx: int,
    lookback: int = 3,
) -> bool:
    """
    Returns True if price crossed above VWAP at candle[idx],
    having been below for the previous `lookback` candles.
    """
    if idx < lookback:
        return False
    current = candles[idx]
    vwap_now = vwap_at(candles, current["ts"])
    if vwap_now is None:
        return False
    if float(current["close"]) <= vwap_now:
        return False
    # Check previous candles were below VWAP
    below_count = 0
    for j in range(idx - lookback, idx):
        c = candles[j]
        v = vwap_at(candles, c["ts"])
        if v is not None and float(c["close"]) < v:
            below_count += 1
    return below_count >= lookback - 1


def vwap_cross_down(
    candles: List[Dict[str, Any]],
    idx: int,
    lookback: int = 3,
) -> bool:
    """Returns True if price crossed below VWAP at candle[idx]."""
    if idx < lookback:
        return False
    current = candles[idx]
    vwap_now = vwap_at(candles, current["ts"])
    if vwap_now is None:
        return False
    if float(current["close"]) >= vwap_now:
        return False
    above_count = 0
    for j in range(idx - lookback, idx):
        c = candles[j]
        v = vwap_at(candles, c["ts"])
        if v is not None and float(c["close"]) > v:
            above_count += 1
    return above_count >= lookback - 1
