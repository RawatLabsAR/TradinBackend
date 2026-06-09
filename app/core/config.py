from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    APP_NAME: str = "Tradin"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Supabase / PostgreSQL — paste the connection string from
    # Supabase Dashboard → Project Settings → Database → Connection string (URI)
    # Use the "Transaction pooler" URI for FastAPI (port 6543).
    DATABASE_URL: str = ""

    # ── Data provider ──────────────────────────────────────────────────────────
    # Accepted values: "coinbase" | "gate"
    DATA_PROVIDER: str = "coinbase"

    # Coinbase Advanced Trade (public endpoints, no key required)
    COINBASE_API_BASE_URL: str = "https://api.coinbase.com/api/v3/brokerage"
    COINBASE_WS_URL: str = "wss://advanced-trade-ws.coinbase.com"

    # Gate.io Spot API (public endpoints, no key required)
    GATE_API_BASE_URL: str = "https://api.gateio.ws/api/v4"
    GATE_WS_URL: str = "wss://api.gateio.ws/ws/v4/"
    GATE_FUTURES_WS_URL: str = "wss://fx-ws.gateio.ws/v4/ws/usdt"
    GATE_DELIVERY_WS_URL: str = "wss://fx-ws.gateio.ws/v4/ws/delivery/usdt"

    FRONTEND_URL: str = "http://localhost:5173"

    CACHE_TTL_PRODUCTS: int = 60
    CACHE_TTL_CANDLES_SHORT: int = 30
    CACHE_TTL_CANDLES_LONG: int = 300

    DEFAULT_PRODUCTS: str = (
        "BTC-USD,ETH-USD,SOL-USD,XRP-USD,DOGE-USD,"
        "ADA-USD,AVAX-USD,MATIC-USD,DOT-USD,LINK-USD"
    )

    # AI / News settings (OPENAI_API_KEY loaded from .env)
    OPENAI_API_KEY: str = ""
    AI_MODEL: str = "gpt-4o-mini"
    AI_CACHE_MINUTES: int = 60

    GNEWS_API_KEY: str = ""

    # Comma-separated symbols for AI processing (defaults to DEFAULT_PRODUCTS bases)
    TRACKED_SYMBOLS: str = "BTC,ETH,SOL,XRP,DOGE,ADA,AVAX,MATIC,DOT,LINK"

    # ── Telegram broadcasting ───────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_DEFAULT_CHAT_ID: str = ""
    BROADCAST_COOLDOWN_SECONDS: int = 30
    BROADCAST_DEDUP_WINDOW_SECONDS: int = 300
    ENABLE_SIGNAL_BROADCAST: bool = True
    ENABLE_AI_BROADCAST: bool = False
    BROADCAST_QUEUE_MAX_SIZE: int = 1000

    # ── On-chain analytics ────────────────────────────────────────────────────
    DUNE_API_KEY: str = ""
    ONCHAIN_SYNC_INTERVAL_MINUTES: int = 15
    WHALE_THRESHOLD_USD: float = 50_000.0
    SMART_MONEY_MIN_SCORE: float = 80.0
    # JSON array or chain:address;chain:address format
    ONCHAIN_TRACKED_TOKENS: str = ""

    # ── Token discovery / search ──────────────────────────────────────────────
    DEXSCREENER_API_URL: str = "https://api.dexscreener.com"
    COINGECKO_API_KEY: str = ""
    TOKEN_SEARCH_CACHE_MINUTES: int = 10

    @property
    def database_url(self) -> str | None:
        url = self.DATABASE_URL.strip()
        if not url:
            return None
        if url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url[len("postgres://") :]
        elif url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://") :]
        elif not url.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must start with postgresql://, postgres://, "
                "or postgresql+asyncpg://"
            )
        return url

    @property
    def default_product_list(self) -> List[str]:
        return [p.strip() for p in self.DEFAULT_PRODUCTS.split(",") if p.strip()]


settings = Settings()
