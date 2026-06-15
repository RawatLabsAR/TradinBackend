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

    # PostgreSQL — use a transaction-pooler URI when hosted on Supabase (port 6543).
    DATABASE_URL: str = ""
    DB_POOL_SIZE: int = 3
    DB_MAX_OVERFLOW: int = 5

    # ── Persistence feature flags ─────────────────────────────────────────────
    ENABLE_ONCHAIN_PERSISTENCE: bool = True
    ENABLE_TOKEN_SEARCH_DB: bool = True
    ENABLE_NEWS_PERSISTENCE: bool = True
    ENABLE_AI_PERSISTENCE: bool = True
    ENABLE_SEARCH_HISTORY: bool = True
    ENABLE_DISCOVERY_PERSISTENCE: bool = True

    # ── Retention (days) ──────────────────────────────────────────────────────
    RETENTION_NEWS_DAYS: int = 7
    RETENTION_AI_SUMMARIES_DAYS: int = 30
    RETENTION_ONCHAIN_TRADES_DAYS: int = 14
    RETENTION_ONCHAIN_OHLCV_DAYS: int = 90
    RETENTION_ONCHAIN_SNAPSHOTS_DAYS: int = 30
    RETENTION_ONCHAIN_EVENTS_DAYS: int = 30
    RETENTION_ONCHAIN_METRICS_DAYS: int = 90
    RETENTION_SEARCH_HISTORY_DAYS: int = 14
    RETENTION_BROADCAST_LOGS_DAYS: int = 30
    RETENTION_STRATEGY_RUNS_DAYS: int = 60
    RETENTION_ACTIVITY_DAYS: int = 90
    RETENTION_PAPER_TRADES_DAYS: int = 365
    RETENTION_DISCOVERY_DAYS: int = 7

    # Optional — for health checks / future Realtime (backend uses DATABASE_URL)
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""

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

    # ── Auth / users ──────────────────────────────────────────────────────────
    JWT_SECRET: str = "change-me-in-production-use-long-random-string"
    JWT_EXPIRE_HOURS: int = 72
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""

    FRONTEND_URL: str = "http://localhost:5173"
    # Comma-separated extra origins (e.g. production + preview Vercel URLs)
    ALLOWED_ORIGINS: str = ""
    # Regex for dynamic preview deployments; set empty to disable
    CORS_ORIGIN_REGEX: str = r"https://.*\.vercel\.app"

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
    ONCHAIN_SYNC_INTERVAL_MINUTES: int = 30
    WHALE_THRESHOLD_USD: float = 50_000.0
    SMART_MONEY_MIN_SCORE: float = 80.0
    # JSON array or chain:address;chain:address format
    ONCHAIN_TRACKED_TOKENS: str = ""

    # ── Token discovery / search ──────────────────────────────────────────────
    DEXSCREENER_API_URL: str = "https://api.dexscreener.com"
    COINGECKO_API_KEY: str = ""
    TOKEN_SEARCH_CACHE_MINUTES: int = 10

    # ── Crypto discovery ──────────────────────────────────────────────────────
    DISCOVERY_SCAN_HOUR: int = 6  # UTC — daily automatic scan
    DISCOVERY_SCAN_MINUTE: int = 0
    DISCOVERY_CACHE_TTL_HOURS: int = 48

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

    @property
    def cors_origins(self) -> List[str]:
        origins = {"http://localhost:5173", "http://localhost:3000"}
        if self.FRONTEND_URL.strip():
            origins.add(self.FRONTEND_URL.strip().rstrip("/"))
        for origin in self.ALLOWED_ORIGINS.split(","):
            normalized = origin.strip().rstrip("/")
            if normalized:
                origins.add(normalized)
        return sorted(origins)

    @property
    def is_supabase(self) -> bool:
        return "supabase.co" in self.DATABASE_URL


settings = Settings()
