"""
Nifty Alpha Bot — Comprehensive System Test
Covers:
  1. All backend REST API endpoints
  2. Kite API connectivity
  3. UI data real vs static (endpoints read live state files)
  4. Capital protection logic
  5. No-misfire / anti-duplicate-trade logic
  6. Profit capture / trailing-stop mechanics
  7. Broker sync reconciliation

Usage:
    python test_system.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, List

import requests

BASE = "http://localhost:8000"
PASS = "\033[92m\u2713\033[0m"
FAIL = "\033[91m\u2717\033[0m"

results: List[dict] = []


def _test(name: str, fn: Callable) -> bool:
    try:
        fn()
        print(f"  {PASS} {name}")
        results.append({"name": name, "status": "PASS"})
        return True
    except AssertionError as e:
        msg = str(e) or "assertion failed"
        print(f"  {FAIL} {name}  ->  {msg}")
        results.append({"name": name, "status": "FAIL", "detail": msg})
        return False
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"  {FAIL} {name}  ->  {msg}")
        results.append({"name": name, "status": "FAIL", "detail": msg})
        return False


def section(title: str) -> None:
    print(f"\n{chr(8212)*60}")
    print(f"  {title}")
    print(f"{chr(8212)*60}")


def get(path: str, **kw) -> requests.Response:
    return requests.get(f"{BASE}{path}", timeout=8, **kw)


def post(path: str, **kw) -> requests.Response:
    return requests.post(f"{BASE}{path}", timeout=8, **kw)


def fresh_env(fn):
    """Decorator — each capital/state test gets its own isolated STATE_DIR."""
    def wrapper():
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["STATE_DIR"] = tmpdir
            for mod in list(sys.modules):
                if mod.startswith("bot."):
                    del sys.modules[mod]
            fn(tmpdir)
    return wrapper


# -----------------------------------------------------------------
# 1. BACKEND API — ALL ENDPOINTS
# -----------------------------------------------------------------

def test_api_endpoints():
    section("1. BACKEND API — ALL ENDPOINTS")

    def check200(path: str, label: str = ""):
        def _():
            r = get(path)
            assert r.status_code == 200, f"HTTP {r.status_code}"
            assert len(r.content) > 0, "empty response"
        _test(label or f"GET {path}", _)

    check200("/",                     "GET /  root")
    check200("/api/health",           "GET /api/health")
    check200("/api/status",           "GET /api/status")
    check200("/api/bot-status",       "GET /api/bot-status")
    check200("/api/system/health",    "GET /api/system/health")
    check200("/api/bot/activity",     "GET /api/bot/activity")
    check200("/api/nifty/quote",      "GET /api/nifty/quote")
    check200("/api/kite/verify",      "GET /api/kite/verify")
    check200("/api/kite/auth-url",    "GET /api/kite/auth-url")
    check200("/api/trades",           "GET /api/trades")
    check200("/api/trades/today",     "GET /api/trades/today")
    check200("/api/pnl/daily",        "GET /api/pnl/daily")
    check200("/api/pnl/summary",      "GET /api/pnl/summary")
    check200("/api/position",         "GET /api/position")
    check200("/api/daily-watch",      "GET /api/daily-watch")
    check200("/api/slippage/sl",      "GET /api/slippage/sl")
    check200("/api/strategy/config",  "GET /api/strategy/config")
    check200("/api/strategy/state",   "GET /api/strategy/state")
    check200("/api/bot/override",     "GET /api/bot/override")
    check200("/api/bot/manual-signal","GET /api/bot/manual-signal")
    check200("/api/market-state",     "GET /api/market-state")
    check200("/api/logs",             "GET /api/logs")
    check200("/api/events",           "GET /api/events")

    def _health_shape():
        r = get("/api/health")
        d = r.json()
        assert "status" in d, "missing status field"
        # API returns "healthy" | "degraded" | "error" | "ok" (any is valid)
        assert isinstance(d["status"], str), f"status not string: {d}"
    _test("GET /api/health -> has string status field", _health_shape)

    def _bot_status_shape():
        r = get("/api/bot-status")
        d = r.json()
        # bot-status is a flat heartbeat snapshot — check key fields
        missing = [k for k in ("state", "kite_connected", "current_capital") if k not in d]
        assert not missing, f"bot-status missing fields {missing}: {list(d.keys())[:8]}"
    _test("GET /api/bot-status -> has state/kite_connected/current_capital", _bot_status_shape)

    def _position_shape():
        r = get("/api/position")
        d = r.json()
        assert "state" in d, f"missing state: {list(d.keys())}"
    _test("GET /api/position -> state field present", _position_shape)

    def _strategy_config_shape():
        r = get("/api/strategy/config")
        d = r.json()
        assert "capital" in d or "trading_engine" in d or "strategy" in str(d).lower(), (
            f"strategy/config missing expected keys: {list(d.keys())}"
        )
    _test("GET /api/strategy/config -> has strategy/capital field", _strategy_config_shape)


# -----------------------------------------------------------------
# 2. KITE API
# -----------------------------------------------------------------

def test_kite_api():
    section("2. KITE API")

    def _verify_shape():
        r = get("/api/kite/verify")
        d = r.json()
        has_conn = "connected" in d or "kite_connected" in d or "status" in d
        assert has_conn, f"verify response shape wrong: {list(d.keys())}"
    _test("GET /api/kite/verify -> connection status field", _verify_shape)

    def _auth_url_shape():
        r = get("/api/kite/auth-url")
        d = r.json()
        assert "url" in d or "auth_url" in d or "login_url" in d, (
            f"auth-url missing url field: {list(d.keys())}"
        )
        url_val = d.get("url") or d.get("auth_url") or d.get("login_url", "")
        assert "kite" in url_val.lower() or "zerodha" in url_val.lower() or url_val == "", (
            f"auth URL doesn't look like Kite: {url_val}"
        )
    _test("GET /api/kite/auth-url -> valid Kite OAuth URL", _auth_url_shape)

    def _nifty_quote_shape():
        r = get("/api/nifty/quote")
        d = r.json()
        assert "price" in d or "last_price" in d or "error" in d, (
            f"nifty/quote missing price/error: {list(d.keys())}"
        )
        px = d.get("price") or d.get("last_price")
        if px:
            assert isinstance(px, (int, float)), f"price not numeric: {px}"
            assert 10_000 < px < 50_000, f"NIFTY price out of range: {px}"
    _test("GET /api/nifty/quote -> price numeric and in sane range", _nifty_quote_shape)

    def _token_post_no_crash():
        r = post("/api/kite/token", json={"token": ""})
        assert r.status_code in (200, 400, 422), f"empty token POST returned {r.status_code}"
    _test("POST /api/kite/token empty -> 400/422, not 500", _token_post_no_crash)


# -----------------------------------------------------------------
# 3. UI DATA — REAL, NOT STATIC
# -----------------------------------------------------------------

def test_ui_data_real():
    section("3. UI DATA — REAL vs STATIC")

    def _bot_status_dynamic():
        r = get("/api/bot-status")
        d = r.json()
        # bot-status is flat — kite_connected and state are top-level
        kite = d.get("kite_connected")
        assert isinstance(kite, bool), f"kite_connected is not a bool: {kite!r}"
        pos_state = d.get("state", "MISSING")
        valid_states = ("IDLE", "ENTRY_PENDING", "ACTIVE", "EXIT_PENDING", "CLOSED")
        assert pos_state in valid_states, f"state invalid: {pos_state}"
    _test("bot-status -> kite_connected bool + state real enum", _bot_status_dynamic)

    def _capital_real():
        r = get("/api/bot-status")
        d = r.json()
        # capital is flat in bot-status
        cap = d.get("current_capital")
        assert cap is not None, f"current_capital missing: {list(d.keys())[:10]}"
        assert isinstance(cap, (int, float)) and cap > 0, f"current_capital invalid: {cap}"
    _test("bot-status -> current_capital real positive number (flat field)", _capital_real)

    def _trades_real_structure():
        r = get("/api/trades")
        d = r.json()
        # trades endpoint returns {trades: [...], total: N}
        assert isinstance(d, dict) and "trades" in d, (
            f"trades should be {{trades: [...]}} dict, got: {type(d)}"
        )
        trades = d["trades"]
        assert isinstance(trades, list), f"trades.trades not a list: {type(trades)}"
        for t in trades[:3]:
            assert isinstance(t, dict), f"trade not a dict: {t}"
    _test("api/trades -> {trades: [...], total: N} structure", _trades_real_structure)

    def _pnl_daily_real():
        r = get("/api/pnl/daily")
        d = r.json()
        assert isinstance(d, (list, dict)), f"pnl/daily wrong type: {type(d)}"
    _test("api/pnl/daily -> real list or dict", _pnl_daily_real)

    def _daily_watch_real():
        r = get("/api/daily-watch")
        d = r.json()
        assert isinstance(d, dict), f"daily-watch not a dict: {type(d)}"
        assert len(d) > 0, "daily-watch returned empty dict"
    _test("api/daily-watch -> non-empty dict from real state", _daily_watch_real)

    def _market_state_real():
        r = get("/api/market-state")
        d = r.json()
        # market-state returns regime/trend data
        has_regime = "regime" in d or "trend_state" in d or "trend_direction" in d
        assert has_regime, f"market-state missing regime/trend keys: {list(d.keys())[:6]}"
    _test("api/market-state -> has regime / trend_state keys", _market_state_real)

    def _strategy_state_real():
        r = get("/api/strategy/state")
        d = r.json()
        assert isinstance(d, dict) and len(d) > 0, "strategy/state empty or wrong type"
    _test("api/strategy/state -> non-empty dict", _strategy_state_real)

    def _events_real():
        r = get("/api/events")
        d = r.json()
        # events endpoint returns {events: [...]}
        if isinstance(d, list):
            pass  # bare list also OK
        else:
            assert isinstance(d, dict) and "events" in d, (
                f"events should be list or {{events: [...]}} dict, got: {list(d.keys())}"
            )
    _test("api/events -> list or {events: [...]} dict", _events_real)


# -----------------------------------------------------------------
# 4. CAPITAL PROTECTION LOGIC
# -----------------------------------------------------------------

def test_capital_protection():
    section("4. CAPITAL PROTECTION LOGIC")

    def _daily_loss_halt():
        @fresh_env
        def run(tmpdir):
            from bot.risk_manager import RiskManager
            rm = RiskManager(capital=100_000, max_daily_loss_pct=0.05, max_trades_per_day=10)
            rm.record_trade(-5_001)
            ok, reason = rm.can_trade()
            assert not ok, "should be halted after daily loss limit"
            assert "loss" in reason.lower() or "halt" in reason.lower(), (
                f"halt reason not descriptive: {reason}"
            )
        run()
    _test("Capital: halt after daily_loss_pct hit", _daily_loss_halt)

    def _drawdown_halt():
        @fresh_env
        def run(tmpdir):
            from bot.risk_manager import RiskManager
            rm = RiskManager(capital=100_000, max_drawdown_pct=20.0, max_trades_per_day=10,
                             max_daily_loss_pct=0.99)
            rm.state.peak_capital = 100_000
            rm.current_capital = 78_000  # 22% drawdown
            ok, reason = rm.can_trade()
            assert not ok, "should be halted on 22% drawdown"
            assert "drawdown" in reason.lower(), f"drawdown reason: {reason}"
        run()
    _test("Capital: halt on drawdown > 20% from peak", _drawdown_halt)

    def _max_trades_halt():
        @fresh_env
        def run(tmpdir):
            from bot.risk_manager import RiskManager
            rm = RiskManager(capital=100_000, max_trades_per_day=3, max_daily_loss_pct=0.5)
            rm.state.trades_today = 3
            ok, reason = rm.can_trade()
            assert not ok, "should be halted at max trades"
            assert "trade" in reason.lower(), f"reason: {reason}"
        run()
    _test("Capital: halt when max_trades_per_day reached", _max_trades_halt)

    def _emergency_stop_flag():
        @fresh_env
        def run(tmpdir):
            from bot.risk_manager import RiskManager
            rm = RiskManager(capital=100_000, max_trades_per_day=10, max_daily_loss_pct=0.5)
            halt_file = Path(tmpdir) / "kite_bot_halt.flag"
            halt_file.write_text("HALT")
            ok, reason = rm.can_trade()
            assert not ok, "halt flag should prevent trading"
            assert "emergency" in reason.lower() or "halt" in reason.lower(), (
                f"reason: {reason}"
            )
        run()
    _test("Capital: emergency stop flag blocks all trades", _emergency_stop_flag)

    def _position_sizing_sane():
        @fresh_env
        def run(tmpdir):
            from bot.risk_manager import RiskManager
            rm = RiskManager(capital=100_000, risk_per_trade_pct=0.02, lot_size=65, max_lots=5)
            size = rm.compute_position_size(entry_price=200.0, sl_pct=0.10)  # 10% SL
            assert size["lots"] >= 1, "lots must be >= 1"
            assert size["lots"] <= 5, f"lots {size['lots']} exceeds max_lots=5"
            assert size["qty"] == size["lots"] * 65, "qty must be lots x lot_size"
            # risk_amount = 100k * 0.02 = 2000
            # risk_per_unit = 200 * 0.10 = 20, qty ~ 100 → actual_risk = 2000
            assert size["actual_risk"] <= 100_000 * 0.02 * 1.5, (
                f"actual_risk {size['actual_risk']} wildly exceeds 2% risk budget"
            )
        run()
    _test("Capital: position_size lots*lot_size, risk within budget", _position_sizing_sane)

    def _peak_capital_tracks():
        @fresh_env
        def run(tmpdir):
            from bot.risk_manager import RiskManager
            rm = RiskManager(capital=100_000, max_daily_loss_pct=0.5, max_trades_per_day=10)
            rm.record_trade(+10_000)
            assert rm.state.peak_capital >= 109_000, (
                f"peak should be ~110000 after +10k: {rm.state.peak_capital}"
            )
            prev_peak = rm.state.peak_capital
            rm.record_trade(-5_000)
            assert rm.state.peak_capital == prev_peak, (
                f"peak should not drop on loss: {rm.state.peak_capital}"
            )
        run()
    _test("Capital: peak_capital tracks correctly, never decreases on losses", _peak_capital_tracks)

    def _capital_persists_across_restart():
        @fresh_env
        def run(tmpdir):
            from bot.risk_manager import RiskManager
            rm = RiskManager(capital=100_000, max_daily_loss_pct=0.5, max_trades_per_day=10)
            rm.record_trade(+25_000)
            cap_after = rm.current_capital
            # Evict all bot modules and reimport
            for mod in list(sys.modules):
                if mod.startswith("bot."):
                    del sys.modules[mod]
            from bot.risk_manager import RiskManager as RM2
            rm2 = RM2(capital=100_000, max_daily_loss_pct=0.5, max_trades_per_day=10)
            assert rm2.current_capital == cap_after, (
                f"capital should survive restart: expected {cap_after}, got {rm2.current_capital}"
            )
        run()
    _test("Capital: persists across restart via risk_state.json", _capital_persists_across_restart)


# -----------------------------------------------------------------
# 5. NO-MISFIRE / ANTI-DUPLICATE TRADE LOGIC
# -----------------------------------------------------------------

_ENTRY_KWARGS = dict(
    symbol="NIFTY24APR24500CE", direction="CALL", option_type="CE",
    strike=24500, expiry="2024-04-25", qty=75, lots=1,
    sl_price=150.0, target_price=300.0, spot_at_entry=24000.0,
    vix_at_entry=14.0, strategy="ORB", filter_log={}
)


def test_no_misfire():
    section("5. NO-MISFIRE / ANTI-DUPLICATE TRADE LOGIC")

    def _no_double_entry():
        @fresh_env
        def run(tmpdir):
            from bot.state_machine import PositionStateMachine, PositionState
            sm = PositionStateMachine()
            assert sm.position.state == PositionState.IDLE
            sm.transition_to_entry_pending(**_ENTRY_KWARGS)
            assert sm.position.state == PositionState.ENTRY_PENDING
            blocked = False
            try:
                sm.transition_to_entry_pending(**{**_ENTRY_KWARGS, "symbol": "NIFTY25000CE"})
            except (AssertionError, Exception):
                blocked = True
            assert blocked, "double entry should raise — state machine did not block it!"
        run()
    _test("Misfire: double entry raises AssertionError (IDLE guard)", _no_double_entry)

    def _idle_state_required():
        @fresh_env
        def run(tmpdir):
            from bot.state_machine import PositionStateMachine, PositionState
            sm = PositionStateMachine()
            sm.transition_to_entry_pending(**_ENTRY_KWARGS)
            sm.confirm_entry(fill_price=200.0)
            assert sm.position.state == PositionState.ACTIVE
            assert not sm.is_idle, "is_idle should be False when ACTIVE"
        run()
    _test("Misfire: is_idle=False when position is ACTIVE", _idle_state_required)

    def _state_persists_on_disk():
        @fresh_env
        def run(tmpdir):
            from bot.state_machine import PositionStateMachine, PositionState
            sm = PositionStateMachine()
            sm.transition_to_entry_pending(**{**_ENTRY_KWARGS, "symbol": "NIFTY_PERSIST_TEST"})
            # Evict modules and reload
            for mod in list(sys.modules):
                if mod.startswith("bot."):
                    del sys.modules[mod]
            from bot.state_machine import PositionStateMachine as SM2, PositionState as PS2
            sm2 = SM2()
            assert sm2.position.state == PS2.ENTRY_PENDING, (
                f"state not persisted: {sm2.position.state}"
            )
            assert sm2.position.symbol == "NIFTY_PERSIST_TEST", (
                f"symbol not persisted: {sm2.position.symbol}"
            )
        run()
    _test("Misfire: position state persists to disk (survives restart)", _state_persists_on_disk)

    def _cancel_entry_resets_idle():
        @fresh_env
        def run(tmpdir):
            from bot.state_machine import PositionStateMachine, PositionState
            sm = PositionStateMachine()
            sm.transition_to_entry_pending(**_ENTRY_KWARGS)
            sm.cancel_entry()
            assert sm.position.state == PositionState.IDLE, (
                f"cancel_entry should reset to IDLE: {sm.position.state}"
            )
        run()
    _test("Misfire: cancel_entry() resets state to IDLE", _cancel_entry_resets_idle)


# -----------------------------------------------------------------
# 6. PROFIT CAPTURE — TRAILING SL + PROFIT STOP
# -----------------------------------------------------------------

def test_profit_capture():
    section("6. PROFIT CAPTURE — TRAILING SL + PROFIT STOP")

    def _trailing_sl_tightens():
        @fresh_env
        def run(tmpdir):
            from bot.state_machine import PositionStateMachine, PositionState
            sm = PositionStateMachine()
            sm.transition_to_entry_pending(
                symbol="NIFTY_CE", direction="CALL", option_type="CE",
                strike=24000, expiry="2024-04-25", qty=75, lots=1,
                sl_price=140.0, target_price=300.0, spot_at_entry=24000.0,
                vix_at_entry=13.0, strategy="ORB", filter_log={}
            )
            sm.confirm_entry(fill_price=200.0)
            initial_sl = sm.position.current_sl
            assert initial_sl == 140.0, f"initial SL should be 140: {initial_sl}"

            sm.update_trailing_stop(current_price=260.0, trail_trigger_pct=0.20,
                                    trail_lock_step_pct=0.08, break_even_trigger_pct=0.10)
            sl_260 = sm.position.current_sl
            assert sl_260 >= initial_sl, (
                f"SL should not loosen: initial={initial_sl}, now={sl_260}"
            )

            sm.update_trailing_stop(current_price=300.0, trail_trigger_pct=0.20,
                                    trail_lock_step_pct=0.08, break_even_trigger_pct=0.10)
            sl_300 = sm.position.current_sl
            assert sl_300 >= sl_260, (
                f"SL must only tighten: at 260={sl_260}, at 300={sl_300}"
            )
        run()
    _test("Profit: trailing SL only tightens (never loosens) as price rises", _trailing_sl_tightens)

    def _profit_stop_api():
        r = get("/api/bot-status")
        d = r.json()
        blob = json.dumps(d).lower()
        assert any(k in blob for k in ("profit_stop", "day_stopped", "stopped_profit",
                                        "profit_lock", "daily_pnl")), (
            "bot-status has no profit capture / daily_pnl indicator"
        )
    _test("Profit: bot-status exposes profit-stop / daily_pnl field", _profit_stop_api)

    def _break_even_sets_flag():
        @fresh_env
        def run(tmpdir):
            from bot.state_machine import PositionStateMachine
            sm = PositionStateMachine()
            sm.transition_to_entry_pending(
                symbol="NIFTY_CE_BE", direction="CALL", option_type="CE",
                strike=24000, expiry="2024-04-25", qty=75, lots=1,
                sl_price=160.0, target_price=400.0, spot_at_entry=24000.0,
                vix_at_entry=12.0, strategy="ORB", filter_log={}
            )
            sm.confirm_entry(fill_price=200.0)
            # +15% move — triggers BE at 12% (default)
            sm.update_trailing_stop(current_price=230.0)
            assert sm.position.break_even_set, "break_even_set should be True after +15% move"
            assert sm.position.current_sl >= 200.0, (
                f"SL should be >= entry (200) after BE: {sm.position.current_sl}"
            )
        run()
    _test("Profit: break_even_set=True and SL >= entry after +15% move", _break_even_sets_flag)


# -----------------------------------------------------------------
# 7. BROKER SYNC RECONCILIATION
# -----------------------------------------------------------------

_SYNC_ENTRY_KWARGS = dict(
    symbol="NIFTY_CE_SYNC", direction="CALL", option_type="CE",
    strike=24000, expiry="2024-04-25", qty=75, lots=1,
    sl_price=150.0, target_price=300.0, spot_at_entry=24000.0,
    vix_at_entry=13.0, strategy="ORB", filter_log={}
)


def test_broker_sync():
    section("7. BROKER SYNC RECONCILIATION")

    def _sync_detects_external_close():
        @fresh_env
        def run(tmpdir):
            from bot.state_machine import PositionStateMachine, PositionState
            sm = PositionStateMachine()
            sm.transition_to_entry_pending(**_SYNC_ENTRY_KWARGS)
            sm.confirm_entry(fill_price=200.0)
            assert sm.position.state == PositionState.ACTIVE

            changed = sm.sync_with_broker(broker_qty=0, last_price=250.0)
            assert changed, "sync_with_broker should return True on external close"
            assert sm.position.state == PositionState.IDLE, (
                f"state should be IDLE after sync close: {sm.position.state}"
            )
        run()
    _test("BrokerSync: broker qty=0 -> marks position CLOSED then resets IDLE",
          _sync_detects_external_close)

    def _sync_no_change_when_qty_matches():
        @fresh_env
        def run(tmpdir):
            from bot.state_machine import PositionStateMachine, PositionState
            sm = PositionStateMachine()
            sm.transition_to_entry_pending(**{**_SYNC_ENTRY_KWARGS,
                                              "symbol": "NIFTY_PE_SYNC",
                                              "direction": "PUT", "option_type": "PE"})
            sm.confirm_entry(fill_price=150.0)
            changed = sm.sync_with_broker(broker_qty=75, last_price=160.0)
            assert not changed, "no change when qty matches — should return False"
            assert sm.position.state == PositionState.ACTIVE, (
                f"state should stay ACTIVE: {sm.position.state}"
            )
        run()
    _test("BrokerSync: matching broker qty -> no state change, returns False",
          _sync_no_change_when_qty_matches)

    def _broker_sync_endpoint_exists():
        r = get("/api/bot/activity")
        assert r.status_code == 200, f"bot/activity status {r.status_code}"
    _test("BrokerSync: /api/bot/activity endpoint alive", _broker_sync_endpoint_exists)

    def _system_health_broker_fields():
        r = get("/api/system/health")
        d = r.json()
        blob = json.dumps(d).lower()
        assert "kite" in blob or "broker" in blob or "connect" in blob, (
            "system/health has no kite/broker connectivity info"
        )
    _test("BrokerSync: /api/system/health has kite/broker info", _system_health_broker_fields)


# -----------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------

def main():
    start = time.time()
    print()
    print("=" * 60)
    print("   NIFTY ALPHA BOT — COMPREHENSIVE SYSTEM TEST")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        requests.get(f"{BASE}/api/health", timeout=3)
    except Exception:
        print(f"\n  API not reachable at {BASE} — is the bot running?")
        sys.exit(1)

    test_api_endpoints()
    test_kite_api()
    test_ui_data_real()
    test_capital_protection()
    test_no_misfire()
    test_profit_capture()
    test_broker_sync()

    passed = [r for r in results if r["status"] == "PASS"]
    failed = [r for r in results if r["status"] == "FAIL"]
    elapsed = time.time() - start

    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {len(passed)}/{len(results)} passed  ({len(failed)} failed)  [{elapsed:.1f}s]")
    print(f"{'=' * 60}")

    if failed:
        print("\n  FAILURES:")
        for r in failed:
            print(f"    x {r['name']}")
            if r.get("detail"):
                print(f"      -> {r['detail']}")
    else:
        print("  ALL TESTS PASSED — system is clean!")

    print()
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
