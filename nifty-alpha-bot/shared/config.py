"""Central configuration — loaded from .env, overridable at runtime."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Kite ──────────────────────────────────────────────────────
    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_access_token: str = ""
    kite_totp_secret: str = ""
    kite_user_id: str = ""
    kite_user_password: str = ""

    # ── Database ──────────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "nifty_trader"
    postgres_user: str = "trader"
    postgres_password: str = "trader"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Capital & Risk ────────────────────────────────────────────
    # At 25k with min 1 lot, actual risk per trade ~₹2,500-3,500.
    # Daily limit must allow at least 2 trades before stopping.
    capital: float = 25_000.0
    max_daily_loss_pct: float = 0.25           # 25% = ₹6,250 (allows 2 full SL hits)
    max_daily_loss_hard: float = 7_000.0       # ₹7,000 absolute hard stop
    max_trades_per_day: int = 3
    max_open_positions: int = 1
    lot_size: int = 65
    live_max_lots: int = 1
    max_lots: int = 1
    thursday_max_lots: int = 1
    paper_mode: bool = False

    # ── Per-Trade Risk Sizing ─────────────────────────────────────
    risk_per_trade_pct: float = 0.02           # 2% target (but min 1 lot floor applies)

    # ── Drawdown-Based Halt (replaces consecutive-loss halt) ──────
    max_drawdown_pct: float = 20.0             # Halt bot if drawdown > 20% from peak
    max_consecutive_losses: int = 8            # High ceiling — drawdown halt is primary

    # ── ORB Strategy (backtest-optimized) ─────────────────────────
    orb_start: str = "09:15"
    orb_end: str = "09:30"
    entry_window_close: str = "10:00"
    force_exit_time: str = "15:15"

    max_orb_range_points: float = 150.0
    min_orb_range_points: float = 40.0
    breakout_buffer_pct: float = 0.0005

    min_breakout_body_ratio: float = 0.45
    min_volume_surge_ratio: float = 1.2

    # ── VWAP Reclaim Strategy ─────────────────────────────────────
    reclaim_window_start: str = "10:00"
    reclaim_window_end: str = "13:30"
    reclaim_min_rejection_points: float = 15.0
    reclaim_confirmation_candles: int = 2
    supertrend_period: int = 10
    supertrend_multiplier: float = 3.0

    # ── Indicator Params ──────────────────────────────────────────
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    atr_period: int = 14
    signal_candle_minutes: int = 5

    # ── Entry Filters ─────────────────────────────────────────────
    require_vwap_confirmation: bool = True
    vwap_buffer_points: float = 5.0

    rsi_bull_min: float = 40.0
    rsi_bear_max: float = 60.0
    rsi_overbought_skip: float = 80.0
    rsi_oversold_skip: float = 20.0

    vix_max: float = 28.0

    # ── SL / Target ───────────────────────────────────────────────
    atr_sl_multiplier: float = 1.2
    atr_sl_min_pct: float = 0.20
    atr_sl_max_pct: float = 0.30
    rr_min: float = 2.0

    trail_trigger_pct: float = 0.20
    trail_lock_step_pct: float = 0.10
    break_even_trigger_pct: float = 0.12

    thursday_max_loss_pct: float = 0.06

    # ── Options Filters ───────────────────────────────────────────
    min_option_price: float = 60.0
    max_option_price: float = 400.0
    max_spread_pct: float = 0.015
    delta_min: float = 0.25
    delta_max: float = 0.65
    strike_step: int = 50

    # ── Broker / Execution ───────────────────────────────────────
    use_limit_orders: bool = True              # Aggressive limit for entry
    limit_price_buffer_pct: float = 0.005      # LTP + 0.5% buffer for aggressive fill
    use_slm_exit: bool = True                  # SL-M for stop-loss protection
    api_retries: int = 3
    api_retry_delay_seconds: float = 0.4
    api_circuit_breaker_failures: int = 5
    api_circuit_breaker_cooldown_seconds: int = 60
    poll_seconds: int = 5

    # ── Notifications ─────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── API / Dashboard ───────────────────────────────────────────
    api_secret_key: str = "change-this-secret"
    dashboard_username: str = "admin"
    dashboard_password: str = "admin"
    environment: str = "development"
    log_level: str = "INFO"


settings = Settings()
