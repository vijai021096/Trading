"""Performance metrics for backtest results."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def compute_metrics(
    trades: List[Dict[str, Any]],
    capital: float = 100_000.0,
    risk_free_rate: float = 0.065,
) -> Dict[str, Any]:
    """
    Compute comprehensive performance metrics from trade log.

    Returns:
        total_trades, win_rate, profit_factor, avg_win, avg_loss,
        total_net_pnl, max_drawdown_abs, max_drawdown_pct,
        sharpe_ratio, calmar_ratio, consecutive_losses_max,
        avg_trade_duration_min, total_charges, gross_pnl
    """
    if not trades:
        return _empty_metrics()

    net_pnls = [float(t["net_pnl"]) for t in trades]
    gross_pnls = [float(t["gross_pnl"]) for t in trades]
    charges = [float(t.get("charges", 0)) for t in trades]

    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p <= 0]

    total_trades = len(trades)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = win_count / total_trades * 100 if total_trades > 0 else 0.0

    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    total_win = sum(wins)
    total_loss = abs(sum(losses))
    profit_factor = total_win / total_loss if total_loss > 0 else float("inf")

    total_net_pnl = sum(net_pnls)
    total_gross_pnl = sum(gross_pnls)
    total_charges = sum(charges)

    # ── Drawdown ─────────────────────────────────────────────────
    equity = capital
    peak = capital
    max_drawdown_abs = 0.0
    equity_curve = [capital]
    for pnl in net_pnls:
        equity += pnl
        equity_curve.append(equity)
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_drawdown_abs:
            max_drawdown_abs = dd

    max_drawdown_pct = (max_drawdown_abs / capital) * 100

    # ── Sharpe Ratio (annualized) ─────────────────────────────────
    # Use daily P&L bucketing
    daily_pnls = _bucket_by_day(trades)
    if len(daily_pnls) > 1:
        mean_daily = sum(daily_pnls) / len(daily_pnls)
        variance = sum((x - mean_daily) ** 2 for x in daily_pnls) / (len(daily_pnls) - 1)
        std_daily = math.sqrt(variance) if variance > 0 else 0.0
        daily_rf = risk_free_rate / 252
        sharpe = ((mean_daily - daily_rf) / std_daily) * math.sqrt(252) if std_daily > 0 else 0.0
    else:
        sharpe = 0.0

    # ── Calmar Ratio ─────────────────────────────────────────────
    trading_days = len(daily_pnls)
    if trading_days > 0 and max_drawdown_abs > 0:
        # Annualize returns
        annualized_pnl = total_net_pnl * (252 / trading_days)
        annualized_return_pct = (annualized_pnl / capital) * 100
        calmar = annualized_return_pct / max_drawdown_pct if max_drawdown_pct > 0 else 0.0
    else:
        calmar = 0.0

    # ── Consecutive losses ────────────────────────────────────────
    max_consec_loss = 0
    curr_consec = 0
    for pnl in net_pnls:
        if pnl <= 0:
            curr_consec += 1
            max_consec_loss = max(max_consec_loss, curr_consec)
        else:
            curr_consec = 0

    # ── Trade duration ────────────────────────────────────────────
    durations = []
    for t in trades:
        try:
            from datetime import datetime
            entry = datetime.fromisoformat(t["entry_ts"])
            exit_ = datetime.fromisoformat(t["exit_ts"])
            durations.append((exit_ - entry).total_seconds() / 60)
        except Exception:
            pass
    avg_duration_min = sum(durations) / len(durations) if durations else 0.0

    # ── Exit reason breakdown ─────────────────────────────────────
    exit_counts: Dict[str, int] = {}
    for t in trades:
        reason = t.get("exit_reason", "UNKNOWN")
        exit_counts[reason] = exit_counts.get(reason, 0) + 1

    # ── Monthly breakdown ─────────────────────────────────────────
    monthly = _monthly_breakdown(trades)

    return {
        "total_trades": total_trades,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate_pct": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "total_net_pnl": round(total_net_pnl, 2),
        "total_gross_pnl": round(total_gross_pnl, 2),
        "total_charges": round(total_charges, 2),
        "max_drawdown_abs": round(max_drawdown_abs, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "sharpe_ratio": round(sharpe, 3),
        "calmar_ratio": round(calmar, 3),
        "consecutive_losses_max": max_consec_loss,
        "avg_trade_duration_min": round(avg_duration_min, 1),
        "exit_reasons": exit_counts,
        "equity_curve": [round(e, 2) for e in equity_curve],
        "final_capital": round(equity_curve[-1], 2),
        "return_pct": round((total_net_pnl / capital) * 100, 2),
        "monthly_breakdown": monthly,
        "trading_days": trading_days,
    }


def _bucket_by_day(trades: List[Dict]) -> List[float]:
    """Sum P&L by calendar day."""
    daily: Dict[str, float] = {}
    for t in trades:
        d = str(t.get("trade_date", t.get("entry_ts", "")[:10]))[:10]
        daily[d] = daily.get(d, 0.0) + float(t["net_pnl"])
    return list(daily.values())


def _monthly_breakdown(trades: List[Dict]) -> List[Dict]:
    monthly: Dict[str, Dict] = {}
    for t in trades:
        d = str(t.get("trade_date", t.get("entry_ts", "")))[:10]
        month = d[:7]  # YYYY-MM
        if month not in monthly:
            monthly[month] = {"month": month, "trades": 0, "net_pnl": 0.0, "wins": 0}
        monthly[month]["trades"] += 1
        monthly[month]["net_pnl"] += float(t["net_pnl"])
        if float(t["net_pnl"]) > 0:
            monthly[month]["wins"] += 1
    result = sorted(monthly.values(), key=lambda x: x["month"])
    for m in result:
        m["net_pnl"] = round(m["net_pnl"], 2)
        m["win_rate"] = round(m["wins"] / m["trades"] * 100, 1) if m["trades"] > 0 else 0.0
    return result


def _empty_metrics() -> Dict[str, Any]:
    return {
        "total_trades": 0, "win_count": 0, "loss_count": 0,
        "win_rate_pct": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        "profit_factor": 0.0, "total_net_pnl": 0.0,
        "total_gross_pnl": 0.0, "total_charges": 0.0,
        "max_drawdown_abs": 0.0, "max_drawdown_pct": 0.0,
        "sharpe_ratio": 0.0, "calmar_ratio": 0.0,
        "consecutive_losses_max": 0, "avg_trade_duration_min": 0.0,
        "exit_reasons": {}, "equity_curve": [], "final_capital": 0.0,
        "return_pct": 0.0, "monthly_breakdown": [], "trading_days": 0,
    }
