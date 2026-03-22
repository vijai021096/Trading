"""
Downloads historical NIFTY50 5-minute candle data and India VIX.
Caches to Parquet files locally to avoid re-downloading.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def _cache_path(name: str) -> Path:
    return DATA_DIR / f"{name}.parquet"


def download_nifty_spot(
    months: int = 12,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Download NIFTY50 (^NSEI) 5-minute OHLCV data.
    yfinance gives at most 60 days of 5m data per request — we chunk it.

    Returns DataFrame with columns: ts, open, high, low, close, volume
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("Run: pip install yfinance")

    cache = _cache_path("nifty_5m")
    if cache.exists() and not force_refresh:
        df = pd.read_parquet(cache)
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=months * 31)
        df["ts"] = pd.to_datetime(df["ts"])
        df = df[df["ts"] >= cutoff]
        if len(df) > 100:
            print(f"[DataLoader] Loaded {len(df)} candles from cache.")
            return df

    print("[DataLoader] Downloading NIFTY50 5m data from yfinance...")
    end_dt = datetime.now()
    chunks = []
    chunk_days = 55  # Stay under 60-day yfinance limit

    total_days = months * 30
    for offset in range(0, total_days, chunk_days):
        chunk_end = end_dt - timedelta(days=offset)
        chunk_start = chunk_end - timedelta(days=chunk_days)
        try:
            ticker = yf.Ticker("^NSEI")
            df_chunk = ticker.history(
                start=chunk_start.strftime("%Y-%m-%d"),
                end=chunk_end.strftime("%Y-%m-%d"),
                interval="5m",
                auto_adjust=True,
            )
            if df_chunk.empty:
                continue
            df_chunk = df_chunk.reset_index()
            # Normalize column names
            df_chunk.columns = [c.lower().replace(" ", "_") for c in df_chunk.columns]
            ts_col = "datetime" if "datetime" in df_chunk.columns else df_chunk.columns[0]
            df_chunk = df_chunk.rename(columns={ts_col: "ts"})
            df_chunk["ts"] = pd.to_datetime(df_chunk["ts"]).dt.tz_localize(None)
            for col in ["open", "high", "low", "close"]:
                df_chunk[col] = df_chunk[col].astype(float)
            df_chunk["volume"] = df_chunk.get("volume", pd.Series(0, index=df_chunk.index)).astype(float)
            chunks.append(df_chunk[["ts", "open", "high", "low", "close", "volume"]])
            print(f"  chunk {chunk_start.date()} → {chunk_end.date()}: {len(df_chunk)} rows")
            time.sleep(0.5)  # Polite delay
        except Exception as e:
            print(f"  [WARN] chunk {chunk_start.date()} failed: {e}")

    if not chunks:
        raise RuntimeError("No data downloaded. Check internet connection.")

    df = pd.concat(chunks).drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)

    # Filter to IST market hours only (9:15–15:30)
    df = df[(df["ts"].dt.time >= pd.Timestamp("09:15").time()) &
            (df["ts"].dt.time <= pd.Timestamp("15:30").time())]

    df.to_parquet(cache, index=False)
    print(f"[DataLoader] Saved {len(df)} candles to {cache}")
    return df


def download_india_vix(
    months: int = 12,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Download India VIX daily data.
    Returns DataFrame with columns: date, vix
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("Run: pip install yfinance")

    cache = _cache_path("india_vix_daily")
    if cache.exists() and not force_refresh:
        df = pd.read_parquet(cache)
        cutoff = (pd.Timestamp.now() - pd.Timedelta(days=months * 31)).date()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df[df["date"] >= cutoff]
        if len(df) > 10:
            print(f"[DataLoader] Loaded {len(df)} VIX rows from cache.")
            return df

    print("[DataLoader] Downloading India VIX from yfinance...")
    try:
        ticker = yf.Ticker("^INDIAVIX")
        df = ticker.history(period=f"{months}mo", interval="1d")
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        date_col = "date" if "date" in df.columns else df.columns[0]
        df = df.rename(columns={date_col: "date", "close": "vix"})
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.date
        df = df[["date", "vix"]].dropna().sort_values("date").reset_index(drop=True)
        df.to_parquet(cache, index=False)
        print(f"[DataLoader] Saved {len(df)} VIX rows.")
        return df
    except Exception as e:
        print(f"[WARN] VIX download failed: {e}. Using synthetic VIX=14.")
        # Return synthetic VIX data (conservative fallback)
        nifty = download_nifty_spot(months)
        dates = nifty["ts"].dt.date.unique()
        df = pd.DataFrame({"date": dates, "vix": 14.0})
        return df


def get_vix_for_date(vix_df: pd.DataFrame, trade_date: date) -> float:
    """Look up VIX for a given date, falling back to recent average."""
    row = vix_df[vix_df["date"] == trade_date]
    if not row.empty:
        return float(row.iloc[0]["vix"])
    # Fallback: last known VIX
    past = vix_df[vix_df["date"] < trade_date]
    if not past.empty:
        return float(past.iloc[-1]["vix"])
    return 14.0  # Conservative default


def get_daily_candles(
    df_5m: pd.DataFrame,
    trade_date: date,
    warmup_days: int = 5,
) -> list:
    """
    Extract 5m candles for a specific trading date.
    Includes `warmup_days` of prior candles so EMAs are properly warmed up.
    Candles from prior days have ts before 9:15 of trade_date so ORB logic
    still only picks up the correct day's range.
    """
    df_5m = df_5m.copy()
    df_5m["ts"] = pd.to_datetime(df_5m["ts"])
    df_5m["date"] = df_5m["ts"].dt.date

    # Get prior days for warmup
    all_dates = sorted(df_5m["date"].unique())
    try:
        idx = all_dates.index(trade_date)
    except ValueError:
        idx = -1

    if idx > 0 and warmup_days > 0:
        prior_dates = all_dates[max(0, idx - warmup_days): idx]
        warmup_df = df_5m[df_5m["date"].isin(prior_dates)]
    else:
        warmup_df = pd.DataFrame(columns=df_5m.columns)

    day_df = df_5m[df_5m["date"] == trade_date]
    combined = pd.concat([warmup_df, day_df]).sort_values("ts")

    candles = []
    for _, row in combined.iterrows():
        candles.append({
            "ts": row["ts"].to_pydatetime(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume", 0.0)),
        })
    return candles
