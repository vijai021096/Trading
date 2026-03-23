"""Helpers for live daily_adaptive engine (parity with daily_backtest_engine)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

from backtest.daily_backtest_engine import DailyBacktestConfig
from shared.config import Settings


def _anchor_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "daily_adaptive_anchor.json"


def load_anchor_ym() -> Tuple[int, int] | None:
    p = _anchor_path()
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        y, m = int(d["year"]), int(d["month"])
        return y, m
    except Exception:
        return None


def save_anchor_ym(year: int, month: int) -> None:
    p = _anchor_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"year": year, "month": month}), encoding="utf-8")


def daily_backtest_config_from_settings(s: Settings) -> DailyBacktestConfig:
    return DailyBacktestConfig(
        capital=s.capital,
        lot_size=s.nifty_option_lot_size,
        lots=s.daily_base_lots,
    )
