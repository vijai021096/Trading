"""
Zerodha Kite API wrapper.
Supports: aggressive limit entry, SL-M exit protection, market orders.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

try:
    from kiteconnect import KiteConnect
except ImportError:
    raise ImportError("Run: pip install kiteconnect")

from shared.indicators import normalize_candles


class KiteClient:

    EXCHANGE = "NFO"
    EXCHANGE_NSE = "NSE"
    PRODUCT_MIS = "MIS"
    PRODUCT_NRML = "NRML"

    def __init__(self, api_key: str, access_token: str) -> None:
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        self._instrument_cache: Dict[str, Any] = {}
        self._instruments_loaded = False
        self.api_retries = 3
        self.api_retry_delay = 0.5

    @classmethod
    def from_token(cls, api_key: str, access_token: str) -> "KiteClient":
        return cls(api_key, access_token)

    def _call(self, fn, *args, **kwargs) -> Any:
        last_err = None
        for attempt in range(1, self.api_retries + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_err = exc
                if attempt < self.api_retries:
                    time.sleep(self.api_retry_delay * attempt)
        raise last_err

    # ─── Authentication ────────────────────────────────────────────

    def check_auth(self) -> bool:
        try:
            self._call(self.kite.profile)
            return True
        except Exception:
            return False

    # ─── Instruments ──────────────────────────────────────────────

    def load_instruments(self, exchange: str = "NFO") -> None:
        instruments = self._call(self.kite.instruments, exchange)
        for inst in instruments:
            key = inst.get("tradingsymbol", "")
            self._instrument_cache[key] = inst
        self._instruments_loaded = True

    def get_instrument(self, trading_symbol: str) -> Optional[Dict]:
        if not self._instruments_loaded:
            self.load_instruments()
        return self._instrument_cache.get(trading_symbol)

    # ─── Quotes ───────────────────────────────────────────────────

    def get_quote(self, symbol: str, exchange: str = "NSE") -> float:
        key = f"{exchange}:{symbol}"
        resp = self._call(self.kite.ltp, [key])
        if resp and key in resp:
            return float(resp[key].get("last_price", 0.0))
        return 0.0

    def get_quote_details(self, symbol: str, exchange: str = "NFO") -> Dict[str, Any]:
        key = f"{exchange}:{symbol}"
        resp = self._call(self.kite.quote, [key])
        if not resp or key not in resp:
            return {"ltp": None, "bid": None, "ask": None, "mid": None, "spread_pct": None}
        q = resp[key]
        ltp = float(q.get("last_price", 0) or 0)
        depth = q.get("depth", {})
        bids = depth.get("buy", [])
        asks = depth.get("sell", [])
        bid = float(bids[0]["price"]) if bids else None
        ask = float(asks[0]["price"]) if asks else None
        mid = (bid + ask) / 2 if bid and ask else None
        spread_pct = (ask - bid) / mid if mid and mid > 0 else None
        return {"ltp": ltp, "bid": bid, "ask": ask, "mid": mid, "spread_pct": spread_pct}

    # ─── Historical candles ───────────────────────────────────────

    def get_candles(
        self,
        instrument_token: int,
        from_dt: datetime,
        to_dt: datetime,
        interval: str = "5minute",
    ) -> List[Dict[str, Any]]:
        raw = self._call(
            self.kite.historical_data,
            instrument_token,
            from_dt,
            to_dt,
            interval,
        )
        candles = []
        for c in raw:
            candles.append({
                "ts": c["date"].replace(tzinfo=None) if hasattr(c["date"], "tzinfo") else c["date"],
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": float(c.get("volume", 0)),
            })
        return sorted(candles, key=lambda x: x["ts"])

    def get_nifty_token(self) -> Optional[int]:
        instruments = self._call(self.kite.instruments, "NSE")
        for inst in instruments:
            if inst.get("tradingsymbol") == "NIFTY 50":
                return inst["instrument_token"]
        return None

    # ─── Options ──────────────────────────────────────────────────

    def get_option_chain_symbols(
        self,
        index_symbol: str = "NIFTY",
        expiry: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        if not self._instruments_loaded:
            self.load_instruments("NFO")
        result = []
        for sym, inst in self._instrument_cache.items():
            if (
                inst.get("name", "") == index_symbol
                and inst.get("instrument_type") in ("CE", "PE")
            ):
                if expiry is None or inst.get("expiry") == expiry:
                    result.append({
                        "symbol": sym,
                        "strike": float(inst.get("strike", 0)),
                        "option_type": inst.get("instrument_type"),
                        "expiry": inst.get("expiry"),
                        "token": inst.get("instrument_token"),
                        "lot_size": inst.get("lot_size", 65),
                    })
        return result

    def select_atm_option(
        self,
        spot: float,
        direction: str,
        strike_step: int = 50,
        expiry: Optional[date] = None,
        index_symbol: str = "NIFTY",
    ) -> Optional[Dict[str, Any]]:
        atm = round(spot / strike_step) * strike_step
        opt_type = "CE" if direction == "CALL" else "PE"
        chain = self.get_option_chain_symbols(index_symbol, expiry)
        candidates = [c for c in chain if c["option_type"] == opt_type]
        if not candidates:
            return None
        candidates.sort(key=lambda c: abs(c["strike"] - atm))
        return candidates[0]

    def get_nearest_expiry(self, index_symbol: str = "NIFTY") -> Optional[date]:
        if not self._instruments_loaded:
            self.load_instruments("NFO")
        today = date.today()
        expiries = set()
        for inst in self._instrument_cache.values():
            if (
                inst.get("name", "") == index_symbol
                and inst.get("instrument_type") in ("CE", "PE")
            ):
                exp = inst.get("expiry")
                if exp and exp >= today:
                    expiries.add(exp)
        if not expiries:
            return None
        return min(expiries)

    # ─── Margins ──────────────────────────────────────────────────

    def get_available_margin(self) -> Optional[float]:
        try:
            resp = self._call(self.kite.margins, "equity")
            if isinstance(resp, dict):
                return float(resp.get("available", {}).get("live_balance", 0))
        except Exception:
            pass
        return None

    # ─── Orders ───────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        exchange: str = "NFO",
        product: str = "MIS",
        limit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Place market or limit order for entry."""
        tx = self.kite.TRANSACTION_TYPE_BUY if side == "BUY" else self.kite.TRANSACTION_TYPE_SELL
        order_type = self.kite.ORDER_TYPE_LIMIT if limit_price else self.kite.ORDER_TYPE_MARKET
        validity = self.kite.VALIDITY_DAY

        kwargs: Dict[str, Any] = dict(
            variety=self.kite.VARIETY_REGULAR,
            exchange=exchange,
            tradingsymbol=symbol,
            transaction_type=tx,
            quantity=qty,
            product=product,
            order_type=order_type,
            validity=validity,
        )
        if limit_price:
            tick = 0.05
            kwargs["price"] = round(float(limit_price) / tick) * tick

        order_id = self._call(self.kite.place_order, **kwargs)
        return {"order_id": order_id, "status": "PENDING", "placed_at": time.time()}

    def place_slm_order(
        self,
        symbol: str,
        qty: int,
        trigger_price: float,
        exchange: str = "NFO",
        product: str = "MIS",
    ) -> Dict[str, Any]:
        """Place SL-M (Stop Loss Market) order for exit protection.
        Triggers a market sell when price drops to trigger_price."""
        tick = 0.05
        trigger = round(float(trigger_price) / tick) * tick

        kwargs: Dict[str, Any] = dict(
            variety=self.kite.VARIETY_REGULAR,
            exchange=exchange,
            tradingsymbol=symbol,
            transaction_type=self.kite.TRANSACTION_TYPE_SELL,
            quantity=qty,
            product=product,
            order_type=self.kite.ORDER_TYPE_SLM,
            validity=self.kite.VALIDITY_DAY,
            trigger_price=trigger,
        )

        order_id = self._call(self.kite.place_order, **kwargs)
        return {"order_id": order_id, "status": "SLM_PLACED", "trigger_price": trigger}

    def modify_slm_order(
        self,
        order_id: str,
        new_trigger_price: float,
    ) -> bool:
        """Modify existing SL-M order trigger price (for trailing SL)."""
        tick = 0.05
        trigger = round(float(new_trigger_price) / tick) * tick
        try:
            self._call(
                self.kite.modify_order,
                self.kite.VARIETY_REGULAR,
                order_id,
                trigger_price=trigger,
            )
            return True
        except Exception:
            return False

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        try:
            orders = self._call(self.kite.orders)
            for o in orders:
                if str(o.get("order_id")) == str(order_id):
                    return o
        except Exception:
            pass
        return {}

    def confirm_fill(self, order_id: str, timeout_seconds: int = 15) -> bool:
        end = time.time() + timeout_seconds
        while time.time() < end:
            time.sleep(1.0)
            status = self.get_order_status(order_id)
            st = str(status.get("status", "")).upper()
            if st in ("COMPLETE",):
                return True
            if st in ("REJECTED", "CANCELLED"):
                return False
        return False

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._call(self.kite.cancel_order, self.kite.VARIETY_REGULAR, order_id)
            return True
        except Exception:
            return False

    # ─── Positions ────────────────────────────────────────────────

    def get_positions(self) -> List[Dict[str, Any]]:
        try:
            resp = self._call(self.kite.positions)
            return resp.get("net", []) or []
        except Exception:
            return []

    def get_open_qty(self, symbol: str) -> int:
        positions = self.get_positions()
        for p in positions:
            if p.get("tradingsymbol") == symbol:
                return int(p.get("quantity", 0))
        return 0
