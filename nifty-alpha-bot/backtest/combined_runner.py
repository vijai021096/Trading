"""
Combined Bear + Bull backtest runner.

Strategy:
  - Bear engine (PUT strategies) handles: STRONG_TREND_DOWN, MILD_TREND,
    MEAN_REVERT, BREAKOUT, VOLATILE days
  - Bull engine (CALL pullback strategies) handles: STRONG_BULL (and
    MILD_BULL when only_mild_bull=True) days

This gives us coverage of ALL good trading days in both directions,
maximising P&L across complete market cycles (bull + bear).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.data_downloader import download_nifty_daily, download_india_vix
from backtest.daily_backtest_engine import DailyBacktestConfig, run_daily_backtest
from backtest.bull_backtest_engine import BullBacktestConfig, run_bull_backtest
from backtest.metrics import compute_metrics


@dataclass
class CombinedBacktestConfig:
    bear_cfg: DailyBacktestConfig = None   # type: ignore
    bull_cfg: BullBacktestConfig  = None   # type: ignore
    only_strong_bull_days: bool = False    # True = bull engine skips MILD_BULL


def run_combined_backtest(
    nifty_daily: pd.DataFrame,
    vix_df: pd.DataFrame,
    cfg: Optional[CombinedBacktestConfig] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Run bear engine (skip STRONG_TREND_UP) + bull engine (STRONG_BULL/MILD_BULL),
    merge trades chronologically and compute combined metrics.
    """
    if cfg is None:
        cfg = CombinedBacktestConfig()
    if cfg.bear_cfg is None:
        cfg.bear_cfg = DailyBacktestConfig()
    if cfg.bull_cfg is None:
        cfg.bull_cfg = BullBacktestConfig()

    # Sync starting capital between engines
    cfg.bull_cfg.capital = cfg.bear_cfg.capital

    # Tell bear engine to skip STRONG_TREND_UP days (handed to bull engine)
    cfg.bear_cfg.skip_strong_trend_up = True

    if verbose:
        print(f"\n{'='*72}")
        print(f" COMBINED BEAR + BULL BACKTEST")
        print(f" Capital: ₹{cfg.bear_cfg.capital:,.0f}")
        print(f" Bear engine: PUT strategies on STRONG_TREND_DOWN / MILD_TREND / MEAN_REVERT / BREAKOUT / VOLATILE")
        print(f" Bull engine: CALL pullback strategies on STRONG_BULL / MILD_BULL days")
        print(f"{'='*72}\n")

    # ── Bear engine run ────────────────────────────────────────────────────
    if verbose:
        print("── BEAR ENGINE ──")
    bear_result = run_daily_backtest(
        nifty_daily, vix_df,
        cfg=cfg.bear_cfg,
        start_date=start_date,
        end_date=end_date,
        verbose=verbose,
    )

    # ── Bull engine run ────────────────────────────────────────────────────
    if verbose:
        print("\n── BULL ENGINE ──")
    bull_result = run_bull_backtest(
        nifty_daily, vix_df,
        cfg=cfg.bull_cfg,
        start_date=start_date,
        end_date=end_date,
        verbose=verbose,
        only_strong_bull_days=cfg.only_strong_bull_days,
    )

    # ── Merge trades by date ───────────────────────────────────────────────
    bear_trades = bear_result["trades"]
    bull_trades  = bull_result["trades"]

    # Tag each trade with its engine
    for t in bear_trades:
        t["engine"] = "BEAR"
    for t in bull_trades:
        t["engine"] = "BULL"

    combined = sorted(
        bear_trades + bull_trades,
        key=lambda t: t.get("trade_date", ""),
    )

    # Recompute combined metrics from scratch on the merged trade list
    combined_metrics = compute_metrics(combined, cfg.bear_cfg.capital)

    if verbose:
        _print_combined_summary(combined, combined_metrics, bear_result, bull_result, cfg)

    return {
        "trades":         combined,
        "metrics":        combined_metrics,
        "bear_result":    bear_result,
        "bull_result":    bull_result,
        "bear_trades":    bear_trades,
        "bull_trades":    bull_trades,
        "start_date":     bear_result.get("start_date") or bull_result.get("start_date"),
        "end_date":       bear_result.get("end_date")   or bull_result.get("end_date"),
        "timeframe":      "combined_daily",
    }


def _print_combined_summary(
    combined: list,
    m: dict,
    bear_result: dict,
    bull_result: dict,
    cfg: CombinedBacktestConfig,
) -> None:
    bm = bear_result["metrics"]
    um = bull_result["metrics"]

    b_trades = bear_result["trades"]
    u_trades = bull_result["trades"]
    b_wins = sum(1 for t in b_trades if t["net_pnl"] > 0)
    u_wins = sum(1 for t in u_trades if t["net_pnl"] > 0)

    print(f"\n{'='*72}")
    print(f" COMBINED RESULT SUMMARY")
    print(f"{'='*72}")
    print(f" {'Engine':<14} {'Trades':>7} {'Win%':>6} {'Net P&L':>11} {'PF':>6} {'DD%':>7}")
    print(f" {'-'*14} {'-'*7} {'-'*6} {'-'*11} {'-'*6} {'-'*7}")

    def _wr(wins, total): return f"{wins/total*100:.1f}%" if total > 0 else "  N/A"

    b_pnl = bm.get("total_net_pnl", 0)
    u_pnl = um.get("total_net_pnl", 0)
    c_pnl = m.get("total_net_pnl", 0)
    print(f" {'Bear (PUT)':<14} {len(b_trades):>7} {_wr(b_wins, len(b_trades)):>6}"
          f"  {'+'if b_pnl>=0 else ''}₹{b_pnl:>9,.0f} {bm.get('profit_factor',0):>6.2f} {bm.get('max_drawdown_pct',0):>6.1f}%")
    print(f" {'Bull (CALL)':<14} {len(u_trades):>7} {_wr(u_wins, len(u_trades)):>6}"
          f"  {'+'if u_pnl>=0 else ''}₹{u_pnl:>9,.0f} {um.get('profit_factor',0):>6.2f} {um.get('max_drawdown_pct',0):>6.1f}%")
    print(f" {'-'*14} {'-'*7} {'-'*6} {'-'*11} {'-'*6} {'-'*7}")
    total_wins = sum(1 for t in combined if t["net_pnl"] > 0)
    print(f" {'COMBINED':<14} {len(combined):>7} {_wr(total_wins, len(combined)):>6}"
          f"  {'+'if c_pnl>=0 else ''}₹{c_pnl:>9,.0f} {m.get('profit_factor',0):>6.2f} {m.get('max_drawdown_pct',0):>6.1f}%")
    print(f"\n Capital: ₹{cfg.bear_cfg.capital:,.0f} → ₹{m.get('final_capital', cfg.bear_cfg.capital):,.0f}"
          f"  ({m.get('return_pct', 0):+.1f}%)")
    print(f" Sharpe: {m.get('sharpe_ratio', 0):.3f}  |  Calmar: {m.get('calmar_ratio', 0):.3f}")
    print(f"{'='*72}\n")


# ═══════════════════════════════════════════════════════════════════
# COMPARISON RUNNER  (bear-only vs combined)
# ═══════════════════════════════════════════════════════════════════

def run_comparison(
    months: int = 24,
    verbose_trades: bool = False,
    force_refresh: bool = False,
) -> None:
    """
    Download data and compare:
      1. Old: Bear engine alone (no skipping of bull days)
      2. New: Combined bear + bull engine
    """
    print(f"\n[CombinedRunner] Downloading {months} months of daily data...")
    nifty_df = download_nifty_daily(months=months, force_refresh=force_refresh)
    vix_df   = download_india_vix(months=months, force_refresh=force_refresh)
    print(f"[CombinedRunner] Data: {len(nifty_df)} daily bars, {len(vix_df)} VIX rows\n")

    # ── 1. Bear-only baseline ───────────────────────────────────────────────
    print("=" * 72)
    print(f" BEAR-ONLY BASELINE  ({months}m)")
    print("=" * 72)
    bear_only_cfg = DailyBacktestConfig(skip_strong_trend_up=False)
    bear_only = run_daily_backtest(
        nifty_df, vix_df,
        cfg=bear_only_cfg,
        verbose=verbose_trades,
    )

    # ── 2. Combined (bear + bull) ──────────────────────────────────────────
    print("\n" + "=" * 72)
    print(f" COMBINED (BEAR + BULL)  ({months}m)")
    print("=" * 72)
    combined_cfg = CombinedBacktestConfig(
        bear_cfg=DailyBacktestConfig(),
        bull_cfg=BullBacktestConfig(),
        only_strong_bull_days=False,
    )
    combined = run_combined_backtest(
        nifty_df, vix_df,
        cfg=combined_cfg,
        verbose=verbose_trades,
    )

    # ── Side-by-side comparison ────────────────────────────────────────────
    _print_comparison(bear_only, combined, months)


def _print_comparison(bear_only: dict, combined: dict, months: int) -> None:
    bm = bear_only["metrics"]
    cm = combined["metrics"]

    b_trades = bear_only["trades"]
    c_trades = combined["trades"]
    b_wins   = sum(1 for t in b_trades if t["net_pnl"] > 0)
    c_wins   = sum(1 for t in c_trades if t["net_pnl"] > 0)

    bull_trades = combined.get("bull_trades", [])
    bull_wins   = sum(1 for t in bull_trades if t["net_pnl"] > 0)

    print(f"\n{'='*80}")
    print(f"  COMPARISON: Bear-Only  vs  Combined (Bear + Bull)  |  {months}m backtest")
    print(f"{'='*80}")
    print(f"  {'Metric':<28} {'Bear Only':>14} {'Combined':>14} {'Δ':>10}")
    print(f"  {'-'*28} {'-'*14} {'-'*14} {'-'*10}")

    def _row(label, bval, cval, fmt="{:.0f}", prefix=""):
        delta = cval - bval
        sign = "+" if delta >= 0 else ""
        bstr = prefix + fmt.format(bval)
        cstr = prefix + fmt.format(cval)
        dstr = f"{sign}" + fmt.format(delta)
        print(f"  {label:<28} {bstr:>14} {cstr:>14} {dstr:>10}")

    n_cap = DailyBacktestConfig().capital
    _row("Total trades",   len(b_trades),                len(c_trades))
    _row("  Bear trades",  len(b_trades),                len(b_trades))
    _row("  Bull trades",  0,                            len(bull_trades))
    _row("Win rate %",     b_wins/len(b_trades)*100 if b_trades else 0,
                           c_wins/len(c_trades)*100 if c_trades else 0,  fmt="{:.1f}")
    _row("Net P&L",        bm.get("total_net_pnl", 0),  cm.get("total_net_pnl", 0),  prefix="₹")
    _row("Return %",       bm.get("return_pct", 0),     cm.get("return_pct", 0),      fmt="{:+.2f}")
    _row("Final capital",  bm.get("final_capital", n_cap), cm.get("final_capital", n_cap), prefix="₹")
    _row("Profit factor",  bm.get("profit_factor", 0),  cm.get("profit_factor", 0),  fmt="{:.2f}")
    _row("Max DD %",       bm.get("max_drawdown_pct", 0), cm.get("max_drawdown_pct", 0), fmt="{:.1f}")
    _row("Sharpe ratio",   bm.get("sharpe_ratio", 0),   cm.get("sharpe_ratio", 0),   fmt="{:.3f}")
    _row("Calmar ratio",   bm.get("calmar_ratio", 0),   cm.get("calmar_ratio", 0),   fmt="{:.3f}")

    print(f"{'='*80}")
    c_pnl  = cm.get("total_net_pnl", 0)
    b_pnl  = bm.get("total_net_pnl", 0)
    uplift = c_pnl - b_pnl
    sign   = "+" if uplift >= 0 else ""
    print(f"\n  Combined P&L uplift from bull engine: {sign}₹{uplift:,.0f}")
    if bull_trades:
        bull_pnl = sum(t["net_pnl"] for t in bull_trades)
        print(f"  Bull engine alone: {len(bull_trades)} trades | "
              f"WR: {bull_wins/len(bull_trades)*100:.1f}% | P&L: ₹{bull_pnl:+,.0f}")
    print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Combined Bear+Bull Backtest Comparison")
    parser.add_argument("--months", type=int, default=24, help="Months of history (default: 24)")
    parser.add_argument("--verbose", action="store_true", help="Show per-trade output")
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    run_comparison(
        months=args.months,
        verbose_trades=args.verbose,
        force_refresh=args.force_refresh,
    )
