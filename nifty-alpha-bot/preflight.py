#!/usr/bin/env python3
"""
Pre-flight checklist — run before market open to verify everything is ready.

Usage:
    python preflight.py           # Full check (needs Kite token)
    python preflight.py --skip-broker   # Skip broker checks (no token needed)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

checks_passed = 0
checks_failed = 0
checks_warned = 0


def ok(msg: str) -> None:
    global checks_passed
    checks_passed += 1
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str) -> None:
    global checks_failed
    checks_failed += 1
    print(f"  {RED}✗{RESET} {msg}")


def warn(msg: str) -> None:
    global checks_warned
    checks_warned += 1
    print(f"  {YELLOW}!{RESET} {msg}")


def header(title: str) -> None:
    print(f"\n{BOLD}{CYAN}── {title} ──{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Pre-flight checklist")
    parser.add_argument("--skip-broker", action="store_true", help="Skip broker connectivity checks")
    args = parser.parse_args()

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD} NIFTY ALPHA BOT — PRE-FLIGHT CHECKLIST{RESET}")
    print(f"{BOLD} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({date.today().strftime('%A')}){RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    # ── 1. Environment ──────────────────────────────────────────
    header("1. ENVIRONMENT")

    env_path = Path(".env")
    if env_path.exists():
        ok(f".env file found ({env_path.stat().st_size} bytes)")
    else:
        fail(".env file missing — copy from .env.example and fill in values")
        print(f"     {YELLOW}cp .env.example .env && nano .env{RESET}")

    try:
        from shared.config import settings
        ok(f"Config loaded successfully")
    except Exception as e:
        fail(f"Config load failed: {e}")
        print(f"     Fix .env values and try again")
        sys.exit(1)

    # ── 2. Trading Mode ─────────────────────────────────────────
    header("2. TRADING MODE")

    if settings.paper_mode:
        warn(f"Running in PAPER MODE — no real orders will be placed")
    else:
        ok(f"Running in LIVE MODE — real money at risk!")

    ok(f"Capital: ₹{settings.capital:,.0f}")
    ok(f"Risk per trade: {settings.risk_per_trade_pct*100:.1f}% = ₹{settings.capital * settings.risk_per_trade_pct:,.0f}")
    ok(f"Max daily loss: {settings.max_daily_loss_pct*100:.0f}% = ₹{settings.capital * settings.max_daily_loss_pct:,.0f}")
    ok(f"Hard daily stop: ₹{settings.max_daily_loss_hard:,.0f}")
    ok(f"Max trades/day: {settings.max_trades_per_day}")
    ok(f"Max consecutive losses: {settings.max_consecutive_losses}")
    ok(f"Lot size: {settings.lot_size} | Max lots: {settings.max_lots}")

    # ── 3. Risk Validation ──────────────────────────────────────
    header("3. RISK VALIDATION")

    risk_per_trade = settings.capital * settings.risk_per_trade_pct
    max_loss_scenario = risk_per_trade * settings.max_consecutive_losses
    max_loss_pct = (max_loss_scenario / settings.capital) * 100

    ok(f"Worst-case streak ({settings.max_consecutive_losses} losses): ₹{max_loss_scenario:,.0f} ({max_loss_pct:.0f}% of capital)")

    if settings.risk_per_trade_pct > 0.02:
        warn(f"Risk per trade ({settings.risk_per_trade_pct*100:.1f}%) is aggressive — consider ≤2%")
    elif settings.risk_per_trade_pct <= 0.01:
        ok(f"Risk per trade is conservative (≤1%) — good for survival")

    if max_loss_pct > 30:
        fail(f"Worst-case max drawdown ({max_loss_pct:.0f}%) exceeds 30% — reduce risk_per_trade_pct or max_consecutive_losses")
    else:
        ok(f"Worst-case drawdown manageable ({max_loss_pct:.0f}%)")

    daily_cap_ok = settings.max_daily_loss_hard <= settings.capital * settings.max_daily_loss_pct * 1.5
    if daily_cap_ok:
        ok(f"Daily hard stop (₹{settings.max_daily_loss_hard:,.0f}) is aligned with % limit")
    else:
        warn(f"Daily hard stop (₹{settings.max_daily_loss_hard:,.0f}) may be too loose vs % limit (₹{settings.capital * settings.max_daily_loss_pct:,.0f})")

    # ── 4. Strategy Params ──────────────────────────────────────
    header("4. STRATEGY PARAMS")

    ok(f"ORB window: {settings.orb_start}-{settings.orb_end}, entry until {settings.entry_window_close}")
    ok(f"VWAP Reclaim: {settings.reclaim_window_start}-{settings.reclaim_window_end}")
    ok(f"Force exit: {settings.force_exit_time}")
    ok(f"VIX max: {settings.vix_max}")
    ok(f"SL range: {settings.atr_sl_min_pct*100:.0f}%-{settings.atr_sl_max_pct*100:.0f}%")
    ok(f"RR min: {settings.rr_min}x")
    ok(f"Option price range: ₹{settings.min_option_price}-₹{settings.max_option_price}")
    ok(f"Max spread: {settings.max_spread_pct*100:.1f}%")

    # ── 5. Kite Credentials ─────────────────────────────────────
    header("5. KITE CREDENTIALS")

    if settings.kite_api_key and settings.kite_api_key != "your_api_key_here":
        ok(f"API key: {settings.kite_api_key[:6]}...")
    else:
        fail("KITE_API_KEY not set")

    if settings.kite_api_secret and settings.kite_api_secret != "your_api_secret_here":
        ok(f"API secret: {'*' * 8}")
    else:
        fail("KITE_API_SECRET not set")

    if settings.kite_user_id and settings.kite_user_id != "your_user_id":
        ok(f"User ID: {settings.kite_user_id}")
    else:
        fail("KITE_USER_ID not set")

    has_totp = bool(settings.kite_totp_secret)
    has_manual_token = bool(settings.kite_access_token)

    if has_totp:
        ok("TOTP secret configured (auto-login available)")
    elif has_manual_token:
        ok("Manual access token configured")
    else:
        warn("No TOTP or manual token — must provide token at startup via --token or dashboard")

    # ── 6. Broker Connectivity ──────────────────────────────────
    if not args.skip_broker:
        header("6. BROKER CONNECTIVITY")

        try:
            from kite_broker.token_manager import get_valid_token
            from kite_broker.client import KiteClient

            token = get_valid_token(
                api_key=settings.kite_api_key,
                api_secret=settings.kite_api_secret,
                user_id=settings.kite_user_id,
                password=settings.kite_user_password,
                totp_secret=settings.kite_totp_secret,
                manual_token=settings.kite_access_token or "",
            )
            if token:
                ok(f"Token obtained: {token[:8]}...")
            else:
                fail("Could not obtain valid token")

            if not settings.paper_mode and token:
                client = KiteClient.from_token(settings.kite_api_key, token)
                auth_ok = client.check_auth()
                if auth_ok:
                    ok("Kite authentication successful")
                else:
                    fail("Kite authentication failed — token may be expired")

                try:
                    client.load_instruments("NFO")
                    count = len(client._instrument_cache)
                    ok(f"NFO instruments loaded: {count}")
                    if count < 100:
                        warn(f"Instrument count seems low ({count}) — market may be closed")
                except Exception as e:
                    fail(f"Instrument load failed: {e}")

        except Exception as e:
            fail(f"Broker connectivity error: {e}")
    else:
        header("6. BROKER CONNECTIVITY (SKIPPED)")
        warn("Broker checks skipped — use --skip-broker=false before live trading")

    # ── 7. State Files ──────────────────────────────────────────
    header("7. STATE FILES")

    state_dir = Path(os.environ.get("STATE_DIR", "/tmp"))
    halt_file = state_dir / "kite_bot_halt.flag"
    if halt_file.exists():
        warn(f"Emergency halt flag EXISTS at {halt_file} — bot will NOT trade!")
        print(f"     {YELLOW}Remove it: rm {halt_file}{RESET}")
    else:
        ok("No emergency halt flag active")

    pos_file = state_dir / "kite_bot_position.json"
    if pos_file.exists():
        try:
            pos = json.loads(pos_file.read_text())
            state = pos.get("state", "IDLE")
            if state != "IDLE":
                warn(f"Position state: {state} — there may be a leftover position")
                print(f"     Symbol: {pos.get('symbol', '?')}")
                print(f"     {YELLOW}If stale, reset: rm {pos_file}{RESET}")
            else:
                ok("Position state: IDLE (clean)")
        except Exception:
            warn(f"Position file exists but unreadable")
    else:
        ok("No position state file (fresh start)")

    strat_file = state_dir / "kite_bot_strategy_state.json"
    if strat_file.exists():
        try:
            strat = json.loads(strat_file.read_text())
            ok(f"Strategy toggles: ORB={'ON' if strat.get('orb_enabled', True) else 'OFF'}, VWAP={'ON' if strat.get('vwap_enabled', True) else 'OFF'}")
        except Exception:
            warn("Strategy state file exists but unreadable")
    else:
        ok("No strategy toggle file (all strategies enabled)")

    events_file = state_dir / "kite_bot_events.jsonl"
    if events_file.exists():
        lines = events_file.read_text().strip().split("\n")
        ok(f"Events log: {len(lines)} entries")
    else:
        ok("No events log yet (will be created)")

    # ── 8. Calendar Check ───────────────────────────────────────
    header("8. CALENDAR CHECK")

    today = date.today()
    weekday = today.weekday()

    if weekday >= 5:
        warn(f"Today is {today.strftime('%A')} — market is closed")
    else:
        ok(f"Today is {today.strftime('%A')} — trading day")

    if weekday == 3:
        ok("EXPIRY DAY (Thursday) — will use conservative lots")
    elif weekday < 5:
        ok(f"Non-expiry day — normal trading parameters")

    # ── 9. Notifications ────────────────────────────────────────
    header("9. NOTIFICATIONS")

    if settings.telegram_bot_token and settings.telegram_chat_id:
        ok(f"Telegram configured (chat: {settings.telegram_chat_id})")
    else:
        warn("Telegram not configured — you'll need to monitor logs manually")

    # ── Summary ─────────────────────────────────────────────────
    print(f"\n{BOLD}{'='*60}{RESET}")
    total = checks_passed + checks_failed + checks_warned
    print(f"{BOLD} RESULTS: {GREEN}{checks_passed} passed{RESET}, {RED}{checks_failed} failed{RESET}, {YELLOW}{checks_warned} warnings{RESET} / {total} total")

    if checks_failed == 0:
        print(f"\n  {GREEN}{BOLD}ALL CLEAR — Ready to trade!{RESET}")
        if settings.paper_mode:
            print(f"  {YELLOW}Start in paper mode:{RESET}  python -m bot.main --paper")
            print(f"  {YELLOW}Start with Docker:{RESET}    docker compose up -d")
        else:
            print(f"  {YELLOW}Start live:{RESET}           python -m bot.main")
            print(f"  {YELLOW}Start with Docker:{RESET}    docker compose up -d")
    else:
        print(f"\n  {RED}{BOLD}FIX {checks_failed} FAILURE(S) BEFORE TRADING{RESET}")

    print(f"{BOLD}{'='*60}{RESET}\n")
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
