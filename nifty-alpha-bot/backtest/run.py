"""
Main backtest runner.
Usage:
    cd nifty-alpha-bot
    python -m backtest.run --months 6
    python -m backtest.run --months 12 --force-refresh
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from backtest.data_downloader import download_nifty_spot, download_india_vix
from backtest.backtest_engine import BacktestConfig, run_backtest


RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def print_report(result: dict) -> None:
    m = result["metrics"]
    trades = result["trades"]

    print("\n" + "=" * 65)
    print("  NIFTY ALPHA BOT — BACKTEST RESULTS")
    print("=" * 65)
    print(f"  Period      : {result['start_date']}  →  {result['end_date']}")
    print(f"  Trading days: {m['trading_days']}")
    print(f"  Total trades: {m['total_trades']}  (W:{m['win_count']}  L:{m['loss_count']})")
    print("-" * 65)
    print(f"  Win rate    : {m['win_rate_pct']:.1f}%")
    print(f"  Avg win     : ₹{m['avg_win']:>8,.0f}")
    print(f"  Avg loss    : ₹{m['avg_loss']:>8,.0f}")
    print(f"  Profit factor: {m['profit_factor']:.2f}x")
    print("-" * 65)
    print(f"  Gross P&L   : ₹{m['total_gross_pnl']:>10,.0f}")
    print(f"  Charges     : ₹{m['total_charges']:>10,.0f}")
    print(f"  Net P&L     : ₹{m['total_net_pnl']:>10,.0f}  ({m['return_pct']:+.1f}%)")
    print(f"  Final capital: ₹{m['final_capital']:>9,.0f}")
    print("-" * 65)
    print(f"  Max drawdown: ₹{m['max_drawdown_abs']:>8,.0f}  ({m['max_drawdown_pct']:.1f}%)")
    print(f"  Sharpe ratio: {m['sharpe_ratio']:.3f}")
    print(f"  Calmar ratio: {m['calmar_ratio']:.3f}")
    print(f"  Max consec. losses: {m['consecutive_losses_max']}")
    print(f"  Avg duration: {m['avg_trade_duration_min']:.0f} min")
    print("-" * 65)

    # Exit reason breakdown
    print("  Exit reasons:")
    for reason, count in m["exit_reasons"].items():
        pct = count / m["total_trades"] * 100
        print(f"    {reason:<20} {count:3d}  ({pct:.0f}%)")

    print("-" * 65)
    # Monthly breakdown
    print("  Monthly P&L:")
    print(f"  {'Month':<10} {'Trades':>7} {'Win%':>6} {'Net P&L':>12}")
    print(f"  {'-'*10} {'-'*7} {'-'*6} {'-'*12}")
    for mo in m["monthly_breakdown"]:
        sign = "+" if mo["net_pnl"] >= 0 else ""
        print(f"  {mo['month']:<10} {mo['trades']:>7} {mo['win_rate']:>5.0f}% {sign}₹{mo['net_pnl']:>9,.0f}")

    print("=" * 65)

    # Strategy breakdown
    strategies = ["ORB", "RELAXED_ORB", "MOMENTUM_BREAKOUT", "EMA_PULLBACK", "VWAP_RECLAIM"]
    labels = {
        "ORB": "ORB           ",
        "RELAXED_ORB": "Relaxed ORB   ",
        "MOMENTUM_BREAKOUT": "Momentum Brkout",
        "EMA_PULLBACK": "EMA Pullback  ",
        "VWAP_RECLAIM": "VWAP Reclaim  ",
    }
    print("  Strategy breakdown:")
    for strat in strategies:
        st = [t for t in trades if t.get("strategy") == strat]
        if st:
            pnl = sum(t["net_pnl"] for t in st)
            wins = sum(1 for t in st if t["net_pnl"] > 0)
            sign = "+" if pnl >= 0 else ""
            print(f"    {labels[strat]}: {len(st):3d} trades | WR: {wins/len(st)*100:.0f}% | P&L: {sign}₹{pnl:,.0f}")

    print("=" * 65)

    # Verdict
    verdict_ok = (
        m["sharpe_ratio"] >= 1.0
        and m["max_drawdown_pct"] <= 15.0
        and m["win_rate_pct"] >= 45.0
        and m["total_net_pnl"] > 0
    )
    print(f"\n  VERDICT: {'✓ STRATEGY PASSES CRITERIA' if verdict_ok else '✗ NEEDS IMPROVEMENT'}")
    print(f"  Criteria: Sharpe≥1.0 ({m['sharpe_ratio']:.2f}), DD≤15% ({m['max_drawdown_pct']:.1f}%), WR≥45% ({m['win_rate_pct']:.1f}%), Profitable")
    print()


def save_results(result: dict, tag: str = "") -> None:
    ts = date.today().isoformat()
    name = f"backtest_{ts}{'_' + tag if tag else ''}"

    # Save full JSON
    json_path = RESULTS_DIR / f"{name}.json"
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"  Results saved: {json_path}")

    # Save trade log CSV
    import csv
    if result["trades"]:
        csv_path = RESULTS_DIR / f"{name}_trades.csv"
        fieldnames = list(result["trades"][0].keys())
        fieldnames = [f for f in fieldnames if f not in ("filter_log",)]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(result["trades"])
        print(f"  Trade log CSV: {csv_path}")


def main():
    parser = argparse.ArgumentParser(description="NIFTY Alpha Bot Backtest")
    parser.add_argument("--months", type=int, default=6, help="Months of history to backtest (default: 6)")
    parser.add_argument("--force-refresh", action="store_true", help="Force re-download data")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Starting capital")
    parser.add_argument("--lots", type=int, default=1, help="Number of lots per trade")
    parser.add_argument("--no-reclaim", action="store_true", help="Disable VWAP reclaim strategy")
    parser.add_argument("--vix-max", type=float, default=18.0, help="Max VIX threshold")
    parser.add_argument("--sl-max-pct", type=float, default=0.12, help="Max SL % (e.g. 0.12 = 12%%)")
    parser.add_argument("--rr", type=float, default=2.5, help="Risk-reward ratio")
    parser.add_argument("--quiet", action="store_true", help="Suppress trade-by-trade output")
    args = parser.parse_args()

    print(f"\n[Backtest] Starting NIFTY Alpha Bot backtest ({args.months} months)")

    # Download data
    nifty_df = download_nifty_spot(months=args.months, force_refresh=args.force_refresh)
    vix_df = download_india_vix(months=args.months, force_refresh=args.force_refresh)

    print(f"[Backtest] Data ready: {len(nifty_df)} candles, {len(vix_df)} VIX days\n")

    # Configure backtest
    cfg = BacktestConfig(
        capital=args.capital,
        lots=args.lots,
        enable_vwap_reclaim=not args.no_reclaim,
        vix_max=args.vix_max,
        atr_sl_max_pct=args.sl_max_pct,
        rr_min=args.rr,
    )

    # Run
    result = run_backtest(
        nifty_df, vix_df, cfg,
        verbose=not args.quiet,
    )

    # Report
    print_report(result)
    save_results(result)


if __name__ == "__main__":
    main()
