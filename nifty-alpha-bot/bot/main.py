"""
Entry point for live trading bot.
Usage:
    python -m bot.main                   # Live mode (uses .env settings)
    python -m bot.main --paper           # Paper trading mode
    python -m bot.main --token TOKEN     # Override Kite access token
    python -m bot.main --capital 65000   # Override capital
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

from loguru import logger


def _setup_logging():
    """Configure loguru: stderr + rotating file in LOG_DIR."""
    log_dir = Path(os.environ.get("LOG_DIR", os.environ.get("STATE_DIR", "/tmp"))) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_dir / "bot_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        compression="gz",
        level="INFO",
        format="{time:HH:mm:ss.SSS} | {level:<7} | {message}",
        enqueue=True,
    )
    logger.info(f"Log file: {log_dir}/bot_*.log")


def _run_bot_diagnostics(settings, client=None, access_token: str = "") -> dict:
    """Comprehensive startup diagnostics for the trading bot."""
    diag: dict = {"checks": [], "passed": 0, "failed": 0, "warnings": 0}

    def _ok(name, ok, detail="", warn=False):
        status = "PASS" if ok else ("WARN" if warn else "FAIL")
        diag["checks"].append({"name": name, "status": status, "detail": detail})
        if ok:
            diag["passed"] += 1
        elif warn:
            diag["warnings"] += 1
        else:
            diag["failed"] += 1
        tag = f"[{status}]"
        logger.info(f"  {tag:8s} {name}" + (f"  — {detail}" if detail else ""))

    logger.info("\n" + "=" * 65)
    logger.info("  BOT STARTUP DIAGNOSTICS")
    logger.info("=" * 65)

    mode = "PAPER" if settings.paper_mode else "LIVE"

    # ── 1. Core config ──
    _ok("Trading mode", True, mode)
    _ok("Capital", True, f"₹{settings.capital:,.0f}")
    _ok("Lot size", True, f"{settings.lot_size} (max {settings.max_lots} lots)")
    daily_limit = settings.capital * settings.max_daily_loss_pct
    _ok("Daily loss limit", True, f"₹{daily_limit:,.0f} ({settings.max_daily_loss_pct*100:.0f}%) | hard=₹{settings.max_daily_loss_hard:,.0f}")
    _ok("Drawdown halt", True, f"{settings.max_drawdown_pct}%")
    _ok("Risk/trade", True, f"{settings.risk_per_trade_pct*100:.1f}% = ₹{settings.capital*settings.risk_per_trade_pct:,.0f}")
    _ok("Max trades/day", True, str(settings.max_trades_per_day))

    # ── 2. Execution config ──
    _ok("Entry orders", True,
        f"{'Aggressive Limit (buffer ' + str(settings.limit_price_buffer_pct*100) + '%)' if settings.use_limit_orders else 'Market'}")
    _ok("SL protection", True, f"{'SL-M (exchange-side)' if settings.use_slm_exit else 'Software SL'}")
    _ok("API retries", True, f"{settings.api_retries} retries, {settings.api_retry_delay_seconds}s delay")

    # ── 3. Time windows ──
    _ok("ORB window", True, f"{settings.orb_start}–{settings.orb_end}, entry till {settings.entry_window_close}")
    _ok("VWAP window", True, f"{settings.reclaim_window_start}–{settings.reclaim_window_end}")
    _ok("Force exit", True, settings.force_exit_time)

    # ── 4. Kite credentials ──
    _ok("KITE_API_KEY", bool(settings.kite_api_key),
        f"{'...' + settings.kite_api_key[-4:] if settings.kite_api_key else 'MISSING'}")
    _ok("KITE_API_SECRET", bool(settings.kite_api_secret),
        f"{'...' + settings.kite_api_secret[-4:] if settings.kite_api_secret else 'MISSING'}")
    _ok("Access token", bool(access_token),
        f"{'...' + access_token[-4:] if access_token else 'MISSING'}")

    # ── 5. Broker client methods ──
    if client:
        required_methods = [
            "check_auth", "get_quote", "get_quote_details", "get_candles",
            "get_nifty_token", "select_atm_option", "get_nearest_expiry",
            "get_available_margin", "place_order", "place_slm_order",
            "modify_slm_order", "get_order_status", "confirm_fill",
            "cancel_order", "get_positions", "get_open_qty",
            "load_instruments", "get_option_chain_symbols",
        ]
        missing = [m for m in required_methods if not hasattr(client, m)]
        _ok("KiteClient methods", not missing,
            f"all {len(required_methods)} present" if not missing else f"MISSING: {missing}")

        # Auth check
        if not settings.paper_mode:
            try:
                auth_ok = client.check_auth()
                _ok("Kite auth verify", auth_ok, "profile() OK" if auth_ok else "FAILED")
            except Exception as e:
                _ok("Kite auth verify", False, str(e)[:50])
        else:
            _ok("Kite auth verify", True, "skipped (paper mode)", warn=False)

        # Margin check
        if not settings.paper_mode:
            try:
                margin = client.get_available_margin()
                _ok("Available margin", margin is not None and margin > 0,
                    f"₹{margin:,.0f}" if margin else "unavailable", warn=margin is None)
            except Exception as e:
                _ok("Available margin", False, str(e)[:50], warn=True)

        # Nifty spot price
        try:
            nifty = client.get_quote("NIFTY 50", "NSE")
            _ok("NIFTY 50 quote", nifty > 0, f"₹{nifty:,.1f}" if nifty else "unavailable")
        except Exception as e:
            _ok("NIFTY 50 quote", False, str(e)[:50], warn=True)

        # Instruments
        if client._instruments_loaded:
            count = len(client._instrument_cache)
            _ok("NFO instruments", count > 0, f"{count:,} loaded")

            # Nearest expiry
            try:
                exp = client.get_nearest_expiry()
                _ok("Nearest expiry", exp is not None, str(exp) if exp else "none found")
            except Exception as e:
                _ok("Nearest expiry", False, str(e)[:50], warn=True)

    # ── 6. Shared modules ──
    for mod in ["shared.indicators", "shared.regime_detector", "shared.orb_engine",
                "shared.vwap_reclaim_engine", "shared.black_scholes"]:
        try:
            importlib.import_module(mod)
            _ok(f"Module: {mod.split('.')[-1]}", True)
        except Exception as e:
            _ok(f"Module: {mod.split('.')[-1]}", False, str(e)[:50])

    # ── 7. Risk manager ──
    try:
        from bot.risk_manager import RiskManager
        rm = RiskManager(
            capital=settings.capital,
            max_daily_loss_pct=settings.max_daily_loss_pct,
            max_trades_per_day=settings.max_trades_per_day,
            max_daily_loss_hard=settings.max_daily_loss_hard,
            risk_per_trade_pct=settings.risk_per_trade_pct,
            lot_size=settings.lot_size,
            max_lots=settings.max_lots,
            max_drawdown_pct=settings.max_drawdown_pct,
        )
        can, reason = rm.can_trade()
        _ok("Risk manager", True,
            f"can_trade={'YES' if can else 'NO'}" + (f" ({reason})" if not can else ""))
        _ok("Position sizing", True,
            f"sample: entry=₹150, SL=30% → {rm.compute_position_size(150, 0.30)}")
        _ok("Drawdown", True,
            f"{rm.drawdown_pct():.1f}% (cap=₹{rm.current_capital:,.0f}, peak=₹{rm.state.peak_capital:,.0f})")
    except Exception as e:
        _ok("Risk manager", False, str(e)[:80])

    # ── 8. State files ──
    state_dir = Path(os.environ.get("STATE_DIR", "/tmp"))
    _ok("State dir", state_dir.exists(), str(state_dir))
    for fname in ["kite_bot_events.jsonl", "kite_bot_position.json",
                   "kite_token_cache.json", "kite_bot_risk_state.json",
                   "kite_bot_strategy_state.json"]:
        fp = state_dir / fname
        exists = fp.exists()
        size = fp.stat().st_size if exists else 0
        _ok(f"  {fname}", True,
            f"{'exists' if exists else 'will create'}" + (f" ({size:,}B)" if exists else ""))

    # ── 9. Notifications ──
    _ok("Telegram", bool(settings.telegram_bot_token and settings.telegram_chat_id),
        "configured" if settings.telegram_bot_token else "not configured", warn=not settings.telegram_bot_token)

    # Summary
    total = diag["passed"] + diag["failed"] + diag["warnings"]
    logger.info("-" * 65)
    summary = f"  {diag['passed']}/{total} passed"
    if diag["warnings"]:
        summary += f", {diag['warnings']} warnings"
    if diag["failed"]:
        summary += f", {diag['failed']} FAILED"
    logger.info(summary)

    if diag["failed"] > 0 and not settings.paper_mode:
        logger.warning("  ⚠ FAILED checks detected in LIVE mode — review before trading!")
    logger.info("=" * 65 + "\n")

    return diag


def main():
    _setup_logging()

    parser = argparse.ArgumentParser(description="NIFTY Alpha Bot — Live Trading")
    parser.add_argument("--paper", action="store_true", help="Run in paper trading mode")
    parser.add_argument("--token", type=str, help="Kite access token (overrides .env)")
    parser.add_argument("--capital", type=float, help="Override capital")
    args = parser.parse_args()

    if args.paper:
        os.environ["PAPER_MODE"] = "true"
    if args.capital:
        os.environ["CAPITAL"] = str(args.capital)

    from shared.config import settings
    from kite_broker.token_manager import get_valid_token, schedule_daily_refresh, register_token_callback
    from kite_broker.client import KiteClient
    from bot.trader import KiteORBTrader

    mode = "PAPER" if settings.paper_mode else "LIVE"
    logger.info(f"\n{'='*60}")
    logger.info(f"  NIFTY ALPHA BOT — {mode} MODE")
    logger.info(f"  Capital: ₹{settings.capital:,.0f}")
    logger.info(f"  Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    logger.info(f"{'='*60}\n")

    # Get valid token
    access_token = get_valid_token(
        api_key=settings.kite_api_key,
        api_secret=settings.kite_api_secret,
        user_id=settings.kite_user_id,
        password=settings.kite_user_password,
        totp_secret=settings.kite_totp_secret,
        manual_token=args.token or "",
    )
    logger.info("[Bot] Kite token: OK")

    # Initialize client
    client = KiteClient.from_token(settings.kite_api_key, access_token)

    # Register token refresh callback
    def on_token_refresh(new_token: str):
        client.kite.set_access_token(new_token)
        logger.info("[Bot] Token hot-reloaded into running client")

    register_token_callback(on_token_refresh)

    # Schedule daily token refresh (pre-market)
    if settings.kite_totp_secret:
        schedule_daily_refresh(
            api_key=settings.kite_api_key,
            api_secret=settings.kite_api_secret,
            user_id=settings.kite_user_id,
            password=settings.kite_user_password,
            totp_secret=settings.kite_totp_secret,
        )

    if not settings.paper_mode:
        ok = client.check_auth()
        if not ok:
            logger.error("[Bot] Kite authentication failed. Check your token.")
            sys.exit(1)
        logger.info("[Bot] Kite authentication: OK")

    logger.info("[Bot] Loading instruments...")
    try:
        client.load_instruments("NFO")
        logger.info(f"[Bot] Loaded {len(client._instrument_cache)} NFO instruments")
    except Exception as e:
        logger.warning(f"[Bot] Instrument load failed: {e}")

    # Run comprehensive diagnostics
    _run_bot_diagnostics(settings, client, access_token)

    # Run module self-test — validates impulse detector, trend detector,
    # all 4 strategy engines, quality filter and risk manager with synthetic data
    from bot.startup_validator import run_startup_validation
    run_startup_validation(paper_mode=settings.paper_mode)

    trader = KiteORBTrader(client)
    trader.startup_sync()   # verify broker position vs local state before starting loop
    trader.run()


if __name__ == "__main__":
    main()
