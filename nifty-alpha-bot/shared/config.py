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
    capital: float = 100_000.0
    max_daily_loss_pct: float = 0.03      # 3% of capital = ₹3,000
    max_daily_loss_hard: float = 3_000.0  # Hard stop regardless of capital
    max_trades_per_day: int = 3
    max_open_positions: int = 1
    max_consecutive_losses: int = 3
    lot_size: int = 65
    live_max_lots: int = 1
    thursday_max_lots: int = 1            # Conservative on expiry day
    paper_mode: bool = False

    # ── ORB Strategy ──────────────────────────────────────────────
    orb_start: str = "09:15"
    orb_end: str = "09:30"
    entry_window_close: str = "09:45"     # No new ORB entries after this
    force_exit_time: str = "15:15"

    max_orb_range_points: float = 150.0
    min_orb_range_points: float = 40.0
    breakout_buffer_pct: float = 0.0003

    # Breakout candle quality
    min_breakout_body_ratio: float = 0.55
    min_volume_surge_ratio: float = 1.8

    # ── VWAP Reclaim Strategy ─────────────────────────────────────
    reclaim_window_start: str = "10:00"
    reclaim_window_end: str = "13:00"
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

    rsi_bull_min: float = 52.0
    rsi_bear_max: float = 48.0
    rsi_overbought_skip: float = 75.0
    rsi_oversold_skip: float = 25.0

    vix_max: float = 18.0

    # ── SL / Target ───────────────────────────────────────────────
    atr_sl_multiplier: float = 1.2
    atr_sl_min_pct: float = 0.08
    atr_sl_max_pct: float = 0.12
    rr_min: float = 2.5

    trail_trigger_pct: float = 0.20
    trail_lock_step_pct: float = 0.10
    break_even_trigger_pct: float = 0.12

    # Thursday expiry
    thursday_max_loss_pct: float = 0.06

    # ── Options Filters ───────────────────────────────────────────
    min_option_price: float = 60.0
    max_option_price: float = 400.0
    max_spread_pct: float = 0.015
    delta_min: float = 0.25
    delta_max: float = 0.65
    strike_step: int = 50

    # ── Broker / Execution ───────────────────────────────────────
    use_limit_orders: bool = False
    limit_price_buffer_pct: float = 0.001
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
