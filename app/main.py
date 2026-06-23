import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.auth import require_verified_user
from app.core.errors import register_exception_handlers
from app.core.rate_limit import limiter
from app.core.security import SecurityHeadersMiddleware, validate_production_settings
from app.db.database import AsyncSessionLocal, create_tables, dispose_engine, database_available
from app.db.retention_scheduler import attach_retention_scheduler
from app.providers.registry import build_ws_client, close_market_session
from app.websocket.manager import ws_manager
from app.websocket.registry import set_active_ws_client
from app.api.routes import products, candles, ws as ws_router
from app.api.routes import news as news_router, ai_insights as ai_router
from app.api.routes import scripts as scripts_router
from app.api.routes import broadcast as broadcast_router
from app.api.routes import telegram as telegram_router
from app.api.routes import alerts as alerts_router
from app.api.routes import onchain as onchain_router
from app.api.routes import token_search as token_search_router
from app.api.routes import discovery as discovery_router
from app.api.routes import whale_scan as whale_scan_router
from app.api.routes import analytics as analytics_router
from app.api.routes import auth as auth_router
from app.api.routes import admin as admin_router
from app.api.routes import paper_trades as paper_trades_router
from app.api.routes import user_data as user_data_router
from app.api.routes import billing as billing_router
from app.services.user_service import ensure_admin_user
from app.services.news.news_scheduler import create_scheduler
from app.services.alert_service import check_alerts_for_ticker
from app.services.paper_order_service import check_paper_orders_for_ticker
from app.broadcast.services.broadcast_service import broadcast_service
from app.broadcast.schedulers.broadcast_scheduler import attach_broadcast_scheduler
from app.broadcast.templates.template_engine import template_engine
from app.onchain.schedulers.onchain_scheduler import attach_onchain_scheduler
from app.token_search.schedulers.search_scheduler import attach_token_search_scheduler
from app.discovery.schedulers.discovery_scheduler import attach_discovery_scheduler
from app.whale_scanner.scheduler import attach_whale_scan_scheduler
from app.discovery.cache.discovery_cache import get_cached_discovery
from app.onchain.collectors.base import close_session as close_onchain_session
from app.integrations.telegram.telegram_service import get_telegram_service, init_telegram_service
import app.models  # ensure all models are registered with Base before create_tables()

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENVIRONMENT,
            integrations=[StarletteIntegration(), FastApiIntegration()],
            traces_sample_rate=0.1 if not settings.DEBUG else 0.0,
        )
        logger.info("Sentry initialized")
    except ImportError:
        logger.warning("sentry-sdk not installed — error tracking disabled")


async def on_ticker(ticker: dict) -> None:
    """Fan out exchange ticker updates to all subscribed frontend clients."""
    product_id = ticker.get("product_id")
    if product_id:
        await ws_manager.broadcast_ticker(product_id, ticker)
        await check_alerts_for_ticker(ticker)
        await check_paper_orders_for_ticker(ticker)


def _build_ws_client():
    """Instantiate the correct exchange WS client based on DATA_PROVIDER."""
    return build_ws_client(on_ticker)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production_settings()
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)

    try:
        await create_tables()
        logger.info("Database tables ready")
        if AsyncSessionLocal is not None:
            async with AsyncSessionLocal() as db:
                await ensure_admin_user(db)
                await db.commit()
    except Exception as exc:
        logger.warning(
            "Database unavailable (%s) — running without persistence", exc
        )

    client, provider = _build_ws_client()
    set_active_ws_client(client)
    await client.start()
    logger.info(
        "%s WS client started; tracking %d default products",
        provider.capitalize(),
        len(settings.default_product_list),
    )

    scheduler = create_scheduler()
    if settings.ENABLE_ONCHAIN_PERSISTENCE:
        attach_onchain_scheduler(scheduler)
    else:
        logger.info("On-chain persistence disabled — ETL scheduler skipped")
    attach_token_search_scheduler(scheduler)
    attach_discovery_scheduler(scheduler)
    attach_whale_scan_scheduler(scheduler)
    attach_retention_scheduler(scheduler)
    scheduler.start()
    logger.info("Background schedulers started")

    if settings.TELEGRAM_BOT_TOKEN:
        tg_service = init_telegram_service(settings.TELEGRAM_BOT_TOKEN)
        await tg_service.start()

        await broadcast_service.start(
            cooldown_seconds=settings.BROADCAST_COOLDOWN_SECONDS
        )
        attach_broadcast_scheduler(scheduler)

        if AsyncSessionLocal is not None:
            async with AsyncSessionLocal() as db:
                try:
                    await template_engine.seed_defaults(db)
                    await db.commit()
                except Exception as exc:
                    logger.warning("Template seeding skipped: %s", exc)
                    await db.rollback()

        logger.info("Telegram broadcast system started")
    else:
        logger.warning(
            "TELEGRAM_BOT_TOKEN not set — broadcast system disabled. "
            "Set it in .env to enable."
        )

    yield

    logger.info("Shutting down…")
    scheduler.shutdown(wait=False)
    await client.stop()

    if settings.TELEGRAM_BOT_TOKEN:
        await broadcast_service.stop()
        try:
            tg = get_telegram_service()
            await tg.stop()
        except RuntimeError:
            pass

    await close_market_session()
    await close_onchain_session()
    await dispose_engine()
    logger.info("Shutdown complete")


_docs_url = "/docs" if settings.DEBUG else None
_redoc_url = "/redoc" if settings.DEBUG else None

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Real-time crypto market tracking dashboard API",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

register_exception_handlers(app)

_cors_kwargs: dict = {
    "allow_origins": settings.cors_origins,
    "allow_credentials": True,
    "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    "allow_headers": ["Authorization", "Content-Type", "Accept", "X-Request-ID"],
}
if settings.CORS_ORIGIN_REGEX.strip():
    _cors_kwargs["allow_origin_regex"] = settings.CORS_ORIGIN_REGEX.strip()

app.add_middleware(CORSMiddleware, **_cors_kwargs)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SlowAPIMiddleware)

API_PREFIX = "/api"
_auth_required = [Depends(require_verified_user)]

app.include_router(products.router, prefix=API_PREFIX)
app.include_router(candles.router, prefix=API_PREFIX)
app.include_router(auth_router.router, prefix=API_PREFIX)
app.include_router(billing_router.router, prefix=API_PREFIX)

app.include_router(news_router.router, prefix=API_PREFIX, dependencies=_auth_required)
app.include_router(ai_router.router, prefix=API_PREFIX, dependencies=_auth_required)
app.include_router(scripts_router.router, prefix=API_PREFIX, dependencies=_auth_required)
app.include_router(alerts_router.router, prefix=API_PREFIX, dependencies=_auth_required)
app.include_router(onchain_router.router, prefix=API_PREFIX, dependencies=_auth_required)
app.include_router(token_search_router.router, prefix=API_PREFIX, dependencies=_auth_required)
app.include_router(discovery_router.router, prefix=API_PREFIX, dependencies=_auth_required)
app.include_router(whale_scan_router.router, prefix=API_PREFIX, dependencies=_auth_required)
app.include_router(analytics_router.router, prefix=API_PREFIX, dependencies=_auth_required)
app.include_router(paper_trades_router.router, prefix=API_PREFIX, dependencies=_auth_required)
app.include_router(user_data_router.router, prefix=API_PREFIX, dependencies=_auth_required)

app.include_router(broadcast_router.router, prefix=API_PREFIX)
app.include_router(broadcast_router.signal_router, prefix=API_PREFIX)
app.include_router(telegram_router.router, prefix=API_PREFIX)
app.include_router(admin_router.router, prefix=API_PREFIX)

app.include_router(ws_router.router)


@app.get("/health", tags=["health"])
async def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@app.get("/", tags=["health"])
async def root():
    payload = {
        "message": f"Welcome to {settings.APP_NAME} API",
        "health": "/health",
    }
    if settings.DEBUG:
        payload["docs"] = "/docs"
    return payload
