"""
Kite Connect historical data downloader for 1-year backtesting.

Fetches 5-minute NIFTY 50 candles via Zerodha Kite API.
Kite allows up to 60 days per request for minute intervals.
We chunk in 55-day windows to stay under the limit.

Usage:
    from backtest.kite_downloader import download_nifty_kite
    df = download_nifty_kite(kite_client, months=12)
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

NIFTY_TOKEN = 256265   # NSE:NIFTY 50 instrument token (standard Kite token)


def download_nifty_kite(
    kite_client,
    months: int = 12,
    force_refresh: bool = False,
    instrument_token: int = NIFTY_TOKEN,
) -> pd.DataFrame:
    """
    Download NIFTY 50 5-minute OHLCV using Kite Connect API.

    Args:
        kite_client:        Authenticated KiteClient instance
        months:             How many months of history to fetch (max ~12 for 5m data)
        force_refresh:      Re-download even if cache exists
        instrument_token:   Kite instrument token for NIFTY 50 index

    Returns:
        DataFrame with columns: ts, open, high, low, close, volume
    """
    cache = DATA_DIR / "nifty_5m_kite.parquet"

    if cache.exists() and not force_refresh:
        df = pd.read_parquet(cache)
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=months * 31)
        df["ts"] = pd.to_datetime(df["ts"])
        df = df[df["ts"] >= cutoff]
        if len(df) > 500:
            print(f"[KiteLoader] Loaded {len(df)} candles from Kite cache.")
            return df
        print(f"[KiteLoader] Cache too small ({len(df)} candles), re-fetching...")

    print(f"[KiteLoader] Downloading {months} months of NIFTY 5m data from Kite...")

    end_dt   = datetime.now().replace(hour=15, minute=30, second=0, microsecond=0)
    chunk_days = 55   # Kite limit is 60 days for minute data, stay under
    total_days = months * 30
    chunks = []

    for offset in range(0, total_days, chunk_days):
        chunk_end   = end_dt - timedelta(days=offset)
        chunk_start = chunk_end - timedelta(days=chunk_days)

        try:
            raw = kite_client.kite.historical_data(
                instrument_token=instrument_token,
                from_date=chunk_start,
                to_date=chunk_end,
                interval="5minute",
                continuous=False,
                oi=False,
            )
            if not raw:
                continue

            rows = []
            for c in raw:
                rows.append({
                    "ts":     c["date"].replace(tzinfo=None) if hasattr(c["date"], "tzinfo") else c["date"],
                    "open":   float(c["open"]),
                    "high":   float(c["high"]),
                    "low":    float(c["low"]),
                    "close":  float(c["close"]),
                    "volume": float(c.get("volume", 0)),
                })

            df_chunk = pd.DataFrame(rows)
            df_chunk["ts"] = pd.to_datetime(df_chunk["ts"])
            chunks.append(df_chunk)
            print(f"  chunk {chunk_start.date()} → {chunk_end.date()}: {len(df_chunk)} rows")
            time.sleep(0.35)   # Kite rate limit: ~3 requests/sec

        except Exception as e:
            print(f"  [WARN] Chunk {chunk_start.date()} failed: {e}")
            time.sleep(1.0)

    if not chunks:
        raise RuntimeError(
            "No data from Kite. Make sure access_token is valid and instrument_token is correct.\n"
            f"NIFTY 50 token = {instrument_token}"
        )

    df = (pd.concat(chunks)
            .drop_duplicates(subset="ts")
            .sort_values("ts")
            .reset_index(drop=True))

    # Filter to IST market hours 9:15 – 15:30
    df = df[
        (df["ts"].dt.time >= pd.Timestamp("09:15").time()) &
        (df["ts"].dt.time <= pd.Timestamp("15:30").time())
    ]

    df.to_parquet(cache, index=False)
    print(f"[KiteLoader] Saved {len(df)} candles to {cache}")
    return df


def download_vix_kite(
    kite_client,
    months: int = 12,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Download India VIX daily data via Kite.
    India VIX instrument token: 264969

    Returns DataFrame with columns: date, vix
    """
    INDIA_VIX_TOKEN = 264969
    cache = DATA_DIR / "india_vix_kite.parquet"

    if cache.exists() and not force_refresh:
        df = pd.read_parquet(cache)
        cutoff = (pd.Timestamp.now() - pd.Timedelta(days=months * 31)).date()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df[df["date"] >= cutoff]
        if len(df) > 10:
            print(f"[KiteLoader] Loaded {len(df)} VIX rows from cache.")
            return df

    print("[KiteLoader] Downloading India VIX from Kite...")
    end_dt   = datetime.now()
    start_dt = end_dt - timedelta(days=months * 31)

    try:
        raw = kite_client.kite.historical_data(
            instrument_token=INDIA_VIX_TOKEN,
            from_date=start_dt,
            to_date=end_dt,
            interval="day",
        )
        rows = []
        for c in raw:
            rows.append({
                "date": c["date"].date() if hasattr(c["date"], "date") else c["date"],
                "vix":  float(c["close"]),
            })
        df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
        df.to_parquet(cache, index=False)
        print(f"[KiteLoader] Saved {len(df)} VIX rows.")
        return df
    except Exception as e:
        print(f"[WARN] VIX Kite download failed: {e}. Falling back to yfinance...")
        from backtest.data_downloader import download_india_vix
        return download_india_vix(months=months, force_refresh=force_refresh)


def run_kite_backtest(months: int = 12, verbose: bool = False):
    """
    Entry point: authenticate with saved Kite tokens, fetch data, run backtest.
    Run from project root: python -m backtest.kite_downloader
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from kite_broker.client import KiteClient
    from kite_broker.token_manager import load_cached_token
    from shared.config import settings
    from backtest.backtest_engine import BacktestConfig, run_backtest
    from backtest.run import print_report, save_results

    print("[KiteBacktest] Authenticating with Kite...")
    access_token = load_cached_token()
    if not access_token:
        print("ERROR: No saved access_token. Log in first via https://bot.fynos.in/api/kite/login")
        return

    kite = KiteClient(api_key=settings.kite_api_key, access_token=access_token)

    print(f"[KiteBacktest] Fetching {months} months of NIFTY 5m data...")
    nifty_df = download_nifty_kite(kite, months=months)
    vix_df   = download_vix_kite(kite, months=months)

    print(f"[KiteBacktest] {len(nifty_df)} candles | {len(vix_df)} VIX days")
    print(f"[KiteBacktest] Period: {nifty_df['ts'].min().date()} → {nifty_df['ts'].max().date()}")

    cfg = BacktestConfig(
        capital=100_000.0,
        lots=1,
        vix_max=20.0,                          # skip chaotic/high-volatility days
        max_trades_per_day=1,                  # highest-conviction setup only
        max_consecutive_losses=3,              # halt after 3 losses, not 5
        enable_quality_filter=True,
        min_quality_score=3,
        enable_choppy_filter=True,
        enable_htf_filter=True,
        enable_overextended_filter=True,
        enable_dynamic_blocklist=True,
        enable_daily_bias_filter=True,         # KEY FIX: only trade in daily trend direction
        enable_reentry=False,                  # re-entry had 0% WR
        momentum_breakout_window_start="10:00",   # wait for trend confirmation (post 10:15)
        momentum_breakout_window_end="11:30",     # avoid midday chop
        ema_pullback_window_start="10:00",        # wait for trend confirmation
        ema_pullback_window_end="12:30",
    )

    result = run_backtest(nifty_df, vix_df, cfg, verbose=verbose)
    print_report(result)
    save_results(result, tag=f"kite_{months}m")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    run_kite_backtest(months=args.months, verbose=args.verbose)
