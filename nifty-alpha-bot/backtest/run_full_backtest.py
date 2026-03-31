"""
Full multi-period backtest runner.
Runs Bear + Bull combined engine across 3 windows:
  - 60 trading days  (~3 months, high-fidelity Kite 5m data aggregated to daily)
  - 1 Year           (Kite 5m data aggregated to daily)
  - 2 Years          (nifty_daily.parquet + india_vix_daily.parquet)

Outputs a flat HTML report.

Usage:
    cd nifty-alpha-bot
    python -m backtest.run_full_backtest
"""
from __future__ import annotations

import json
import warnings
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

warnings.filterwarnings("ignore")

DATA_DIR  = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# DATA HELPERS
# ═══════════════════════════════════════════════════════════════════

def _agg_5m_to_daily(df_5m: pd.DataFrame) -> pd.DataFrame:
    """Collapse 5-minute OHLCV candles into daily OHLCV bars."""
    df = df_5m.copy()
    df["ts"] = pd.to_datetime(df["ts"])
    df["date"] = df["ts"].dt.date
    daily = df.groupby("date").agg(
        open  = ("open", "first"),
        high  = ("high", "max"),
        low   = ("low", "min"),
        close = ("close", "last"),
        volume= ("volume", "sum"),
    ).reset_index()
    daily = daily.rename(columns={"date": "ts"})
    daily["ts"] = pd.to_datetime(daily["ts"])
    return daily.sort_values("ts").reset_index(drop=True)


def _load_vix(vix_path: str) -> pd.DataFrame:
    vix = pd.read_parquet(vix_path)
    vix["date"] = pd.to_datetime(vix["date"]).dt.date
    return vix[["date", "vix"]].dropna().sort_values("date").reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════
# RUN ONE PERIOD
# ═══════════════════════════════════════════════════════════════════

def _run_period(
    label: str,
    nifty_daily: pd.DataFrame,
    vix_df: pd.DataFrame,
    start_date: Optional[date],
    end_date: Optional[date],
    capital: float = 100_000.0,
) -> Dict[str, Any]:
    from backtest.combined_runner import CombinedBacktestConfig, run_combined_backtest
    from backtest.daily_backtest_engine import DailyBacktestConfig
    from backtest.bull_backtest_engine import BullBacktestConfig

    print(f"\n{'─'*70}")
    print(f"  {label}  ({start_date} → {end_date})")
    print(f"{'─'*70}")

    bear_cfg = DailyBacktestConfig(
        capital=capital,
        skip_strong_trend_up=True,
    )
    bull_cfg = BullBacktestConfig(capital=capital)
    cfg = CombinedBacktestConfig(
        bear_cfg=bear_cfg,
        bull_cfg=bull_cfg,
        only_strong_bull_days=False,
    )

    result = run_combined_backtest(
        nifty_daily, vix_df,
        cfg=cfg,
        start_date=start_date,
        end_date=end_date,
        verbose=True,
    )
    result["label"] = label
    result["start_date"] = str(start_date) if start_date else ""
    result["end_date"] = str(end_date) if end_date else ""
    return result


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main() -> None:
    today = date.today()

    # ── Load data ──────────────────────────────────────────────────
    print("\n[BacktestRunner] Loading data...")

    # 5m data → aggregate to daily (used for 60d and 1y runs)
    # Try kite-specific file first, fall back to combined
    _5m_candidates = ["nifty_5m_kite.parquet", "nifty_5m_combined.parquet", "nifty_5m.parquet"]
    df_5m = None
    for _fn in _5m_candidates:
        try:
            df_5m = pd.read_parquet(DATA_DIR / _fn)
            print(f"  5m data: {_fn}")
            break
        except Exception:
            continue
    if df_5m is None:
        raise RuntimeError("No readable 5m parquet file found in backtest/data/")
    df_5m["ts"] = pd.to_datetime(df_5m["ts"])
    kite_daily = _agg_5m_to_daily(df_5m)

    # VIX — try kite-specific then fallback to 2yr file
    _vix_candidates = ["india_vix_kite.parquet", "india_vix_daily.parquet", "india_vix_2yr.parquet"]
    vix_parts = []
    for _fn in _vix_candidates:
        try:
            vix_parts.append(_load_vix(str(DATA_DIR / _fn)))
        except Exception:
            pass
    if not vix_parts:
        raise RuntimeError("No readable VIX parquet file found in backtest/data/")
    vix_merged = pd.concat(vix_parts).drop_duplicates("date", keep="last") \
                    .sort_values("date").reset_index(drop=True)

    # Daily data for 2-year run (goes further back than kite 5m)
    _daily_candidates = ["nifty_daily.parquet", "nifty_daily_2yr.parquet"]
    nifty_daily_full = None
    for _fn in _daily_candidates:
        try:
            nifty_daily_full = pd.read_parquet(DATA_DIR / _fn)
            print(f"  Daily data: {_fn}")
            break
        except Exception:
            continue
    if nifty_daily_full is None:
        raise RuntimeError("No readable daily parquet file found in backtest/data/")
    nifty_daily_full["ts"] = pd.to_datetime(nifty_daily_full["ts"])

    kite_start = df_5m["ts"].dt.date.min()
    kite_end   = df_5m["ts"].dt.date.max()
    print(f"  Kite 5m:    {kite_start} → {kite_end}  ({len(kite_daily)} daily bars)")
    print(f"  Daily full: {nifty_daily_full['ts'].dt.date.min()} → {nifty_daily_full['ts'].dt.date.max()}")
    print(f"  VIX:        {vix_merged['date'].min()} → {vix_merged['date'].max()}  ({len(vix_merged)} rows)")

    # ── Define periods ─────────────────────────────────────────────
    # 60 trading days ≈ 90 calendar days
    d60_start  = today - timedelta(days=90)
    d1y_start  = today - timedelta(days=370)
    d2y_start  = today - timedelta(days=740)

    # Clamp to available data
    d60_start  = max(d60_start,  kite_start)
    d1y_start  = max(d1y_start,  kite_start)
    d2y_start  = max(d2y_start,  nifty_daily_full["ts"].dt.date.min())

    capital = 100_000.0  # ₹1 lakh starting capital

    # ── Run backtests ──────────────────────────────────────────────
    results: Dict[str, Dict[str, Any]] = {}

    results["60d"] = _run_period(
        "60 TRADING DAYS", kite_daily, vix_merged, d60_start, today, capital
    )
    results["1y"] = _run_period(
        "1 YEAR", kite_daily, vix_merged, d1y_start, today, capital
    )
    results["2y"] = _run_period(
        "2 YEARS", nifty_daily_full, vix_merged, d2y_start, today, capital
    )

    # ── Save JSON ──────────────────────────────────────────────────
    out_path = RESULTS_DIR / f"full_backtest_{today}.json"
    summary = {}
    for key, r in results.items():
        summary[key] = {
            "label": r["label"],
            "start_date": r["start_date"],
            "end_date": r["end_date"],
            "metrics": r["metrics"],
            "bear_metrics": r["bear_result"]["metrics"],
            "bull_metrics": r["bull_result"]["metrics"],
            "trades": r.get("trades", []),
        }
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n[BacktestRunner] Saved → {out_path}")

    # ── Generate HTML report ───────────────────────────────────────
    html_path = RESULTS_DIR / f"backtest_report_{today}.html"
    _generate_html_report(summary, html_path, today)
    print(f"[BacktestRunner] Report → {html_path}")

    return html_path


# ═══════════════════════════════════════════════════════════════════
# HTML REPORT GENERATOR
# ═══════════════════════════════════════════════════════════════════

def _generate_html_report(
    summary: Dict[str, Any],
    html_path: Path,
    today: date,
) -> None:
    """
    Flat HTML + Chart.js + Tailwind CDN report.
    Single file, no server needed.
    """
    # Build equity curves and monthly series per period
    def _monthly(trades: list) -> tuple[list, list]:
        if not trades:
            return [], []
        by_month: Dict[str, list] = {}
        for t in trades:
            td = str(t.get("trade_date", ""))[:7]  # "YYYY-MM"
            if not td:
                continue
            by_month.setdefault(td, []).append(t.get("net_pnl", 0))
        months = sorted(by_month.keys())
        pnls   = [round(sum(by_month[m]), 0) for m in months]
        return months, pnls

    def _equity(trades: list, capital: float) -> list:
        equity = [capital]
        for t in trades:
            equity.append(equity[-1] + t.get("net_pnl", 0))
        return [round(v, 0) for v in equity]

    def _exit_breakdown(trades: list) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for t in trades:
            r = t.get("exit_reason", "UNKNOWN")
            out[r] = out.get(r, 0) + 1
        return out

    def _strategy_breakdown(trades: list) -> list:
        by_strat: Dict[str, dict] = {}
        for t in trades:
            s = t.get("strategy", "UNKNOWN")
            if s not in by_strat:
                by_strat[s] = {"wins": 0, "losses": 0, "pnl": 0.0}
            pnl = t.get("net_pnl", 0)
            if pnl > 0:
                by_strat[s]["wins"] += 1
            else:
                by_strat[s]["losses"] += 1
            by_strat[s]["pnl"] += pnl
        rows = []
        for s, v in sorted(by_strat.items(), key=lambda x: -abs(x[1]["pnl"])):
            total = v["wins"] + v["losses"]
            wr = v["wins"] / total * 100 if total > 0 else 0
            rows.append({"strategy": s, "total": total, "wins": v["wins"],
                         "losses": v["losses"], "win_rate": round(wr, 1),
                         "net_pnl": round(v["pnl"], 0)})
        return rows

    def _regime_breakdown(trades: list) -> list:
        by_regime: Dict[str, dict] = {}
        for t in trades:
            r = t.get("regime", t.get("engine", "UNKNOWN"))
            if r not in by_regime:
                by_regime[r] = {"wins": 0, "losses": 0, "pnl": 0.0}
            pnl = t.get("net_pnl", 0)
            if pnl > 0:
                by_regime[r]["wins"] += 1
            else:
                by_regime[r]["losses"] += 1
            by_regime[r]["pnl"] += pnl
        rows = []
        for r, v in sorted(by_regime.items(), key=lambda x: -abs(x[1]["pnl"])):
            total = v["wins"] + v["losses"]
            wr = v["wins"] / total * 100 if total > 0 else 0
            rows.append({"regime": r, "total": total, "wins": v["wins"],
                         "losses": v["losses"], "win_rate": round(wr, 1),
                         "net_pnl": round(v["pnl"], 0)})
        return rows

    capital = 100_000.0
    period_data = {}
    for key, r in summary.items():
        trades = r.get("trades", [])
        months, mpnl = _monthly(trades)
        eq = _equity(trades, capital)
        exits = _exit_breakdown(trades)
        strats = _strategy_breakdown(trades)
        regimes = _regime_breakdown(trades)
        period_data[key] = {
            "months": months,
            "monthly_pnl": mpnl,
            "equity": eq,
            "exits": exits,
            "strategies": strats,
            "regimes": regimes,
            "trades": trades,
        }

    # Inline all data as JS
    data_js = f"const BACKTEST_DATA = {json.dumps(period_data, default=str)};"
    # Pre-compute summary without trades (to keep it lean)
    summary_no_trades = {
        k: {kk: vv for kk, vv in v.items() if kk != "trades"}
        for k, v in summary.items()
    }
    data_js += f"\nconst SUMMARY = {json.dumps(summary_no_trades, default=str)};"

    # ── Insights text ───────────────────────────────────────────────
    def _insights(key: str) -> str:
        r = summary.get(key, {})
        m = r.get("metrics", {})
        bm = r.get("bear_metrics", {})
        um = r.get("bull_metrics", {})
        if not m:
            return "No data for this period."
        pnl = m.get("total_net_pnl", 0)
        wr  = m.get("win_rate_pct", 0)
        pf  = m.get("profit_factor", 0)
        dd  = m.get("max_drawdown_pct", 0)
        sh  = m.get("sharpe_ratio", 0)
        ret = m.get("return_pct", 0)
        trades_n = m.get("total_trades", 0)
        sign = "+" if pnl >= 0 else ""
        observations = []
        if wr >= 60:
            observations.append(f"<b>Win rate of {wr:.1f}% is excellent</b> — strategy is firing on the right setups.")
        elif wr >= 50:
            observations.append(f"<b>Win rate {wr:.1f}%</b> with profit factor {pf:.2f}x — winners are meaningfully larger than losers.")
        else:
            observations.append(f"Win rate is {wr:.1f}% — below 50%. Edge comes from outsized winners vs small losers (PF={pf:.2f}x).")
        if dd < 10:
            observations.append(f"Max drawdown of <b>{dd:.1f}%</b> is very controlled for an options strategy.")
        elif dd < 20:
            observations.append(f"Max drawdown of {dd:.1f}% is moderate — acceptable for intraday options.")
        else:
            observations.append(f"Max drawdown of {dd:.1f}% is elevated — consider tightening position sizing on choppy days.")
        if sh > 2.0:
            observations.append(f"<b>Sharpe {sh:.2f}</b> — exceptional risk-adjusted returns. Hedge funds aim for 1.5+.")
        elif sh > 1.0:
            observations.append(f"Sharpe {sh:.2f} — solid risk-adjusted performance above most benchmarks.")
        if pf > 2.0:
            observations.append(f"<b>Profit factor {pf:.2f}x</b> — every ₹1 risked returned ₹{pf:.2f}. Strategy has clear edge.")
        b_pnl = bm.get("total_net_pnl", 0)
        u_pnl = um.get("total_net_pnl", 0)
        if b_pnl > 0 and u_pnl > 0:
            observations.append(f"Both engines profitable: Bear (PUT) <b>+₹{b_pnl:,.0f}</b> + Bull (CALL) <b>+₹{u_pnl:,.0f}</b>.")
        elif b_pnl > 0:
            observations.append(f"Bear (PUT) engine carried performance (+₹{b_pnl:,.0f}). Bull engine had mixed results (+₹{u_pnl:,.0f}).")
        observations.append(f"Over {trades_n} trades, net P&L is <b>{sign}₹{abs(pnl):,.0f}</b> ({ret:+.1f}% return on ₹1L capital).")
        return " ".join(f"<li>{o}</li>" for o in observations)

    insights = {k: _insights(k) for k in ["60d", "1y", "2y"]}

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nifty Alpha Bot — Backtest Report {today}</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
<style>
  body {{ background:#0f172a; color:#e2e8f0; font-family:'Inter',system-ui,sans-serif; }}
  .card {{ background:#1e293b; border:1px solid #334155; border-radius:1rem; padding:1.5rem; }}
  .badge-green {{ background:rgba(34,197,94,0.1); color:#4ade80; border:1px solid rgba(34,197,94,0.25); border-radius:0.5rem; padding:0.15rem 0.6rem; font-size:0.75rem; font-weight:700; }}
  .badge-red   {{ background:rgba(239,68,68,0.1);  color:#f87171; border:1px solid rgba(239,68,68,0.25);  border-radius:0.5rem; padding:0.15rem 0.6rem; font-size:0.75rem; font-weight:700; }}
  .badge-blue  {{ background:rgba(59,130,246,0.1); color:#60a5fa; border:1px solid rgba(59,130,246,0.25); border-radius:0.5rem; padding:0.15rem 0.6rem; font-size:0.75rem; font-weight:700; }}
  .stat-val    {{ font-size:1.75rem; font-weight:900; letter-spacing:-0.04em; }}
  .tab {{ cursor:pointer; padding:0.5rem 1.25rem; border-radius:0.75rem; font-size:0.8rem; font-weight:700; letter-spacing:0.05em; text-transform:uppercase; transition:all 0.15s; }}
  .tab.active  {{ background:#0053e2; color:#fff; }}
  .tab.inactive{{ background:#1e293b; color:#94a3b8; }}
  .tab.inactive:hover{{ background:#334155; color:#e2e8f0; }}
  tr:nth-child(even) {{ background:rgba(51,65,85,0.4); }}
  th {{ color:#94a3b8; font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; }}
  .chart-wrap {{ position:relative; height:240px; }}
  .chart-wrap-lg {{ position:relative; height:320px; }}
</style>
</head>
<body class="min-h-screen">

<!-- HEADER -->
<div class="bg-[#0053e2] px-8 py-5">
  <div class="max-w-7xl mx-auto flex items-center justify-between">
    <div>
      <div class="text-white font-black text-2xl tracking-tight">🐾 Nifty Alpha Bot</div>
      <div class="text-blue-200 text-sm mt-0.5">Strategy Backtest Report &middot; Generated {today}</div>
    </div>
    <div class="text-right">
      <div class="text-blue-200 text-xs">Capital: ₹1,00,000 &nbsp;|&nbsp; Bear (PUT) + Bull (CALL) engines</div>
      <div class="text-blue-100 text-xs mt-0.5">Combined daily-adaptive strategy with ATR-based SL</div>
    </div>
  </div>
</div>

<div class="max-w-7xl mx-auto px-6 py-8 space-y-8">

  <!-- PERIOD TABS -->
  <div class="flex gap-3 flex-wrap">
    <button class="tab active" onclick="switchPeriod('60d',this)">⏱ 60 Trading Days</button>
    <button class="tab inactive" onclick="switchPeriod('1y',this)">📅 1 Year</button>
    <button class="tab inactive" onclick="switchPeriod('2y',this)">🗓 2 Years</button>
  </div>

  <!-- INSIGHTS -->
  <div id="insights-panel" class="card border-l-4 border-l-[#ffc220]">
    <div class="text-xs font-bold text-[#ffc220] uppercase tracking-widest mb-3">📊 Executive Insights</div>
    <ul id="insights-text" class="space-y-1 text-sm text-slate-300 list-disc list-inside"></ul>
  </div>

  <!-- METRIC CARDS -->
  <div id="metric-cards" class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4"></div>

  <!-- CHARTS ROW 1 -->
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <div class="card">
      <div class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Equity Curve</div>
      <div class="chart-wrap-lg"><canvas id="equityChart"></canvas></div>
    </div>
    <div class="card">
      <div class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Monthly P&amp;L</div>
      <div class="chart-wrap-lg"><canvas id="monthlyChart"></canvas></div>
    </div>
  </div>

  <!-- CHARTS ROW 2 -->
  <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
    <div class="card">
      <div class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Exit Reasons</div>
      <div class="chart-wrap"><canvas id="exitChart"></canvas></div>
    </div>
    <div class="card md:col-span-2">
      <div class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">P&amp;L Distribution (₹ per trade)</div>
      <div class="chart-wrap"><canvas id="distChart"></canvas></div>
    </div>
  </div>

  <!-- STRATEGY TABLE -->
  <div class="card">
    <div class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Strategy Breakdown</div>
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead><tr class="text-left">
          <th class="py-2 pr-4">Strategy</th>
          <th class="py-2 pr-4 text-right">Trades</th>
          <th class="py-2 pr-4 text-right">Win%</th>
          <th class="py-2 pr-4 text-right">Wins</th>
          <th class="py-2 pr-4 text-right">Losses</th>
          <th class="py-2 text-right">Net P&amp;L</th>
        </tr></thead>
        <tbody id="strat-table"></tbody>
      </table>
    </div>
  </div>

  <!-- REGIME TABLE -->
  <div class="card">
    <div class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Engine / Regime Breakdown</div>
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead><tr class="text-left">
          <th class="py-2 pr-4">Engine/Regime</th>
          <th class="py-2 pr-4 text-right">Trades</th>
          <th class="py-2 pr-4 text-right">Win%</th>
          <th class="py-2 pr-4 text-right">Wins</th>
          <th class="py-2 pr-4 text-right">Losses</th>
          <th class="py-2 text-right">Net P&amp;L</th>
        </tr></thead>
        <tbody id="regime-table"></tbody>
      </table>
    </div>
  </div>

  <!-- TRADE LOG -->
  <div class="card">
    <div class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Trade Log (last 30)</div>
    <div class="overflow-x-auto">
      <table class="w-full text-xs font-mono">
        <thead><tr class="text-left">
          <th class="py-2 pr-3">Date</th>
          <th class="py-2 pr-3">Strategy</th>
          <th class="py-2 pr-3">Dir</th>
          <th class="py-2 pr-3">Engine</th>
          <th class="py-2 pr-3 text-right">Entry</th>
          <th class="py-2 pr-3 text-right">Exit</th>
          <th class="py-2 pr-3">Exit Reason</th>
          <th class="py-2 text-right">Net P&amp;L</th>
        </tr></thead>
        <tbody id="trade-table"></tbody>
      </table>
    </div>
  </div>

  <!-- FOOTER -->
  <div class="text-center text-xs text-slate-500 pb-6">
    Nifty Alpha Bot &middot; Combined Bear+Bull Daily Adaptive Strategy &middot; {today} &middot; Capital ₹1,00,000
    <br/>Past performance does not guarantee future results. This is a simulation — actual fills may differ.
  </div>

</div>

<script>
{data_js}

const INSIGHTS = {json.dumps(insights)};

// ── State ────────────────────────────────────────────────────────
let currentPeriod = '60d';
let equityChart, monthlyChart, exitChart, distChart;

// ── Switch period ────────────────────────────────────────────────
function switchPeriod(period, btn) {{
  currentPeriod = period;
  document.querySelectorAll('.tab').forEach(t => {{
    t.className = t === btn ? 'tab active' : 'tab inactive';
  }});
  render();
}}

// ── Format helpers ───────────────────────────────────────────────
const fmt = (n, sign=false) => {{
  const s = Math.abs(n).toLocaleString('en-IN', {{maximumFractionDigits:0}});
  if (sign) return (n >= 0 ? '+₹' : '-₹') + s;
  return '₹' + s;
}};
const pct = n => (n >= 0 ? '+' : '') + n.toFixed(1) + '%';
const color = n => n >= 0 ? '#4ade80' : '#f87171';

// ── Metric cards ─────────────────────────────────────────────────
function renderCards() {{
  const m  = SUMMARY[currentPeriod]?.metrics || {{}};
  const bm = SUMMARY[currentPeriod]?.bear_metrics || {{}};
  const um = SUMMARY[currentPeriod]?.bull_metrics || {{}};
  const cards = [
    {{ label:'Net P&L',    val: fmt(m.total_net_pnl||0, true), color: color(m.total_net_pnl||0), sub: (m.return_pct||0).toFixed(1)+'% return' }},
    {{ label:'Win Rate',   val: (m.win_rate_pct||0).toFixed(1)+'%', color: (m.win_rate_pct||0)>=50?'#4ade80':'#f87171', sub: `${{m.win_count||0}}W / ${{m.loss_count||0}}L` }},
    {{ label:'Profit Factor', val: (m.profit_factor||0).toFixed(2)+'x', color: (m.profit_factor||0)>=2?'#4ade80':(m.profit_factor||0)>=1?'#fbbf24':'#f87171', sub:'gross/loss ratio' }},
    {{ label:'Max Drawdown', val: (m.max_drawdown_pct||0).toFixed(1)+'%', color: (m.max_drawdown_pct||0)<10?'#4ade80':'#f87171', sub: fmt(m.max_drawdown_abs||0) }},
    {{ label:'Sharpe',    val: (m.sharpe_ratio||0).toFixed(2), color:(m.sharpe_ratio||0)>=2?'#4ade80':(m.sharpe_ratio||0)>=1?'#fbbf24':'#94a3b8', sub:'risk-adj return' }},
    {{ label:'Calmar',    val: (m.calmar_ratio||0).toFixed(2), color:(m.calmar_ratio||0)>=3?'#4ade80':'#94a3b8', sub:'return/drawdown' }},
    {{ label:'Bear P&L',  val: fmt(bm.total_net_pnl||0, true), color: color(bm.total_net_pnl||0), sub:`${{bm.win_rate_pct||0}}% WR` }},
    {{ label:'Bull P&L',  val: fmt(um.total_net_pnl||0, true), color: color(um.total_net_pnl||0), sub:`${{um.win_rate_pct||0}}% WR` }},
  ];
  document.getElementById('metric-cards').innerHTML = cards.map(c =>
    `<div class="card flex flex-col gap-1">
      <div class="text-[10px] font-bold text-slate-400 uppercase tracking-widest">${{c.label}}</div>
      <div class="stat-val" style="color:${{c.color}}">${{c.val}}</div>
      <div class="text-[11px] text-slate-500">${{c.sub}}</div>
    </div>`
  ).join('');
}}

// ── Insights ─────────────────────────────────────────────────────
function renderInsights() {{
  document.getElementById('insights-text').innerHTML = INSIGHTS[currentPeriod] || '';
}}

// ── Equity chart ─────────────────────────────────────────────────
function renderEquity() {{
  const pd = BACKTEST_DATA[currentPeriod];
  const trades = pd.trades || [];
  // Build labels from trade dates
  const labels = ['Start', ...trades.map((t,i) => t.trade_date||`T${{i+1}}`)];
  const eq = pd.equity || [100000];
  if (equityChart) equityChart.destroy();
  equityChart = new Chart(document.getElementById('equityChart'), {{
    type:'line',
    data: {{
      labels,
      datasets: [{{
        label:'Equity (₹)',
        data: eq,
        borderColor:'#0053e2',
        backgroundColor:'rgba(0,83,226,0.08)',
        fill:true,
        tension:0.25,
        pointRadius:0,
        borderWidth:2,
      }}]
    }},
    options:{{
      responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{display:false}}, tooltip:{{
        callbacks:{{
          label: ctx => ' ₹' + ctx.raw.toLocaleString('en-IN'),
        }}
      }}}},
      scales:{{
        x:{{ display:false }},
        y:{{
          ticks:{{ color:'#64748b', callback: v => '₹'+Math.round(v/1000)+'k' }},
          grid:{{ color:'rgba(51,65,85,0.5)' }},
        }}
      }}
    }}
  }});
}}

// ── Monthly chart ─────────────────────────────────────────────────
function renderMonthly() {{
  const pd = BACKTEST_DATA[currentPeriod];
  const colors = (pd.monthly_pnl||[]).map(v => v>=0?'rgba(34,197,94,0.8)':'rgba(239,68,68,0.8)');
  const borders = (pd.monthly_pnl||[]).map(v => v>=0?'#22c55e':'#ef4444');
  if (monthlyChart) monthlyChart.destroy();
  monthlyChart = new Chart(document.getElementById('monthlyChart'), {{
    type:'bar',
    data:{{
      labels: pd.months || [],
      datasets:[{{
        label:'Monthly P&L (₹)',
        data: pd.monthly_pnl || [],
        backgroundColor: colors,
        borderColor: borders,
        borderWidth:1,
        borderRadius:4,
      }}]
    }},
    options:{{
      responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{display:false}}, tooltip:{{
        callbacks:{{ label: ctx => (ctx.raw>=0?'+':'')+' ₹'+Math.abs(ctx.raw).toLocaleString('en-IN') }}
      }}}},
      scales:{{
        x:{{ ticks:{{ color:'#64748b', font:{{size:10}} }}, grid:{{display:false}} }},
        y:{{
          ticks:{{ color:'#64748b', callback: v=>(v>=0?'+':'')+Math.round(v/1000)+'k' }},
          grid:{{ color:'rgba(51,65,85,0.5)' }},
        }}
      }}
    }}
  }});
}}

// ── Exit donut ───────────────────────────────────────────────────
function renderExit() {{
  const exits = BACKTEST_DATA[currentPeriod].exits || {{}};
  const labels = Object.keys(exits);
  const values = Object.values(exits);
  const palette = ['#0053e2','#4ade80','#f87171','#fbbf24','#a78bfa','#34d399'];
  if (exitChart) exitChart.destroy();
  exitChart = new Chart(document.getElementById('exitChart'), {{
    type:'doughnut',
    data:{{
      labels,
      datasets:[{{ data:values, backgroundColor:palette, borderColor:'#1e293b', borderWidth:2 }}]
    }},
    options:{{
      responsive:true, maintainAspectRatio:false,
      plugins:{{
        legend:{{ position:'right', labels:{{ color:'#94a3b8', font:{{size:11}}, padding:12 }} }},
        tooltip:{{ callbacks:{{ label: ctx => ` ${{ctx.label}}: ${{ctx.raw}} trades` }} }}
      }}
    }}
  }});
}}

// ── Distribution histogram ────────────────────────────────────────
function renderDist() {{
  const trades = BACKTEST_DATA[currentPeriod].trades || [];
  if (!trades.length) return;
  const pnls = trades.map(t => t.net_pnl||0);
  // Bucket into ₹2k bins
  const minP = Math.floor(Math.min(...pnls)/2000)*2000;
  const maxP = Math.ceil(Math.max(...pnls)/2000)*2000;
  const buckets = {{}};
  for (let b=minP; b<=maxP; b+=2000) buckets[b]=0;
  pnls.forEach(p => {{
    const key = Math.floor(p/2000)*2000;
    buckets[key] = (buckets[key]||0)+1;
  }});
  const labels = Object.keys(buckets).map(k => (parseInt(k)>=0?'+':'')+Math.round(parseInt(k)/1000)+'k');
  const values = Object.values(buckets);
  const colors = Object.keys(buckets).map(k => parseInt(k)>=0?'rgba(34,197,94,0.7)':'rgba(239,68,68,0.7)');
  if (distChart) distChart.destroy();
  distChart = new Chart(document.getElementById('distChart'), {{
    type:'bar',
    data:{{
      labels,
      datasets:[{{ label:'# Trades', data:values, backgroundColor:colors, borderRadius:2 }}]
    }},
    options:{{
      responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{display:false}} }},
      scales:{{
        x:{{ ticks:{{ color:'#64748b', font:{{size:9}} }}, grid:{{display:false}} }},
        y:{{ ticks:{{ color:'#64748b' }}, grid:{{ color:'rgba(51,65,85,0.5)' }} }}
      }}
    }}
  }});
}}

// ── Strategy table ───────────────────────────────────────────────
function renderStratTable() {{
  const strats = BACKTEST_DATA[currentPeriod].strategies || [];
  document.getElementById('strat-table').innerHTML = strats.map(s =>
    `<tr>
      <td class="py-1.5 pr-4 font-mono text-slate-200">${{s.strategy}}</td>
      <td class="py-1.5 pr-4 text-right text-slate-300">${{s.total}}</td>
      <td class="py-1.5 pr-4 text-right"><span class="${{s.win_rate>=50?'badge-green':'badge-red'}}">${{s.win_rate}}%</span></td>
      <td class="py-1.5 pr-4 text-right text-green-400">${{s.wins}}</td>
      <td class="py-1.5 pr-4 text-right text-red-400">${{s.losses}}</td>
      <td class="py-1.5 text-right font-bold" style="color:${{s.net_pnl>=0?'#4ade80':'#f87171'}}">${{s.net_pnl>=0?'+':''}}₹${{Math.abs(s.net_pnl).toLocaleString('en-IN')}}</td>
    </tr>`
  ).join('');
}}

// ── Regime table ─────────────────────────────────────────────────
function renderRegimeTable() {{
  const regs = BACKTEST_DATA[currentPeriod].regimes || [];
  document.getElementById('regime-table').innerHTML = regs.map(r =>
    `<tr>
      <td class="py-1.5 pr-4 font-mono text-slate-200">${{r.regime}}</td>
      <td class="py-1.5 pr-4 text-right text-slate-300">${{r.total}}</td>
      <td class="py-1.5 pr-4 text-right"><span class="${{r.win_rate>=50?'badge-green':'badge-red'}}">${{r.win_rate}}%</span></td>
      <td class="py-1.5 pr-4 text-right text-green-400">${{r.wins}}</td>
      <td class="py-1.5 pr-4 text-right text-red-400">${{r.losses}}</td>
      <td class="py-1.5 text-right font-bold" style="color:${{r.net_pnl>=0?'#4ade80':'#f87171'}}">${{r.net_pnl>=0?'+':''}}₹${{Math.abs(r.net_pnl).toLocaleString('en-IN')}}</td>
    </tr>`
  ).join('');
}}

// ── Trade log ────────────────────────────────────────────────────
function renderTradeLog() {{
  const trades = [...(BACKTEST_DATA[currentPeriod].trades || [])].reverse().slice(0,30);
  const exitColor = r => r==='TARGET_HIT'?'#4ade80':r==='SL_HIT'?'#f87171':'#fbbf24';
  document.getElementById('trade-table').innerHTML = trades.map(t =>
    `<tr>
      <td class="py-1 pr-3 text-slate-300">${{t.trade_date||''}}</td>
      <td class="py-1 pr-3 text-slate-300">${{(t.strategy||'').replace(/_/g,' ')}}</td>
      <td class="py-1 pr-3 font-bold" style="color:${{t.signal==='CALL'?'#4ade80':'#f87171'}}">${{t.signal||t.direction||''}}</td>
      <td class="py-1 pr-3 text-slate-400">${{t.engine||t.regime||''}}</td>
      <td class="py-1 pr-3 text-right text-slate-300">₹${{(t.entry_price||0).toFixed(0)}}</td>
      <td class="py-1 pr-3 text-right text-slate-300">₹${{(t.exit_price||0).toFixed(0)}}</td>
      <td class="py-1 pr-3" style="color:${{exitColor(t.exit_reason)}}">${{t.exit_reason||''}}</td>
      <td class="py-1 text-right font-bold" style="color:${{(t.net_pnl||0)>=0?'#4ade80':'#f87171'}}">${{(t.net_pnl||0)>=0?'+':''}}₹${{Math.abs(t.net_pnl||0).toLocaleString('en-IN',{{maximumFractionDigits:0}})}}</td>
    </tr>`
  ).join('');
}}

// ── Full render ──────────────────────────────────────────────────
function render() {{
  renderCards();
  renderInsights();
  renderEquity();
  renderMonthly();
  renderExit();
  renderDist();
  renderStratTable();
  renderRegimeTable();
  renderTradeLog();
}}

render();
</script>
</body>
</html>"""

    html_path.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    html_path = main()
    print(f"\n✅ Done! Open: {html_path}")
