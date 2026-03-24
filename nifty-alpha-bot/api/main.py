"""
FastAPI backend — serves dashboard data and WebSocket live feed.
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.config import settings

_STATE_DIR = Path(os.environ.get("STATE_DIR", "/tmp"))
EVENTS_LOG = _STATE_DIR / "kite_bot_events.jsonl"
POSITION_FILE = _STATE_DIR / "kite_bot_position.json"

# ── WebSocket manager ─────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)


manager = ConnectionManager()


# ── App ───────────────────────────────────────────────────────────

def _run_startup_diagnostics() -> dict:
    """Run comprehensive startup checks and return results dict."""
    import importlib
    import sys as _sys
    diag: dict = {"checks": [], "passed": 0, "failed": 0, "warnings": 0}

    def _log(msg: str):
        print(msg, flush=True)

    def _check(name: str, ok: bool, detail: str = "", warn: bool = False):
        status = "PASS" if ok else ("WARN" if warn else "FAIL")
        diag["checks"].append({"name": name, "status": status, "detail": detail})
        if ok:
            diag["passed"] += 1
        elif warn:
            diag["warnings"] += 1
        else:
            diag["failed"] += 1
        tag = f"[{status}]"
        _log(f"  {tag:8s} {name}" + (f"  — {detail}" if detail else ""))

    _log("\n" + "=" * 60)
    _log("  NIFTY ALPHA BOT — STARTUP DIAGNOSTICS")
    _log("=" * 60)

    # 1. Config loaded
    _check("Config loaded", bool(settings), f"capital=₹{settings.capital:,.0f}")

    # 2. Kite API Key
    api_key = settings.kite_api_key
    _check("KITE_API_KEY", bool(api_key),
           f"{'...'+api_key[-4:] if api_key else 'MISSING'}")

    # 3. Kite API Secret
    api_secret = settings.kite_api_secret
    _check("KITE_API_SECRET", bool(api_secret),
           f"{'...'+api_secret[-4:] if api_secret else 'MISSING'}")

    # 4. kiteconnect importable
    try:
        importlib.import_module("kiteconnect")
        _check("kiteconnect package", True)
    except ImportError:
        _check("kiteconnect package", False, "pip install kiteconnect")

    # 5. Token cache
    token = ""
    try:
        from kite_broker.token_manager import load_cached_token
        token = load_cached_token() or ""
        _check("Token cache (today)", bool(token),
               f"{'saved' if token else 'no token for today'}", warn=not token)
    except Exception as e:
        _check("Token cache", False, str(e))

    # 6. Kite connection test (only if token exists)
    if token and api_key:
        try:
            from kiteconnect import KiteConnect
            k = KiteConnect(api_key=api_key)
            k.set_access_token(token)
            profile = k.profile()
            user_name = profile.get("user_name", "?")
            _check("Kite API connection", True, f"user={user_name}")
            global _kite_verified
            _kite_verified = True
        except Exception as e:
            err = str(e)[:60]
            _check("Kite API connection", False, err, warn=True)
    else:
        _check("Kite API connection", False, "skipped — no token", warn=True)

    # 7. State directory
    _check("State directory", _STATE_DIR.exists(), str(_STATE_DIR))

    # 8. Events log
    _check("Events log", True,
           f"{EVENTS_LOG} ({'exists' if EVENTS_LOG.exists() else 'will create'})")

    # 9. Position file
    _check("Position file", True,
           f"{'exists' if POSITION_FILE.exists() else 'idle — no active position'}")

    # 10. Risk state
    risk_file = _STATE_DIR / "kite_bot_risk_state.json"
    if risk_file.exists():
        try:
            rd = json.loads(risk_file.read_text())
            _check("Risk state", True,
                   f"capital=₹{rd.get('current_capital',0):,.0f} peak=₹{rd.get('peak_capital',0):,.0f}")
        except Exception:
            _check("Risk state", True, "exists but unreadable", warn=True)
    else:
        _check("Risk state", True, "fresh — no persisted state", warn=False)

    # 11. Shared modules
    for mod_name in ["shared.indicators", "shared.regime_detector", "shared.orb_engine",
                     "shared.vwap_reclaim_engine"]:
        try:
            importlib.import_module(mod_name)
            _check(f"Module: {mod_name.split('.')[-1]}", True)
        except Exception as e:
            _check(f"Module: {mod_name.split('.')[-1]}", False, str(e)[:50])

    # 12. Paper mode
    mode = "PAPER" if settings.paper_mode else "LIVE"
    _check(f"Trading mode: {mode}", True,
           f"lot_size={settings.lot_size}, max_lots={settings.max_lots}")

    # 13. Risk parameters
    daily_limit = settings.capital * settings.max_daily_loss_pct
    _check("Risk config", True,
           f"daily_limit=₹{daily_limit:,.0f}, drawdown_halt={settings.max_drawdown_pct}%, "
           f"risk/trade={settings.risk_per_trade_pct*100:.1f}%")

    # 14. Execution settings
    _check("Execution config", True,
           f"limit_orders={'ON' if settings.use_limit_orders else 'OFF'}, "
           f"SL-M={'ON' if settings.use_slm_exit else 'OFF'}, "
           f"buffer={settings.limit_price_buffer_pct*100:.1f}%")

    # Summary
    total = diag["passed"] + diag["failed"] + diag["warnings"]
    _log("-" * 60)
    summary = f"  {diag['passed']}/{total} passed"
    if diag["warnings"]:
        summary += f", {diag['warnings']} warnings"
    if diag["failed"]:
        summary += f", {diag['failed']} FAILED"
    _log(summary)
    _log("=" * 60 + "\n")

    return diag


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    diag = _run_startup_diagnostics()
    append_bot_event("SYSTEM_READY", {
        "message": "API server started — diagnostics complete",
        "paper_mode": settings.paper_mode,
        "capital": settings.capital,
        "kite_configured": bool(settings.kite_api_key),
        "checks_passed": diag["passed"],
        "checks_failed": diag["failed"],
        "checks_warnings": diag["warnings"],
        "checks": diag["checks"],
    })
    task = asyncio.create_task(broadcast_loop())
    hb_task = asyncio.create_task(heartbeat_loop())
    yield
    task.cancel()
    hb_task.cancel()


app = FastAPI(
    title="NIFTY Alpha Bot Dashboard API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Background broadcaster ────────────────────────────────────────

async def broadcast_loop():
    """Poll events log and broadcast new events to WS clients."""
    import asyncio
    last_size = 0
    while True:
        try:
            if EVENTS_LOG.exists():
                size = EVENTS_LOG.stat().st_size
                if size != last_size:
                    last_size = size
                    events = read_recent_events(10)
                    if events:
                        await manager.broadcast({
                            "type": "EVENTS_UPDATE",
                            "events": events,
                        })

            pos = read_position()
            await manager.broadcast({
                "type": "POSITION_UPDATE",
                "position": pos,
                "timestamp": datetime.now().isoformat(),
            })
        except Exception:
            pass
        await asyncio.sleep(2)


async def heartbeat_loop():
    """Emit a HEARTBEAT event every ~10s with full system state."""
    import asyncio
    while True:
        try:
            now = datetime.now()
            h, m = now.hour, now.minute

            # Market status
            is_market_day = now.weekday() < 5
            pre_market = is_market_day and 8 <= h < 9
            market_open = is_market_day and ((h == 9 and m >= 15) or (10 <= h <= 14) or (h == 15 and m <= 30))
            post_market = is_market_day and h == 15 and m > 30
            market_closed = not market_open

            if market_open:
                market_status = "OPEN"
            elif pre_market:
                market_status = "PRE_MARKET"
            elif post_market:
                market_status = "POST_MARKET"
            elif not is_market_day:
                market_status = "WEEKEND"
            else:
                market_status = "CLOSED"

            # Kite connection
            kite_status = _kite_connection_status()

            # Position state
            pos = read_position()
            pos_state = pos.get("state", "IDLE")

            # Risk state
            risk_file = _STATE_DIR / "kite_bot_risk_state.json"
            risk_data = {}
            if risk_file.exists():
                try:
                    risk_data = json.loads(risk_file.read_text())
                except Exception:
                    pass

            # Strategy state
            strat_file = _STATE_DIR / "kite_bot_strategy_state.json"
            strat_data = {"orb_enabled": True, "vwap_enabled": True}
            if strat_file.exists():
                try:
                    strat_data = json.loads(strat_file.read_text())
                except Exception:
                    pass

            # Today's trades
            today_str = now.strftime("%Y-%m-%d")
            all_trades = get_trades_from_events()
            today_trades = [t for t in all_trades if _trade_date(t) == today_str]
            today_pnl = sum(t.get("net_pnl", 0) for t in today_trades)

            # Halt flag
            halt_active = (_STATE_DIR / "kite_bot_halt.flag").exists()

            # Bot process check
            bot_running = POSITION_FILE.exists() and pos_state != "IDLE"

            # Nifty price (from cache, not a live call)
            nifty_price = None
            try:
                token = (os.environ.get("KITE_ACCESS_TOKEN") or "").strip()
                if not token:
                    from kite_broker.token_manager import load_cached_token
                    token = load_cached_token() or ""
                if token and settings.kite_api_key:
                    from kiteconnect import KiteConnect
                    k = KiteConnect(api_key=settings.kite_api_key)
                    k.set_access_token(token)
                    q = k.ltp(["NSE:NIFTY 50"])
                    nifty_price = q.get("NSE:NIFTY 50", {}).get("last_price")
            except Exception:
                pass

            # Decide "thinking" message
            if halt_active:
                thinking = "HALTED — emergency stop active"
            elif market_status == "WEEKEND":
                thinking = "Weekend — markets closed, resting"
            elif market_status == "CLOSED":
                thinking = "Markets closed — waiting for next session"
            elif market_status == "PRE_MARKET":
                thinking = "Pre-market — warming up, checking token & instruments"
            elif market_status == "POST_MARKET":
                thinking = f"Post-market — today: {len(today_trades)} trades, P&L ₹{today_pnl:,.0f}"
            elif pos_state == "ACTIVE":
                sym = pos.get("symbol", "?")
                entry = pos.get("entry_price", 0)
                thinking = f"IN TRADE — {sym} entry ₹{entry:.1f}, managing position"
            elif len(today_trades) >= settings.max_trades_per_day:
                thinking = f"Max trades reached ({len(today_trades)}/{settings.max_trades_per_day}) — done for today"
            elif today_pnl <= -(settings.capital * settings.max_daily_loss_pct):
                thinking = f"Daily loss limit hit (₹{today_pnl:,.0f}) — halted"
            else:
                if settings.trading_engine.strip().lower() == "daily_adaptive":
                    thinking = (
                        f"Daily adaptive — entry window {settings.daily_adaptive_window_start}–"
                        f"{settings.daily_adaptive_window_end} IST | "
                        f"{len(today_trades)}/{settings.max_trades_per_day} trades | "
                        f"filter={settings.daily_strategy_filter}"
                    )
                else:
                    strategies_on = []
                    if strat_data.get("orb_enabled"):
                        strategies_on.append("ORB")
                    if strat_data.get("vwap_enabled"):
                        strategies_on.append("VWAP")
                    strat_str = "+".join(strategies_on) if strategies_on else "none"
                    thinking = (
                        f"Scanning for entry — {strat_str} active, "
                        f"{len(today_trades)}/{settings.max_trades_per_day} trades used"
                    )

            # Market intelligence (trend + regime from bot events)
            mkt_state = get_latest_market_state()
            trend_ev = mkt_state.get("trend") or {}
            regime_ev = mkt_state.get("regime") or {}

            # Latest scan cycle data
            scan_data = _get_latest_event("SCAN_CYCLE") or {}

            payload = {
                "state": pos_state,
                "market_status": market_status,
                "market_open": market_open,
                "thinking": thinking,
                "nifty_price": nifty_price,
                "kite_connected": kite_status.get("kite_connected", False),
                "kite_token_saved": kite_status.get("kite_token_saved", False),
                "trades_today": len(today_trades),
                "max_trades": settings.max_trades_per_day,
                "daily_pnl": round(today_pnl, 2),
                "current_capital": risk_data.get("current_capital", settings.capital),
                "starting_capital": settings.capital,
                "peak_capital": risk_data.get("peak_capital", settings.capital),
                "drawdown_pct": round(
                    ((risk_data.get("peak_capital", settings.capital) - risk_data.get("current_capital", settings.capital))
                     / max(risk_data.get("peak_capital", settings.capital), 1)) * 100, 1
                ) if risk_data else 0.0,
                "max_drawdown_pct": settings.max_drawdown_pct,
                "halt_active": halt_active,
                "strategies": strat_data,
                "paper_mode": settings.paper_mode,
                "trading_engine": settings.trading_engine,
                "daily_strategy_filter": settings.daily_strategy_filter,
                "consecutive_losses": risk_data.get("consecutive_losses", 0),
                "risk_per_trade_pct": settings.risk_per_trade_pct,
                "max_daily_loss_pct": settings.max_daily_loss_pct,
                # Market intelligence fields
                "trend_state": trend_ev.get("state"),
                "trend_direction": trend_ev.get("direction"),
                "trend_conviction": trend_ev.get("conviction"),
                "risk_multiplier": trend_ev.get("risk_multiplier"),
                "strategy_priority": trend_ev.get("strategy_priority", []),
                "trend_scores": trend_ev.get("scores", {}),
                "regime": regime_ev.get("regime"),
                "regime_atr_ratio": regime_ev.get("atr_ratio"),
                "regime_adx": regime_ev.get("adx_proxy"),
                "regime_vix": regime_ev.get("vix"),
                "regime_rsi": regime_ev.get("rsi"),
                # Scan cycle intelligence
                "last_scan": {
                    "strategies_evaluated": scan_data.get("strategies_evaluated", 0),
                    "signals_detected": scan_data.get("signals_detected", 0),
                    "candidates": scan_data.get("candidates", []),
                    "scans": scan_data.get("scans", []),
                } if scan_data else None,
                # Position details (if active)
                "position": pos if pos_state == "ACTIVE" else None,
            }

            append_bot_event("HEARTBEAT", payload)

        except Exception:
            pass
        await asyncio.sleep(10)


def _get_latest_event(event_type: str) -> Optional[dict]:
    """Get the most recent event of a given type from the events log."""
    if not EVENTS_LOG.exists():
        return None
    try:
        lines = EVENTS_LOG.read_text().strip().split("\n")
        for line in reversed(lines[-500:]):
            try:
                ev = json.loads(line)
                if ev.get("event") == event_type:
                    return ev
            except Exception:
                pass
    except Exception:
        pass
    return None


# ── Helpers ───────────────────────────────────────────────────────

def read_recent_events(n: int = 50) -> List[dict]:
    if not EVENTS_LOG.exists():
        return []
    try:
        lines = EVENTS_LOG.read_text().strip().split("\n")
        events = []
        for line in lines[-n:]:
            try:
                events.append(json.loads(line))
            except Exception:
                pass
        return list(reversed(events))
    except Exception:
        return []


def read_all_events() -> List[dict]:
    return read_recent_events(10000)


def append_bot_event(event_type: str, payload: dict) -> None:
    """Append one line to kite_bot_events.jsonl (same format as trading bot)."""
    entry = {"ts": datetime.now().isoformat(), "event": event_type, **payload}
    try:
        EVENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(EVENTS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


_kite_verified = False  # set True after explicit verify succeeds


def _verify_kite_token(token: str) -> tuple:
    """Network call to Kite — only use for explicit auth actions, not on every page load."""
    global _kite_verified
    from shared.config import settings
    if not settings.kite_api_key:
        return False, "KITE_API_KEY missing in .env"
    try:
        from kiteconnect import KiteConnect
        k = KiteConnect(api_key=settings.kite_api_key)
        k.set_access_token(token)
        k.profile()
        _kite_verified = True
        return True, ""
    except Exception as e:
        _kite_verified = False
        return False, str(e)


def _kite_connection_status() -> dict:
    """Fast check — no network call. Token presence + last verify result."""
    from shared.config import settings

    api_ok = bool(settings.kite_api_key and settings.kite_api_secret)
    token = (os.environ.get("KITE_ACCESS_TOKEN") or "").strip()
    if not token:
        try:
            from kite_broker.token_manager import load_cached_token
            token = load_cached_token() or ""
        except Exception:
            token = ""
    token_saved = bool(token)
    return {
        "kite_api_configured": api_ok,
        "kite_token_saved": token_saved,
        "kite_connected": token_saved and _kite_verified,
    }


def read_position() -> dict:
    if not POSITION_FILE.exists():
        return {"state": "IDLE"}
    try:
        return json.loads(POSITION_FILE.read_text())
    except Exception:
        return {"state": "UNKNOWN"}


def _trade_date(t: dict) -> str:
    """Extract YYYY-MM-DD from a TRADE_CLOSED event regardless of field name."""
    for key in ("trade_date", "entry_ts", "entry_time", "ts"):
        val = t.get(key, "")
        if val:
            return str(val)[:10]
    return ""


def _normalize_trade(t: dict) -> dict:
    """Add trade_date and entry_ts fields the dashboard expects, derived from existing fields."""
    out = dict(t)
    # trade_date: YYYY-MM-DD
    if not out.get("trade_date"):
        out["trade_date"] = _trade_date(t)
    # entry_ts: ISO timestamp string for entry time
    if not out.get("entry_ts"):
        out["entry_ts"] = t.get("entry_time") or t.get("ts") or ""
    return out


def get_trades_from_events() -> List[dict]:
    events = read_all_events()
    return [_normalize_trade(e) for e in events if e.get("event") == "TRADE_CLOSED"]


def daily_pnl_summary() -> dict:
    trades = get_trades_from_events()
    today = date.today().isoformat()
    today_trades = [t for t in trades if _trade_date(t) == today]
    total = sum(float(t.get("net_pnl", 0)) for t in today_trades)
    # Only closed (non-zero pnl) trades count for win/loss — exclude open/breakeven
    closed = [t for t in today_trades if abs(float(t.get("net_pnl", 0))) > 0.01]
    wins = sum(1 for t in closed if float(t.get("net_pnl", 0)) > 0)
    losses = len(closed) - wins
    return {
        "date": today,
        "trades": len(today_trades),
        "wins": wins,
        "losses": losses,
        "net_pnl": round(total, 2),
        "win_rate": round(wins / len(closed) * 100, 1) if closed else 0.0,
    }


# ── REST endpoints ────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "NIFTY Alpha Bot API"}


@app.get("/api/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/api/bot-status")
def bot_status_rest():
    """REST endpoint returning the latest full bot status (same as WebSocket push).
    Reads the most recent HEARTBEAT event which contains paper_mode, capital,
    kite_connected, trading_engine, skip_reasons, etc."""
    ev = _get_latest_event("HEARTBEAT")
    if ev:
        return ev
    # Fallback when bot hasn't started yet
    return {
        "state": "IDLE",
        "market_open": False,
        "paper_mode": settings.paper_mode,
        "starting_capital": settings.capital,
        "current_capital": settings.capital,
        "peak_capital": settings.capital,
        "drawdown_pct": 0.0,
        "trading_engine": settings.trading_engine,
        "max_trades": settings.max_trades_per_day,
        "trades_today": 0,
        "daily_pnl": 0.0,
        "kite_connected": False,
        "halt_active": False,
        "consecutive_losses": 0,
        "skip_reasons": [],
    }


@app.get("/api/status")
def status():
    pos = read_position()
    pnl = daily_pnl_summary()
    return {
        "position": pos,
        "daily_pnl": pnl,
        "timestamp": datetime.now().isoformat(),
        "trading_engine": settings.trading_engine,
        "daily_strategy_filter": settings.daily_strategy_filter,
        **_kite_connection_status(),
    }


@app.get("/api/daily-watch")
def daily_watch():
    """
    Live daily-adaptive evaluation (parity with daily backtest): regime, planned legs,
    breakout watch levels. Uses Kite daily history + live VIX when token present; else yfinance cache.
    """
    import pandas as pd

    token = (os.environ.get("KITE_ACCESS_TOKEN") or "").strip()
    if not token:
        try:
            from kite_broker.token_manager import load_cached_token
            token = load_cached_token() or ""
        except Exception:
            token = ""

    vix = 14.0
    df = None
    if token and settings.kite_api_key:
        try:
            from kite_broker.client import KiteClient
            from datetime import timedelta

            c = KiteClient.from_token(settings.kite_api_key, token)
            vix_q = c.get_quote("INDIA VIX", "NSE")
            if vix_q and vix_q > 0:
                vix = float(vix_q)
            tid = c.get_nifty_token()
            if tid:
                to_dt = datetime.now()
                from_dt = to_dt - timedelta(days=520)
                raw = c.get_candles(tid, from_dt, to_dt, "day")
                if raw:
                    df = pd.DataFrame(raw)
        except Exception:
            pass

    if df is None or len(df) < 60:
        try:
            from backtest.data_downloader import download_nifty_daily

            df = download_nifty_daily(months=24, force_refresh=False)
        except Exception as e:
            return {"ok": False, "error": f"no_daily_data: {e}"}

    cap = float(settings.capital)
    peak = float(settings.capital)
    cons = 0
    risk_file = _STATE_DIR / "kite_bot_risk_state.json"
    if risk_file.exists():
        try:
            rd = json.loads(risk_file.read_text())
            cap = float(rd.get("current_capital", cap))
            peak = float(rd.get("peak_capital", peak))
            cons = int(rd.get("consecutive_losses", 0))
        except Exception:
            pass

    try:
        from backtest.daily_backtest_engine import evaluate_live_daily_adaptive
        from bot.daily_adaptive_support import daily_backtest_config_from_settings, load_anchor_ym

        dcfg = daily_backtest_config_from_settings(settings)
        anchor = load_anchor_ym()
        out = evaluate_live_daily_adaptive(
            df,
            vix,
            dcfg,
            strategy_filter=settings.daily_strategy_filter,
            drop_incomplete_today=True,
            anchor_ym=anchor,
            capital=cap,
            peak_equity=peak,
            consecutive_losses=cons,
        )
        out["trading_engine"] = settings.trading_engine
        out["daily_strategy_filter"] = settings.daily_strategy_filter
        out["anchor_ym"] = list(anchor) if anchor else None
        out["window"] = {
            "start": settings.daily_adaptive_window_start,
            "end": settings.daily_adaptive_window_end,
        }
        return out
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/trades")
def trades(limit: int = 100, date_filter: Optional[str] = None):
    all_trades = get_trades_from_events()
    if date_filter:
        all_trades = [t for t in all_trades if _trade_date(t) == date_filter]
    return {"trades": all_trades[-limit:], "total": len(all_trades)}


@app.get("/api/trades/today")
def trades_today():
    today = date.today().isoformat()
    all_trades = get_trades_from_events()
    today_trades = [t for t in all_trades if _trade_date(t) == today]
    return {"trades": today_trades, "date": today}


@app.get("/api/slippage/sl")
def sl_slippage_stats():
    """SL slippage report: shows planned vs actual SL fill for every SL_HIT trade."""
    trades = get_trades_from_events()
    sl_trades = [t for t in trades if t.get("exit_reason") == "SL_HIT" and "sl_trigger_price" in t]
    slm_events = [e for e in read_all_events() if e.get("event") == "SLM_EXECUTED"]

    items = []
    for t in sl_trades:
        items.append({
            "date": _trade_date(t),
            "symbol": t.get("symbol", ""),
            "trigger_price": t.get("sl_trigger_price"),
            "fill_price": t.get("sl_fill_price"),
            "slippage": t.get("sl_slippage"),
            "slippage_pct": t.get("sl_slippage_pct"),
            "extra_loss": t.get("sl_extra_loss"),
        })

    total_extra_loss = sum(i["extra_loss"] or 0 for i in items)
    avg_slip_pct = (
        sum(abs(i["slippage_pct"] or 0) for i in items) / len(items) if items else 0
    )
    worst = max(items, key=lambda x: abs(x["slippage_pct"] or 0)) if items else None

    return {
        "total_sl_trades": len(items),
        "total_extra_loss": round(total_extra_loss, 2),
        "avg_slippage_pct": round(avg_slip_pct, 3),
        "worst_slip": worst,
        "trades": items,
    }


@app.get("/api/pnl/daily")
def pnl_daily():
    return daily_pnl_summary()


@app.get("/api/pnl/summary")
def pnl_summary():
    trades = get_trades_from_events()
    total = sum(float(t.get("net_pnl", 0)) for t in trades)
    closed = [t for t in trades if abs(float(t.get("net_pnl", 0))) > 0.01]
    wins = sum(1 for t in closed if float(t.get("net_pnl", 0)) > 0)
    losses = len(closed) - wins
    return {
        "total_trades": len(trades),
        "wins": wins,
        "losses": losses,
        "total_net_pnl": round(total, 2),
        "win_rate": round(wins / len(closed) * 100, 1) if closed else 0.0,
        "daily": daily_pnl_summary(),
    }


@app.get("/api/events")
def events(limit: int = 50):
    return {"events": read_recent_events(limit)}


@app.get("/api/position")
def position():
    return read_position()


@app.post("/api/emergency-stop")
def emergency_stop():
    """Trigger emergency stop — write a halt file the bot polls."""
    halt_file = _STATE_DIR / "kite_bot_halt.flag"
    halt_file.write_text(datetime.now().isoformat())
    return {"status": "EMERGENCY_STOP_TRIGGERED", "timestamp": datetime.now().isoformat()}


@app.delete("/api/emergency-stop")
def clear_emergency_stop():
    halt_file = _STATE_DIR / "kite_bot_halt.flag"
    if halt_file.exists():
        halt_file.unlink()
    return {"status": "CLEARED"}


@app.get("/api/strategy/config")
def get_config():
    try:
        from shared.trend_detector import (
            SL_TARGET_BY_STRATEGY, STRATEGY_PRIORITY_BY_TREND,
            STRATEGY_BACKTEST_WR, STRATEGY_BACKTEST_PF,
        )
        return {
            "bot_version": "v3.1.0",
            "capital": settings.capital,
            "lot_size": settings.lot_size,
            "vix_max": settings.vix_max,
            "atr_sl_min_pct": settings.atr_sl_min_pct,
            "atr_sl_max_pct": settings.atr_sl_max_pct,
            "rr_min": settings.rr_min,
            "max_trades_per_day": settings.max_trades_per_day,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
            "max_daily_loss_hard": settings.max_daily_loss_hard,
            "max_drawdown_pct": settings.max_drawdown_pct,
            "risk_per_trade_pct": settings.risk_per_trade_pct,
            "paper_mode": settings.paper_mode,
            "orb_start": settings.orb_start,
            "orb_end": settings.orb_end,
            "entry_window_close": settings.entry_window_close,
            "reclaim_window_start": settings.reclaim_window_start,
            "reclaim_window_end": settings.reclaim_window_end,
            "ema_pullback_window_start": settings.ema_pullback_window_start,
            "ema_pullback_window_end": settings.ema_pullback_window_end,
            "momentum_breakout_window_start": settings.momentum_breakout_window_start,
            "momentum_breakout_window_end": settings.momentum_breakout_window_end,
            "trail_trigger_pct": settings.trail_trigger_pct,
            "break_even_trigger_pct": settings.break_even_trigger_pct,
            "use_limit_orders": settings.use_limit_orders,
            "use_slm_exit": settings.use_slm_exit,
            "limit_price_buffer_pct": settings.limit_price_buffer_pct,
            "trading_engine": settings.trading_engine,
            "daily_strategy_filter": settings.daily_strategy_filter,
            "nifty_option_lot_size": settings.nifty_option_lot_size,
            "daily_base_lots": settings.daily_base_lots,
            "daily_adaptive_window_start": settings.daily_adaptive_window_start,
            "daily_adaptive_window_end": settings.daily_adaptive_window_end,
            "sl_target_by_strategy": {
                k: {"sl_pct": v[0], "target_pct": v[1]} for k, v in SL_TARGET_BY_STRATEGY.items()
            },
            "strategy_priority_by_trend": {
                k.value if hasattr(k, "value") else k: v
                for k, v in STRATEGY_PRIORITY_BY_TREND.items()
            },
            "backtest_stats": {
                s: {"win_rate": STRATEGY_BACKTEST_WR.get(s, 0), "profit_factor": STRATEGY_BACKTEST_PF.get(s, 0)}
                for s in SL_TARGET_BY_STRATEGY
            },
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/kite/token")
def set_kite_token(body: dict):
    """Accept manual Kite token refresh from dashboard."""
    token = body.get("access_token", "")
    if not token:
        raise HTTPException(400, "access_token required")
    ok, detail = _verify_kite_token(token)
    if not ok:
        raise HTTPException(401, f"Invalid token: {detail}")
    os.environ["KITE_ACCESS_TOKEN"] = token
    from kite_broker.token_manager import save_token
    save_token(token)
    append_bot_event("KITE_AUTH", {"method": "manual_paste", "message": "Access token saved and verified"})
    return {"status": "TOKEN_UPDATED", "timestamp": datetime.now().isoformat(), "kite_connected": True}


@app.get("/api/kite/verify")
def verify_kite():
    """Explicitly test if the saved Kite token is valid (calls profile())."""
    token = (os.environ.get("KITE_ACCESS_TOKEN") or "").strip()
    if not token:
        try:
            from kite_broker.token_manager import load_cached_token
            token = load_cached_token() or ""
        except Exception:
            token = ""
    if not token:
        return {"kite_connected": False, "error": "No token saved"}
    ok, detail = _verify_kite_token(token)
    return {"kite_connected": ok, "error": detail if not ok else None}


@app.get("/api/nifty/quote")
def nifty_quote():
    """Get live NIFTY 50 price from Kite. Falls back gracefully if not connected."""
    token = (os.environ.get("KITE_ACCESS_TOKEN") or "").strip()
    if not token:
        try:
            from kite_broker.token_manager import load_cached_token
            token = load_cached_token() or ""
        except Exception:
            token = ""
    if not token:
        return {"price": None, "change": None, "change_pct": None, "error": "No token"}
    from shared.config import settings
    try:
        from kiteconnect import KiteConnect
        k = KiteConnect(api_key=settings.kite_api_key)
        k.set_access_token(token)
        q = k.quote(["NSE:NIFTY 50"])
        d = q.get("NSE:NIFTY 50", {})
        ltp = d.get("last_price", 0)
        ohlc = d.get("ohlc", {})
        prev_close = ohlc.get("close", ltp)
        change = ltp - prev_close if prev_close else 0
        change_pct = (change / prev_close * 100) if prev_close else 0
        return {
            "price": ltp,
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "open": ohlc.get("open"),
            "high": ohlc.get("high"),
            "low": ohlc.get("low"),
            "close": prev_close,
        }
    except Exception as e:
        return {"price": None, "error": str(e)}


@app.get("/api/kite/auth-url")
def kite_auth_url():
    """Return the Kite Connect login URL for OAuth flow."""
    from shared.config import settings
    if not settings.kite_api_key:
        raise HTTPException(400, "KITE_API_KEY not configured in .env")
    url = f"https://kite.trade/connect/login?api_key={settings.kite_api_key}&v=3"
    return {"url": url, "api_key": settings.kite_api_key}


@app.get("/callback")
@app.get("/api/kite/callback")
def kite_callback(request_token: str = "", status: str = "", type: str = "", action: str = ""):
    """
    Kite OAuth callback — exchanges request_token for access_token.
    After Kite login, browser redirects here with ?request_token=XXX&status=success.
    Returns an HTML page that auto-closes and notifies the parent window.
    """
    from fastapi.responses import HTMLResponse
    import html as html_module

    if status != "success" or not request_token:
        append_bot_event("KITE_AUTH", {"method": "oauth", "message": "Kite redirect missing request_token", "success": False})
        fail_msg = json.dumps({"type": "KITE_AUTH_FAIL", "error": "Kite did not return request_token"})
        html = f"""<html><body><h2>Authentication failed</h2>
        <p>Kite did not return a valid token.</p>
        <script>
          if (window.opener) {{ window.opener.postMessage({fail_msg}, '*'); }}
          setTimeout(() => window.close(), 3000);
        </script></body></html>"""
        return HTMLResponse(html)

    from shared.config import settings
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=settings.kite_api_key)
        session = kite.generate_session(request_token, api_secret=settings.kite_api_secret)
        access_token = session["access_token"]

        os.environ["KITE_ACCESS_TOKEN"] = access_token
        from kite_broker.token_manager import save_token
        save_token(access_token)
        append_bot_event("KITE_AUTH", {"method": "oauth", "message": "Access token saved via Kite login popup", "success": True})

        ok_msg = json.dumps({"type": "KITE_AUTH_OK", "token_prefix": access_token[:8] + "..."})
        html = f"""<html><body style="font-family:system-ui;text-align:center;padding:60px;background:#0d1117;color:#c9d1d9">
        <h2 style="color:#3fb950">Authentication Successful</h2>
        <p>Token has been saved. This window will close automatically.</p>
        <script>
          if (window.opener) {{ window.opener.postMessage({ok_msg}, '*'); }}
          setTimeout(() => window.close(), 2000);
        </script></body></html>"""
        return HTMLResponse(html)

    except Exception as e:
        err_txt = str(e)
        append_bot_event("KITE_AUTH", {"method": "oauth", "message": "Token exchange failed", "success": False, "error": err_txt})
        fail_msg = json.dumps({"type": "KITE_AUTH_FAIL", "error": err_txt})
        esc = html_module.escape(err_txt)
        html = f"""<html><body style="font-family:system-ui;text-align:center;padding:60px;background:#0d1117;color:#c9d1d9">
        <h2 style="color:#f85149">Token Exchange Failed</h2>
        <p>{esc}</p>
        <script>
          if (window.opener) {{ window.opener.postMessage({fail_msg}, '*'); }}
          setTimeout(() => window.close(), 5000);
        </script></body></html>"""
        return HTMLResponse(html)


@app.post("/api/kite/auto-auth")
def auto_auth_kite():
    """Trigger automated TOTP login via Playwright headless browser."""
    from shared.config import settings
    if not settings.kite_totp_secret:
        raise HTTPException(400, "KITE_TOTP_SECRET not configured in .env")
    from kite_broker.token_manager import get_token_automated
    token = get_token_automated(
        api_key=settings.kite_api_key,
        api_secret=settings.kite_api_secret,
        user_id=settings.kite_user_id,
        password=settings.kite_user_password,
        totp_secret=settings.kite_totp_secret,
    )
    if not token:
        raise HTTPException(500, "Auto-auth failed — check TOTP secret and credentials")
    os.environ["KITE_ACCESS_TOKEN"] = token
    append_bot_event("KITE_AUTH", {"method": "totp_auto", "message": "Access token via server TOTP automation", "success": True})
    return {"status": "AUTO_AUTH_SUCCESS", "message": "Token refreshed via TOTP automation", "timestamp": datetime.now().isoformat()}


@app.post("/api/backtest/run")
@app.post("/api/backtest")
async def run_backtest_api(body: dict):
    """
    Trigger a backtest run. Accepts strategy, start_date, end_date, months, capital.
    """
    strategy = body.get("strategy", "BOTH")
    months = body.get("months", 6)
    capital = body.get("capital", 100_000.0)
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, _run_backtest_sync, months, capital, strategy, start_date, end_date
        )
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, str(e))


def _run_backtest_sync(months: int, capital: float, strategy: str = "BOTH",
                       start_date_str: Optional[str] = None,
                       end_date_str: Optional[str] = None) -> dict:
    from backtest.data_downloader import download_nifty_spot, download_nifty_daily, download_india_vix
    from backtest.backtest_engine import BacktestConfig, run_backtest
    from backtest.daily_backtest_engine import DailyBacktestConfig, run_daily_backtest
    from datetime import date as date_cls

    sd = None
    ed = None
    if start_date_str:
        sd = date_cls.fromisoformat(start_date_str)
    if end_date_str:
        ed = date_cls.fromisoformat(end_date_str)

    if sd and ed:
        diff_months = max(1, ((ed.year - sd.year) * 12 + ed.month - sd.month) + 1)
    else:
        diff_months = months

    vix_df = download_india_vix(months=max(diff_months, 24))

    use_daily = diff_months > 2

    if use_daily:
        nifty_df = download_nifty_daily(months=diff_months, force_refresh=True)
        cfg = DailyBacktestConfig(capital=capital)
        result = run_daily_backtest(nifty_df, vix_df, cfg, start_date=sd, end_date=ed, verbose=True, strategy_filter=strategy)
    else:
        nifty_df = download_nifty_spot(months=diff_months)
        cfg = BacktestConfig(capital=capital)
        if strategy == "ORB":
            cfg.enable_vwap_reclaim = False
        elif strategy == "VWAP":
            cfg.enable_vwap_reclaim = True
        result = run_backtest(nifty_df, vix_df, cfg, start_date=sd, end_date=ed, verbose=False)

    eq = result["metrics"].get("equity_curve", [])
    trades_list = result.get("trades", [])

    # Build equity curve with dates from trades
    eq_with_dates = []
    if eq and trades_list:
        eq_with_dates.append({"date": "Start", "equity": eq[0]})
        for i, t in enumerate(trades_list):
            date_str = _trade_date(t)
            if i + 1 < len(eq):
                eq_with_dates.append({"date": date_str, "equity": eq[i + 1]})
        if len(eq) > len(trades_list) + 1:
            eq_with_dates.append({"date": "End", "equity": eq[-1]})
    elif eq:
        eq_with_dates = [{"date": str(i), "equity": v} for i, v in enumerate(eq)]

    if len(eq_with_dates) > 500:
        step = max(1, len(eq_with_dates) // 300)
        eq_with_dates = eq_with_dates[::step] + [eq_with_dates[-1]]
    result["equity_curve"] = eq_with_dates

    monthly = result["metrics"].get("monthly_breakdown", [])
    result["monthly"] = [{"month": m["month"], "return": m["net_pnl"], **m} for m in monthly]

    for t in trades_list:
        for k, v in list(t.items()):
            if hasattr(v, "isoformat"):
                t[k] = v.isoformat()
            elif isinstance(v, float) and (v != v):
                t[k] = 0

    return result


# ── Logs endpoint — full event log with scan details ──────────
@app.get("/api/logs")
def get_logs(limit: int = 500, event_type: Optional[str] = None):
    """Return detailed bot logs for the Logs panel."""
    events = read_all_events()
    if event_type:
        events = [e for e in events if e.get("event") == event_type]
    return {"logs": events[:limit], "total": len(events)}


# ── Market state helper ───────────────────────────────────────

def get_latest_market_state() -> dict:
    """
    Reads the most recent TREND_DETECTED/TREND_SHIFTED and REGIME_DETECTED events
    from the events log and returns a combined market-state dict for the dashboard.
    """
    if not EVENTS_LOG.exists():
        return {"trend": None, "regime": None}
    try:
        lines = EVENTS_LOG.read_text().strip().split("\n")
        trend_ev: Optional[dict] = None
        regime_ev: Optional[dict] = None
        for line in reversed(lines[-1000:]):
            try:
                ev = json.loads(line)
                etype = ev.get("event", "")
                if trend_ev is None and etype in ("TREND_DETECTED", "TREND_SHIFTED"):
                    trend_ev = ev
                if regime_ev is None and etype == "REGIME_DETECTED":
                    regime_ev = ev
                if trend_ev is not None and regime_ev is not None:
                    break
            except Exception:
                pass
        return {"trend": trend_ev, "regime": regime_ev}
    except Exception:
        return {"trend": None, "regime": None}


@app.get("/api/market-state")
def market_state_endpoint():
    """Return current trend state, conviction, regime, risk multiplier for the dashboard."""
    return get_latest_market_state()


# ── Strategy toggle ───────────────────────────────────────────
STRATEGY_STATE_FILE = _STATE_DIR / "kite_bot_strategy_state.json"

_STRATEGY_DEFAULTS = {
    "orb_enabled":               True,
    "relaxed_orb_enabled":       True,
    "momentum_breakout_enabled": True,
    "ema_pullback_enabled":      True,
    "vwap_reclaim_enabled":      True,
    "quality_filter_enabled":    True,
    "choppy_filter_enabled":     True,
    "htf_filter_enabled":        True,
}

@app.get("/api/strategy/state")
def get_strategy_state():
    state = dict(_STRATEGY_DEFAULTS)
    if STRATEGY_STATE_FILE.exists():
        try:
            saved = json.loads(STRATEGY_STATE_FILE.read_text())
            state.update(saved)
        except Exception:
            pass
    return state

@app.post("/api/strategy/toggle")
def toggle_strategy(body: dict):
    state = get_strategy_state()
    for key in _STRATEGY_DEFAULTS:
        if key in body:
            state[key] = bool(body[key])
    STRATEGY_STATE_FILE.write_text(json.dumps(state))
    return state


# ── WebSocket ─────────────────────────────────────────────────────

@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial state on connect
        pos = read_position()
        pnl = daily_pnl_summary()
        await websocket.send_json({
            "type": "INIT",
            "position": pos,
            "daily_pnl": pnl,
            "events": read_recent_events(20),
        })
        while True:
            # Keep alive — receive ping from client
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
