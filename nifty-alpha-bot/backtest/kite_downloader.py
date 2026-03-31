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


def download_nifty_daily_kite(
    kite_client,
    months: int = 24,
    force_refresh: bool = False,
    instrument_token: int = NIFTY_TOKEN,
) -> pd.DataFrame:
    """
    Download NIFTY 50 **daily** OHLCV from Kite (same venue as live bot).

    Returns DataFrame with columns: ts, open, high, low, close, volume
    (matches ``download_nifty_daily`` / ``run_daily_backtest`` input).
    """
    cache = DATA_DIR / "nifty_daily_kite.parquet"

    if cache.exists() and not force_refresh:
        df = pd.read_parquet(cache)
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=months * 31)
        df["ts"] = pd.to_datetime(df["ts"])
        df = df[df["ts"] >= cutoff]
        if len(df) > 60:
            print(f"[KiteLoader] Loaded {len(df)} daily bars from Kite cache.")
            return df.sort_values("ts").reset_index(drop=True)
        print(f"[KiteLoader] Daily cache too small ({len(df)} rows), re-fetching...")

    end_dt = datetime.now().replace(hour=23, minute=59, second=0, microsecond=0)
    start_limit = end_dt - timedelta(days=months * 31 + 5)
    chunk_days = 90
    chunks: list = []
    cursor = end_dt

    print(f"[KiteLoader] Downloading ~{months}m of NIFTY 50 **daily** from Kite...")
    while cursor > start_limit:
        chunk_start = max(start_limit, cursor - timedelta(days=chunk_days))
        try:
            raw = kite_client.kite.historical_data(
                instrument_token=instrument_token,
                from_date=chunk_start,
                to_date=cursor,
                interval="day",
            )
            rows = []
            for c in raw or []:
                ts = c["date"]
                if hasattr(ts, "replace") and hasattr(ts, "tzinfo") and ts.tzinfo is not None:
                    ts = ts.replace(tzinfo=None)
                rows.append({
                    "ts": ts,
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                    "volume": float(c.get("volume", 0)),
                })
            if rows:
                chunks.append(pd.DataFrame(rows))
                print(f"  chunk {chunk_start.date()} → {cursor.date()}: {len(rows)} days")
        except Exception as e:
            print(f"  [WARN] Daily chunk {chunk_start.date()} → {cursor.date()}: {e}")
        cursor = chunk_start
        time.sleep(0.35)

    if not chunks:
        raise RuntimeError(
            "No daily NIFTY data from Kite. Check access_token and NIFTY 50 token "
            f"({instrument_token})."
        )

    df = (
        pd.concat(chunks, ignore_index=True)
        .drop_duplicates(subset="ts")
        .sort_values("ts")
        .reset_index(drop=True)
    )
    df["ts"] = pd.to_datetime(df["ts"])
    df.to_parquet(cache, index=False)
    print(f"[KiteLoader] Saved {len(df)} daily rows to {cache}")
    return df


def _kite_token_for_backtest() -> Optional[str]:
    """Env / .env first, then today's cache, then any cached token (historical API may still work)."""
    import json
    import os

    from kite_broker.token_manager import TOKEN_CACHE, load_cached_token
    from shared.config import settings

    for t in (
        (os.environ.get("KITE_ACCESS_TOKEN") or "").strip(),
        (settings.kite_access_token or "").strip(),
    ):
        if t:
            return t
    t = load_cached_token()
    if t:
        return t
    if TOKEN_CACHE.exists():
        try:
            data = json.loads(TOKEN_CACHE.read_text())
            return (data.get("access_token") or "").strip() or None
        except Exception:
            return None
    return None


def run_adaptive_daily_kite_backtest(
    months: int = 24,
    capital: float = 25_000.0,
    force_refresh: bool = False,
    verbose: bool = False,
    strategy_filter: str = "BOTH",
) -> dict:
    """
    Adaptive Alpha **daily** backtest on Kite-sourced NIFTY daily + India VIX daily.
    """
    import json

    from backtest.daily_backtest_engine import DailyBacktestConfig, run_daily_backtest
    from kite_broker.client import KiteClient
    from shared.config import settings

    access_token = _kite_token_for_backtest()
    if not access_token:
        raise RuntimeError(
            "No Kite access_token. Set KITE_ACCESS_TOKEN in .env, paste token in dashboard, "
            "or save today's token to STATE_DIR/kite_token_cache.json"
        )
    if not settings.kite_api_key:
        raise RuntimeError("KITE_API_KEY missing in .env")

    kite = KiteClient(api_key=settings.kite_api_key, access_token=access_token)
    nifty_df = download_nifty_daily_kite(kite, months=months, force_refresh=force_refresh)
    vix_df = download_vix_kite(kite, months=months, force_refresh=force_refresh)

    cfg = DailyBacktestConfig(capital=capital)
    print(
        f"[AdaptiveKite] {len(nifty_df)} daily bars | {len(vix_df)} VIX days | "
        f"capital=₹{capital:,.0f} | months≈{months}"
    )
    result = run_daily_backtest(
        nifty_df,
        vix_df,
        cfg,
        verbose=verbose,
        strategy_filter=strategy_filter,
    )

    out_path = DATA_DIR.parent / "results" / "adaptive_alpha_kite_25k_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "data_source": "kite",
        "period": (result.get("start_date"), result.get("end_date")),
        "capital_start": capital,
        "metrics": result.get("metrics"),
        "regime_counts": result.get("regime_counts"),
        "strategy_counts": result.get("strategy_counts"),
        "skip_reasons": result.get("skip_reasons"),
    }
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"[AdaptiveKite] Summary written to {out_path}")
    return result


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
        enable_daily_bias_filter=True,         # only trade in daily trend direction
        enable_reentry=False,                  # re-entry had poor WR in tests
        momentum_breakout_window_start="10:00",
        momentum_breakout_window_end="11:30",
        ema_pullback_window_start="10:00",
        ema_pullback_window_end="12:30",
        enable_momentum_breakout=False,
        max_entry_option_price=120.0,
        enable_regime_classifier=True,
        regime_vix_skip_threshold=22.0,
        regime_gap_skip_pct=0.012,
        regime_strong_gap_pct=0.003,
        regime_strong_5d_ret_pct=0.01,
        regime_breakout_prev_range_max=120.0,
        regime_pullback_5d_ret_pct=0.003,
        regime_pullback_flat_open_pct=0.002,
        stop_after_2r_profit=True,
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
    parser.add_argument(
        "--adaptive-daily",
        action="store_true",
        help="Run Adaptive Alpha daily backtest on Kite NIFTY+VIX (real broker history)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=25_000.0,
        help="Starting capital for --adaptive-daily (default ₹25k)",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Re-download Kite caches instead of using parquet",
    )
    args = parser.parse_args()
    if args.adaptive_daily:
        run_adaptive_daily_kite_backtest(
            months=args.months,
            capital=args.capital,
            force_refresh=args.force_refresh,
            verbose=args.verbose,
        )
    else:
        run_kite_backtest(months=args.months, verbose=args.verbose)
