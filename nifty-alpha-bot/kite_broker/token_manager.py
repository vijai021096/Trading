"""
Zerodha Kite daily token refresh manager.

Kite requires a new access_token every day. Three modes:
  1. Dashboard API — user pastes token via web UI (recommended for cloud)
  2. TOTP automation (headless browser) — for fully automated servers
  3. Manual — user provides token via env var or CLI --token

Token refresh propagates to the running bot via a shared file + hot-reload.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

_STATE_DIR = Path(os.environ.get("STATE_DIR", "/tmp"))
TOKEN_CACHE = _STATE_DIR / "kite_token_cache.json"

_on_token_refresh: Optional[Callable[[str], None]] = None


def register_token_callback(fn: Callable[[str], None]) -> None:
    """Register a callback that gets called when token is refreshed."""
    global _on_token_refresh
    _on_token_refresh = fn


def save_token(access_token: str) -> None:
    data = {
        "access_token": access_token,
        "date": date.today().isoformat(),
        "saved_at": datetime.now().isoformat(),
    }
    TOKEN_CACHE.write_text(json.dumps(data))


def load_cached_token() -> Optional[str]:
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
    """Automated TOTP login using Playwright headless browser."""
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

            page.goto(login_url, wait_until="networkidle", timeout=30000)
            page.fill('input[type="text"]', user_id)
            page.fill('input[type="password"]', password)
            page.click('button[type="submit"]')
            page.wait_for_timeout(2000)

            try:
                page.fill('input[type="number"]', totp.now())
                page.click('button[type="submit"]')
                page.wait_for_timeout(3000)
            except Exception:
                try:
                    page.fill('input[label="External TOTP"]', totp.now())
                    page.click('button[type="submit"]')
                    page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"[TokenManager] TOTP fill failed: {e}")

            current_url = page.url
            if "request_token=" in current_url:
                request_token = current_url.split("request_token=")[1].split("&")[0]
            else:
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

    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=api_key)
        session = kite.generate_session(request_token, api_secret=api_secret)
        access_token = session["access_token"]
        save_token(access_token)

        if _on_token_refresh:
            _on_token_refresh(access_token)

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
    1. manual_token (CLI --token or dashboard API)
    2. ENV var KITE_ACCESS_TOKEN
    3. Cached token from today
    4. Automated TOTP refresh
    """
    if manual_token:
        save_token(manual_token)
        return manual_token

    env_token = os.environ.get("KITE_ACCESS_TOKEN", "")
    if env_token:
        cached = load_cached_token()
        if cached == env_token:
            return env_token
        save_token(env_token)
        return env_token

    cached = load_cached_token()
    if cached:
        return cached

    if totp_secret and user_id and password:
        print("[TokenManager] Attempting automated TOTP login...")
        token = get_token_automated(api_key, api_secret, user_id, password, totp_secret)
        if token:
            return token

    raise RuntimeError(
        "No valid Kite access token. Options:\n"
        "  1. Set KITE_ACCESS_TOKEN in .env\n"
        "  2. Use dashboard: POST /api/kite/token {token: ...}\n"
        "  3. CLI: python -m bot.main --token YOUR_TOKEN\n"
        "  4. Configure KITE_TOTP_SECRET for auto-login"
    )


def schedule_daily_refresh(
    api_key: str,
    api_secret: str,
    user_id: str,
    password: str,
    totp_secret: str,
    refresh_time: str = "08:55",
) -> None:
    """Schedule daily token refresh. Token propagates via callback + env + cache file."""
    try:
        import schedule

        def do_refresh():
            print(f"[TokenManager] Scheduled daily refresh starting...")
            token = get_token_automated(api_key, api_secret, user_id, password, totp_secret)
            if token:
                os.environ["KITE_ACCESS_TOKEN"] = token
                print(f"[TokenManager] Daily token refresh successful.")
            else:
                print("[TokenManager] Daily token refresh FAILED. Set token via dashboard.")

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
