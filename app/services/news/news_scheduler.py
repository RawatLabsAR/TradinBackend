"""
Background scheduler using APScheduler AsyncIOScheduler.

Jobs:
  1. fetch_gnews_job      — every 15 minutes: pull latest news from GNews
                            (per-symbol; free tier: 100 req/day shared across all symbols)
  2. process_ai_job       — every 30 minutes: for each symbol whose AI cache has
                            expired, call OpenAI with web_search_preview to search
                            the live web and regenerate insights.
  3. cleanup_old_news_job — daily: remove articles older than 7 days.

Note: OpenAI web_search_analyze handles both news discovery AND analysis in
one call — GNews articles are a secondary, visual feed only.
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.models.news_article import NewsArticle
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
    """
    Fetch latest news from GNews for all tracked symbols and persist to DB.
    These articles populate the NewsFeed UI on the Coin Detail page.

    GNews free tier: 100 req/day.  With ~10 symbols, 15-min intervals would
    be ~960 req/day — adjust TRACKED_SYMBOLS or interval if on free tier.
    Tip: set AI_CACHE_MINUTES=720 and change the interval to 120 min to stay
    within 100 req/day on the free tier.
    """
    if not settings.GNEWS_API_KEY:
        logger.debug("Scheduler[gnews]: GNEWS_API_KEY not set, skipping GNews fetch")
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
    """
    For each tracked symbol whose AI cache has expired, trigger a fresh
    OpenAI web-search analysis.  Symbols with a live cache are skipped.
    """
    if not settings.OPENAI_API_KEY:
        logger.debug("Scheduler[ai]: OPENAI_API_KEY not set, skipping AI job")
        return

    symbols = _active_symbols()
    logger.info("Scheduler[ai]: starting web-search AI refresh for %d symbols", len(symbols))

    async with AsyncSessionLocal() as session:
        await insight_service.refresh_insights_for_symbols(session, symbols)

    logger.info("Scheduler[ai]: AI refresh complete")


async def cleanup_old_news_job() -> None:
    """Remove articles older than 7 days to keep DB lean."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(NewsArticle).where(NewsArticle.published_at < cutoff)
        )
        await session.commit()
        logger.info("Scheduler[cleanup]: removed %d old articles", result.rowcount)


_scheduler: AsyncIOScheduler | None = None


def create_scheduler() -> AsyncIOScheduler:
    global _scheduler
    scheduler = AsyncIOScheduler()

    # GNews article feed — every 15 minutes
    scheduler.add_job(
        fetch_gnews_job,
        "interval",
        minutes=15,
        id="fetch_gnews",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
    )

    # OpenAI web-search AI analysis — every 30 minutes
    scheduler.add_job(
        process_ai_job,
        "interval",
        minutes=30,
        id="process_ai",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2),
    )

    # Daily cleanup at 03:00 UTC
    scheduler.add_job(
        cleanup_old_news_job,
        "cron",
        hour=3,
        minute=0,
        id="cleanup_news",
        replace_existing=True,
    )

    _scheduler = scheduler
    return scheduler


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler
