"""Whale scanner job settings (Render cron worker)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class WhaleScannerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    DATABASE_URL: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WHALE_CHANNEL_ID: str = ""
    TELEGRAM_DEFAULT_CHAT_ID: str = ""

    WHALE_THRESHOLD_USD: float = 50_000.0
    MAX_AGE_DAYS: int = 30
    MAX_TOKENS_PER_RUN: int = 200
    MIN_LIQUIDITY_USD: float = 5_000.0
    MIN_VOLUME_24H: float = 10_000.0
    WHALE_LOOKBACK_HOURS: int = 24
    MAX_TELEGRAM_ALERTS: int = 15
    SCAN_CONCURRENCY: int = 3
    SCAN_DELAY_MS: int = 1200
    FRONTEND_URL: str = "http://localhost:5173"
    DRY_RUN: bool = False

    @property
    def max_age_hours(self) -> float:
        return float(self.MAX_AGE_DAYS * 24)

    @property
    def telegram_chat_id(self) -> str:
        return (self.TELEGRAM_WHALE_CHANNEL_ID or self.TELEGRAM_DEFAULT_CHAT_ID).strip()

    @property
    def app_link_base(self) -> str:
        return self.FRONTEND_URL.rstrip("/")


whale_scan_settings = WhaleScannerSettings()
