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

EVENTS_LOG = Path("/tmp/kite_bot_events.jsonl")
POSITION_FILE = Path("/tmp/kite_bot_position.json")

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background task to poll events and broadcast
    import asyncio
    task = asyncio.create_task(broadcast_loop())
    yield
    task.cancel()


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

            # Broadcast position state
            pos = read_position()
            await manager.broadcast({
                "type": "POSITION_UPDATE",
                "position": pos,
                "timestamp": datetime.now().isoformat(),
            })
        except Exception:
            pass
        await asyncio.sleep(2)


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


def read_position() -> dict:
    if not POSITION_FILE.exists():
        return {"state": "IDLE"}
    try:
        return json.loads(POSITION_FILE.read_text())
    except Exception:
        return {"state": "UNKNOWN"}


def get_trades_from_events() -> List[dict]:
    events = read_all_events()
    return [e for e in events if e.get("event") == "TRADE_CLOSED"]


def daily_pnl_summary() -> dict:
    trades = get_trades_from_events()
    today = date.today().isoformat()
    today_trades = [t for t in trades if str(t.get("trade_date", t.get("entry_ts", "")))[:10] == today]
    total = sum(float(t.get("net_pnl", 0)) for t in today_trades)
    wins = sum(1 for t in today_trades if float(t.get("net_pnl", 0)) > 0)
    return {
        "date": today,
        "trades": len(today_trades),
        "wins": wins,
        "losses": len(today_trades) - wins,
        "net_pnl": round(total, 2),
        "win_rate": round(wins / len(today_trades) * 100, 1) if today_trades else 0.0,
    }


# ── REST endpoints ────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "NIFTY Alpha Bot API"}


@app.get("/api/status")
def status():
    pos = read_position()
    pnl = daily_pnl_summary()
    return {
        "position": pos,
        "daily_pnl": pnl,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/trades")
def trades(limit: int = 100, date_filter: Optional[str] = None):
    all_trades = get_trades_from_events()
    if date_filter:
        all_trades = [t for t in all_trades if str(t.get("trade_date", t.get("entry_ts", "")))[:10] == date_filter]
    return {"trades": all_trades[-limit:], "total": len(all_trades)}


@app.get("/api/trades/today")
def trades_today():
    today = date.today().isoformat()
    all_trades = get_trades_from_events()
    today_trades = [t for t in all_trades if str(t.get("trade_date", t.get("entry_ts", "")))[:10] == today]
    return {"trades": today_trades, "date": today}


@app.get("/api/pnl/daily")
def pnl_daily():
    return daily_pnl_summary()


@app.get("/api/pnl/summary")
def pnl_summary():
    trades = get_trades_from_events()
    total = sum(float(t.get("net_pnl", 0)) for t in trades)
    wins = sum(1 for t in trades if float(t.get("net_pnl", 0)) > 0)
    return {
        "total_trades": len(trades),
        "wins": wins,
        "losses": len(trades) - wins,
        "total_net_pnl": round(total, 2),
        "win_rate": round(wins / len(trades) * 100, 1) if trades else 0.0,
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
    HALT_FILE = Path("/tmp/kite_bot_halt.flag")
    HALT_FILE.write_text(datetime.now().isoformat())
    return {"status": "EMERGENCY_STOP_TRIGGERED", "timestamp": datetime.now().isoformat()}


@app.delete("/api/emergency-stop")
def clear_emergency_stop():
    HALT_FILE = Path("/tmp/kite_bot_halt.flag")
    if HALT_FILE.exists():
        HALT_FILE.unlink()
    return {"status": "CLEARED"}


@app.get("/api/strategy/config")
def get_config():
    try:
        from shared.config import settings
        return {
            "capital": settings.capital,
            "vix_max": settings.vix_max,
            "atr_sl_min_pct": settings.atr_sl_min_pct,
            "atr_sl_max_pct": settings.atr_sl_max_pct,
            "rr_min": settings.rr_min,
            "max_trades_per_day": settings.max_trades_per_day,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
            "paper_mode": settings.paper_mode,
            "orb_start": settings.orb_start,
            "orb_end": settings.orb_end,
            "trail_trigger_pct": settings.trail_trigger_pct,
            "break_even_trigger_pct": settings.break_even_trigger_pct,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/kite/token")
def set_kite_token(body: dict):
    """Accept manual Kite token refresh from dashboard."""
    token = body.get("access_token", "")
    if not token:
        raise HTTPException(400, "access_token required")
    os.environ["KITE_ACCESS_TOKEN"] = token
    from kite_broker.token_manager import save_token
    save_token(token)
    return {"status": "TOKEN_UPDATED", "timestamp": datetime.now().isoformat()}


@app.post("/api/backtest/run")
async def run_backtest_api(body: dict):
    """
    Trigger a backtest run. Returns results when complete.
    For long runs, use async task pattern.
    """
    months = body.get("months", 6)
    capital = body.get("capital", 100_000.0)
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _run_backtest_sync, months, capital)
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


def _run_backtest_sync(months: int, capital: float) -> dict:
    from backtest.data_downloader import download_nifty_spot, download_india_vix
    from backtest.backtest_engine import BacktestConfig, run_backtest
    nifty_df = download_nifty_spot(months=months)
    vix_df = download_india_vix(months=months)
    cfg = BacktestConfig(capital=capital)
    result = run_backtest(nifty_df, vix_df, cfg, verbose=False)
    # Remove equity curve from API response (too large)
    result["metrics"].pop("equity_curve", None)
    return result


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
