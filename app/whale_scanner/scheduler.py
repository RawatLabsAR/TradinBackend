"""Whale scanner background scheduler — runs inside the web process."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.db.database import database_available
from app.whale_scanner import progress
from app.whale_scanner.runner import background_task_running
from app.whale_scanner.service import run_daily

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()


async def whale_scan_job() -> None:
    """Scheduled job: discover new tokens and scan for whale activity."""
    if not settings.ENABLE_WHALE_SCAN_SCHEDULER:
        return
    if not database_available():
        logger.debug("Whale scan job skipped — DATABASE_URL not configured")
        return
    if progress.is_running() or background_task_running():
        logger.info("Whale scan job skipped — scan already in progress")
        return
    if _lock.locked():
        logger.info("Whale scan job skipped — previous run still finishing")
        return

    async with _lock:
        if progress.is_running() or background_task_running():
            return
        logger.info(
            "Whale scan job starting (interval=%dm, limit=%s)",
            settings.WHALE_SCAN_INTERVAL_MINUTES,
            settings.WHALE_SCAN_SCHEDULED_LIMIT or "default",
        )
        try:
            limit = settings.WHALE_SCAN_SCHEDULED_LIMIT if settings.WHALE_SCAN_SCHEDULED_LIMIT > 0 else None
            await run_daily(limit=limit, track_progress=False)
        except Exception as exc:
            logger.exception("Whale scan job failed: %s", exc)


def attach_whale_scan_scheduler(scheduler) -> None:
    if not settings.ENABLE_WHALE_SCAN_SCHEDULER:
        logger.info("Whale scan scheduler disabled (ENABLE_WHALE_SCAN_SCHEDULER=false)")
        return
    interval = settings.WHALE_SCAN_INTERVAL_MINUTES
    scheduler.add_job(
        whale_scan_job,
        "interval",
        minutes=interval,
        id="whale_scan",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "Whale scan scheduler attached (every %dm, runs on startup, limit=%s)",
        interval,
        settings.WHALE_SCAN_SCHEDULED_LIMIT or "MAX_TOKENS_PER_RUN",
    )
