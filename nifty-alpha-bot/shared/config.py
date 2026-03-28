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
    capital: float = 100000.0
    max_daily_loss_pct: float = 0.03           # 3% daily hard stop (scales with capital)
    max_daily_loss_hard: float = 5000.0        # ₹5,000 absolute floor (early-capital safety)
    max_trades_per_day: int = 4
    max_open_positions: int = 1
    lot_size: int = 65
    live_max_lots: int = 3                     # Live cap (safety — raise to 5 only in paper)
    max_lots: int = 5                          # Paper/backtest cap
    thursday_max_lots: int = 2                 # Expiry day cap
    paper_mode: bool = False

    # ── Conviction / Impulse-based sizing ─────────────────────────
    # A+ = EXTREME impulse + STRONG_BEAR/BULL → deep OTM + max lots
    aplus_risk_pct: float = 0.05               # 5% risk for A+ setups (3-4 lots at ₹1L)
    aplus_otm_steps: int = 2                   # Steps OTM for A+ (100 pts for Nifty 50-step)
    strong_otm_steps: int = 1                  # 1-OTM for STRONG trend (not A+)
    normal_otm_steps: int = 0                  # ATM for normal signals

    # ── Engine: intraday (5m ORB/VWAP/…) vs daily_adaptive (same as daily backtest) ──
    trading_engine: str = "daily_adaptive"
    daily_strategy_filter: str = "BOTH"
    nifty_option_lot_size: int = 65
    daily_base_lots: int = 1
    daily_adaptive_window_start: str = "09:16"
    daily_adaptive_window_end: str = "13:00"
    # Late window: tighter A+ filters apply after the early window
    late_window_start: str = "10:30"
    late_window_vix_max: float = 22.0          # VIX must be calm for late entries
    late_window_sl_pct: float = 0.12           # 12% SL (less time to recover)
    late_window_target_pct: float = 0.30       # 30% target (2.5x RR, achievable intraday)
    # Strategies allowed in late window (A+ only)
    late_window_strategies: str = "BREAKOUT_MOMENTUM,TREND_CONTINUATION,INSIDE_BAR_BREAK"
    # Extended window for trending regimes (mild/strong trend: moves continue past 11:30)
    trending_regime_window_end: str = "13:30"
    trending_regimes_for_extended_window: str = "MILD_TREND,STRONG_TREND_UP,STRONG_TREND_DOWN"

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

    max_orb_range_points: float = 200.0       # Raised: 150→200 to capture normal wide-open days
    relaxed_orb_max_range_points: float = 320.0  # RELAXED_ORB allows wider opening ranges
    min_orb_range_points: float = 40.0
    breakout_buffer_pct: float = 0.0005

    min_breakout_body_ratio: float = 0.45
    min_volume_surge_ratio: float = 1.2

    # ── EMA Pullback Strategy ─────────────────────────────────────
    ema_pullback_window_start: str = "09:30"
    ema_pullback_window_end: str = "13:00"
    ema_pullback_proximity_pct: float = 0.006     # 0.6% — within 0.6% of EMA21 counts as pullback
    ema_pullback_lookback_candles: int = 4        # How many past candles to check for EMA21 touch
    ema_pullback_min_body_ratio: float = 0.38

    # ── Momentum Breakout Strategy ────────────────────────────────
    momentum_breakout_window_start: str = "09:30"
    momentum_breakout_window_end: str = "12:00"   # Morning momentum only
    momentum_breakout_lookback: int = 20           # N-candle range to break above/below
    momentum_breakout_min_body_ratio: float = 0.50
    momentum_breakout_rsi_bull_min: float = 55.0
    momentum_breakout_rsi_bull_max: float = 78.0
    momentum_breakout_rsi_bear_min: float = 22.0
    momentum_breakout_rsi_bear_max: float = 45.0
    momentum_breakout_min_volume_surge: float = 1.3

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

    trail_trigger_pct: float = 0.14
    trail_lock_step_pct: float = 0.09
    break_even_trigger_pct: float = 0.08

    # ── Signal quality thresholds ─────────────────────────────────────
    min_confidence_score: float = 65.0      # min confidence to take any trade (was 70 — lowered for more frequency)
    min_quality_score: float = 4.0          # min quality score (0-5 scale)
    structure_exit_min_profit_pct: float = 0.05  # only exit on structure break if 5%+ in profit

    # ── Conviction-based max trades ───────────────────────────────────
    strong_trend_conviction_min: float = 0.70   # conviction >= this → allow more trades
    strong_trend_max_trades: int = 3            # max trades on strong trend days

    # ── Overextension filter ──────────────────────────────────────────
    overextended_move_pct: float = 0.015    # if Nifty moved >1.5% intraday in signal direction, skip in late window

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
