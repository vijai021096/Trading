"""
Watchdog — monitors bot health and sends daily reports.

Runs as a separate container alongside the bot. Responsibilities:
  1. Check bot state file for staleness (no update = bot may be stuck)
  2. Send daily pre-market health notification via Telegram
  3. Send post-market daily P&L summary
  4. Verify token is valid before market open
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


STATE_DIR = Path(os.environ.get("STATE_DIR", "/tmp"))
EVENTS_LOG = STATE_DIR / "kite_bot_events.jsonl"
POSITION_FILE = STATE_DIR / "kite_bot_position.json"
TOKEN_CACHE = STATE_DIR / "kite_token_cache.json"


def _notify(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.info(f"[Watchdog] No Telegram config — message: {message}")
        return
    try:
        import httpx
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
    except Exception as e:
        logger.error(f"[Watchdog] Telegram send failed: {e}")


def _check_token() -> dict:
    """Check if we have a valid token for today."""
    if not TOKEN_CACHE.exists():
        return {"valid": False, "detail": "No token cache file"}
    try:
        data = json.loads(TOKEN_CACHE.read_text())
        if data.get("date") == date.today().isoformat():
            return {"valid": True, "detail": f"Token from {data.get('saved_at', '?')}"}
        return {"valid": False, "detail": f"Token from {data.get('date', '?')} (stale)"}
    except Exception as e:
        return {"valid": False, "detail": str(e)}


def _daily_summary() -> str:
    """Summarize today's trades from events log."""
    if not EVENTS_LOG.exists():
        return "No events log found"

    try:
        lines = EVENTS_LOG.read_text().strip().split("\n")
    except Exception:
        return "Could not read events"

    today = date.today().isoformat()
    trades = []
    for line in lines:
        try:
            e = json.loads(line)
            if e.get("event") == "TRADE_CLOSED" and e.get("ts", "").startswith(today):
                trades.append(e)
        except Exception:
            continue

    if not trades:
        return f"📊 {today}: No trades executed"

    total_pnl = sum(t.get("net_pnl", 0) for t in trades)
    wins = sum(1 for t in trades if t.get("net_pnl", 0) > 0)
    losses = len(trades) - wins

    lines_out = [f"📊 DAILY REPORT — {today}"]
    lines_out.append(f"Trades: {len(trades)} ({wins}W / {losses}L)")
    lines_out.append(f"P&L: {'+'if total_pnl>=0 else ''}₹{total_pnl:,.0f}")

    for t in trades:
        net = t.get("net_pnl", 0)
        sign = "+" if net >= 0 else ""
        lines_out.append(
            f"  {'✅' if net > 0 else '❌'} {t.get('strategy', '?')} "
            f"{t.get('direction', '?')} {sign}₹{net:,.0f} ({t.get('exit_reason', '?')})"
        )

    return "\n".join(lines_out)


def run():
    logger.info("[Watchdog] Starting watchdog service")
    logger.info(f"[Watchdog] State dir: {STATE_DIR}")

    last_premarket_date = None
    last_postmarket_date = None

    while True:
        try:
            now = datetime.now()
            today = now.date()
            weekday = now.weekday()

            # Skip weekends
            if weekday >= 5:
                time.sleep(300)
                continue

            hour_min = now.hour * 100 + now.minute

            # Pre-market check: 8:50-8:55 AM
            if 850 <= hour_min <= 855 and last_premarket_date != today:
                last_premarket_date = today
                token_info = _check_token()

                msg = f"🌅 PRE-MARKET CHECK — {today.strftime('%A %d %b')}\n"
                msg += f"Token: {'✅ Valid' if token_info['valid'] else '❌ INVALID — LOGIN NEEDED'}\n"
                msg += f"  {token_info['detail']}\n"

                # Check position state
                if POSITION_FILE.exists():
                    try:
                        pos = json.loads(POSITION_FILE.read_text())
                        state = pos.get("state", "IDLE")
                        msg += f"Position: {state}"
                        if state != "IDLE":
                            msg += f" ⚠️ {pos.get('symbol', '?')}"
                    except Exception:
                        msg += "Position: Could not read state file"
                else:
                    msg += "Position: IDLE (clean)"

                _notify(msg)
                logger.info(f"[Watchdog] Pre-market check sent")

            # Post-market report: 3:30-3:35 PM
            if 1530 <= hour_min <= 1535 and last_postmarket_date != today:
                last_postmarket_date = today
                summary = _daily_summary()
                _notify(summary)
                logger.info(f"[Watchdog] Post-market report sent")

            # Staleness check every 5 minutes during market hours
            if 915 <= hour_min <= 1515:
                if POSITION_FILE.exists():
                    age = time.time() - POSITION_FILE.stat().st_mtime
                    if age > 600:  # 10 minutes stale
                        logger.warning(f"[Watchdog] Position file stale ({age/60:.0f}min)")

        except Exception as e:
            logger.error(f"[Watchdog] Error: {e}")

        time.sleep(60)


if __name__ == "__main__":
    run()
