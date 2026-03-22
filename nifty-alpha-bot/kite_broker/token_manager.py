"""
Zerodha Kite daily token refresh manager.

Kite requires a new access_token every day. Two modes:
  1. TOTP automation (headless browser) — for AWS/server use
  2. Manual — user provides token via env var or dashboard API

TOTP automation uses playwright + pyotp to:
  1. Open Kite login page
  2. Fill credentials
  3. Auto-fill TOTP
  4. Capture redirect URL
  5. Exchange request_token for access_token
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

TOKEN_CACHE = Path("/tmp/kite_token_cache.json")


def save_token(access_token: str) -> None:
    """Save token with today's date for cache validation."""
    data = {
        "access_token": access_token,
        "date": date.today().isoformat(),
        "saved_at": datetime.now().isoformat(),
    }
    TOKEN_CACHE.write_text(json.dumps(data))


def load_cached_token() -> Optional[str]:
    """Return cached token if it was saved today, else None."""
    if not TOKEN_CACHE.exists():
        return None
    try:
        data = json.loads(TOKEN_CACHE.read_text())
        if data.get("date") == date.today().isoformat():
            return data.get("access_token")
    except Exception:
        pass
    return None


def get_token_automated(
    api_key: str,
    api_secret: str,
    user_id: str,
    password: str,
    totp_secret: str,
) -> Optional[str]:
    """
    Automated TOTP login using Playwright headless browser.
    Returns access_token or None on failure.
    """
    try:
        import pyotp
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        print("[TokenManager] playwright/pyotp not installed. Run: pip install playwright pyotp && playwright install chromium")
        return None

    totp = pyotp.TOTP(totp_secret)
    login_url = f"https://kite.trade/connect/login?api_key={api_key}&v=3"
    request_token = None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()

            # Navigate to login
            page.goto(login_url, wait_until="networkidle", timeout=30000)

            # Fill credentials
            page.fill('input[type="text"]', user_id)
            page.fill('input[type="password"]', password)
            page.click('button[type="submit"]')
            page.wait_for_timeout(2000)

            # Fill TOTP
            try:
                page.fill('input[type="number"]', totp.now())
                page.click('button[type="submit"]')
                page.wait_for_timeout(3000)
            except Exception:
                # Some flows use text type for TOTP
                try:
                    page.fill('input[label="External TOTP"]', totp.now())
                    page.click('button[type="submit"]')
                    page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"[TokenManager] TOTP fill failed: {e}")

            # Capture redirect URL with request_token
            current_url = page.url
            if "request_token=" in current_url:
                request_token = current_url.split("request_token=")[1].split("&")[0]
            else:
                # Wait for redirect
                try:
                    page.wait_for_url("**/request_token=*", timeout=10000)
                    current_url = page.url
                    if "request_token=" in current_url:
                        request_token = current_url.split("request_token=")[1].split("&")[0]
                except PlaywrightTimeout:
                    print(f"[TokenManager] Timeout waiting for redirect. URL: {current_url}")

            browser.close()
    except Exception as e:
        print(f"[TokenManager] Browser automation error: {e}")
        return None

    if not request_token:
        print("[TokenManager] Failed to capture request_token")
        return None

    # Exchange request_token for access_token
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=api_key)
        session = kite.generate_session(request_token, api_secret=api_secret)
        access_token = session["access_token"]
        save_token(access_token)
        print(f"[TokenManager] Token refreshed successfully at {datetime.now().strftime('%H:%M:%S')}")
        return access_token
    except Exception as e:
        print(f"[TokenManager] Session generation failed: {e}")
        return None


def get_valid_token(
    api_key: str,
    api_secret: str,
    user_id: str = "",
    password: str = "",
    totp_secret: str = "",
    manual_token: str = "",
) -> str:
    """
    Get a valid access token. Priority:
    1. manual_token (if provided)
    2. ENV var KITE_ACCESS_TOKEN (if set today)
    3. Cached token from today
    4. Automated TOTP refresh
    """
    # Manual override
    if manual_token:
        save_token(manual_token)
        return manual_token

    # ENV var
    env_token = os.environ.get("KITE_ACCESS_TOKEN", "")
    if env_token:
        cached = load_cached_token()
        if cached == env_token:
            return env_token
        # ENV token might be from today — trust it and cache it
        save_token(env_token)
        return env_token

    # Cache
    cached = load_cached_token()
    if cached:
        return cached

    # Automated
    if totp_secret and user_id and password:
        print("[TokenManager] Attempting automated TOTP login...")
        token = get_token_automated(api_key, api_secret, user_id, password, totp_secret)
        if token:
            return token

    raise RuntimeError(
        "No valid Kite access token. Set KITE_ACCESS_TOKEN env var or provide TOTP credentials."
    )


def schedule_daily_refresh(
    api_key: str,
    api_secret: str,
    user_id: str,
    password: str,
    totp_secret: str,
    refresh_time: str = "08:55",
) -> None:
    """
    Schedule daily token refresh at refresh_time (IST).
    Call this in a background thread at bot startup.
    """
    try:
        import schedule

        def do_refresh():
            print(f"[TokenManager] Scheduled daily refresh starting...")
            token = get_token_automated(api_key, api_secret, user_id, password, totp_secret)
            if token:
                os.environ["KITE_ACCESS_TOKEN"] = token
                print(f"[TokenManager] Daily token refresh successful.")
            else:
                print("[TokenManager] Daily token refresh FAILED. Manual token required.")

        schedule.every().day.at(refresh_time).do(do_refresh)

        import threading
        def run_schedule():
            while True:
                schedule.run_pending()
                time.sleep(30)

        t = threading.Thread(target=run_schedule, daemon=True)
        t.start()
        print(f"[TokenManager] Daily refresh scheduled at {refresh_time} IST")

    except ImportError:
        print("[TokenManager] schedule not installed — daily refresh disabled")
