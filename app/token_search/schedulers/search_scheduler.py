"""Token search scheduler jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db.database import AsyncSessionLocal
from app.token_search.cache.search_cache import cleanup_expired_cache
from app.token_search.services.trending_service import compute_trending_tokens

logger = logging.getLogger(__name__)


async def refresh_trending_job() -> None:
    async with AsyncSessionLocal() as db:
        try:
            count = await compute_trending_tokens(db)
            logger.info("Scheduler[trending]: refreshed %d tokens", count)
        except Exception as exc:
            logger.exception("Scheduler[trending] failed: %s", exc)
            await db.rollback()


async def cleanup_search_cache_job() -> None:
    async with AsyncSessionLocal() as db:
        try:
            removed = await cleanup_expired_cache(db)
            await db.commit()
            logger.info("Scheduler[search_cache]: removed %d expired entries", removed)
        except Exception as exc:
            logger.warning("Scheduler[search_cache] failed: %s", exc)
            await db.rollback()


def attach_token_search_scheduler(scheduler) -> None:
    scheduler.add_job(
        refresh_trending_job,
        "interval",
        minutes=30,
        id="token_trending",
        replace_existing=True,
    )
    scheduler.add_job(
        cleanup_search_cache_job,
        "cron",
        hour=4,
        minute=0,
        id="search_cache_cleanup",
        replace_existing=True,
    )
