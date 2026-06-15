"""
Background scheduler using APScheduler AsyncIOScheduler.

Jobs:
  1. fetch_gnews_job      — every 15 minutes: pull latest news from GNews
  2. process_ai_job       — every 30 minutes: refresh expired AI insights
  3. DB retention         — handled by app.db.retention_scheduler (daily)
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.services.news import gnews_service
from app.services.news.news_normalizer import upsert_articles
from app.services.ai import insight_service

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "DOGE", "XRP", "ADA", "AVAX", "DOT", "LINK"]


def _active_symbols() -> list[str]:
    raw = getattr(settings, "TRACKED_SYMBOLS", "")
    if raw:
        return [s.strip().upper() for s in raw.split(",") if s.strip()]
    return DEFAULT_SYMBOLS


async def fetch_gnews_job() -> None:
    if not settings.ENABLE_NEWS_PERSISTENCE:
        return
    if not settings.GNEWS_API_KEY:
        logger.debug("Scheduler[gnews]: GNEWS_API_KEY not set, skipping GNews fetch")
        return
    if AsyncSessionLocal is None:
        return

    symbols = _active_symbols()
    logger.info("Scheduler[gnews]: fetching for %d symbols", len(symbols))

    total_inserted = 0
    async with AsyncSessionLocal() as session:
        for sym in symbols:
            articles = await gnews_service.fetch_news(sym, max_results=10)
            if articles:
                inserted, _ = await upsert_articles(session, articles)
                total_inserted += inserted

    logger.info("Scheduler[gnews]: fetch complete — +%d new articles", total_inserted)


async def process_ai_job() -> None:
    if not settings.OPENAI_API_KEY:
        logger.debug("Scheduler[ai]: OPENAI_API_KEY not set, skipping AI job")
        return

    symbols = _active_symbols()
    logger.info("Scheduler[ai]: starting web-search AI refresh for %d symbols", len(symbols))

    if AsyncSessionLocal is None:
        await insight_service.refresh_insights_for_symbols(None, symbols)
    else:
        async with AsyncSessionLocal() as session:
            await insight_service.refresh_insights_for_symbols(session, symbols)

    logger.info("Scheduler[ai]: AI refresh complete")


_scheduler: AsyncIOScheduler | None = None


def create_scheduler() -> AsyncIOScheduler:
    global _scheduler
    scheduler = AsyncIOScheduler()

    if settings.ENABLE_NEWS_PERSISTENCE:
        scheduler.add_job(
            fetch_gnews_job,
            "interval",
            minutes=15,
            id="fetch_gnews",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
        )

    if settings.OPENAI_API_KEY:
        scheduler.add_job(
            process_ai_job,
            "interval",
            minutes=30,
            id="process_ai",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2),
        )

    _scheduler = scheduler
    return scheduler


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler
