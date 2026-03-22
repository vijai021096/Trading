"""
Entry point for live trading bot.
Usage:
    cd nifty-alpha-bot
    python -m bot.main
    python -m bot.main --paper
    python -m bot.main --token YOUR_KITE_ACCESS_TOKEN
"""
from __future__ import annotations

import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="NIFTY Alpha Bot — Live Trading")
    parser.add_argument("--paper", action="store_true", help="Run in paper trading mode")
    parser.add_argument("--token", type=str, help="Kite access token (overrides .env)")
    parser.add_argument("--capital", type=float, help="Override capital")
    args = parser.parse_args()

    # Apply CLI overrides before importing settings
    if args.paper:
        os.environ["PAPER_MODE"] = "true"
    if args.capital:
        os.environ["CAPITAL"] = str(args.capital)

    from shared.config import settings
    from kite_broker.token_manager import get_valid_token, schedule_daily_refresh
    from kite_broker.client import KiteClient
    from bot.trader import KiteORBTrader

    print(f"\n[Bot] NIFTY Alpha Bot starting...")
    print(f"[Bot] Mode: {'PAPER' if settings.paper_mode else 'LIVE'}")
    print(f"[Bot] Capital: ₹{settings.capital:,.0f}")

    # Get valid token
    access_token = get_valid_token(
        api_key=settings.kite_api_key,
        api_secret=settings.kite_api_secret,
        user_id=settings.kite_user_id,
        password=settings.kite_user_password,
        totp_secret=settings.kite_totp_secret,
        manual_token=args.token or "",
    )
    print(f"[Bot] Kite token: {'OK (paper mode)' if settings.paper_mode else 'OK'}")

    # Schedule daily token refresh
    if settings.kite_totp_secret:
        schedule_daily_refresh(
            api_key=settings.kite_api_key,
            api_secret=settings.kite_api_secret,
            user_id=settings.kite_user_id,
            password=settings.kite_user_password,
            totp_secret=settings.kite_totp_secret,
        )

    # Initialize client
    client = KiteClient.from_token(settings.kite_api_key, access_token)

    if not settings.paper_mode:
        ok = client.check_auth()
        if not ok:
            print("[Bot] ERROR: Kite authentication failed. Check your token.")
            sys.exit(1)
        print("[Bot] Kite authentication: OK")

    # Load instrument cache
    print("[Bot] Loading instruments...")
    try:
        client.load_instruments("NFO")
        print(f"[Bot] Loaded {len(client._instrument_cache)} NFO instruments")
    except Exception as e:
        print(f"[Bot] WARNING: Instrument load failed: {e}")

    # Start trader
    trader = KiteORBTrader(client)
    trader.run()


if __name__ == "__main__":
    main()
